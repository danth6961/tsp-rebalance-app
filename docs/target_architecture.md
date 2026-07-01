# Target Architecture

## Design Goals

The refactor should preserve the core behavior of the tactical TSP engine while making the codebase easier to maintain, test, and keep synchronized.

The project already has the right broad module split:

- `app.py` handles orchestration and Streamlit UI wiring
- `engine.py` handles scoring, regime selection, allocation logic, and IFT recommendation logic
- `data_sources.py` handles market data acquisition and snapshot assembly
- `storage.py` handles persistence and state management
- `ui.py` provides reusable rendering helpers
- `constants.py` contains shared defaults, file paths, thresholds, and regime definitions
- `models.py` defines typed domain structures
- `validation.py` checks data and allocation integrity
- `ift_state_machine.py` enforces monthly IFT rules and pure-G safety behavior
- `utils.py` contains generic helper functions

The main goals of the refactor are:

- keep recommendation separate from manual confirmation
- preserve the pure G Fund safety move path
- keep F Fund conditional only
- keep regime definitions centralized
- keep styling separate from app orchestration
- make module boundaries explicit
- reduce the risk of drift between UI, engine, storage, and validation defaults

---

## Target Module Layout

### Core logic
- `engine.py`
- `data_sources.py`
- `storage.py`
- `validation.py`
- `ift_state_machine.py`
- `models.py`
- `constants.py`
- `utils.py`

### Presentation
- `ui.py`
- `styles.py`

### Application entrypoint
- `app.py`

This separation keeps the decision engine, persistence layer, and presentation layer isolated from one another.

---

## 1) `constants.py`

### Owns
- file paths
- default inputs
- proxy ticker mapping
- shared regime definitions
- stable threshold constants
- any truly global labels or static configuration values

### Should contain
- `STATE_FILE`
- `CONFIG_FILE`
- `LOG_FILE`
- `TRANSACTION_FILE`
- `DEFAULTS`
- `PROXIES`
- `DXY_TILT_THRESHOLD`
- `REGIME_DEFINITIONS`
- `REGIME_ORDER`
- `BASELINE_ALLOCATIONS`

### Should not contain
- scoring logic
- Streamlit code
- persistence functions
- data fetching logic
- UI rendering logic

### Why
`constants.py` should be the single source of truth for allocations, regime names, and project-wide thresholds. The repository already contains tests that enforce alignment between `constants.py`, `engine.py`, `storage.py`, `ui.py`, `validation.py`, and `ift_state_machine.py`, which is exactly the right safeguard against drift .  

The current code also centralizes the DXY tilt threshold here, which is preferable because it removes hardcoded threshold drift between engine logic and scoring documentation .

### Recommended structure
`REGIME_DEFINITIONS` should be the authoritative regime registry.  
`BASELINE_ALLOCATIONS` should be derived from `REGIME_DEFINITIONS` so the allocations cannot silently diverge.

### Important note
Do not keep duplicate allocation maps anywhere else in the codebase.

---

## 2) `models.py`

### Owns
Typed domain objects only.

### Should contain
- `MarketData`
- `EngineResult`
- `Config`
- `AppState`
- `TransactionRecord` if audit rows are formalized further
- any small typed helper models used across modules

### Should not contain
- business logic
- file I/O
- UI code
- API calls

### Why
The current dataclasses already form the contract between modules, especially `MarketData`, `EngineResult`, `Config`, and `AppState`. Keeping these objects typed and minimal reduces ambiguity and makes the engine, storage, and UI layers easier to test and reason about.

---

## 3) `data_sources.py`

### Owns
All external data acquisition and market snapshot assembly.

### Should contain
- live market fetches
- fallback merge logic
- source provenance
- derived market snapshot assembly
- proxy price helpers
- freshness / quality metadata where possible

### Should return
A normalized `MarketData` object, or a plain dict that is immediately validated and normalized into a `MarketData` contract.

