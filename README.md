# Deriv Digit Predictor — starter deployment

This is an initial Streamlit app for a Deriv live tick digit analysis dashboard:
- Matches, Over/Under, and Exact Digit views
- Tick digit frequency table and chart
- Estimated probability from observed frequencies (not a predictive guarantee)
- Estimated next-tick timing and contract-duration control
- No trade execution

## Run locally
1. Install Python 3.10+.
2. In this folder run:
   `pip install -r requirements.txt`
3. Run:
   `streamlit run app.py`

## Host online with Streamlit Community Cloud
1. Create a GitHub repository and upload `app.py`, `requirements.txt`, and this README.
2. Open Streamlit Community Cloud and deploy the repository, selecting `app.py`.
3. Use your Deriv App ID in the sidebar. The default ID is a public example; use your own app ID for a production setup.

## Important limitations
This starter currently obtains a finite batch of ticks on activation. It does not yet keep a continuous WebSocket connection, preserve records across sessions, or run a validated forecasting model. The displayed frequency estimates are empirical summaries, not financial advice and not evidence of a reliable edge. It does not place trades or access your Deriv account credentials.
