from __future__ import annotations

from datetime import datetime
import math
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Tuple, Dict, Any

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


def calc_spx_metrics_from_closes(closes: List[float]) -> Tuple[float, float, float]:
    if len(closes) < 200:
        return 0.0, 0.0, 0.0
    current_spot = closes[-1]
    peak = max(closes)
    drawdown_pct = ((peak - current_spot) / peak) * 100.0
    sma_200 = sum(closes[-200:]) / 200.0
    dist_200sma = ((current_spot - sma_200) / sma_200) * 100.0
    return round(dist_200sma, 2), round(drawdown_pct, 2), round(current_spot, 2)


# ==============================================================================
# CACHED FUNCTIONS
# ==============================================================================

@st.cache_data(ttl=900)
def cached_fred(series_id: str) -> Optional[float]:
    return fetch_fred_latest(series_id)


@st.cache_data(ttl=900)
def cached_yahoo_closes(ticker: str, period: str, interval: str) -> List[float]:
    return fetch_yfinance_closes(ticker, period=period, interval=interval)


@st.cache_data(ttl=900)
def get_market_snapshot() -> Dict[str, Any]:
    results: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(cached_fred, "DRTSCIS"): "sloos_val",
            executor.submit(cached_fred, "BAMLH0A0HYM2"): "hy_val",
            executor.submit(cached_fred, "STLFSI4"): "stlfsi_val",
            executor.submit(cached_fred, "DGS10"): "bond_val",
            executor.submit(cached_yahoo_closes, "^VIX", "1mo", "1d"): "vix_closes",
            executor.submit(cached_yahoo_closes, "DX-Y.NYB", "1mo", "1d"): "dxy_closes",
            executor.submit(cached_yahoo_closes, "^GSPC", "1y", "1d"): "spx_closes",
        }

        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = None

    vix_closes = results.get("vix_closes") or []
    dxy_closes = results.get("dxy_closes") or []
    spx_closes = results.get("spx_closes") or []

    sma_dist_live, drawdown_live, spx_spot = calc_spx_metrics_from_closes(spx_closes)

    return {
        "core_pce_yoy": DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "sloos_net_pct": results.get("sloos_val") if results.get("sloos_val") is not None else DEFAULTS["sloos_net_pct"],
        "hy_oas": results.get("hy_val") if results.get("hy_val") is not None else DEFAULTS["hy_oas"],
        "shiller_cape": DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "vix_spot": vix_closes[-1] if vix_closes else DEFAULTS["vix_spot"],
        "pct_dist_200_sma": sma_dist_live,
        "drawdown_pct": drawdown_live,
        "stlfsi_index": results.get("stlfsi_val") if results.get("stlfsi_val") is not None else DEFAULTS["stlfsi_index"],
        "bond_yield_10y": results.get("bond_val") if results.get("bond_val") is not None else DEFAULTS["bond_yield_10y"],
        "dxy_spot": dxy_closes[-1] if dxy_closes else DEFAULTS["dxy_spot"],
        "market_breadth_pct": DEFAULTS["market_breadth_pct"],
        "spx_spot": spx_spot,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ==============================================================================
# ENGINE
# ==============================================================================

def execute_tsp_allocation_engine_final(data: Dict[str, Any]):
    scores: Dict[str, int] = {}

    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    pmi = safe_float(data.get("ism_pmi"), DEFAULTS["ism_pmi"])
    sloos = safe_float(data.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    hy_spread = safe_float(data.get("hy_oas"), DEFAULTS["hy_oas"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    fwd_eps = safe_float(data.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"])
    vix = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    sma_dist = safe_float(data.get("pct_dist_200_sma"), 0.0)
    drawdown = safe_float(data.get("drawdown_pct"), 0.0)
    stlfsi = safe_float(data.get("stlfsi_index"), DEFAULTS["stlfsi_index"])
    bond_yield = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
    dxy_spot = safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"])

    # Scoring
    if pce < 1.8: scores["inflation"] = 3
    elif pce < 2.0: scores["inflation"] = 1
    elif pce <= 2.3: scores["inflation"] = 0
    elif pce <= 3.0: scores["inflation"] = -3
    else: scores["inflation"] = -5

    if pmi > 55.0: scores["growth"] = 3
    elif pmi >= 52.0: scores["growth"] = 0
    elif pmi >= 50.0: scores["growth"] = -3
    else: scores["growth"] = -5

    if sloos < -15.0: scores["liquidity"] = 3
    elif sloos <= 5.0: scores["liquidity"] = 0
    else: scores["liquidity"] = -5

    if hy_spread < 3.0: scores["credit_spreads"] = 3
    elif hy_spread < 4.0: scores["credit_spreads"] = 1
    elif hy_spread <= 5.0: scores["credit_spreads"] = 0
    elif hy_spread <= 6.0: scores["credit_spreads"] = -3
    else: scores["credit_spreads"] = -5

    active_cape_ceiling = 42.0 if fwd_eps >= 15.0 else 35.0
    if cape < 20.0: scores["valuation"] = 3
    elif cape <= 26.0: scores["valuation"] = 0
    elif cape <= active_cape_ceiling: scores["valuation"] = -3
    else: scores["valuation"] = -5

    if vix < 12.0: scores["market_stress"] = 3
    elif vix < 15.0: scores["market_stress"] = 1
    elif vix <= 22.0: scores["market_stress"] = 0
    elif vix <= 30.0: scores["market_stress"] = -3
    else: scores["market_stress"] = -5

    if sma_dist > 5.0: scores["momentum"] = 3
    elif sma_dist >= 0.0: scores["momentum"] = 1
    elif sma_dist >= -5.0: scores["momentum"] = -3
    else: scores["momentum"] = -5

    if drawdown < 5.0: scores["drawdown"] = 3
    elif drawdown < 10.0: scores["drawdown"] = 1
    elif drawdown <= 15.0: scores["drawdown"] = 0
    elif drawdown <= 20.0: scores["drawdown"] = -3
    else: scores["drawdown"] = -5

    if 0.0 <= stlfsi <= 1.0:
        scores["market_stress"] -= 1
        scores["momentum"] -= 1
    elif 1.0 < stlfsi <= 2.0:
        scores["market_stress"] -= 3
        scores["momentum"] -= 3
    elif stlfsi > 2.0:
        scores["market_stress"] = -10
        scores["momentum"] = -10
        scores["valuation"] = min(scores["valuation"], -5)

    composite_score = sum(scores.values())

    momentum_breaker = scores["momentum"] <= -3
    asymmetric_vol_trigger = scores["market_stress"] <= -3 or scores["momentum"] <= -3
    f_fund_unlocked = (bond_yield - pce) >= 1.5
    dxy_strong = dxy_spot >= 103.5

    if composite_score >= 5 and pce < 2.0 and cape < 26.0 and not momentum_breaker:
        regime_name = "RISK-ON OVERRIDE"
        base_alloc = {"G": 35, "C": 45, "I": 15, "S": 5, "F": 0}
    elif composite_score >= 0:
        regime_name = "OPTIMIZED NEUTRAL"
        base_alloc = {"G": 45, "C": 35, "I": 10, "S": 10, "F": 0}
    else:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = {"G": 65, "C": 20, "I": 10, "S": 5, "F": 0}
        if scores["valuation"] == -5 and vix > 24.0:
            base_alloc = {"G": 70, "C": 20, "I": 5, "S": 5, "F": 0}

    if f_fund_unlocked and base_alloc["G"] >= 10:
        base_alloc["G"] -= 10
        base_alloc["F"] += 10

    alloc = base_alloc.copy()

    if asymmetric_vol_trigger:
        s_w = alloc["S"]
        alloc["S"] = 0
        if composite_score >= 0:
            alloc["G"] += s_w
        else:
            alloc["I"] += s_w

    if dxy_strong and alloc["I"] >= 5:
        alloc["I"] -= 5
        alloc["C"] += 5

    total = sum(alloc.values()) or 100
    final_alloc = {k: round((v / total) * 100, 1) for k, v in alloc.items()}

    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


# ==============================================================================
# STREAMLIT APP
# ==============================================================================

st.set_page_config(page_title="TSP Rebalance Engine - Stage 2", layout="wide")
st.title("TSP Rebalance Engine — Stage 2")
st.caption("Live data + scoring + regime + target allocation")

if st.button("Fetch & Run Engine"):
    with st.spinner("Loading live data and running engine..."):
        market_data = get_market_snapshot()
        allocations, factor_scores, total_score, regime, baseline, vol_t, dxy_t = execute_tsp_allocation_engine_final(market_data)

    st.success("Engine run complete")

    col1, col2, col3 = st.columns(3)
    col1.metric("Composite Score", total_score)
    col2.metric("Regime", regime)
    col3.metric("Emergency Valve", "ACTIVE" if total_score <= -20 else "CLEAR")

    st.subheader("Factor Scores")
    st.json(factor_scores)

    st.subheader("Market Snapshot")
    st.json(market_data)

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Baseline Allocation")
        st.json(baseline)

    with c2:
        st.subheader("Final Target Allocation")
        st.json(allocations)

    st.write(f"**Asymmetric Vol Trigger:** {vol_t}")
    st.write(f"**Strong DXY Trigger:** {dxy_t}")

else:
    st.info("Click **Fetch & Run Engine** to load live data and compute the allocation.")