### Should not contain
- regime logic
- scoring
- persistence
- UI state mutation
- IFT state mutation

### Why
This keeps “what data do we have right now?” in one place, which matters because the app relies on live/fallback behavior to remain functional when external feeds fail. The remaining architectural improvement here is to make source quality and provenance more explicit so the UI can distinguish fresh live data from fallback or stale data.

### Recommended additions
Add metadata such as:
- `source`
- `timestamp`
- `is_fallback`
- `freshness`
- `confidence`

That would make the snapshot contract much easier to audit and would reduce the risk that fallback defaults masquerade as live inputs.

---

## 4) `engine.py`

### Owns
All tactical decision logic.

### Should contain
- factor scoring
- macro overlay scoring
- regime selection
- allocation construction
- emergency handling
- F Fund unlock logic
- DXY and asymmetric volatility overlays
- IFT recommendation logic
- allocation drift calculations
- regime explanation generation

### Should expose
Examples:
- `score_market_data(data) -> scores`
- `determine_allocation(data, scores, ...) -> result`
- `build_engine_result(...) -> EngineResult`
- `should_use_tsp_ift(...) -> decision`

### Should not contain
- Streamlit widgets
- file writes
- log formatting
- direct config editing
- CSS or presentation logic

### Why
The engine is the heart of the tactical system. The scoring guide shows that it already carries layered factor logic with core scores plus macro overlays, and the app renders those decisions for transparency.

### Important rule
`engine.py` should never hardcode regime allocations. It should import them from `constants.py`.

### Recommended internal decomposition
Break the engine into pure sub-functions such as:
- `score_inflation`
- `score_growth`
- `score_liquidity`
- `score_credit`
- `score_valuation`
- `score_stress`
- `score_momentum`
- `score_drawdown`
- `score_overlay_adjustments`
- `select_regime`
- `build_allocation`
- `should_recommend_ift`

### Why this matters
This makes the engine easier to test, easier to backtest, and easier to calibrate over time. It also reduces the chance that a new indicator accidentally gets mixed into an unrelated scoring block.

---

## 5) `ift_state_machine.py`

### Owns
IFT rule enforcement and state transitions.

### Should contain
- monthly IFT cap logic
- pure G Fund safety move detection
- confirmation eligibility checks
- state transition helpers
- month rollover behavior
- decision result objects for confirmations

### Should not contain
- regime scoring
- market logic
- UI code
- generic storage concerns

### Why
This module is one of the most important robustness improvements in the project. It gives the IFT rules a dedicated boundary instead of scattering them across the UI and engine.

### Recommended behavior
The state machine should be the only place that:
- decides whether a confirmation is allowed
- distinguishes a pure G safety move from a normal IFT
- updates IFT counters and confirmation state

No other module should mutate IFT state directly.

---

## 6) `validation.py`

### Owns
Validation and guardrail checks.

### Should contain
- market data validation
- allocation sum checks
- allocation key checks
- value range checks
- schema-like validation for engine inputs
- warnings for implausible or stale data

### Should not contain
- scoring logic
- UI code
- persistence logic
- IFT state mutations

### Why
Validation should protect the engine from bad inputs and should be simple, deterministic, and explicit. The current test suite already checks allocation sum integrity and market data behavior, which is a strong foundation for this layer .

### Recommended behavior
Validation should return structured issues rather than only booleans where possible. That makes it easier for the UI to explain what failed and why.

---

## 7) `storage.py`

### Owns
Persistence and state management only.

### Should contain
- load/save config
- load/save state
- append log row
- append transaction row
- safe JSON helpers
- backup / restore behavior
- month rollover helpers if they are strictly persistence-related

### Should not contain
- engine scoring
- UI logic
- regime selection
- data fetching logic
- IFT decision logic

### Why
`storage.py` is the right place for JSON persistence and CSV audit logging. It should derive its defaults from shared constants rather than recreating allocation literals.

