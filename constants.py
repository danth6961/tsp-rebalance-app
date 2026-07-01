from __future__ import annotations

from pathlib import Path

# -----------------------------------------------------------------------------
# Runtime and retry configuration
# -----------------------------------------------------------------------------
# These values are shared across data fetching, caching, and app orchestration.
# Keep them here so the rest of the codebase does not hardcode operational
# behavior in multiple places.
# -----------------------------------------------------------------------------
MAX_RETRIES: int = 3
RETRY_SLEEP_SEC: float = 1.5
CACHE_TTL_SEC: int = 3600

# -----------------------------------------------------------------------------
# Persistence file locations
# -----------------------------------------------------------------------------
# Flat-file persistence is acceptable for a single-user Streamlit application,
# but the paths must remain centralized so storage.py, app.py, and tests all
# reference the same canonical locations.
# -----------------------------------------------------------------------------
STATE_FILE: Path = Path("tsp_state.json")
CONFIG_FILE: Path = Path("tsp_config.json")
LOG_FILE: Path = Path("tsp_daily_log.csv")
TRANSACTION_FILE: Path = Path("tsp_transactions.csv")

# -----------------------------------------------------------------------------
# Default fallback market / macro values
# -----------------------------------------------------------------------------
# These values are used when live data is unavailable or a source fails.
# They should be treated as fallback inputs and not as live observations.
# -----------------------------------------------------------------------------
DEFAULTS: dict[str, float] = {
    "core_pce_yoy": 3.4,
    "ism_pmi": 54.0,
    "services_pmi": 54.5,
    "initial_claims": 215.0,
    "breakeven_inflation": 2.25,
    "fed_assets_growth_yoy": -4.5,
    "real_yield_10y": 2.00,
    "move_index": 105.0,
    "sloos_net_pct": 6.6,
    "hy_oas": 2.76,
    "shiller_cape": 39.66,
    "fwd_eps_growth_yoy": 31.21,
    "stlfsi_index": -0.9568,
    "bond_yield_3m": 4.20,
    "bond_yield_10y": 4.50,
    "market_breadth_pct": 73.20,
    "vix_spot": 19.0,
    "dxy_spot": 105.80,
    "spx_spot": 5000.0,
}

# -----------------------------------------------------------------------------
# Macro / market thresholds
# -----------------------------------------------------------------------------
# DXY tilt threshold is intentionally centralized so the engine, tests, and
# documentation all use the exact same trigger level.
# -----------------------------------------------------------------------------
DXY_TILT_THRESHOLD: float = 103.5

# -----------------------------------------------------------------------------
# Fund proxy symbols
# -----------------------------------------------------------------------------
# These proxies are used when the app needs market-surrogate instruments for
# display, validation, or historical approximation.
# -----------------------------------------------------------------------------
PROXIES: dict[str, str] = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL",
}

# -----------------------------------------------------------------------------
# Regime definitions
# -----------------------------------------------------------------------------
# This is the single source of truth for regime names, descriptions, display
# metadata, and canonical allocations.
#
# Other modules should import from here instead of duplicating allocations or
# labels. This prevents drift between engine.py, app.py, ui.py, and storage.py.
# -----------------------------------------------------------------------------
REGIME_DEFINITIONS: dict[str, dict[str, object]] = {
    "RISK-ON OVERRIDE": {
        "icon": "🚀",
        "score_label": "Score: ≥ +5",
        "profile": "Aggressive Profile",
        "allocation": {"G": 30, "C": 40, "I": 20, "S": 10, "F": 0},
        "description": "Strong macro backdrop and solid upward momentum.",
        "color": "#10b981",
        "bg": "rgba(16, 185, 129, 0.08)",
    },
    "OPTIMIZED NEUTRAL": {
        "icon": "⚖️",
        "score_label": "Score: 0 to +4",
        "profile": "Balanced Profile",
        "allocation": {"G": 40, "C": 30, "I": 20, "S": 10, "F": 0},
        "description": "Default balanced state when signals are constructive but mixed.",
        "color": "#3b82f6",
        "bg": "rgba(59, 130, 246, 0.08)",
    },
    "DEFENSIVE ALLOCATION": {
        "icon": "🛡️",
        "score_label": "Score: < 0",
        "profile": "Defensive Profile",
        "allocation": {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0},
        "description": "Used when risk rises or the composite turns negative.",
        "color": "#f59e0b",
        "bg": "rgba(245, 158, 11, 0.08)",
    },
    "EMERGENCY DISPATCH": {
        "icon": "🚨",
        "score_label": "Score: -50",
        "profile": "Maximum Defense",
        "allocation": {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0},
        "alloc_display": "G 90% / F 10% (or G 100% / F 0%)",
        "description": "3-day panic valve breach.",
        "color": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.08)",
    },
}

# -----------------------------------------------------------------------------
# Regime display order
# -----------------------------------------------------------------------------
# Keep the order stable for UI cards, dropdowns, and documentation.
# -----------------------------------------------------------------------------
REGIME_ORDER: list[str] = [
    "RISK-ON OVERRIDE",
    "OPTIMIZED NEUTRAL",
    "DEFENSIVE ALLOCATION",
    "EMERGENCY DISPATCH",
]

# -----------------------------------------------------------------------------
# Derived allocation map
# -----------------------------------------------------------------------------
# This is generated from REGIME_DEFINITIONS to prevent drift. The emergency
# F-unlocked variant is exposed as an overlay allocation rather than a full
# top-level regime card.
# -----------------------------------------------------------------------------
BASELINE_ALLOCATIONS: dict[str, dict[str, int]] = {
    name: dict(info["allocation"]) for name, info in REGIME_DEFINITIONS.items()
}
BASELINE_ALLOCATIONS["EMERGENCY DISPATCH (F-Unlocked)"] = {
    "G": 90,
    "C": 0,
    "I": 0,
    "S": 0,
    "F": 10,
}

# -----------------------------------------------------------------------------
# Explicit public exports
# -----------------------------------------------------------------------------
# This keeps the module interface clear and prevents accidental reliance on
# internal helper names if new constants are added later.
# -----------------------------------------------------------------------------
__all__: list[str] = [
    "MAX_RETRIES",
    "RETRY_SLEEP_SEC",
    "CACHE_TTL_SEC",
    "STATE_FILE",
    "CONFIG_FILE",
    "LOG_FILE",
    "TRANSACTION_FILE",
    "DEFAULTS",
    "DXY_TILT_THRESHOLD",
    "PROXIES",
    "REGIME_DEFINITIONS",
    "REGIME_ORDER",
    "BASELINE_ALLOCATIONS",
]
