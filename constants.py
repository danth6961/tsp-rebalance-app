"""
constants.py — Centralized thresholds, weights, configuration settings, file paths,
and regime metadata.

This file is intended to centralize all "magic numbers," storage file names,
and regime definitions that are shared across modules such as data_sources.py,
ui.py, storage.py, and tests.
"""

from pathlib import Path

# ----------------------------
# Baseline regime allocations (percentages).
# ----------------------------
BASELINE_ALLOCATIONS = {
    "RISK-ON OVERRIDE": {"G": 10.0, "C": 40.0, "I": 30.0, "S": 10.0, "F": 10.0},
    "OPTIMIZED NEUTRAL": {"G": 20.0, "C": 30.0, "I": 30.0, "S": 10.0, "F": 10.0},
    "DEFENSIVE ALLOCATION": {"G": 40.0, "C": 20.0, "I": 20.0, "S": 10.0, "F": 10.0},
    "EMERGENCY DISPATCH": {"G": 60.0, "C": 10.0, "I": 10.0, "S": 10.0, "F": 10.0},
}

# ----------------------------
# REGIME_DEFINITIONS - additional UI metadata for each regime.
# ----------------------------
REGIME_DEFINITIONS = {
    "RISK-ON OVERRIDE": {
        "icon": "🔥",
        "score_label": "High",
        "profile": "Aggressive",
        "allocation": BASELINE_ALLOCATIONS["RISK-ON OVERRIDE"],
        "description": "A regime with high market confidence, favoring risk-on strategies.",
        "color": "#f97316",
        "bg": "#fff7ed",
    },
    "OPTIMIZED NEUTRAL": {
        "icon": "🧭",
        "score_label": "Balanced",
        "profile": "Neutral",
        "allocation": BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"],
        "description": "A regime with moderate market sentiment, aiming for balanced exposure.",
        "color": "#3b82f6",
        "bg": "#eff6ff",
    },
    "DEFENSIVE ALLOCATION": {
        "icon": "🛡️",
        "score_label": "Low",
        "profile": "Defensive",
        "allocation": BASELINE_ALLOCATIONS["DEFENSIVE ALLOCATION"],
        "description": "A regime that favors safety by reducing equity exposure.",
        "color": "#10b981",
        "bg": "#ecfdf5",
    },
    "EMERGENCY DISPATCH": {
        "icon": "🚨",
        "score_label": "Critical",
        "profile": "Emergency",
        "allocation": BASELINE_ALLOCATIONS["EMERGENCY DISPATCH"],
        "description": "An extreme market downturn regime; shift to only the safest assets.",
        "color": "#ef4444",
        "bg": "#fef2f2",
    },
}

# ----------------------------
# Order of regimes for manual override selections.
# ----------------------------
REGIME_ORDER = [
    "RISK-ON OVERRIDE",
    "OPTIMIZED NEUTRAL",
    "DEFENSIVE ALLOCATION",
    "EMERGENCY DISPATCH",
]

# ----------------------------
# Default values for missing market inputs.
# ----------------------------
DEFAULTS = {
    "core_pce_yoy": 2.0,
    "ism_pmi": 50.0,
    "services_pmi": 50.0,
    "initial_claims": 250.0,
    "breakeven_inflation": 2.0,
    "fed_assets_growth_yoy": 0.0,
    "real_yield_10y": 1.5,
    "sloos_net_pct": 0.0,
    "hy_oas": 4.0,
    "shiller_cape": 25.0,
    "fwd_eps_growth_yoy": 10.0,
    "vix_spot": 15.0,
    "stlfsi_index": 0.0,
    "move_index": 100.0,
    "bond_yield_10y": 2.0,
    "dxy_spot": 95.0,
    "market_breadth_pct": 70.0,
}

# ----------------------------
# Retry settings for network calls used in data_sources.py.
# ----------------------------
MAX_RETRIES = 3
RETRY_SLEEP_SEC = 2

# ----------------------------
# Indicator thresholds for piecewise interpolation.
# ----------------------------
# Inflation (based on core PCE YoY)
INFLATION_BREAKPOINTS = [1.8, 2.0, 2.3, 3.0]
INFLATION_SCORES = [3.0, 1.0, 0.0, -3.0]
INFLATION_MIN_SCORE = -5.0  # For pce > 3.0

# Growth (composite PMI: 0.2 * ism_pmi + 0.8 * services_pmi)
GROWTH_BREAKPOINTS = [48.0, 50.0, 51.5, 55.0]
GROWTH_SCORES = [-5.0, -3.0, 0.0, 1.0]  # Above 55 we assign 3.0
GROWTH_MAX_SCORE = 3.0

# Liquidity (using sloos_net_pct as primary driver)
LIQUIDITY_BREAKPOINTS = [-15.0, 5.0]
LIQUIDITY_SCORES = [3.0, 0.0]
LIQUIDITY_MIN_SCORE = -5.0  # If above 5.0

# Credit spreads (using hy_oas)
CREDIT_BREAKPOINTS = [3.0, 4.0, 5.0, 6.0]
CREDIT_SCORES = [3.0, 1.0, 0.0, -3.0]
CREDIT_MIN_SCORE = -5.0

# Valuation (using shiller_cape with adjustments)
VALUATION_BREAKPOINTS = [20.0, 25.0]
VALUATION_MIN_SCORE = -5.0
BASE_CAPE_CEILING = 30.0
HIGH_EPS_CAPE_CEILING = 35.0
REAL_YIELD_THRESHOLD = 2.2  # Adjust ceiling based on 10Y real yield

# Market stress (using vix_spot)
STRESS_BREAKPOINTS = [12.0, 15.0, 22.0, 30.0]
STRESS_SCORES = [3.0, 1.0, 0.0, -3.0]
STRESS_MIN_SCORE = -5.0

# Momentum (using percent distance from 200SMA)
MOMENTUM_BREAKPOINTS = [-5.0, 0.0, 5.0]
MOMENTUM_SCORES = [-5.0, -3.0, 1.0]  # Above 5 assign 3.0
MOMENTUM_MAX_SCORE = 3.0

# Drawdown (using percentage drawdown)
DRAWDOWN_BREAKPOINTS = [5.0, 10.0, 15.0, 20.0]
DRAWDOWN_SCORES = [3.0, 1.0, 0.0, -3.0]
DRAWDOWN_MIN_SCORE = -5.0

# ----------------------------
# Overlay adjustment cap.
# ----------------------------
OVERLAY_ADJUSTMENT_CAP = 2.0

# ----------------------------
# Weights for composite score.
# ----------------------------
FACTOR_WEIGHTS = {
    "growth": 2.0,
    "liquidity": 2.0,
    "credit_spreads": 2.0,
    "market_stress": 2.0,
    "inflation": 1.5,
    "momentum": 1.5,
    "valuation": 1.0,
    "drawdown": 1.0,
}

# ----------------------------
# DXY / currency tilt threshold.
# ----------------------------
# Note: Test expectations require the threshold to be 103.5.
DXY_TILT_THRESHOLD = 103.5

# ----------------------------
# File paths for persistence.
# ----------------------------
CONFIG_FILE = Path("tsp_config.json")
STATE_FILE = Path("tsp_state.json")
LOG_FILE = Path("tsp_daily_log.csv")
TRANSACTION_FILE = Path("tsp_transactions.csv")