### Recommended hardening
- atomic file writes
- schema validation on load
- explicit transaction row validation
- separate daily-run logging from confirmed transaction logging

### Design note
Keep persistence lightweight unless the project grows into a multi-user or concurrent environment. At that point, a proper data store would be preferable to flat-file persistence.

---

## 8) `ui.py`

### Owns
Reusable rendering helpers and presentation semantics.

### Should contain
- metric cards
- editable metric tile rendering
- history tables
- score chart helpers
- allocation comparison chart
- recent state cards
- regime card rendering helpers
- decision breakdown helpers
- HTML structure helpers for badges, pills, and compact UI tiles

### Should not contain
- engine logic
- file I/O
- state mutation
- business rules
- CSS definitions

### Why
The current UI layer is already doing the right kind of work: reusable rendering and display formatting. It should remain presentational, not policy-driven.

### Important separation
`ui.py` may emit HTML class names and component markup, but it should not own CSS rules themselves.

---

## 9) `styles.py`

### Owns
All CSS and visual tokens.

### Should contain
- layout padding
- card styling
- pill styling
- KPI / metric tile styling
- badge colors
- chart container styling
- theme adjustments
- reusable style tokens

### Should not contain
- app logic
- rendering logic
- data logic
- regime logic

### Why
The app currently contains inline style blocks, which mixes visual rules with orchestration code. Moving CSS into a dedicated `styles.py` file or external asset makes `app.py` thinner and keeps `ui.py` semantically clean.

### Recommended usage
`app.py` should call one style injection function at startup, and `ui.py` should render markup that simply references those classes.

### If styling grows further
If the CSS becomes extensive later, it can be moved from `styles.py` into an external `assets/styles.css` file without changing the overall architecture.

---

## 10) `app.py`

### Owns
Streamlit orchestration only.

### Should contain
- page layout
- sidebar controls
- config save/reset buttons
- manual override controls
- fetch/run button
- engine result display
- decision breakdown display
- transaction history display
- manual confirmation button
- G-only safety action handling
- log export / clear actions
- style injection call

### Should not contain
- scoring logic
- allocation math
- persistence internals
- data source internals
- regime definitions
- hardcoded regime dictionaries
- CSS definitions

### Why
`app.py` is currently doing a lot, which is acceptable for now but not ideal long-term. The target is a thinner controller layer that coordinates the modules rather than hosting business rules or style definitions.

### Desired shape
After refactoring, `app.py` should read like:
- load state
- fetch snapshot
- score snapshot
- render result
- handle confirmation
- persist updates

Nothing more.

---

## 11) `utils.py`

### Owns
Generic helpers that do not belong anywhere else.

### Good candidates
- time helpers
- parsing helpers
- safe numeric conversion
- date formatting
- small allocation formatting helpers
- snapshot quality helpers if they are truly generic

### Should not contain
- domain rules
- scoring logic
- UI code
- persistence logic

### Why
This keeps the utility layer from becoming a dumping ground.

---

# Recommended Module Boundaries in Practice

## Core flow

1. `app.py`
2. `data_sources.py`
3. `validation.py`
4. `engine.py`
5. `ift_state_machine.py`
6. `storage.py`
7. `ui.py`
8. `styles.py`

### Flow detail
- `app.py` loads config/state via `storage.py`
- `app.py` injects styles via `styles.py`
- `app.py` fetches a market snapshot via `data_sources.py`
- `validation.py` checks the snapshot
- `engine.py` scores the snapshot and returns an `EngineResult`
- `ui.py` renders the result
- `ift_state_machine.py` validates and records confirmation logic
- `storage.py` persists run state and transaction state

This keeps recommendation and confirmation separate and keeps presentation separate from decision logic.

---

# Recommended Dependency Direction

Use this dependency hierarchy:

