from __future__ import annotations

from pathlib import Path

# -----------------------------------------------------------------------------
# Runtime and persistence config
# -----------------------------------------------------------------------------
MAX_RETRIES: int = 3
RETRY_SLEEP_SEC: float = 1.5
CACHE_TTL_SEC: int = 3600

STATE_FILE: Path = Path("tsp_state.json")
CONFIG_FILE: Path = Path("tsp_config.json")
LOG_FILE: Path = Path("tsp_daily_log.csv")
TRANSACTION_FILE: Path = Path("tsp_transactions.csv")

# -----------------------------------------------------------------------------
# Defaults
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
# Canonical regime allocations
# -----------------------------------------------------------------------------
BASELINE_ALLOCATIONS: dict[str, dict[str, float]] = {
    "RISK-ON OVERRIDE": {"G": 30.0, "C": 40.0, "I": 20.0, "S": 10.0, "F": 0.0},
    "OPTIMIZED NEUTRAL": {"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0},
    "DEFENSIVE ALLOCATION": {"G": 70.0, "C": 15.0, "I": 10.0, "S": 5.0, "F": 0.0},
    "EMERGENCY DISPATCH": {"G": 100.0, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.0},
}

REGIME_ORDER: list[str] = [
    "RISK-ON OVERRIDE",
    "OPTIMIZED NEUTRAL",
    "DEFENSIVE ALLOCATION",
    "EMERGENCY DISPATCH",
]

REGIME_DEFINITIONS: dict[str, dict[str, object]] = {
    "RISK-ON OVERRIDE": {
        "icon": "🚀",
        "score_label": "Composite ≥ +60",
        "profile": "Aggressive Profile",
        "allocation": BASELINE_ALLOCATIONS["RISK-ON OVERRIDE"],
        "description": "Strong macro backdrop and constructive risk conditions.",
        "color": "#10b981",
        "bg": "rgba(16, 185, 129, 0.08)",
    },
    "OPTIMIZED NEUTRAL": {
        "icon": "⚖️",
        "score_label": "Composite +25 to +59",
        "profile": "Balanced Profile",
        "allocation": BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"],
        "description": "Default balanced state when signals are mixed but constructive.",
        "color": "#3b82f6",
        "bg": "rgba(59, 130, 246, 0.08)",
    },
    "DEFENSIVE ALLOCATION": {
        "icon": "🛡️",
        "score_label": "Composite < +25",
        "profile": "Defensive Profile",
        "allocation": BASELINE_ALLOCATIONS["DEFENSIVE ALLOCATION"],
        "description": "Used when macro risk rises or the composite weakens.",
        "color": "#f59e0b",
        "bg": "rgba(245, 158, 11, 0.08)",
    },
    "EMERGENCY DISPATCH": {
        "icon": "🚨",
        "score_label": "Panic valve",
        "profile": "Maximum Defense",
        "allocation": BASELINE_ALLOCATIONS["EMERGENCY DISPATCH"],
        "alloc_display": "G 100% / F 0%",
        "description": "3-day panic valve breach.",
        "color": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.08)",
    },
}

# -----------------------------------------------------------------------------
# Market state thresholds
# -----------------------------------------------------------------------------
THRESHOLDS: dict[str, float] = {
    # Inflation
    "inflation_cooling": 2.0,
    "inflation_stable": 2.3,
    "inflation_rising": 3.0,
    "breakeven_elevated": 2.6,
    "breakeven_depressed": 1.8,

    # Growth
    "pmi_expanding": 55.0,
    "pmi_ok": 51.5,
    "pmi_flat": 50.0,
    "pmi_contracting": 48.0,
    "claims_mild_pressure": 250.0,
    "claims_severe_pressure": 280.0,

    # Liquidity
    "sloos_loose": -15.0,
    "sloos_neutral": 5.0,
    "fed_assets_expanding": 0.0,

    # Credit
    "hy_spread_tight": 3.0,
    "hy_spread_ok": 4.0,
    "hy_spread_stress": 5.0,
    "hy_spread_high_stress": 6.0,

    # Stress
    "vix_calm": 12.0,
    "vix_normal": 15.0,
    "vix_stress": 22.0,
    "vix_high_stress": 30.0,
    "stlfsi_mild": 1.0,
    "stlfsi_moderate": 2.0,
    "stlfsi_extreme": 2.0,

    # Trend / momentum
    "sma_bullish": 5.0,
    "sma_neutral": 0.0,
    "sma_bearish": -5.0,
    "drawdown_light": 5.0,
    "drawdown_moderate": 10.0,
    "drawdown_elevated": 15.0,
    "drawdown_severe": 20.0,

    # Policy / rates
    "curve_inverted": 0.0,
    "curve_deep_inverted": -0.5,
    "policy_restrictive": -2.0,
    "policy_aggressive": -3.0,

    # DXY
    "dxy_tilt_threshold": 103.5,
}

DXY_TILT_THRESHOLD: float = THRESHOLDS["dxy_tilt_threshold"]

# -----------------------------------------------------------------------------
# Scoring system
# -----------------------------------------------------------------------------
FACTOR_WEIGHTS: dict[str, float] = {
    "growth": 2.0,
    "liquidity": 2.0,
    "credit": 2.0,
    "stress": 2.0,
    "inflation": 1.5,
    "momentum": 1.5,
    "valuation": 1.0,
    "drawdown": 1.0,
}

NORMALIZED_SCORE_MIN: float = 0.0
NORMALIZED_SCORE_MAX: float = 100.0

FACTOR_SCORE_MAP: dict[str, dict[str, float]] = {
    "inflation": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "growth": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "liquidity": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "credit": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "stress": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "momentum": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "valuation": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
    "drawdown": {"very_positive": 100.0, "positive": 75.0, "neutral": 50.0, "negative": 25.0, "very_negative": 0.0},
}

COMPOSITE_RISK_ON: float = 60.0
COMPOSITE_NEUTRAL: float = 25.0

# -----------------------------------------------------------------------------
# Overlay caps
# -----------------------------------------------------------------------------
OVERLAY_CAPS: dict[str, float] = {
    "asymmetric_vol_max_shift_pct": 10.0,
    "dxy_max_shift_pct": 5.0,
    "macro_defensive_max_shift_pct": 15.0,
}

# -----------------------------------------------------------------------------
# Proxy symbols
# -----------------------------------------------------------------------------
PROXIES: dict[str, str] = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL",
}
