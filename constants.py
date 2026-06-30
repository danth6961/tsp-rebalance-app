from pathlib import Path

# ============================================================
# Core file paths
# ============================================================

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 1.5
CACHE_TTL_SEC = 3600

STATE_FILE = Path("tsp_state.json")
CONFIG_FILE = Path("tsp_config.json")
LOG_FILE = Path("tsp_daily_log.csv")
TRANSACTION_FILE = Path("tsp_transactions.csv")

# ============================================================
# Shared default market / macro inputs
# These are used whenever live data is unavailable.
# ============================================================

DEFAULTS = {
    # Existing engine inputs
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
    "bond_yield_10y": 4.50,
    "market_breadth_pct": 73.20,
    "vix_spot": 19.0,
    "dxy_spot": 105.80,
    "spx_spot": 5000.0,

    # ========================================================
    # New Step 2 macro factors
    # Keep these neutral by default so missing data does not
    # bias the engine bullish or bearish.
    # ========================================================

    # Yield curve slope: positive = steeper / healthier curve
    "yield_curve_slope": 0.0,

    # Inflation trend: positive = disinflating / improving
    "inflation_trend": 0.0,

    # Labor trend: positive = improving, negative = weakening
    "labor_trend": 0.0,

    # Volatility term structure:
    # positive = calmer / contango-like
    # negative = stressed / backwardated
    "vol_term_structure": 0.0,

    # Commodity shock proxy:
    # positive = recent spike, usually bearish/stagflationary
    "commodity_shock": 0.0,

    # Earnings breadth proxy:
    # positive = broad participation, negative = narrow leadership
    "earnings_breadth": 0.0,

    # Optional helper fields if used downstream
    "macro_regime_score": 0.0,
    "signal_confidence": 0.0,
}

# ============================================================
# Proxy tickers used by the UI and performance charts
# ============================================================

PROXIES = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL",
}

# ============================================================
# Canonical tactical baseline allocations
# IMPORTANT: Keep these synchronized with engine.py and app.py
# ============================================================

BASELINE_ALLOCATIONS = {
    "RISK-ON OVERRIDE": {"G": 30, "C": 40, "I": 25, "S": 10, "F": 0},
    "OPTIMIZED NEUTRAL": {"G": 40, "C": 30, "I": 20, "S": 10, "F": 0},
    "DEFENSIVE ALLOCATION": {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0},
    "EMERGENCY DISPATCH": {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0},
    "EMERGENCY DISPATCH (F-Unlocked)": {"G": 90, "C": 0, "I": 0, "S": 0, "F": 10},
}

# ============================================================
# Optional UI labels / factor groupings
# ============================================================

FACTOR_GROUPS = {
    "macro": [
        "core_pce_yoy",
        "inflation_trend",
        "ism_pmi",
        "services_pmi",
        "yield_curve_slope",
        "labor_trend",
    ],
    "liquidity": [
        "fed_assets_growth_yoy",
        "real_yield_10y",
        "sloos_net_pct",
        "hy_oas",
        "stlfsi_index",
        "vol_term_structure",
    ],
    "market": [
        "move_index",
        "vix_spot",
        "pct_dist_200_sma",
        "drawdown_pct",
        "market_breadth_pct",
        "earnings_breadth",
    ],
    "valuation": [
        "shiller_cape",
        "fwd_eps_growth_yoy",
        "breakeven_inflation",
        "commodity_shock",
        "dxy_spot",
    ],
}

# ============================================================
# Display names for UI purposes
# ============================================================

DISPLAY_NAMES = {
    "core_pce_yoy": "Core PCE YoY",
    "ism_pmi": "ISM PMI",
    "services_pmi": "Services PMI",
    "initial_claims": "Initial Claims",
    "breakeven_inflation": "Breakeven Inflation",
    "fed_assets_growth_yoy": "Fed Assets Growth YoY",
    "real_yield_10y": "10Y Real Yield",
    "move_index": "MOVE Index",
    "sloos_net_pct": "SLOOS Net %",
    "hy_oas": "HY OAS",
    "shiller_cape": "Shiller CAPE",
    "fwd_eps_growth_yoy": "Forward EPS Growth YoY",
    "stlfsi_index": "STLFSI",
    "bond_yield_10y": "10Y Treasury Yield",
    "market_breadth_pct": "Market Breadth %",
    "vix_spot": "VIX Spot",
    "dxy_spot": "DXY Spot",
    "spx_spot": "SPX Spot",
    "yield_curve_slope": "Yield Curve Slope",
    "inflation_trend": "Inflation Trend",
    "labor_trend": "Labor Trend",
    "vol_term_structure": "Volatility Term Structure",
    "commodity_shock": "Commodity Shock",
    "earnings_breadth": "Earnings Breadth",
}

# ============================================================
# Editable input order for the UI
# ============================================================

EDITABLE_KEYS = [
    "core_pce_yoy",
    "ism_pmi",
    "services_pmi",
    "initial_claims",
    "breakeven_inflation",
    "fed_assets_growth_yoy",
    "real_yield_10y",
    "move_index",
    "sloos_net_pct",
    "hy_oas",
    "shiller_cape",
    "fwd_eps_growth_yoy",
    "vix_spot",
    "pct_dist_200_sma",
    "drawdown_pct",
    "stlfsi_index",
    "bond_yield_10y",
    "dxy_spot",
    "market_breadth_pct",
    "spx_spot",

    # New Step 2 factors
    "yield_curve_slope",
    "inflation_trend",
    "labor_trend",
    "vol_term_structure",
    "commodity_shock",
    "earnings_breadth",
]
