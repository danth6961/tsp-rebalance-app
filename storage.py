"""
storage.py — persistence and local state management.

Owns config/state load-save, CSV append helpers, and monthly state rollover.
Does not own engine logic, UI logic, regime selection, or data fetching.
"""

import csv
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Callable
from datetime import date

from constants import STATE_FILE, CONFIG_FILE, LOG_FILE, TRANSACTION_FILE, BASELINE_ALLOCATIONS


def safe_save_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Save JSON with a simple backup copy of the previous file."""
    if file_path.exists() and file_path.stat().st_size > 0:
        shutil.copy(file_path, file_path.with_suffix(".json.bak"))
    temp_file = file_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    temp_file.replace(file_path)


def safe_load_json(file_path: Path, default_factory: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Load JSON, falling back to .bak and then to the default factory."""
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
    """Load persisted state without applying monthly rollover."""
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
    """Reset monthly counters and recent history when the month changes."""
    current_month = today.strftime("%Y-%m")
    if state.get("month") != current_month:
        state["month"] = current_month
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []
    return state


def load_state_for_today(today: date) -> Dict[str, Any]:
    """Load state and apply monthly rollover in one step."""
    return roll_state_if_new_month(load_state(), today)


MAX_HISTORY_ENTRIES = 90


def save_state(state_data: Dict[str, Any]) -> None:
    """Save state after trimming history lists to the configured maximum."""
    for key in ("recent_regimes", "recent_scores", "recent_allocations"):
        values = state_data.get(key)
        if isinstance(values, list) and len(values) > MAX_HISTORY_ENTRIES:
            state_data[key] = values[-MAX_HISTORY_ENTRIES:]
    safe_save_json(STATE_FILE, state_data)


def default_config() -> Dict[str, Any]:
    """Build the default config using the neutral allocation from constants."""
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
    """Load config and overlay it on top of defaults."""
    base = default_config()
    loaded = safe_load_json(CONFIG_FILE, lambda: {})
    base.update(loaded)
    return base


def save_config(config_data: Dict[str, Any]) -> None:
    """Persist config to disk."""
    safe_save_json(CONFIG_FILE, config_data)


def append_log_row(row: Dict[str, Any]) -> None:
    """Append one daily log row to the CSV file."""
    file_exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_transaction_row(date_str: str, from_alloc: Dict[str, float], to_alloc: Dict[str, float], regime: str) -> None:
    """Append one confirmed IFT transaction row to the audit CSV."""
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