- `constants.py` → imported by almost everything
- `models.py` → imported by engine/data/storage/app/validation/ui
- `utils.py` → imported by data/storage/engine/validation as needed
- `data_sources.py` → depends on constants/models/utils
- `validation.py` → depends on constants/models/utils
- `engine.py` → depends on constants/models/utils/validation
- `ift_state_machine.py` → depends on constants/models/storage
- `storage.py` → depends on constants/models/utils
- `ui.py` → depends on models/utils/constants
- `styles.py` → depends on nothing else
- `app.py` → depends on all of the above

## Avoid
- `engine.py` importing `app.py`
- `storage.py` importing `engine.py`
- `ui.py` importing `storage.py`
- `data_sources.py` importing `app.py`
- `styles.py` importing anything else

---

# Suggested Internal Sub-Structure

## `engine.py`
- `score_inflation()`
- `score_growth()`
- `score_liquidity()`
- `score_credit()`
- `score_valuation()`
- `score_stress()`
- `score_momentum()`
- `score_drawdown()`
- `score_overlay_adjustments()`
- `select_regime()`
- `apply_baseline_allocation()`
- `apply_f_fund_unlock()`
- `apply_overlays()`
- `should_recommend_ift()`

## `data_sources.py`
- `fetch_fred_series()`
- `fetch_yahoo_proxy_history()`
- `build_snapshot_from_sources()`
- `derive_overlay_signals()`

## `storage.py`
- `load_config()`
- `save_config()`
- `load_state()`
- `save_state()`
- `append_log_row()`
- `append_transaction_row()`

## `ift_state_machine.py`
- `is_pure_g_move()`
- `can_confirm()`
- `confirm()`
- `roll_month_if_needed()`

## `validation.py`
- `validate_market_data()`
- `validate_allocation_sums_to_100()`
- `validate_allocation_keys()`
- `validate_snapshot_quality()`

## `ui.py`
- `render_metric_cards()`
- `render_history_table()`
- `make_score_chart()`
- `make_alloc_chart()`
- `render_regime_cards()`
- `render_decision_breakdown()`

## `styles.py`
- `inject_styles()`
- shared CSS string constants

## `app.py`
- `main()`
- `handle_run_clicked()`
- `handle_manual_submit_clicked()`
- `handle_config_save_clicked()`
- `handle_state_reset_clicked()`

---

# What to Move Out of `app.py` First

### Move to `ui.py`
- regime directory cards
- decision breakdown rendering
- allocation comparison formatting
- repeated captions and labels

### Move to `styles.py`
- inline `<style>` block
- badge / pill / KPI / card CSS
- layout and hover styling

### Move to `constants.py`
- regime names
- regime descriptions
- regime base allocations
- stable display ordering

### Move to `engine.py`
- any remaining allocation selection logic still embedded in app-side helpers

### Move to `ift_state_machine.py`
- any remaining IFT eligibility or cap logic still embedded in app-side helpers

---

# What the Final Shape Should Feel Like

After the refactor:

- `app.py` reads like a controller
- `engine.py` reads like a decision model
- `data_sources.py` reads like a data adapter
- `storage.py` reads like persistence
- `ui.py` reads like presentation helpers
- `styles.py` reads like the visual system
- `constants.py` reads like project-wide truth
- `models.py` reads like contracts
- `validation.py` reads like guardrails
- `ift_state_machine.py` reads like execution safety
- `utils.py` reads like small helpers

That is the clean target.

---

# Bottom Line

The best architecture is:

- one source of truth in `constants.py`
- decision logic isolated in `engine.py`
- orchestration only in `app.py`
- reusable rendering in `ui.py`
- CSS isolated in `styles.py`
- persistence only in `storage.py`
- data acquisition only in `data_sources.py`
- typed contracts in `models.py`
- guardrails in `validation.py`
- IFT execution safety in `ift_state_machine.py`
- shared helpers in `utils.py`
