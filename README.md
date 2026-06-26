# tsp-rebalance-app
An open-source, mobile-first TSP (Thrift Savings Plan) portfolio tracker and rebalancing companion tool. Features daily fund price updates, advanced portfolio data visualization, and custom allocation target notifications without requiring direct account credentials
# TSP Rebalance Engine

A Streamlit-based TSP allocation rebalance app that:

- fetches live FRED and Yahoo Finance data
- computes factor scores and a market regime
- outputs a target TSP allocation
- decides HOLD vs SUBMIT IFT
- tracks monthly IFT usage manually
- saves config/state locally
- logs daily runs
- supports CSV/JSON exports
- shows a regime summary table

## Files
- `app.py` — main Streamlit app
- `requirements.txt` — dependencies
- `tsp_config.json` — saved config
- `tsp_state.json` — saved state
- `tsp_daily_log.csv` — daily log

## Setup
Install dependencies:
```bash
pip install -r requirements.txt

---

## File tree

```text
tsp-rebalance-app/
├── app.py
├── requirements.txt
├── README.md
├── PROJECT_HANDOFF.md
├── tsp_config.json
├── tsp_state.json
└── tsp_daily_log.csv
