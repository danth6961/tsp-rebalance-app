"""
constants.py — Centralized thresholds, weights, configuration settings, and file paths.
"""

from pathlib import Path

# ----------------------------
# Baseline regimes allocations (percentages).
# (These must sum to 100, though engine.py normalizes on its own.)
# ----------------------------
BASELINE_ALLOCATIONS = {
    "RISK-ON OVERRIDE": {"G": 10.0, "C": 40.0, "I": 30.0, "S": 10.0, "F": 10.0},
    "OPTIMIZED NEUTRAL": {"G": 20.0, "C": 30.0, "I": 30.0, "S": 10.0, "F": 10.0},
    "DEFENSIVE ALLOCATION": {"G": 40.0, "C": 20.0, "I": 20.0, "S": 10.0, "F": 10.0},
    "EMERGENCY DISPATCH": {"G": 60.0, "C": 10.0, "I": 10.0, "S": 10.0, "F": 10.0},
}

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
    # Add other defaults as needed.
}

# ----------------------------
# Indicator thresholds for piecewise interpolation.
# ----------------------------
# Inflation (using core PCE YoY as the driver)
INFLATION_BREAKPOINTS = [1.8, 2.0, 2.3, 3.0]
INFLATION_SCORES = [3.0, 1.0, 0.0, -3.0]
INFLATION_MIN_SCORE = -5.0  # for pce > 3.0

# Growth (using composite PMI = 0.2 * ism_pmi + 0.8 * services_pmi)
GROWTH_BREAKPOINTS = [48.0, 50.0, 51.5, 55.0]
GROWTH_SCORES = [-5.0, -3.0, 0.0, 1.0]  # above 55 we assign 3.0
GROWTH_MAX_SCORE = 3.0

# Liquidity (using sloos_net_pct as primary driver)
LIQUIDITY_BREAKPOINTS = [-15.0, 5.0]
LIQUIDITY_SCORES = [3.0, 0.0]
LIQUIDITY_MIN_SCORE = -5.0  # if above 5.0

# Credit spreads (using hy_oas)
CREDIT_BREAKPOINTS = [3.0, 4.0, 5.0, 6.0]
CREDIT_SCORES = [3.0, 1.0, 0.0, -3.0]
CREDIT_MIN_SCORE = -5.0

# Valuation (using shiller_cape with adjustments)
VALUATION_BREAKPOINTS = [20.0, 25.0]  # if cape <20 -> 3, if cape <=25 -> 0, then negative if between 25 and active ceiling
VALUATION_MIN_SCORE = -5.0
BASE_CAPE_CEILING = 30.0
HIGH_EPS_CAPE_CEILING = 35.0
REAL_YIELD_THRESHOLD = 2.2  # if real_yield_10y > 2.2, reduce ceiling by 5; if < 0.5 raise ceiling by 3

# Market stress (using vix_spot)
STRESS_BREAKPOINTS = [12.0, 15.0, 22.0, 30.0]
STRESS_SCORES = [3.0, 1.0, 0.0, -3.0]
STRESS_MIN_SCORE = -5.0

# Momentum (using sma_dist: percentage distance from 200 SMA)
MOMENTUM_BREAKPOINTS = [-5.0, 0.0, 5.0]
MOMENTUM_SCORES = [-5.0, -3.0, 1.0]  # above 5 we assign 3
MOMENTUM_MAX_SCORE = 3.0

# Drawdown (using drawdown percentage)
DRAWDOWN_BREAKPOINTS = [5.0, 10.0, 15.0, 20.0]
DRAWDOWN_SCORES = [3.0, 1.0, 0.0, -3.0]
DRAWDOWN_MIN_SCORE = -5.0

# ----------------------------
# Overlay adjustment caps.
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
DXY_TILT_THRESHOLD = 100.0  # adjust as needed

# ----------------------------
# IFT state machine configuration.
# ----------------------------
G_MOVE_TOLERANCE_PCT = 0.5
MONTHLY_IFT_LIMIT = 2

# ----------------------------
# Additional configuration required by app.py.
# ----------------------------
# LOG_FILE: the file where run logs are stored.
LOG_FILE = Path("tsp_daily_log.csv")

# TRANSACTION_FILE: the file where IFT audit/trail transactions are stored.
TRANSACTION_FILE = Path("tsp_transactions.csv")

# PROXIES: a mapping for TSP fund proxy tickers. Adjust these as needed.
PROXIES = {
    "C": "IVV",   # example: S&P 500 ETF for C Fund
    "S": "IJR",   # example: ETF for Mid/Small Cap for S Fund
    "I": "ACWX",  # example: International ETF for I Fund
    "F": "BND",   # example: Bond ETF for F Fund
    "G": "GSY",   # example: Short-term T-Bill ETF for G Fund
}

# REGIME_ORDER: the order of regimes for manual override selections.
REGIME_ORDER = ["RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL", "DEFENSIVE ALLOCATION", "EMERGENCY DISPATCH"]
