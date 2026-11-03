import asyncio
import json
import time
from collections import Counter, deque
from datetime import datetime
import streamlit as st
import websockets

st.set_page_config(page_title="Deriv Digit Predictor", page_icon="📊", layout="wide")

st.title("Deriv Digit Predictor")
st.caption("Live tick analysis • Matches • Over/Under • Exact digit • Estimated tick + contract countdown")

# This is a research dashboard, not a guaranteed signal or auto-trader.
st.warning("Digits in synthetic markets can be random. Frequencies and model estimates are descriptive, not guaranteed predictive edges. This dashboard does not place trades.")

with st.sidebar:
    st.header("Market connection")
    app_id = st.text_input("Deriv App ID", value="1089", help="Use your own Deriv app ID for reliable access.")
    symbol = st.selectbox("Market", ["R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"], index=4)
    sample_size = st.slider("Analysis window (ticks)", 50, 2000, 500, 50)
    contract_seconds = st.slider("Contract duration (seconds)", 5, 300, 30, 5)
    mode = st.radio("Prediction mode", ["Matches", "Over / Under", "Exact digit"])
    target_digit = st.selectbox("Target digit (Matches)", list(range(10)), index=7)
    barrier = st.selectbox("Barrier (Over / Under)", list(range(10)), index=4)
    refresh = st.slider("Refresh interval (seconds)", 1, 10, 2)
    run = st.toggle("Connect to live market", value=False)

def last_digit(quote, pip_size):
    try:
        # Deriv quote is numeric; pip_size is decimal precision.
        decimals = int(pip_size)
        formatted = f"{float(quote):.{decimals}f}"
        digits = "".join(c for c in formatted if c.isdigit())
        return int(digits[-1]) if digits else None
    except Exception:
        return None

async def fetch_ticks(app_id, symbol, n):
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    ticks = []
    pip_size = 2
    async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
        # Try to retrieve pip size metadata.
        await ws.send(json.dumps({"contracts_for": symbol, "currency": "USD"}))
        deadline = time.time() + 18
        while time.time() < deadline and len(ticks) < n:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", "Deriv API error"))
            if "contracts_for" in msg:
                continue
            tick = msg.get("tick")
            if tick:
                quote = tick.get("quote")
                pip_size = tick.get("pip_size", pip_size)
                digit = last_digit(quote, pip_size)
                if digit is not None:
                    ticks.append({
                        "epoch": tick.get("epoch", time.time()),
                        "quote": quote,
                        "digit": digit
                    })
    return ticks, pip_size

def estimate(digits):
    if not digits:
        return [0.1] * 10
    counts = Counter(digits)
    # Small Laplace smoothing prevents zero estimates.
    total = len(digits) + 10
    return [(counts[d] + 1) / total for d in range(10)]

def countdown_text(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"

left, right = st.columns([2, 1])
with left:
    st.subheader("Live signal")
with right:
    st.metric("Contract expiry countdown", countdown_text(contract_seconds))

if not run:
    st.info("Turn on **Connect to live market** in the sidebar to start receiving live ticks.")
    st.markdown("### Dashboard preview")
    cols = st.columns(5)
    for i, c in enumerate(cols):
        c.metric(f"Digit {i}", "—")
    st.markdown("The prediction panel will populate from the incoming tick stream. No sample predictions are presented as live data.")
    st.stop()

placeholder = st.empty()
status = st.empty()

try:
    ticks, pip_size = asyncio.run(fetch_ticks(app_id.strip(), symbol, sample_size))
    if not ticks:
        st.error("No ticks received in the connection window. Try again or check the market/App ID.")
        st.stop()

    digits = [t["digit"] for t in ticks[-sample_size:]]
    probs = estimate(digits)
    latest = ticks[-1]
    avg_interval = 1.0
    if len(ticks) > 1:
        intervals = [max(0.01, ticks[i]["epoch"] - ticks[i-1]["epoch"]) for i in range(1, len(ticks))]
        avg_interval = sum(intervals) / len(intervals)

    if mode == "Matches":
        chosen = target_digit
        chance = probs[chosen]
        label = f"Matches {chosen}"
    elif mode == "Over / Under":
        chosen = barrier
        over_prob = sum(probs[chosen+1:])
        under_prob = sum(probs[:chosen])
        label = f"Over {chosen}" if over_prob >= under_prob else f"Under {chosen}"
        chance = max(over_prob, under_prob)
    else:
        chosen = max(range(10), key=lambda d: probs[d])
        chance = probs[chosen]
        label = f"Exact digit {chosen}"

    # Approximate next tick ETA from recent average. It is an estimate, not a promise.
    tick_eta = avg_interval
    now = time.time()
    last_epoch = float(latest["epoch"])
    tick_remaining = max(0, tick_eta - max(0, now - last_epoch))
    expiry_remaining = contract_seconds

    with placeholder.container():
        a, b, c, d = st.columns(4)
        a.metric("Current quote", str(latest["quote"]))
        b.metric("Current last digit", str(latest["digit"]))
        c.metric("Candidate signal", label)
        d.metric("Empirical estimate", f"{chance*100:.1f}%")
        st.caption(f"Next tick ETA (estimated): ~{tick_remaining:.1f}s • Average observed tick interval: {avg_interval:.2f}s")
        st.progress(min(1.0, max(0.0, chance)), text="Estimated probability (historical frequency; not a guarantee)")
        st.subheader("Digit distribution")
        chart_data = {str(i): probs[i] * 100 for i in range(10)}
        st.bar_chart(chart_data)
        st.subheader("Recent last digits")
        recent = "  ".join(str(d) for d in digits[-50:])
        st.code(recent)
        st.subheader("Observed digit counts")
        counts = Counter(digits)
        st.dataframe(
            [{"Digit": i, "Count": counts[i], "Observed share": f"{counts[i]/len(digits)*100:.1f}%"} for i in range(10)],
            use_container_width=True,
            hide_index=True
        )
        st.caption(f"Received {len(ticks)} ticks. Last update: {datetime.now().strftime('%H:%M:%S')}")

    st.info("This initial version collects a live tick batch when started. Continuous streaming, persistent history, live countdown updates, and validated predictive models are the next build stage.")
except Exception as e:
    st.error(f"Connection or data error: {e}")
