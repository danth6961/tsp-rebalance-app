# Project Handoff

## Purpose

This project is a Streamlit-based tactical TSP allocation assistant.

It analyzes macro and market data, scores the current environment, selects a regime, recommends a target allocation, and helps decide whether to submit an IFT or hold. The system is intentionally tactical, quantitative, transparent, and manually confirmable for IFT tracking.

The current architecture is organized around a few clear boundaries:

- `app.py` handles orchestration and Streamlit UI wiring
- `engine.py` handles scoring, regime selection, allocation logic, and IFT recommendation
- `data_sources.py` handles market data acquisition and snapshot assembly
- `storage.py` handles persistence and state management
- `ui.py` provides reusable rendering helpers
- `styles.py` owns CSS and visual tokens
- `constants.py` contains shared defaults, paths, thresholds, and regime definitions
- `models.py` defines typed domain structures
- `validation.py` checks data and allocation integrity
- `ift_state_machine.py` enforces monthly IFT rules and pure-G safety behavior
- `utils.py` contains generic helper functions

The biggest earlier risk was drift across allocations, thresholds, and IFT rules. That risk has been materially reduced by centralizing regime definitions in `constants.py` and by using consistency tests to keep the major modules aligned  

---

## Current High-Level Behavior

### Main Flow
1. Load config and state.
2. Fetch live or fallback market data.
3. Validate the snapshot.
4. Score the market.
5. Select a regime.
6. Build target allocation.
7. Compare current vs target allocation.
8. Determine HOLD vs SUBMIT IFT.
9. Display detailed reasoning.
10. Save state and log the run.
11. Manually confirm any actual IFT action.

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
- style injection at startup

The app should remain a thin controller. It should not own CSS definitions, regime definitions, or business-rule logic.

### `engine.py`
Core decision logic.

It:
- scores macro and market inputs
- selects the regime
- applies allocation adjustments
- handles panic/emergency logic
- applies F Fund unlock logic
- applies asymmetric volatility and strong DXY adjustments
- determines IFT recommendation

Important:
- `engine.py` should use the same baseline regime allocations as `constants.py`
- emergency and F Fund overlay logic should remain intact
- any remaining IFT gating nuances should stay inside the engine / IFT state-machine boundary, not in the UI

### `data_sources.py`
External data acquisition.

It fetches or derives market and macro inputs and provides fallback handling if live data is unavailable.

The source layer should also surface provenance and freshness metadata where possible so the UI can distinguish live, stale, and fallback inputs.

### `storage.py`
Persistence layer.

It stores:
- config
- state
- daily run log
- transaction audit trail

This should remain lightweight flat-file persistence unless the project grows into a concurrent or multi-user deployment.

### `ui.py`
Reusable UI helpers.

It contains:
- metric cards
- history table
- score chart
- allocation chart
- editable metric tile rendering
- decision breakdown rendering helpers

`ui.py` should remain presentation-only. It may emit class names and markup, but it should not contain CSS definitions.

### `styles.py`
CSS and visual tokens.

This module owns:
- layout spacing
- pills
- KPI cards
- chart containers
- badge colors
- visual tokens used by the UI

`app.py` should inject styles once at startup. `ui.py` should rely on the class names and tokens provided by this module.

### `constants.py`
Shared constants and defaults.

Current important values:
- file paths
- proxy tickers
- default market inputs
- baseline allocations
- stable thresholds
- regime definitions

`REGIME_DEFINITIONS` is the canonical registry. `BASELINE_ALLOCATIONS` should be derived from it rather than maintained separately by hand.

### `models.py`
Typed dataclasses for:
- market data
- engine result
- config
- app state
- transaction records, if formalized further

### `validation.py`
Validation helpers for:
- allocation totals
- market data structure
- value ranges
- freshness / fallback quality checks

### `ift_state_machine.py`
IFT rule utilities for:
- pure-G move detection
- monthly IFT cap logic
- confirmation eligibility
- state transition enforcement

### `utils.py`
Generic helpers:
- time handling
- parsing
- small utility support

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

Do not let the recommendation path and the confirmation path both update the IFT state.

### 3) The app is tactical, not lifecycle
This is not intended to mimic TSP L Funds.

The regime logic is meant to be:
- quantitative
- rule-based
- adaptable
- responsive to changing macro conditions

### 4) Styling is separate from orchestration
Do not keep large CSS blocks inside `app.py`.

If styling changes are needed, update `styles.py` first and keep `ui.py` focused on rendering semantics only.

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
- `storage.py`
- `ui.py`
- `validation.py`
- `ift_state_machine.py`

### 2) Transaction history should reflect actual confirmations
Only confirmed IFTs should be written to `tsp_transactions.csv`.

### 3) IFT gate could still be tightened further
The current app supports a G-only safety move path, but the underlying engine eligibility logic may still be more permissive than desired if you want stricter turnover control.

### 4) Flat-file persistence is intentionally lightweight
This is appropriate for a single-user Streamlit workflow, but it is not concurrency-safe.

### 5) Source quality should be made more explicit
Live, fallback, stale, and partial snapshots should be easier to distinguish in the UI.

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

Also help keep the UI and style layers cleanly separated:
- `ui.py` for rendering semantics
- `styles.py` for CSS
- `app.py` for orchestration

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

If you change the IFT workflow:
- ensure only one path updates count and history
- recommendation should remain separate from confirmation
- G-only safety moves should be visually obvious

If you change styling:
- update `styles.py`
- keep `ui.py` presentation-only
- avoid large inline CSS in `app.py`

---

## Short Summary for the Next AI

This is a tactical TSP engine with updated allocations, manual IFT confirmation, a pure G Fund safety move path, and a detailed decision UI. The main remaining risks are file mismatch between `engine.py`, `app.py`, `constants.py`, and `storage.py`, plus source-quality ambiguity in the data layer. Keep baseline regime allocations synchronized, preserve the manual confirmation workflow, and keep styling isolated in `styles.py`.
