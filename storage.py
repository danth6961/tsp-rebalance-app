"""
Author: Donald J Anthony
Date: Today's Date

storage.py — Persistence and local state management.

Owns:
    - Config load/save
    - State load/save
    - Daily log append
    - Transaction log append
    - Month rollover helpers

Does not own:
    - Engine scoring
    - UI logic
    - Regime selection
    - Data fetching
    - IFT decision logic
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Callable

from constants import BASELINE_ALLOCATIONS, CONFIG_FILE, LOG_FILE, STATE_FILE, TRANSACTION_FILE

# -----------------------------------------------------------------------------
# Persistence tuning
# -----------------------------------------------------------------------------
# Keep history bounded so state files do not grow without limit in a long-lived
# Streamlit session.
# -----------------------------------------------------------------------------
MAX_HISTORY_ENTRIES: int = 90

# Explicit CSV column orders to prevent accidental schema drift.
DAILY_LOG_FIELDS: list[str] = [
    "date",
    "action",
    "reason",
    "regime",
    "total_score",
    "ift_count_this_month",
    "current_alloc",
    "target_alloc",
    "vix",
    "spx_200sma_dist",
    "drawdown_pct",
]

TRANSACTION_FIELDS: list[str] = [
    "date",
    "regime",
    "from_G",
    "from_C",
    "from_I",
    "from_S",
    "from_F",
    "to_G",
    "to_C",
    "to_I",
    "to_S",
    "to_F",
]


# -----------------------------------------------------------------------------
# Atomic JSON helpers
# -----------------------------------------------------------------------------
# Writes a temporary file in the same directory and replaces the target only
# after the write succeeds.
# -----------------------------------------------------------------------------
def safe_save_json(file_path: Path, data: dict[str, Any]) -> None:
    """
    Atomically save JSON to disk.

    Parameters
    ----------
    file_path : Path
        Destination JSON file.
    data : dict[str, Any]
        Serializable payload to write.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file in the same directory.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=file_path.parent,
        delete=False,
    ) as tmp:
        json.dump(data, tmp, indent=4, sort_keys=True, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)

    # Atomically replace the target file with the temporary file.
    os.replace(tmp_path, file_path)


