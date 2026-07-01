# Design Goals

The refactor should preserve the core behavior of the tactical TSP engine while making the codebase easier to maintain, test, and keep synchronized.

The current project already has the right broad module split: `app.py` handles orchestration and UI, `engine.py` handles scoring and allocation logic, `data_sources.py` handles market data, `storage.py` handles persistence, `ui.py` provides reusable rendering helpers, `constants.py` contains defaults and paths, and `models.py` defines typed structures.

The main goals of the refactor are:

- keep recommendation separate from manual confirmation
- preserve the pure G Fund safety move path
- keep F Fund conditional only
- remove duplicated regime definitions
- make the module boundaries explicit
- reduce the risk of drift between UI, engine, and storage defaults

---

# Proposed Target Architecture

## 1) `constants.py`

### Owns
- file paths
- default inputs
- proxy ticker mapping
- shared regime definitions
- any truly global static labels or thresholds

### Should contain
- `STATE_FILE`
- `CONFIG_FILE`
- `LOG_FILE`
- `TRANSACTION_FILE`
- `DEFAULTS`
- `PROXIES`
- `REGIME_DEFINITIONS`
- `BASELINE_ALLOCATIONS` as a derived alias if backward compatibility is needed

### Should not contain
- scoring logic
- Streamlit code
- persistence functions
- data fetching logic

### Why
This file should be the single source of truth for allocations and regime names. Right now, the tactical baselines exist in `constants.py`, but similar values are also hardcoded in `engine.py` and `app.py`, which creates drift risk.

---

## 2) `models.py`

### Owns
Typed domain objects only.

### Should contain
- `MarketData`
- `EngineResult`
- `Config`
- `AppState`
- optionally a `TransactionRecord` dataclass if you want to formalize audit rows

### Should not contain
- business logic
- file I/O
- UI code
- API calls

### Why
The current dataclasses already form a good contract between the major modules, especially `MarketData`, `EngineResult`, `Config`, and `AppState`.

---

## 3) `data_sources.py`

### Owns
All external data acquisition and market snapshot building.

### Should contain
- live market fetches
- fallback merge logic
- source provenance
- derived market snapshot assembly
- proxy price helpers

### Should return
A normalized `MarketData` object or a plain dict compatible with `models.py`

### Should not contain
- regime logic
- scoring
- persistence
- UI state mutation

### Why
This keeps “what data do we have right now?” in one place, which is important because the app already relies on live/fallback behavior to stay functional when external feeds fail.

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

### Why
The engine is the heart of the tactical system. The scoring guide shows that it already carries the core factor and macro overlay rules, and the app renders those decisions for transparency.

### Important rule
`engine.py` should never hardcode regime allocations. It should import them from `constants.py`.

---

## 5) `storage.py`

### Owns
Persistence and state management only.

### Should contain
- load/save config
- load/save state
- append log row
- append transaction row
- safe JSON helpers
- backup/restore behavior

### Should not contain
- engine scoring
- UI logic
- regime selection
- data fetching logic

### Why
`storage.py` is already the right place for atomic-ish JSON persistence and CSV audit logging, but its neutral startup config currently duplicates the tactical neutral allocation literal, which should be derived from `constants.py` instead.

---

## 6) `ui.py`

### Owns
Reusable rendering helpers.

### Should contain
- metric cards
- editable metric tile rendering
- history tables
- score chart helpers
- allocation comparison chart
- recent state cards
- regime card rendering helpers

### Should not contain
- engine logic
- file I/O
- state mutation
- business rules

### Why
The current `ui.py` is already doing this well, with reusable helpers like `recent_state_cards`, `render_history_table`, `make_score_chart`, and `make_alloc_chart`.

---

## 7) `app.py`

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

### Should not contain
- scoring logic
- allocation math
- persistence internals
- data source internals
- regime definitions
- hardcoded regime dictionaries

### Why
`app.py` is currently doing a lot: sidebar controls, manual submit handling, run history, transaction history, daily logs, and decision breakdown rendering. That is workable, but the target should be a thinner controller layer.

---

## 8) `utils.py`

### Owns
Generic helpers that do not belong anywhere else.

### Good candidates
- time helpers
- parsing helpers
- safe numeric conversion
- date formatting
- small allocation formatting helpers

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
3. `engine.py`
4. `storage.py`
5. `ui.py`

### Flow detail
- `app.py` loads config/state via `storage.py`
- `app.py` fetches market snapshot via `data_sources.py`
- `app.py` passes snapshot into `engine.py`
- `engine.py` returns an `EngineResult`
- `app.py` renders the result using `ui.py`
- `app.py` confirms manual IFT actions via `storage.py`

This keeps recommendation and confirmation separate, which matches the project’s current workflow and safety rules.

---

# Recommended Dependency Direction

Use this dependency hierarchy:

- `constants.py` → imported by almost everything
- `models.py` → imported by engine/data/storage/app
- `utils.py` → imported by data/storage/engine as needed
- `data_sources.py` → depends on constants/models/utils
- `engine.py` → depends on constants/models/utils
- `storage.py` → depends on constants/models/utils
- `ui.py` → depends on models/utils
- `app.py` → depends on all of the above

## Avoid
- `engine.py` importing `app.py`
- `storage.py` importing `engine.py`
- `ui.py` importing `storage.py`
- `data_sources.py` importing `app.py`

---

# Suggested Internal Sub-Structure

## `engine.py`
- `score_core_factors()`
- `score_macro_overlays()`
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

## `ui.py`
- `render_metric_cards()`
- `render_history_table()`
- `make_score_chart()`
- `make_alloc_chart()`
- `render_regime_cards()`
- `render_decision_breakdown()`

## `app.py`
- `main()`
- `handle_run_clicked()`
- `handle_manual_submit_clicked()`
- `handle_config_save_clicked()`
- `handle_state_reset_clicked()`

---

# What to Move Out of `app.py` First

The best first extraction would be:

### Move to `ui.py`
- regime directory cards
- decision breakdown rendering
- allocation comparison formatting
- repeated captions and labels

### Move to `constants.py`
- regime names
- regime descriptions
- regime base allocations
- stable display ordering

---

# What the Final Shape Should Feel Like

After the refactor:

- `app.py` reads like a controller
- `engine.py` reads like a decision model
- `data_sources.py` reads like a data adapter
- `storage.py` reads like persistence
- `ui.py` reads like presentation helpers
- `constants.py` reads like project-wide truth
- `models.py` reads like contracts
- `utils.py` reads like small helpers

That is the clean target.
