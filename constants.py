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
    "services_pmi": 53.5,
    "initial_claims": 215.0,
    "breakeven_inflation": 2.25,
    "fed_assets_growth_yoy": -4.5,
    "real_yield_10y": 2.00,
    "move_index": 105.0,
    "sloos_net_pct": 6.6,
    "hy_oas": 2.76,
    "shiller_cape": 39.66,
    "fwd_eps_growth_yoy": 21.00,
    "stlfsi_index": -0.9568,
    "bond_yield_10y": 4.50,
    "market_breadth_pct": 73.20,
    "vix_spot": 19.0,
    "dxy_spot": 105.80,
    "spx_spot": 5000.0,
}

PROXIES = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL",
}

BASELINE_ALLOCATIONS = {
    "RISK-ON OVERRIDE": {"G": 35, "C": 45, "I": 15, "S": 5, "F": 0},
    "OPTIMIZED NEUTRAL": {"G": 45, "C": 35, "I": 10, "S": 10, "F": 0},
    "DEFENSIVE ALLOCATION": {"G": 65, "C": 20, "I": 10, "S": 5, "F": 0},
    "EMERGENCY DISPATCH": {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0},
    "EMERGENCY DISPATCH (F-Unlocked)": {"G": 90, "C": 0, "I": 0, "S": 0, "F": 10},
    "DEFENSIVE ALLOCATION (High Risk)": {"G": 70, "C": 20, "I": 5, "S": 5, "F": 0},
}