def safe_load_json(
    file_path: Path,
    default_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """
    Load JSON from file, with fallback to a backup file and then a default.

    Parameters
    ----------
    file_path : Path
        Path to the target JSON file.
    default_factory : Callable[[], dict[str, Any]]
        Function to produce a default dictionary if no file is found.

    Returns
    -------
    dict[str, Any]
        Loaded JSON data or default.
    """
    if file_path.exists():
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback to backup file.
    bak_path = file_path.with_suffix(file_path.suffix + ".bak")
    if bak_path.exists():
        try:
            with bak_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Restore the backup to the original file.
            safe_save_json(file_path, data)
            return data
        except Exception:
            pass

    return default_factory()


# -----------------------------------------------------------------------------
# State defaults and rollover
# -----------------------------------------------------------------------------
def default_state() -> dict[str, Any]:
    """
    Return the default persisted application state.

    Returns
    -------
    dict[str, Any]
        Default state dictionary.
    """
    return {
        "month": date.today().strftime("%Y-%m"),
        "ift_count_this_month": 0,
        "last_ift_date": None,
        "last_run_date": None,
        "recent_regimes": [],
        "recent_scores": [],
        "recent_allocations": [],
        "recent_run_dates": [],
        "last_confirmation_key": None,
    }


def load_state() -> dict[str, Any]:
    """
    Load persisted state without applying monthly rollover.

    Ensures required keys exist even if the file was modified manually.

    Returns
    -------
    dict[str, Any]
        Current persisted state.
    """
    state = safe_load_json(STATE_FILE, default_state)

    # Ensure all required keys exist with default values.
    state.setdefault("month", date.today().strftime("%Y-%m"))
    state.setdefault("ift_count_this_month", 0)
    state.setdefault("last_ift_date", None)
    state.setdefault("last_run_date", None)
    state.setdefault("recent_regimes", [])
    state.setdefault("recent_scores", [])
    state.setdefault("recent_allocations", [])
    state.setdefault("recent_run_dates", [])
    state.setdefault("last_confirmation_key", None)

    return state


def roll_state_if_new_month(state: dict[str, Any], today: date) -> dict[str, Any]:
    """
    Reset monthly counters and recent history when the month changes.

    Parameters
    ----------
    state : dict[str, Any]
        The current persisted state.
    today : date
        Today's date used for comparison.

    Returns
    -------
    dict[str, Any]
        Updated state with counters reset if a new month is detected.
    """
    current_month = today.strftime("%Y-%m")
    if state.get("month") != current_month:
        state["month"] = current_month
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []
        state["recent_run_dates"] = []
        state["last_confirmation_key"] = None
    return state


def load_state_for_today(today: date) -> dict[str, Any]:
    """
    Load state and apply monthly rollover in one step.

    Parameters
    ----------
    today : date
        Current date.

    Returns
    -------
    dict[str, Any]
        State updated with monthly rollover logic.
    """
    return roll_state_if_new_month(load_state(), today)


def save_state(state_data: dict[str, Any]) -> None:
    """
    Save persisted state after trimming history lists to a maximum length.

    Parameters
    ----------
    state_data : dict[str, Any]
        The state dictionary to persist.
    """
    # Trim history lists to prevent unbounded growth.
    for key in ("recent_regimes", "recent_scores", "recent_allocations", "recent_run_dates"):
        values = state_data.get(key)
        if isinstance(values, list) and len(values) > MAX_HISTORY_ENTRIES:
            state_data[key] = values[-MAX_HISTORY_ENTRIES:]

    safe_save_json(STATE_FILE, state_data)


# -----------------------------------------------------------------------------
# Config defaults and persistence
# -----------------------------------------------------------------------------
def default_config() -> dict[str, Any]:
    """
    Build the default configuration using the neutral allocation from constants.

    Returns
    -------
    dict[str, Any]
        Default configuration settings.
    """
    neutral_alloc = {
        k: float(v)
        for k, v in BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"].items()
    }
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


def load_config() -> dict[str, Any]:
    """
    Load configuration from disk and overlay it on top of the defaults.

    Returns
    -------
    dict[str, Any]
        Merged configuration dictionary.
    """
    base = default_config()
    loaded = safe_load_json(CONFIG_FILE, lambda: {})
    base.update(loaded)
    return base


def save_config(config_data: dict[str, Any]) -> None:
    """
    Persist configuration to disk.

    Parameters
    ----------
    config_data : dict[str, Any]
        Configuration dictionary to save.
    """
    safe_save_json(CONFIG_FILE, config_data)


# -----------------------------------------------------------------------------
# CSV append helpers
# -----------------------------------------------------------------------------
def append_log_row(row: dict[str, Any]) -> None:
    """
    Append one daily log row to the CSV file.

    Parameters
    ----------
    row : dict[str, Any]
        A dictionary representing a single row in the daily log.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=DAILY_LOG_FIELDS,
            extrasaction="ignore",
        )
        # Write header if CSV is being created.
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_transaction_row(
    date_str: str,
    from_alloc: dict[str, float],
    to_alloc: dict[str, float],
    regime: str,
) -> None:
    """
    Append one confirmed IFT transaction row to the audit CSV.

    Parameters
    ----------
    date_str : str
        ISO-formatted date string for the transaction.
    from_alloc : dict[str, float]
        Allocation before the transaction.
    to_alloc : dict[str, float]
        Allocation after the transaction.
    regime : str
        The regime associated with this transaction.
    """
    row: dict[str, Any] = {
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

    TRANSACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = TRANSACTION_FILE.exists()

    with TRANSACTION_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=TRANSACTION_FIELDS,
            extrasaction="ignore",
        )
        # Write header if file does not exist.
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


__all__ = [
    "MAX_HISTORY_ENTRIES",
    "DAILY_LOG_FIELDS",
    "TRANSACTION_FIELDS",
    "safe_save_json",
    "safe_load_json",
    "default_state",
    "load_state",
    "roll_state_if_new_month",
    "load_state_for_today",
    "save_state",
    "default_config",
    "load_config",
    "save_config",
    "append_log_row",
    "append_transaction_row",
]
