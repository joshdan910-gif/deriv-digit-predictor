import asyncio
import json
import threading
import time
from collections import Counter, deque
from datetime import datetime

import streamlit as st
import websockets

st.set_page_config(page_title="Deriv Digit Predictor", page_icon="📊", layout="wide")
st.title("Deriv Digit Predictor")
st.caption("Live tick stream • Matches • Over/Under • Exact digit • Estimated tick + countdown")

st.warning(
    "Digits in synthetic markets may be random. Historical frequencies are descriptive, "
    "not guaranteed predictive edges. This dashboard does not place trades."
)

# Shared background worker: keeps the WebSocket alive between Streamlit reruns.
_WORKERS = {}


class TickWorker:
    def __init__(self, app_id, symbol, keep=2000):
        self.app_id = app_id
        self.symbol = symbol
        self.ticks = deque(maxlen=keep)
        self.status = "Connecting…"
        self.error = ""
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return list(self.ticks), self.status, self.error

    def _thread_main(self):
        asyncio.run(self._run())

    async def _run(self):
        uri = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"
        delay = 1
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    self.status = "Connecting to Deriv…"
                    self.error = ""
                async with websockets.connect(
                    uri, ping_interval=20, ping_timeout=20, open_timeout=20
                ) as ws:
                    await ws.send(json.dumps({"ticks": self.symbol, "subscribe": 1}))
                    with self.lock:
                        self.status = "Connected — receiving live ticks"
                    delay = 1

                    while not self.stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=45)
                        msg = json.loads(raw)

                        if msg.get("error"):
                            raise RuntimeError(msg["error"].get("message", "Deriv API error"))

                        tick = msg.get("tick")
                        if not tick:
                            continue

                        quote = tick.get("quote")
                        pip_size = int(tick.get("pip_size", 2))
                        formatted = f"{float(quote):.{pip_size}f}"
                        digits_only = "".join(c for c in formatted if c.isdigit())
                        if not digits_only:
                            continue

                        item = {
                            "epoch": float(tick.get("epoch", time.time())),
                            "quote": quote,
                            "digit": int(digits_only[-1]),
                        }
                        with self.lock:
                            self.ticks.append(item)
                            self.status = "Connected — receiving live ticks"
                            self.error = ""
            except Exception as exc:
                with self.lock:
                    self.status = "Disconnected — retrying"
                    self.error = str(exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 20)


def get_worker(app_id, symbol):
    key = (app_id, symbol)
    # Stop an old worker if the user changes market or app ID.
    for old_key, old_worker in list(_WORKERS.items()):
        if old_key != key:
            old_worker.stop_event.set()
            _WORKERS.pop(old_key, None)
    worker = _WORKERS.get(key)
    if worker is None or worker.stop_event.is_set():
        worker = TickWorker(app_id, symbol)
        _WORKERS[key] = worker
    return worker


def estimates(digits):
    counts = Counter(digits)
    total = len(digits) + 10  # Laplace smoothing
    return [(counts[d] + 1) / total for d in range(10)]


def mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


with st.sidebar:
    st.header("Market connection")
    app_id = st.text_input("Deriv App ID", value="1089", help="Use your own registered app ID if you have one.")
    symbol = st.selectbox(
        "Market",
        ["R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"],
        index=4,
    )
    sample_size = st.slider("Analysis window (ticks)", 50, 2000, 500, 50)
    contract_seconds = st.slider("Countdown duration (seconds)", 5, 300, 30, 5)
    mode = st.radio("Prediction mode", ["Matches", "Over / Under", "Exact digit"])
    target_digit = st.selectbox("Target digit (Matches)", list(range(10)), index=7)
    barrier = st.selectbox("Barrier (Over / Under)", list(range(10)), index=4)
    connect = st.toggle("Connect to live market", value=False)

if not connect:
    st.info("Turn on **Connect to live market** to begin the live tick stream.")
    st.markdown("### Dashboard preview")
    st.write("The live signal, digit distribution, and recent tick history will appear here.")
    st.stop()

worker = get_worker(app_id.strip(), symbol)

# Streamlit fragment refreshes this panel without restarting the WebSocket worker.
@st.fragment(run_every=1)
def live_panel():
    ticks, status, error = worker.snapshot()
    st.subheader("Live signal")
    st.caption(status)

    if error:
        st.error(f"Connection issue: {error}")

    if not ticks:
        st.info("Waiting for the first market ticks. If connection fails repeatedly, verify the App ID or try again shortly.")
        return

    digits = [item["digit"] for item in ticks[-sample_size:]]
    probs = estimates(digits)
    latest = ticks[-1]

    if len(ticks) > 1:
        intervals = [
            max(0.01, ticks[i]["epoch"] - ticks[i - 1]["epoch"])
            for i in range(max(1, len(ticks) - 30), len(ticks))
        ]
        avg_interval = sum(intervals) / len(intervals) if intervals else 1.0
    else:
        avg_interval = 1.0

    if mode == "Matches":
        chosen = target_digit
        chance = probs[chosen]
        label = f"Matches {chosen}"
    elif mode == "Over / Under":
        over_prob = sum(probs[barrier + 1 :])
        under_prob = sum(probs[:barrier])
        label = f"Over {barrier}" if over_prob >= under_prob else f"Under {barrier}"
        chance = max(over_prob, under_prob)
    else:
        chosen = max(range(10), key=lambda d: probs[d])
        chance = probs[chosen]
        label = f"Exact digit {chosen}"

    tick_eta = max(0, avg_interval - max(0, time.time() - latest["epoch"]))
    # This is a visual timer only; no contract is opened or tracked by the app.
    countdown = contract_seconds - (int(time.time()) % contract_seconds)

    a, b, c, d = st.columns(4)
    a.metric("Current quote", str(latest["quote"]))
    b.metric("Current last digit", str(latest["digit"]))
    c.metric("Candidate signal", label)
    d.metric("Historical estimate", f"{chance * 100:.1f}%")

    e, f = st.columns(2)
    e.metric("Next tick ETA (estimated)", f"~{tick_eta:.1f}s")
    f.metric("Visual countdown", mmss(countdown))
    st.progress(min(1.0, max(0.0, chance)), text="Smoothed historical frequency — not a guarantee")

    st.subheader("Digit distribution")
    st.bar_chart({str(i): probs[i] * 100 for i in range(10)})

    st.subheader("Recent last digits")
    st.code("  ".join(str(digit) for digit in digits[-50:]))

    counts = Counter(digits)
    st.subheader("Observed digit counts")
    st.dataframe(
        [
            {"Digit": i, "Count": counts[i], "Observed share": f"{counts[i] / len(digits) * 100:.1f}%"}
            for i in range(10)
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Ticks in memory: {len(ticks)} • Last tick received: {datetime.fromtimestamp(latest['epoch']).strftime('%H:%M:%S')}")
    st.info("The stream updates continuously while this dashboard is open. The countdown is a visual timer, not an actual contract expiry.")

live_panel()
