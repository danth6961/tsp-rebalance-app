"""
storage.py — Persistence layer only (config, state, CSV audit logs).

Owns: load/save config, load/save state, log/transaction append,
atomic-ish JSON read/write with backup fallback, and now the single
source of truth for monthly state rollover.

Should NOT contain: engine scoring, UI logic, regime selection,
data-fetching logic (see target_architecture.md).
"""
import csv
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Callable
from datetime import date

from constants import STATE_FILE, CONFIG_FILE, LOG_FILE, TRANSACTION_FILE, BASELINE_ALLOCATIONS


def safe_save_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically-ish, keeping a .bak copy of the prior version."""
    if file_path.exists() and file_path.stat().st_size > 0:
        shutil.copy(file_path, file_path.with_suffix(".json.bak"))
    temp_file = file_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    temp_file.replace(file_path)


def safe_load_json(file_path: Path, default_factory: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Load JSON, falling back to .bak, then to a fresh default on any failure."""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    bak_path = file_path.with_suffix(".json.bak")
    if bak_path.exists():
        try:
            with open(bak_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            shutil.copy(bak_path, file_path)
            return data
        except Exception:
            pass

    return default_factory()


def default_state() -> Dict[str, Any]:
    return {
        "month": date.today().strftime("%Y-%m"),
        "ift_count_this_month": 0,
        "last_ift_date": None,
        "last_run_date": None,
        "recent_regimes": [],
        "recent_scores": [],
        "recent_allocations": [],
    }


def load_state() -> Dict[str, Any]:
    """Load raw state from disk. Does NOT apply month rollover — use
    load_state_for_today() for that, unless you specifically need the
    on-disk state as-is (e.g. for a migration script)."""
    state = safe_load_json(STATE_FILE, default_state)

    state.setdefault("month", date.today().strftime("%Y-%m"))
    state.setdefault("ift_count_this_month", 0)
    state.setdefault("last_ift_date", None)
    state.setdefault("last_run_date", None)
    state.setdefault("recent_regimes", [])
    state.setdefault("recent_scores", [])
    state.setdefault("recent_allocations", [])

    return state


def roll_state_if_new_month(state: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    Reset monthly-scoped counters (IFT count, recent history) when the
    calendar month has changed since the state was last saved.

    This is the ONLY place month-rollover should happen. app.py must
    route all reads of monthly-scoped state through this function (or
    load_state_for_today below) rather than re-implementing the
    comparison inline — that duplication previously caused the IFT
    counter to display stale numbers on the 1st of a new month until
    the user clicked a button.
    """
    current_month = today.strftime("%Y-%m")
    if state.get("month") != current_month:
        state["month"] = current_month
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []
    return state


def load_state_for_today(today: date) -> Dict[str, Any]:
    """Load state from disk and apply month rollover in one call.

    This is the normal entrypoint app.py should use whenever the result
    will be used to display or act on ift_count_this_month / recent_*
    history.
    """
    return roll_state_if_new_month(load_state(), today)


# Caps how many daily entries recent_regimes/recent_scores/recent_allocations
# can hold. should_use_tsp_ift() and the confirmation-days check only ever
# look at the last (confirmation_days + 1) entries, so unbounded growth here
# was pure waste.
MAX_HISTORY_ENTRIES = 90


def save_state(state_data: Dict[str, Any]) -> None:
    for key in ("recent_regimes", "recent_scores", "recent_allocations"):
        values = state_data.get(key)
        if isinstance(values, list) and len(values) > MAX_HISTORY_ENTRIES:
            state_data[key] = values[-MAX_HISTORY_ENTRIES:]
    safe_save_json(STATE_FILE, state_data)


def default_config() -> Dict[str, Any]:
    # Tactical neutral starting point, derived from constants.py so it can
    # never drift out of sync with the engine's OPTIMIZED NEUTRAL baseline.
    neutral_alloc = {k: float(v) for k, v in BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"].items()}
    return {
        "current_alloc": neutral_alloc,
        "allow_second_ift": False,
        "normal_drift_threshold_pct": 7.5,
        "score_change_threshold": 3,
        "confirmation_days": 3,
        "cooldown_days": 5,
        "use_live_macro": True,
        "fred_api_key": "",
        "manual_override_enabled": False,
        "manual_regime": "OPTIMIZED NEUTRAL",
    }


def load_config() -> Dict[str, Any]:
    base = default_config()
    loaded = safe_load_json(CONFIG_FILE, lambda: {})
    base.update(loaded)
    return base


def save_config(config_data: Dict[str, Any]) -> None:
    safe_save_json(CONFIG_FILE, config_data)


def append_log_row(row: Dict[str, Any]) -> None:
    file_exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_transaction_row(date_str: str, from_alloc: Dict[str, float], to_alloc: Dict[str, float], regime: str) -> None:
    row = {
        "date": date_str,
        "regime": regime,
        "from_G": from_alloc.get("G", 0.0),
        "from_C": from_alloc.get("C", 0.0),
        "from_I": from_alloc.get("I", 0.0),
        "from_S": from_alloc.get("S", 0.0),
        "from_F": from_alloc.get("F", 0.0),
        "to_G": to_alloc.get("G", 0.0),
        "to_C": to_alloc.get("C", 0.0),
        "to_I": to_alloc.get("I", 0.0),
        "to_S": to_alloc.get("S", 0.0),
        "to_F": to_alloc.get("F", 0.0),
    }
    file_exists = TRANSACTION_FILE.exists()
    with TRANSACTION_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
