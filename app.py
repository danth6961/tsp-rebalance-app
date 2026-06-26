from __future__ import annotations

from datetime import datetime
import math
import time
import urllib.request
import urllib.parse
from typing import Optional, List, Tuple

import pandas as pd
import yfinance as yf
import streamlit as st


# ==============================================================================
# CONFIG
# ==============================================================================

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 1.5

DEFAULTS = {
    "core_pce_yoy": 3.4,
    "ism_pmi": 54.0,
    "sloos_net_pct": 6.6,
    "hy_oas": 2.76,
    "shiller_cape": 39.66,
    "fwd_eps_growth_yoy": 11.8,
    "stlfsi_index": -0.9568,
    "bond_yield_10y": 4.50,
    "market_breadth_pct": 73.20,
    "vix_spot": 19.0,
    "dxy_spot": 105.80,
}


# ==============================================================================
# UTILITIES
# ==============================================================================

def is_finite_number(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except Exception:
        return False


def safe_float(x, default=None):
    return float(x) if is_finite_number(x) else default


def retry_call(func, *args, retries=MAX_RETRIES, sleep_sec=RETRY_SLEEP_SEC, **kwargs):
    last_err = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(sleep_sec)
    raise last_err


# ==============================================================================
# DATA HELPERS
# ==============================================================================

def fetch_fred_latest(series_id: str) -> Optional[float]:
    """
    Fetch latest FRED value using the official CSV endpoint.
    Returns None on failure.
    """
    def _load():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id={urllib.parse.quote(series_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            df = pd.read_csv(response)

        if df.empty or len(df.columns) < 2:
            return None

        value_col = df.columns[1]
        series = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if series.empty:
            return None
        return float(series.iloc[-1])

    try:
        return retry_call(_load)
    except Exception:
        return None


def fetch_yfinance_closes(ticker: str, period: str = "1y", interval: str = "1d") -> List[float]:
    """
    Fetch close series from Yahoo Finance using yfinance.
    Returns [] on failure.
    """
    def _load():
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            if ("Close", ticker) in df.columns:
                close = df[("Close", ticker)]
            else:
                close_candidates = [c for c in df.columns if c[0] == "Close"]
                if not close_candidates:
                    return []
                close = df[close_candidates[0]]
        else:
            if "Close" not in df.columns:
                return []
            close = df["Close"]

        return pd.to_numeric(close, errors="coerce").dropna().astype(float).tolist()

    try:
        return retry_call(_load)
    except Exception:
        return []


def calculate_sp500_metrics() -> Tuple[float, float, float]:
    """
    Returns:
        current_200sma_distance_pct,
        drawdown_pct,
        current_spot
    """
    closes = fetch_yfinance_closes("^GSPC", period="1y", interval="1d")
    if len(closes) < 200:
        return 0.0, 0.0, 0.0

    current_spot = closes[-1]
    peak = max(closes)
    drawdown_pct = ((peak - current_spot) / peak) * 100.0

    sma_200 = sum(closes[-200:]) / 200.0
    dist_200sma = ((current_spot - sma_200) / sma_200) * 100.0

    return round(dist_200sma, 2), round(drawdown_pct, 2), round(current_spot, 2)


# ==============================================================================
# CACHED MARKET SNAPSHOT
# ==============================================================================

@st.cache_data(ttl=900)
def get_market_snapshot():
    sloos_val = fetch_fred_latest("DRTSCIS")
    hy_val = fetch_fred_latest("BAMLH0A0HYM2")
    stlfsi_val = fetch_fred_latest("STLFSI4")
    bond_val = fetch_fred_latest("DGS10")

    vix_closes = fetch_yfinance_closes("^VIX", period="1mo", interval="1d")
    dxy_closes = fetch_yfinance_closes("DX-Y.NYB", period="1mo", interval="1d")

    sma_dist_live, drawdown_live, spx_spot = calculate_sp500_metrics()

    market_data = {
        "core_pce_yoy": DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "sloos_net_pct": sloos_val if sloos_val is not None else DEFAULTS["sloos_net_pct"],
        "hy_oas": hy_val if hy_val is not None else DEFAULTS["hy_oas"],
        "shiller_cape": DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "vix_spot": vix_closes[-1] if vix_closes else DEFAULTS["vix_spot"],
        "pct_dist_200_sma": sma_dist_live,
        "drawdown_pct": drawdown_live,
        "stlfsi_index": stlfsi_val if stlfsi_val is not None else DEFAULTS["stlfsi_index"],
        "bond_yield_10y": bond_val if bond_val is not None else DEFAULTS["bond_yield_10y"],
        "dxy_spot": dxy_closes[-1] if dxy_closes else DEFAULTS["dxy_spot"],
        "market_breadth_pct": DEFAULTS["market_breadth_pct"],
        "spx_spot": spx_spot,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    return market_data


# ==============================================================================
# STREAMLIT APP
# ==============================================================================

st.set_page_config(page_title="TSP Rebalance Engine - Stage 1", layout="wide")
st.title("TSP Rebalance Engine — Stage 1")
st.caption("Live data fetch and market snapshot")

col_a, col_b = st.columns([1, 1])

with col_a:
    fetch_now = st.button("Fetch Live Data")

with col_b:
    st.write("Cached for 15 minutes to reduce slow reloads.")

if fetch_now:
    with st.spinner("Loading live data..."):
        market_data = get_market_snapshot()

    st.success("Live data loaded")

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Market Snapshot")
        st.json(market_data)

    with c2:
        st.subheader("Data Source Notes")
        st.write("- Core PCE, ISM PMI, CAPE, and forward EPS are still defaults for now.")
        st.write("- SLOOS, HY OAS, STLFSI, and 10Y yield are fetched from FRED.")
        st.write("- VIX, DXY, and S&P 500 are fetched from Yahoo Finance.")
        st.write("- Next stage will add scoring and allocation logic.")
else:
    st.info("Click **Fetch Live Data** to load the latest market snapshot.")
