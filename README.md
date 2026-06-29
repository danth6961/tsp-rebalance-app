# TSP Rebalance Engine

A Streamlit-based TSP (Thrift Savings Plan) allocation and rebalancing companion app that analyzes market and macro conditions, scores the current environment, recommends a target allocation, and helps decide whether to submit an IFT or hold.

The app is designed to work without direct account access. It uses public market and macro data, local state files, and manual inputs to support a transparent, operator-guided workflow.

## Features

- Fetches live market and macro data from public sources
- Computes factor scores and a composite market regime
- Maps the environment into one of four policy regimes:
  - Risk-On Override
  - Optimized Neutral
  - Defensive Allocation
  - Emergency Dispatch
- Recommends a target TSP allocation
- Evaluates whether an IFT should be submitted
- Tracks monthly IFT usage manually
- Persists config and state locally
- Logs daily runs
- Maintains a transaction/audit trail
- Supports CSV and JSON exports
- Shows historical score and allocation views
- Supports manual override for regime locking

## Project structure

- `app.py` — Streamlit application entrypoint and UI orchestration
- `engine.py` — factor scoring, regime selection, allocation logic, and IFT decision rules
- `data_sources.py` — live market/macro data collection and fallback logic
- `storage.py` — local config/state persistence and CSV logging helpers
- `ui.py` — reusable Streamlit rendering utilities
- `constants.py` — shared paths, defaults, and static configuration
- `models.py` — typed data structures used by the app
- `utils.py` — general-purpose helper functions
- `requirements.txt` — Python dependencies

## How it works

1. The app loads saved config and state from local JSON files.
2. It fetches the latest market and macro data.
3. The engine scores the environment across several factor buckets.
4. The composite score maps to a regime and target allocation.
5. The app compares current allocation to the target allocation.
6. A rule engine determines whether a TSP IFT should be submitted.
7. The run is saved to local logs and history files.

## Regimes

### Risk-On Override
Used when conditions are strongly constructive.

Typical allocation:
- G: 35%
- C: 45%
- I: 15%
- S: 5%
- F: 0%

### Optimized Neutral
Used when conditions are constructive but mixed.

Typical allocation:
- G: 45%
- C: 35%
- I: 10%
- S: 10%
- F: 0%

### Defensive Allocation
Used when the composite score turns negative.

Typical allocation:
- G: 65%
- C: 20%
- I: 10%
- S: 5%
- F: 0%

### Emergency Dispatch
Used when panic conditions are triggered.

Typical allocation:
- G: 90% to 100%
- F: 0% to 10%
- C/I/S: 0%

## Data sources

The app may use:
- FRED
- DBnomics
- TradingEconomics web data
- Yahoo Finance proxy price series for TSP fund tracking

If a source is unavailable, the app falls back to defaults or alternate sources.

## Local files

The app creates or updates the following local files:

- `tsp_config.json` — saved configuration
- `tsp_state.json` — saved run history and IFT state
- `tsp_daily_log.csv` — daily engine run log
- `tsp_transactions.csv` — transaction/audit trail
- backup files such as `.json.bak`

## Installation

Install dependencies:

```bash
pip install -r requirements.txt
