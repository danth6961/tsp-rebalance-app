# TSP Rebalance Engine

A Streamlit-based TSP (Thrift Savings Plan) tactical allocation companion app.

The app analyzes macro and market inputs, scores the current environment, maps it to a regime, recommends a target allocation, and helps decide whether to submit an IFT or hold. It is designed as a tactical and quantitative overlay, not as a lifecycle-fund clone.

## What it does

- Fetches live market and macro data
- Computes factor scores and a composite regime score
- Selects one of four policy regimes:
  - Risk-On Override
  - Optimized Neutral
  - Defensive Allocation
  - Emergency Dispatch
- Produces a target allocation for TSP funds
- Evaluates whether an IFT should be submitted
- Supports manual IFT confirmation
- Tracks monthly IFT usage locally
- Stores logs and state on disk
- Shows proxy fund performance and historical views

## Current tactical allocation model

The current baseline regime targets are:

### Risk-On Override
- G: 30%
- C: 40%
- I: 25%
- S: 10%
- F: 0%

### Optimized Neutral
- G: 40%
- C: 30%
- I: 20%
- S: 10%
- F: 0%

### Defensive Allocation
- G: 70%
- C: 15%
- I: 10%
- S: 5%
- F: 0%

### Emergency Dispatch
- G: 100%
- C: 0%
- I: 0%
- S: 0%
- F: 0%

### Emergency Dispatch with F Fund unlocked
- G: 90%
- C: 0%
- I: 0%
- S: 0%
- F: 10%

The F Fund is treated as a conditional overlay only. It is added only when the engine’s F Fund unlock rule is satisfied.

## Project structure

- `app.py` — Streamlit app entrypoint and UI orchestration
- `engine.py` — factor scoring, regime selection, allocation logic, and IFT logic
- `data_sources.py` — market and macro data acquisition
- `storage.py` — config, state, and CSV persistence
- `ui.py` — reusable Streamlit display helpers
- `constants.py` — shared defaults, paths, proxy tickers, and allocation baselines
- `models.py` — typed data models for the app
- `utils.py` — general helper functions
- `requirements.txt` — Python dependencies

## How it works

1. The app loads config and state from local JSON files.
2. It fetches market and macro data.
3. The engine scores the environment across multiple factors.
4. The engine selects a regime and target allocation.
5. The app compares the current allocation to the target.
6. The IFT rule engine decides whether to submit or hold.
7. The result is logged locally.

## Data inputs used by the engine

The scoring engine uses inputs such as:
- Core PCE YoY
- PMI and services PMI
- initial claims
- breakeven inflation
- Fed assets growth
- real yield
- SLOOS
- HY spread
- CAPE
- forward EPS growth
- VIX
- 200-day distance
- drawdown
- STLFSI
- 10Y yield
- DXY
- market breadth
- panic flags

## Manual IFT workflow

The safest operating mode is manual confirmation:

- the app can recommend `SUBMIT IFT`
- but the monthly IFT count and transaction history are only updated when you click the manual submit button

This keeps the recommendation separate from the actual transaction.

## Live files created by the app

- `tsp_config.json` — saved config
- `tsp_state.json` — saved state
- `tsp_daily_log.csv` — daily run log
- `tsp_transactions.csv` — audit trail / transaction history
- backup JSON files when applicable

## Installation

```bash
pip install -r requirements.txt
