from pathlib import Path

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 1.5
CACHE_TTL_SEC = 3600

STATE_FILE = Path("tsp_state.json")
CONFIG_FILE = Path("tsp_config.json")
LOG_FILE = Path("tsp_daily_log.csv")
TRANSACTION_FILE = Path("tsp_transactions.csv")

DEFAULTS = {
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
    "fwd_eps_growth_yoy": 30.82,
    "stlfsi_index": -0.9568,
    "bond_yield_3m": 4.20,
    "bond_yield_10y": 4.50,
    "market_breadth_pct": 73.20,
    "vix_spot": 19.0,
    "dxy_spot": 105.80,
    "spx_spot": 5000.0,
}

# Single source of truth for the DXY tilt trigger. Referenced by both
# engine.py (allocation logic) and factor_scoring_guide.md (documentation).
# Previously engine.py hardcoded 105.0 (the STRONG/VERY STRONG boundary)
# while the guide documented 103.5 -- a real spec/code drift that silently
# narrowed the tilt's trigger window. This constant is now the only place
# that number lives.
DXY_TILT_THRESHOLD = 103.5

PROXIES = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL",
}

# ---------------------------------------------------------------------------
# Single source of truth for regime definitions.
#
# engine.py, app.py, storage.py, and ui.py should all derive their regime
# names, base allocations, and display metadata from this dict rather than
# hardcoding literals. This is the fix for the "file drift" risk called out
# in Project_Handoff.md and target_architecture.md: previously the same
# allocation numbers were duplicated in constants.py, engine.py, and app.py.
# ---------------------------------------------------------------------------
REGIME_DEFINITIONS = {
    "RISK-ON OVERRIDE": {
        "icon": "🚀",
        "score_label": "Score: ≥ +5",
        "profile": "Aggressive Profile",
        # I Fund corrected 25 -> 20 (was: G30/C40/I25/S10/F0 = 105%, a
        # pre-existing data bug caught by tests/test_regime_consistency.py).
        # Now G30/C40/I20/S10/F0 = 100%.
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

# Stable display ordering for regime cards / directories.
REGIME_ORDER = [
    "RISK-ON OVERRIDE",
    "OPTIMIZED NEUTRAL",
    "DEFENSIVE ALLOCATION",
    "EMERGENCY DISPATCH",
]

# Flat name -> allocation map, derived from REGIME_DEFINITIONS so it can
# never drift out of sync. Kept for callers (engine.py's IFT gate, storage
# defaults) that just want the numbers. Includes the F-unlocked emergency
# variant, which is an overlay on top of EMERGENCY DISPATCH rather than a
# distinct top-level regime card.
BASELINE_ALLOCATIONS = {
    name: dict(info["allocation"]) for name, info in REGIME_DEFINITIONS.items()
}
BASELINE_ALLOCATIONS["EMERGENCY DISPATCH (F-Unlocked)"] = {"G": 90, "C": 0, "I": 0, "S": 0, "F": 10}
