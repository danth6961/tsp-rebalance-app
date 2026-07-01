# Project Handoff

## Purpose

This project is a Streamlit-based tactical TSP allocation assistant.

It analyzes macro and market data, scores the current environment, selects a regime, recommends a target TSP allocation, and decides whether an IFT should be submitted or held.

The system is meant to be:
- tactical
- quantitative
- transparent
- manually confirmable for IFT tracking

---

## Current high-level behavior

### Main flow
1. Load config and state.
2. Fetch live or fallback market data.
3. Score the market.
4. Select a regime.
5. Build target allocation.
6. Compare current vs target allocation.
7. Determine HOLD vs SUBMIT IFT.
8. Display detailed reasoning.
9. Save state and log the run.

### Important workflow rule
The safest workflow is:
- the engine may recommend `SUBMIT IFT`
- but only the manual submit button should increment the IFT count and write the transaction row

That means recommendation and actual confirmation are intentionally separated.

---

## Current regime allocations

These are the current tactical baselines:

### Risk-On Override
- G 30
- C 40
- I 20
- S 10
- F 0

### Optimized Neutral
- G 40
- C 30
- I 20
- S 10
- F 0

### Defensive Allocation
- G 70
- C 15
- I 10
- S 5
- F 0

### Emergency Dispatch
- G 100
- C 0
- I 0
- S 0
- F 0

### Emergency Dispatch with F unlocked
- G 90
- C 0
- I 0
- S 0
- F 10

The current baseline allocations are stored in `constants.py`, and `engine.py` should match them exactly. `app.py` also displays the same regime cards in the UI.

---

## Manual IFT and G Fund behavior

### Normal IFTs
Normal IFT confirmations:
- are manual
- increment the monthly IFT counter
- write to the transaction audit trail
- must respect the 2-IFT monthly limit

### Pure G Fund safety move
A pure 100% G allocation is treated as a TSP-safe safety move:
- it does not consume a monthly IFT
- it does not count toward the normal 2-IFT cap
- it is still recorded by the app as a safety action

This is meant to support the TSP rule that moving to G can be handled as a special safety path.

---

## Files and roles

### `app.py`
Main Streamlit application and orchestration layer.

Current responsibilities:
- sidebar controls
- config save/reset
- live data fetch
- engine execution
- result display
- transaction history display
- daily log export
- manual IFT submit button
- G Fund safety move handling

The app also contains the detailed “Engine Decision Breakdown” section and the regime summary cards.

### `engine.py`
Core decision logic.

It:
- scores macro/market inputs
- selects the regime
- applies allocation adjustments
- handles panic/emergency logic
- applies F Fund unlock logic
- applies asymmetric volatility and strong DXY adjustments
- determines IFT eligibility

Important:
- `engine.py` should use the same baseline regime allocations as `constants.py`
- emergency and F Fund overlay logic should remain intact
- the current IFT gating logic still needs review if you want it stricter and more conservative

### `data_sources.py`
External data acquisition.

It fetches or derives market/macro inputs and provides fallback handling if live data is unavailable.

### `storage.py`
Persistence layer.

It stores:
- config
- state
- daily run log
- transaction audit trail

### `ui.py`
Reusable UI helpers.

It contains:
- metric cards
- history table
- score chart
- allocation chart
- editable metric tile rendering

### `constants.py`
Shared constants and defaults.

Current important values:
- file paths
- proxy tickers
- default market inputs
- baseline allocations

`BASELINE_ALLOCATIONS` includes the tactical regime set and may still contain leftover experimental entries that should be reviewed if you want the cleanest setup.

### `models.py`
Typed dataclasses for:
- market data
- engine result
- config
- app state

### `utils.py`
Generic helpers:
- time handling
- parsing
- small utility support

---

## Important current design decisions

### 1) F Fund is conditional only
Do not treat F as part of the normal baseline mix.

The engine should:
- start with a baseline allocation using G/C/I/S
- then add F only if the unlock rule allows it

### 2) Manual IFT confirmation is the source of truth
The safest workflow is:

- engine recommends
- user submits in TSP
- user clicks manual submit in the app
- app increments IFT count and writes transaction row

Do not let the recommendation path and the confirmation path both update the IFT state.

### 3) The app is tactical, not lifecycle
This is not intended to mimic TSP L Funds.

The regime logic is meant to be:
- quantitative
- rule-based
- adaptable
- more aggressive or defensive based on market conditions

---

## Current UI details

### Regime directory
The app shows four regime cards:
- Risk-On Override
- Optimized Neutral
- Defensive Allocation
- Emergency Dispatch

### Detailed decision breakdown
The app includes a detailed decision expander with:
- summary
- factor score detail
- factor interpretation
- regime/allocation build
- IFT logic

### Proxy chart default
The performance chart timeframe defaults to `10 Years`.

---

## Known issues / things to watch

### 1) Possible mismatch if files are edited independently
If allocations are changed in one place but not others, the app can show one set of numbers while the engine calculates another.

Make sure these stay aligned:
- `constants.py`
- `engine.py`
- `app.py`
- optionally `storage.py` default config

### 2) Transaction history should reflect actual confirmations
Only confirmed IFTs should be written to `tsp_transactions.csv`.

### 3) IFT gate could still be tightened further
The current app now supports a G-only safety move path, but the underlying engine eligibility logic may still be more permissive than desired if you want stricter turnover control.

---

## Suggested next steps for the next AI

Help incorporate macro context such as:
- yield curve dynamics
- inflation shocks
- central bank policy and liquidity
- global growth trends
- risk-on / risk-off regimes

Ensure logic respects the TSP rule of only two Interfund Transfers (IFTs) per calendar month. Actively guard against:
- look-ahead bias
- data leakage
- excessive turnover
- overconcentration
- fragile backtests

---

## Quantitative Scoring and Portfolio Logic

Help review, design, and improve:
- momentum
- volatility-adjusted momentum
- risk parity / risk budgeting
- trend following
- defensive allocation
- hysteresis / buffer-zone logic

---

## Conversation context to preserve

The user prefers:
- plain English explanations
- tactical/quantitative framing
- manual IFT confirmation
- detailed reasoning in the UI
- updated regime allocations:
  - Risk-On 30/40/20/10
  - Neutral 40/30/20/10
  - Defensive 70/15/10/5

The user also wants:
- safer IFT handling
- beginner-friendly guidance
- clear separation between recommendation and confirmation

---

## Notes for future edits

If you change the regime mix again:
- update `constants.py`
- update `engine.py`
- update `app.py` UI labels
- optionally update `storage.py` default allocation

Keep all of them synchronized.

If you change the IFT workflow:
- ensure only one path updates count/history
- recommendation should remain separate from confirmation
- G-only safety moves should be visually obvious

---

## Short summary for the next AI
This is a tactical TSP engine with updated allocations, manual IFT confirmation, a pure G Fund safety move path, and a detailed decision UI. The main remaining risk is file mismatch between `engine.py`, `app.py`, `constants.py`, and `storage.py`. Keep the baseline regime allocations synchronized and preserve the manual confirmation workflow.
