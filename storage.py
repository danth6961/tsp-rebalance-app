"""
storage.py — persistence and local state management.

Owns:
- config load/save
- state load/save
- daily log append
- transaction log append
- month rollover helpers

Does not own:
- engine scoring
- UI logic
- regime selection
- data fetching
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

# Explicit CSV column orders prevent accidental schema drift.
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
    """Atomically save JSON to disk.

    Parameters
    ----------
    file_path:
        Destination JSON file.
    data:
        Serializable payload to write.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

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

    os.replace(tmp_path, file_path)


def safe_load_json(
    file_path: Path,
    default_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Load JSON, falling back to .bak and then to the default factory."""
    if file_path.exists():
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    bak_path = file_path.with_suffix(file_path.suffix + ".bak")
    if bak_path.exists():
        try:
            with bak_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Restore the backup if it was valid.
            safe_save_json(file_path, data)
            return data
        except Exception:
            pass

    return default_factory()


# -----------------------------------------------------------------------------
# State defaults and rollover
# -----------------------------------------------------------------------------


def default_state() -> dict[str, Any]:
    """Return the default persisted application state."""
    return {
        "month": date.today().strftime("%Y-%m"),
        "ift_count_this_month": 0,
        "last_ift_date": None,
        "last_run_date": None,
        "recent_regimes": [],
        "recent_scores": [],
        "recent_allocations": [],
        "last_confirmation_key": None,
    }


def load_state() -> dict[str, Any]:
    """Load persisted state without applying monthly rollover."""
    state = safe_load_json(STATE_FILE, default_state)

    # Ensure required keys always exist even if the file was manually edited.
    state.setdefault("month", date.today().strftime("%Y-%m"))
    state.setdefault("ift_count_this_month", 0)
    state.setdefault("last_ift_date", None)
    state.setdefault("last_run_date", None)
    state.setdefault("recent_regimes", [])
    state.setdefault("recent_scores", [])
    state.setdefault("recent_allocations", [])
    state.setdefault("last_confirmation_key", None)

    return state


def roll_state_if_new_month(state: dict[str, Any], today: date) -> dict[str, Any]:
    """Reset monthly counters and recent history when the month changes."""
    current_month = today.strftime("%Y-%m")
    if state.get("month") != current_month:
        state["month"] = current_month
        state["ift_count_this_month"] = 0
        state["recent_regimes"] = []
        state["recent_scores"] = []
        state["recent_allocations"] = []
        state["last_confirmation_key"] = None
    return state


def load_state_for_today(today: date) -> dict[str, Any]:
    """Load state and apply monthly rollover in one step."""
    return roll_state_if_new_month(load_state(), today)


def save_state(state_data: dict[str, Any]) -> None:
    """Save state after trimming bounded history lists."""
    for key in ("recent_regimes", "recent_scores", "recent_allocations"):
        values = state_data.get(key)
        if isinstance(values, list) and len(values) > MAX_HISTORY_ENTRIES:
            state_data[key] = values[-MAX_HISTORY_ENTRIES:]

    safe_save_json(STATE_FILE, state_data)


# -----------------------------------------------------------------------------
# Config defaults and persistence
# -----------------------------------------------------------------------------


def default_config() -> dict[str, Any]:
    """Build the default config using the neutral allocation from constants."""
    neutral_alloc = {
        fund: float(weight)
        for fund, weight in BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"].items()
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
    """Load config and overlay it on top of defaults."""
    base = default_config()
    loaded = safe_load_json(CONFIG_FILE, lambda: {})
    base.update(loaded)
    return base


def save_config(config_data: dict[str, Any]) -> None:
    """Persist config to disk."""
    safe_save_json(CONFIG_FILE, config_data)


# -----------------------------------------------------------------------------
# CSV append helpers
# -----------------------------------------------------------------------------


def append_log_row(row: dict[str, Any]) -> None:
    """Append one daily log row to the CSV file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_transaction_row(
    date_str: str,
    from_alloc: dict[str, float],
    to_alloc: dict[str, float],
    regime: str,
) -> None:
    """Append one confirmed IFT transaction row to the audit CSV."""
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
        writer = csv.DictWriter(f, fieldnames=TRANSACTION_FIELDS, extrasaction="ignore")
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
