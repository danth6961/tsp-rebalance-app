# Project Handoff

## Purpose

This project is a Streamlit-based tactical TSP allocation assistant.

It analyzes macro and market data, scores the current environment, selects a regime, recommends a target allocation, and helps decide whether to submit an IFT or hold. The system is designed to be tactical, quantitative, transparent, and manually confirmable for IFT tracking.

The current codebase already reflects a strong module split:
- `app.py` handles orchestration and UI
- `engine.py` handles tactical decision logic
- `data_sources.py` builds the market snapshot
- `storage.py` handles persistence
- `ui.py` provides reusable rendering helpers
- `constants.py`, `models.py`, `utils.py`, `validation.py`, and `ift_state_machine.py` support the main flow

The largest earlier risk was drift across allocations, thresholds, and IFT rules. That risk has been materially reduced by centralizing regime definitions in `constants.py` and adding consistency tests around the shared regime and IFT rules.

---

## Current High-Level Behavior

### Main Flow
1. Load config and state.
2. Fetch live or fallback market data.
3. Score the market.
4. Select a regime.
5. Build target allocation.
6. Compare current vs target allocation.
7. Determine HOLD vs SUBMIT IFT.
8. Display detailed reasoning.
9. Save state and log the run.
10. Manually confirm any actual IFT action.

### Important Workflow Rule
The safest workflow is:
- the engine may recommend `SUBMIT IFT`
- but only the manual submit button should increment the IFT count and write the transaction row

Recommendation and confirmation must remain separate.

---

## Current Regime Allocations

These are the current tactical baselines and should be treated as canonical unless intentionally changed in `constants.py`.

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

`constants.py` is the source of truth for regime allocations, and `engine.py` should match it exactly. The UI should render the same regime cards and allocation logic.

---

## Manual IFT and G Fund Behavior

### Normal IFTs
Normal IFT confirmations:
- are manual
- increment the monthly IFT counter
- write to the transaction audit trail
- must respect the 2-IFT monthly limit

### Pure G Fund Safety Move
A pure 100% G allocation is treated as a TSP-safe safety move:
- it does not consume a monthly IFT
- it does not count toward the normal 2-IFT cap
- it is still recorded by the app as a safety action

This supports the TSP rule that moving to G can be handled as a special safety path.

---

## Files and Roles

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

The app also contains the detailed Engine Decision Breakdown section and the regime summary cards.

### `engine.py`
Core decision logic.

It:
- scores macro and market inputs
- selects the regime
- applies allocation adjustments
- handles panic and emergency logic
- applies F Fund unlock logic
- applies asymmetric volatility and strong DXY adjustments
- determines IFT eligibility

Important:
- `engine.py` should use the same baseline regime allocations as `constants.py`
- emergency and F Fund overlay logic should remain intact
- IFT gating is functional, but if stricter turnover control is desired, it may need further tightening

### `data_sources.py`
External data acquisition.

It fetches or derives market and macro inputs and provides fallback handling if live data is unavailable.

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

`REGIME_DEFINITIONS` and the derived allocation structures should remain synchronized with the engine and UI.

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

### `validation.py`
Validation helpers for:
- allocation totals
- input quality
- market data structure

### `ift_state_machine.py`
IFT rule utilities for:
- pure G move detection
- monthly IFT cap logic
- state machine enforcement

---

## Important Current Design Decisions

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

Do not let the recommendation path and confirmation path both update the IFT state.

### 3) The app is tactical, not lifecycle
This is not intended to mimic TSP L Funds.

The regime logic is meant to be:
- quantitative
- rule-based
- adaptable
- responsive to changing macro conditions

---

## Current UI Details

### Regime Directory
The app shows regime cards for the tactical allocation set.

### Detailed Decision Breakdown
The app includes a detailed decision expander with:
- summary
- factor score detail
- factor interpretation
- regime / allocation build
- IFT logic

### Proxy Chart Default
The performance chart timeframe defaults to `10 Years`.

---

## Known Issues / Things to Watch

### 1) Possible mismatch if files are edited independently
If allocations are changed in one place but not others, the app can show one set of numbers while the engine calculates another.

Keep these aligned:
- `constants.py`
- `engine.py`
- `app.py`
- optionally `storage.py` default config

### 2) Transaction history should reflect actual confirmations
Only confirmed IFTs should be written to `tsp_transactions.csv`.

### 3) IFT gate could still be tightened further
The current app supports a G-only safety move path, but the underlying engine eligibility logic may still be more permissive than desired if you want stricter turnover control.

### 4) Flat-file persistence is intentionally lightweight
This is appropriate for a single-user Streamlit workflow, but it is not concurrency-safe.

---

## Suggested Next Steps for the Next AI

Help incorporate additional macro context such as:
- yield curve dynamics
- inflation shocks
- central bank policy and liquidity
- global growth trends
- risk-on / risk-off regimes

Ensure logic respects the TSP rule of only two Interfund Transfers per calendar month. Actively guard against:
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

## Conversation Context to Preserve

The user prefers:
- plain English explanations
- tactical and quantitative framing
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

## Notes for Future Edits

If you change the regime mix again:
- update `constants.py`
- update `engine.py`
- update `app.py` UI labels
- update `storage.py` defaults if needed
- update regime consistency tests

Keep all of them synchronized.

If you change the IFT workflow:
- ensure only one path updates count and history
- recommendation should remain separate from confirmation
- G-only safety moves should be visually obvious

---

## Short Summary for the Next AI

This is a tactical TSP engine with updated allocations, manual IFT confirmation, a pure G Fund safety move path, and a detailed decision UI. The main remaining risk is file mismatch between `engine.py`, `app.py`, `constants.py`, and `storage.py`. Keep baseline regime allocations synchronized and preserve the manual confirmation workflow.
