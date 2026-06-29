---

# TSP Rebalance Engine — Project Handoff

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
- I 25
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

Important: `engine.py` should use the same baseline regime allocations as `constants.py`. Its emergency and F Fund overlay logic are still important and should remain intact.  

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

Important note: the default config still has an older starting allocation of `G 40 / C 30 / I 20 / S 5 / F 5`, so if you want startup defaults to match the new regime philosophy, update that later. 

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

`BASELINE_ALLOCATIONS` is already updated to the new tactical regime set. 

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

### 3) Default config still needs review
If you want startup allocation to reflect the new tactical framework, update the default current allocation in `storage.py`.

---

## Suggested next steps for the next AI

1. Verify `engine.py` allocations match `constants.py`.
2. Verify `app.py` regime card labels match `constants.py`.
3. Decide whether to update `storage.py` default current allocation.
4. Remove any remaining automatic IFT count / auto-transaction logging if it still exists.
5. Consider making the detailed decision breakdown a little more compact or more visual.
6. Consider adding a “data source health” section so the app clearly shows when it is using fallback/default values.

---

## Conversation context to preserve

The user prefers:
- plain English explanations
- tactical/quantitative framing
- manual IFT confirmation
- detailed reasoning in the UI
- updated regime allocations:
  - Risk-On 30/40/25/10
  - Neutral 40/30/20/10
  - Defensive 70/15/10/5

The user also wants:
- a more detailed engine reasoning section
- cleaner transaction history display
- safer IFT handling
- beginner-friendly guidance

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

---

## Short summary for the next AI

This is a tactical TSP engine with updated allocations, manual IFT confirmation, and a detailed decision UI. The main remaining risk is file mismatch between `engine.py`, `app.py`, `constants.py`, and `storage.py`. Keep the baseline regime allocations synchronized and preserve the manual confirmation workflow.
