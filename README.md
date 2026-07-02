# TSP Rebalance Engine

A Streamlit-based tactical TSP allocation assistant for macro-aware fund rotation and manual IFT decision support.

The app analyzes market and macro inputs, scores the current environment, maps that environment to a regime, recommends a target TSP allocation, and helps decide whether to submit an IFT or hold. It is intentionally tactical and quantitative, not a lifecycle-fund clone.

## What It Does

- Fetches live market and macro data
- Validates the snapshot before scoring
- Computes factor scores and a composite regime score
- Selects one of the current tactical regimes:
  - Risk-On Override
  - Optimized Neutral
  - Defensive Allocation
  - Emergency Dispatch
- Produces a target allocation for TSP funds
- Evaluates whether an IFT should be recommended
- Supports manual IFT confirmation
- Tracks monthly IFT usage locally
- Stores logs and state on disk
- Shows proxy fund performance and historical views

## Current Tactical Allocation Model

The current baseline regime targets are defined in `constants.py` and should be treated as the source of truth for regime allocations. This is reinforced by the consistency tests, which verify alignment across the engine, UI, validation layer, and IFT state machine  

### Risk-On Override
- G: 30%
- C: 40%
- I: 20%
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

### Emergency Dispatch with F Fund Unlocked
- G: 90%
- C: 0%
- I: 0%
- S: 0%
- F: 10%

The F Fund is treated as a conditional overlay only. It is added only when the engine’s F Fund unlock rule is satisfied.

## Project Structure

The codebase is split into clear modules so that decision logic, persistence, presentation, and styling do not drift into one another.

### Core logic
- `engine.py` — factor scoring, regime selection, allocation logic, and IFT recommendation logic
- `data_sources.py` — market and macro data acquisition
- `validation.py` — input and allocation validation
- `ift_state_machine.py` — monthly IFT rule enforcement and pure-G safety handling
- `storage.py` — config, state, and CSV persistence
- `constants.py` — shared defaults, paths, thresholds, regime definitions
- `models.py` — typed data models
- `utils.py` — general helper functions

### Presentation
- `ui.py` — reusable Streamlit display helpers
- `styles.py` — CSS and visual tokens

### Application entrypoint
- `app.py` — Streamlit app orchestration and UI wiring

## How It Works

1. The app loads config and state from local JSON files.
2. It injects the shared styles.
3. It fetches market and macro data.
4. The snapshot is validated.
5. The engine scores the environment across multiple factors.
6. The engine selects a regime and target allocation.
7. The app compares the current allocation to the target.
8. The IFT rule engine decides whether to submit or hold.
9. The result is logged locally.
10. Manual confirmation updates the transaction state.

## Data Inputs Used by the Engine

The scoring engine uses inputs such as:
- Core PCE YoY
- PMI and services PMI
- Initial claims
- Breakeven inflation
- Fed assets growth
- Real yield
- SLOOS
- HY spread
- CAPE
- Forward EPS growth
- VIX
- 200-day distance
- Drawdown
- STLFSI
- 10Y yield
- 3M yield
- DXY
- Market breadth
- Panic flags

## Manual IFT Workflow

The safest operating mode is manual confirmation:

- the app can recommend `SUBMIT IFT`
- but the monthly IFT count and transaction history are only updated when you click the manual submit button

This keeps the recommendation separate from the actual transaction and reduces the risk of accidental state drift.

## Current Files Created by the App

- `tsp_config.json` — saved config
- `tsp_state.json` — saved state
- `tsp_daily_log.csv` — daily run log
- `tsp_transactions.csv` — audit trail / transaction history

## Important Limitations

- Live market data may fall back to defaults if a source is unavailable.
- Multiple macro indicators are lagged and may update asynchronously.
- The engine is rule-based and can flip regimes around hard thresholds.
- Flat-file persistence is suitable for a single-user Streamlit workflow, not multi-user concurrency.
- Snapshot quality should be interpreted alongside source provenance and freshness where available.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
