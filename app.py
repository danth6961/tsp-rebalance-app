from __future__ import annotations

from datetime import datetime, date
import re
import csv
import json
import math
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import pandas as pd
import yfinance as yf
import streamlit as st


# ==============================================================================
# PAGE CONFIG
# ==============================================================================

st.set_page_config(
    page_title="TSP Rebalance Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==============================================================================
# FILES / CONFIG & ROBUST FALLBACKS
# ==============================================================================

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 1.5

STATE_FILE = Path("tsp_state.json")
CONFIG_FILE = Path("tsp_config.json")
LOG_FILE = Path("tsp_daily_log.csv")

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

# Standard liquid ETFs that approximate the respective TSP funds
PROXIES = {
    "C Fund (S&P 500 Stock Index)": "SPY",
    "S Fund (Mid/Small Cap Stock Index)": "VXF",
    "I Fund (New Benchmark: ACWI ex USA ex China/HK)": "ACWX",
    "F Fund (U.S. Aggregate Bond Index)": "AGG",
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL"
}


# ==============================================================================
# STYLE (Dark-Mode Compliant & Modern Cards)
# ==============================================================================

def inject_custom_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 1450px;
        }

        .app-header {
            padding: 0.2rem 0 0.8rem 0;
            margin-bottom: 1.5rem;
            border-bottom: 1px solid rgba(148,163,184,0.2);
        }

        .app-title {
            font-size: 2.2rem;
            font-weight: 800;
            line-height: 1.15;
            margin: 0;
        }

        .app-subtitle {
            color: #64748b;
            font-size: 0.95rem;
            margin-top: 0.25rem;
        }

        .pill {
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            border: 1px solid rgba(148,163,184,0.18);
        }

        .pill-live { background: #dcfce7; color: #15803d; border-color: #bbf7d0; }
        .pill-default { background: #f3f4f6; color: #4b5563; border-color: #e5e7eb; }

        .small-kpi {
            padding: 0.9rem;
            border-radius: 12px;
            border: 1px solid rgba(148,163,184,0.18);
            background-color: rgba(248, 250, 252, 0.5);
            box-shadow: 0 2px 8px rgba(15,23,42,0.02);
            margin-bottom: 0.6rem;
        }

        .small-kpi-title {
            font-size: 0.75rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.25rem;
            font-weight: 700;
        }

        .small-kpi-value {
            font-size: 1.2rem;
            font-weight: 800;
            line-height: 1.15;
            word-break: break-word;
        }

        .small-kpi-note {
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 0.15rem;
        }

        [data-testid="stSidebar"] {
            background: #f8fafc;
            border-right: 1px solid rgba(148,163,184,0.14);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.4rem;
        }

        .stTabs [data-baseweb="tab"] {
            background: #f8fafc;
            border-radius: 8px 8px 0 0;
            padding: 0.5rem 0.9rem;
            border: 1px solid rgba(148,163,184,0.16);
        }

        .stTabs [aria-selected="true"] {
            background: #e0f2fe !important;
            border-color: #7dd3fc !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_custom_css()

st.markdown(
    """
    <div class="app-header">
        <div style="display:flex; align-items:center; gap:0.75rem;">
            <div style="font-size:2rem; line-height:1;">🏛️</div>
            <div>
                <div class="app-title">TSP Rebalance Engine</div>
                <div class="app-subtitle">Decision support dashboard for TSP allocation management and IFT discipline.</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


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


def max_alloc_drift(current_alloc: Dict[str, float], target_alloc: Dict[str, float]) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)


def append_log_row(row: Dict[str, Any]) -> None:
    try:
        file_exists = LOG_FILE.exists()
        with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        pass


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def df_to_json_bytes(df: pd.DataFrame) -> bytes:
    return df.to_json(orient="records", indent=2).encode("utf-8")


# ==============================================================================
# STATE / CONFIG
# ==============================================================================

def default_state() -> Dict[str, Any]:
    return {
        "month": None,
        "ift_count_this_month": 0,
        "last_ift_date": None,
        "recent_regimes": [],
        "recent_scores": [],
        "recent_allocations": [],
    }


def load_state() -> Dict[str, Any]:
    if "session_state_fallback" not in st.session_state:
        st.session_state["session_state_fallback"] = default_state()
        
    if not STATE_FILE.exists():
        return st.session_state["session_state_fallback"]
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return st.session_state["session_state_fallback"]
    base = default_state()
    base.update(state)
    return base


def save_state(state: Dict[str, Any]) -> None:
    st.session_state["session_state_fallback"] = state
    try:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True, default=str)
    except Exception:
        pass


def reset_monthly_if_needed(state: Dict[str, Any], today: date) -> Dict[str, Any]:
    current_month = today.strftime("%Y-%m")
    if state.get("month") != current_month:
        state["month"] = current_month
        state["ift_count_this_month"] = 0
        state["last_ift_date"] = None
    return state


def update_signal_history(state: Dict[str, Any], regime: str, total_score: int, alloc: Dict[str, float]) -> Dict[str, Any]:
    state["recent_regimes"].append(regime)
    state["recent_scores"].append(int(total_score))
    state["recent_allocations"].append(alloc)
    state["recent_regimes"] = state["recent_regimes"][-30:]
    state["recent_scores"] = state["recent_scores"][-30:]
    state["recent_allocations"] = state["recent_allocations"][-30:]
    return state


def load_config() -> Dict[str, Any]:
    default_cfg = {
        "current_alloc": {"G": 40.0, "C": 30.0, "I": 20.0, "S": 5.0, "F": 5.0},
        "allow_second_ift": False,
        "normal_drift_threshold_pct": 7.5,
        "score_change_threshold": 3,
        "confirmation_days": 3,
        "cooldown_days": 5,
        "core_pce_yoy": DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "shiller_cape": DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "market_breadth_pct": DEFAULTS["market_breadth_pct"],
        "use_live_macro": True,
    }
    if not CONFIG_FILE.exists():
        return default_cfg
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return default_cfg
    default_cfg.update(cfg)
    default_cfg["current_alloc"] = cfg.get("current_alloc", default_cfg["current_alloc"])
    return default_cfg


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True, default=str)
    except Exception:
        pass


# ==============================================================================
# DATA HELPERS & ADVANCED SCAPING LOGIC
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


def fetch_fred_core_pce_yoy() -> Optional[float]:
    """Downloads monthly core PCE index values from FRED and calculates the 12-month change %."""
    def _load():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id=PCEPILFE"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            df = pd.read_csv(response)

        if df.empty or len(df.columns) < 2:
            return None

        value_col = df.columns[1]
        series = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if len(series) < 13:
            return None
        
        latest_val = float(series.iloc[-1])
        past_val = float(series.iloc[-13])
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    try:
        return retry_call(_load)
    except Exception:
        return None


def fetch_shiller_cape_live() -> Optional[float]:
    """Parses multpl.com's HTML payload to read the latest cyclically adjusted P/E."""
    def _load():
        url = "https://www.multpl.com/shiller-pe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
        
        # S&P 500 Shiller P/E main number is typically inside <span class="num">
        match = re.search(r'class=["\']num["\']>\s*([0-9\.]+)\s*<', html)
        if match:
            return float(match.group(1))
        
        match_alt = re.search(r'Current Shiller PE Ratio is\s+([0-9\.]+)', html, re.IGNORECASE)
        if match_alt:
            return float(match_alt.group(1))
            
        return None

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


def fetch_yfinance_dataframe(ticker: str, period: str = "1y") -> pd.DataFrame:
    def _load():
        df = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            if ("Close", ticker) in df.columns:
                close_series = df[("Close", ticker)]
            else:
                close_candidates = [c for c in df.columns if c[0] == "Close"]
                if not close_candidates:
                    return pd.DataFrame()
                close_series = df[close_candidates[0]]
        else:
            if "Close" not in df.columns:
                return pd.DataFrame()
            close_series = df["Close"]

        clean_df = pd.DataFrame({
            "Date": close_series.index,
            "Price": pd.to_numeric(close_series.values, errors="coerce")
        }).dropna()
        return clean_df

    try:
        return retry_call(_load)
    except Exception:
        return pd.DataFrame()


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
# CACHED SNAPSHOTS
# ==============================================================================

@st.cache_data(ttl=900)
def cached_fred(series_id: str) -> Optional[float]:
    return fetch_fred_latest(series_id)


@st.cache_data(ttl=900)
def cached_fred_core_pce_yoy() -> Optional[float]:
    return fetch_fred_core_pce_yoy()


@st.cache_data(ttl=900)
def cached_shiller_cape_live() -> Optional[float]:
    return fetch_shiller_cape_live()


@st.cache_data(ttl=900)
def cached_yahoo_closes(ticker: str, period: str, interval: str) -> List[float]:
    return fetch_yfinance_closes(ticker, period=period, interval=interval)


@st.cache_data(ttl=900)
def get_cached_proxy_df(ticker: str, period: str) -> pd.DataFrame:
    return fetch_yfinance_dataframe(ticker, period)


@st.cache_data(ttl=900)
def get_market_snapshot() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(cached_fred, "DRTSCIS"): "sloos_val",
            executor.submit(cached_fred, "BAMLH0A0HYM2"): "hy_val",
            executor.submit(cached_fred, "STLFSI4"): "stlfsi_val",
            executor.submit(cached_fred, "DGS10"): "bond_val",
            executor.submit(cached_fred_core_pce_yoy): "pce_yoy_val",
            executor.submit(cached_shiller_cape_live): "shiller_cape_val",
            executor.submit(cached_yahoo_closes, "^VIX", "1mo", "1d"): "vix_closes",
            executor.submit(cached_yahoo_closes, "DX-Y.NYB", "1mo", "1d"): "dxy_closes",
            executor.submit(cached_yahoo_closes, "^GSPC", "1y", "1d"): "spx_closes",
            executor.submit(cached_yahoo_closes, "^S5TH", "1mo", "1d"): "breadth_closes",
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
    breadth_closes = results.get("breadth_closes") or []
    
    sma_dist_live, drawdown_live, spx_spot = calc_spx_metrics_from_closes(spx_closes)
    
    pce_yoy = results.get("pce_yoy_val")
    shiller_cape = results.get("shiller_cape_val")
    live_breadth = breadth_closes[-1] if breadth_closes else None

    # 3-day Panic Valve Logic Evaluations
    vix_3d_panic = False
    vix_last_3 = []
    if len(vix_closes) >= 3:
        vix_last_3 = [round(x, 2) for x in vix_closes[-3:]]
        vix_3d_panic = all(x >= 30.0 for x in vix_closes[-3:])

    spx_3d_panic = False
    spx_dist_last_3 = []
    if len(spx_closes) >= 202:
        sma_0 = sum(spx_closes[-200:]) / 200.0
        dist_0 = ((spx_closes[-1] - sma_0) / sma_0) * 100.0

        sma_1 = sum(spx_closes[-201:-1]) / 200.0
        dist_1 = ((spx_closes[-2] - sma_1) / sma_1) * 100.0

        sma_2 = sum(spx_closes[-202:-2]) / 200.0
        dist_2 = ((spx_closes[-3] - sma_2) / sma_2) * 100.0

        spx_dist_last_3 = [round(dist_2, 2), round(dist_1, 2), round(dist_0, 2)]
        spx_3d_panic = all(x <= -5.0 for x in [dist_2, dist_1, dist_0])

    market_data = {
        "core_pce_yoy": pce_yoy if pce_yoy is not None else DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "sloos_net_pct": results.get("sloos_val") if results.get("sloos_val") is not None else DEFAULTS["sloos_net_pct"],
        "hy_oas": results.get("hy_val") if results.get("hy_val") is not None else DEFAULTS["hy_oas"],
        "shiller_cape": shiller_cape if shiller_cape is not None else DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "vix_spot": vix_closes[-1] if vix_closes else DEFAULTS["vix_spot"],
        "pct_dist_200_sma": sma_dist_live,
        "drawdown_pct": drawdown_live,
        "stlfsi_index": results.get("stlfsi_val") if results.get("stlfsi_val") is not None else DEFAULTS["stlfsi_index"],
        "bond_yield_10y": results.get("bond_val") if results.get("bond_val") is not None else DEFAULTS["bond_yield_10y"],
        "dxy_spot": dxy_closes[-1] if dxy_closes else DEFAULTS["dxy_spot"],
        "market_breadth_pct": live_breadth if live_breadth is not None else DEFAULTS["market_breadth_pct"],
        "spx_spot": spx_spot,
        "vix_3d_panic": vix_3d_panic,
        "vix_last_3": vix_last_3,
        "spx_3d_panic": spx_3d_panic,
        "spx_dist_last_3": spx_dist_last_3,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    market_sources = {
        "core_pce_yoy": "LIVE (FRED PCEPILFE YoY)" if pce_yoy is not None else "CONFIG/DEFAULT",
        "ism_pmi": "CONFIG/DEFAULT",
        "sloos_net_pct": "LIVE" if results.get("sloos_val") is not None else "DEFAULT",
        "hy_oas": "LIVE" if results.get("hy_val") is not None else "DEFAULT",
        "shiller_cape": "LIVE (Multpl.com CAPE)" if shiller_cape is not None else "CONFIG/DEFAULT",
        "fwd_eps_growth_yoy": "CONFIG/DEFAULT",
        "vix_spot": "LIVE" if vix_closes else "DEFAULT",
        "pct_dist_200_sma": "LIVE" if spx_closes else "DEFAULT",
        "drawdown_pct": "LIVE" if spx_closes else "DEFAULT",
        "stlfsi_index": "LIVE" if results.get("stlfsi_val") is not None else "DEFAULT",
        "bond_yield_10y": "LIVE" if results.get("bond_val") is not None else "DEFAULT",
        "dxy_spot": "LIVE" if dxy_closes else "DEFAULT",
        "market_breadth_pct": "LIVE (Yahoo Finance ^S5TH)" if live_breadth is not None else "CONFIG/DEFAULT",
        "spx_spot": "LIVE" if spx_closes else "DEFAULT",
    }

    return {"market_data": market_data, "market_sources": market_sources}


# ==============================================================================
# ENGINE / IFT DECISION
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
    market_breadth = safe_float(data.get("market_breadth_pct"), DEFAULTS["market_breadth_pct"])

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

    # Evaluation of Panic Valve Logic
    vix_3d_panic = data.get("vix_3d_panic", False)
    spx_3d_panic = data.get("spx_3d_panic", False)
    panic_valve_triggered = (vix_3d_panic or spx_3d_panic) and (market_breadth <= 60.0)

    if panic_valve_triggered:
        regime_name = "EMERGENCY DISPATCH"
        composite_score = -50
        if f_fund_unlocked:
            base_alloc = {"G": 90, "C": 0, "I": 0, "S": 0, "F": 10}
        else:
            base_alloc = {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0}
        alloc = base_alloc.copy()
    else:
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
            alloc["G" if composite_score >= 0 else "I"] += s_w
        if dxy_strong and alloc["I"] >= 5:
            alloc["I"] -= 5
            alloc["C"] += 5

    total = sum(alloc.values()) or 100
    final_alloc = {k: round((v / total) * 100, 1) for k, v in alloc.items()}
    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def should_use_tsp_ift(
    today: date,
    current_alloc: Dict[str, float],
    target_alloc: Dict[str, float],
    recent_regimes: List[str],
    recent_scores: List[int],
    emergency_triggered: bool,
    ift_count_this_month: int,
    last_ift_date: Optional[date],
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
    confirmation_days: int,
    cooldown_days: int,
) -> Tuple[bool, str]:
    if ift_count_this_month >= 2:
        return False, "No IFTs remaining this month"
    if last_ift_date is not None and (today - last_ift_date).days < cooldown_days:
        return False, f"Cooldown active ({cooldown_days} days)"
    if emergency_triggered:
        return True, "Emergency trigger activated"
    if ift_count_this_month >= 1 and not allow_second_ift:
        return False, "Preserving final IFT reserve"
    if len(recent_regimes) < confirmation_days or len(recent_scores) < confirmation_days:
        return False, "Insufficient confirmation history"
    if len(set(recent_regimes[-confirmation_days:])) != 1:
        return False, "Regime not yet confirmed"
    score_span = max(recent_scores[-confirmation_days:]) - min(recent_scores[-confirmation_days:])
    if score_span < score_change_threshold:
        return False, "Score change not strong enough"
    drift = max_alloc_drift(current_alloc, target_alloc)
    if drift < normal_drift_threshold_pct:
        return False, f"Allocation drift too small ({drift:.1f}%)"
    return True, f"Confirmed regime shift with {drift:.1f}% drift"


# ==============================================================================
# DISPLAY HELPERS
# ==============================================================================

def render_metric_cards(total_score, regime, action, ift_used, reason):
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid #3b82f6;">
                <div class="small-kpi-title">Composite Score</div>
                <div class="small-kpi-value">{total_score}</div>
                <div class="small-kpi-note">Higher is more risk-on</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        action_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#22c55e" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid {action_color};">
                <div class="small-kpi-title">Action</div>
                <div class="small-kpi-value" style="color:{action_color};">{action}</div>
                <div class="small-kpi-note">Decision recommendation</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid #f59e0b;">
                <div class="small-kpi-title">IFTs Used</div>
                <div class="small-kpi-value">{ift_used}/2</div>
                <div class="small-kpi-note">Monthly transfer count</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid #a78bfa;">
                <div class="small-kpi-title">Regime</div>
                <div class="small-kpi-value" style="font-size:1.0rem;">{regime}</div>
                <div class="small-kpi-note">Model state</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c5:
        reason_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#16a34a" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            f"""
            <div class="small-kpi" style="border-left: 5px solid {reason_color};">
                <div class="small-kpi-title">IFT Reason</div>
                <div class="small-kpi-value" style="font-size:0.95rem; color:{reason_color}; line-height:1.2;">
                    {reason}
                </div>
                <div class="small-kpi-note">Why this action was chosen</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def make_score_chart(state: Dict[str, Any]):
    if not state["recent_scores"]:
        return None
    return pd.DataFrame({
        "Run": list(range(1, len(state["recent_scores"]) + 1)),
        "Score": state["recent_scores"],
    }).set_index("Run")


def make_alloc_chart(target_alloc: Dict[str, float], current_alloc: Dict[str, float]):
    funds = ["G", "C", "I", "S", "F"]
    return pd.DataFrame({
        "Fund": funds,
        "Current": [current_alloc.get(f, 0.0) for f in funds],
        "Target": [target_alloc.get(f, 0.0) for f in funds],
    })


def make_regime_summary_df(current_regime: str) -> pd.DataFrame:
    df = pd.DataFrame([
        {
            "Regime": "RISK-ON OVERRIDE",
            "Score Range": ">= 5",
            "Base Allocation": "G 35 / C 45 / I 15 / S 5 / F 0",
            "Profile": "Aggressive",
            "Notes": "Strong macro backdrop and supportive momentum."
        },
        {
            "Regime": "OPTIMIZED NEUTRAL",
            "Score Range": ">= 0",
            "Base Allocation": "G 45 / C 35 / I 10 / S 10 / F 0",
            "Profile": "Balanced",
            "Notes": "Default regime when the signal is constructive but mixed."
        },
        {
            "Regime": "DEFENSIVE ALLOCATION",
            "Score Range": "< 0",
            "Base Allocation": "G 65 / C 20 / I 10 / S 5 / F 0",
            "Profile": "Defensive",
            "Notes": "Used when risk rises or the composite turns negative."
        },
        {
            "Regime": "EMERGENCY DISPATCH",
            "Score Range": "-50",
            "Base Allocation": "G 90 / C 0 / I 0 / S 0 / F 10 (or G 100 / F 0)",
            "Profile": "Maximum defense",
            "Notes": "3-day panic valve breach."
        },
    ])
    df["Current"] = df["Regime"].eq(current_regime).map({True: "★", False: ""})
    return df


def score_card_html(label: str, value: Any, note: str, color: str, icon: str) -> str:
    return f"""
    <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom:0.6rem;">
        <div class="small-kpi-title">{label}</div>
        <div class="small-kpi-value" style="color:{color};">{icon} {value}</div>
        <div class="small-kpi-note">{note}</div>
    </div>
    """


def source_pill_html(source: str) -> str:
    cls = "pill-live" if source.startswith("LIVE") else "pill-default"
    return f"<span class='pill {cls}'>{source}</span>"


# ==============================================================================
# APP STATE
# ==============================================================================

today = date.today()
state = reset_monthly_if_needed(load_state(), today)
cfg = load_config()


# ==============================================================================
# SIDEBAR (Decluttered with drop-down expanders & Plain-English tooltips)
# ==============================================================================

with st.sidebar:
    st.markdown("## ⚙️ Settings Dashboard")

    with st.expander("💼 Your Current Allocation", expanded=True):
        st.info("Input your current TSP holdings percentage. They must sum to 100%.")
        current_alloc = {
            "G": st.number_input("G Fund %", value=float(cfg.get("current_alloc", {}).get("G", 40.0)), step=1.0, help="Government Securities Fund: Extremely low-risk; safe interest-earning fund."),
            "C": st.number_input("C Fund %", value=float(cfg.get("current_alloc", {}).get("C", 30.0)), step=1.0, help="Common Stock Index Fund: Mimics the S&P 500 Index (large US companies)."),
            "I": st.number_input("I Fund %", value=float(cfg.get("current_alloc", {}).get("I", 20.0)), step=1.0, help="International Stock Index Fund: Tracks international company stocks."),
            "S": st.number_input("S Fund %", value=float(cfg.get("current_alloc", {}).get("S", 5.0)), step=1.0, help="Small Cap Stock Index Fund: Tracks smaller-sized US company stocks."),
            "F": st.number_input("F Fund %", value=float(cfg.get("current_alloc", {}).get("F", 5.0)), step=1.0, help="Fixed Income Index Fund: Tracks US bond market index."),
        }

    with st.expander("🛡️ Transfer Rules & Safeties", expanded=False):
        st.info("Safety limits designed to preserve your monthly transfer quotas.")
        allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg.get("allow_second_ift", False)), help="Normally you are limited to 2 transfers a month. Enabling this allows the system to make a second transfer in normal regimes if conditions are favorable.")
        normal_drift_threshold_pct = st.number_input("Normal drift threshold %", value=float(cfg.get("normal_drift_threshold_pct", 7.5)), step=0.5, help="How far out of alignment your real portfolio is from target before recommending an adjustment.")
        score_change_threshold = st.number_input("Score change threshold", value=int(cfg.get("score_change_threshold", 3)), step=1, help="Required point difference to qualify as a strong trend adjustment.")
        confirmation_days = st.number_input("Confirmation days", value=int(cfg.get("confirmation_days", 3)), step=1, help="Number of consecutive days a signal must remain in a new regime before triggering action.")
        cooldown_days = st.number_input("Cooldown days", value=int(cfg.get("cooldown_days", 5)), step=1, help="Minimum days to wait after making a transfer before making another.")

    with st.expander("📊 Market Overrides (Advanced)", expanded=False):
        use_live_macro = st.checkbox("Use Live Macro Data where available", value=bool(cfg.get("use_live_macro", True)), help="When checked, the engine automatically calculates Core PCE YoY inflation from FRED, reads Shiller CAPE from multpl.com, and extracts Market Breadth from ^S5TH. It falls back to your manual entries below only if the live downloads fail.")
        st.markdown("---")
        st.warning("These manual values serve as overrides or fallback configurations.")
        core_pce_yoy = st.number_input("Core PCE Inflation %", value=float(cfg.get("core_pce_yoy", DEFAULTS["core_pce_yoy"])), step=0.1, help="Core Personal Consumption Expenditures index. Tracks core inflation trends.")
        ism_pmi = st.number_input("ISM PMI (Growth)", value=float(cfg.get("ism_pmi", DEFAULTS["ism_pmi"])), step=0.5, help="Manufacturing Purchasing Managers Index. Measures economic growth strength.")
        shiller_cape = st.number_input("Shiller CAPE (Valuation)", value=float(cfg.get("shiller_cape", DEFAULTS["shiller_cape"])), step=0.5, help="Cyclically Adjusted Price-to-Earnings. Tracks long-term valuation of stocks.")
        fwd_eps_growth_yoy = st.number_input("Fwd EPS Growth %", value=float(cfg.get("fwd_eps_growth_yoy", DEFAULTS["fwd_eps_growth_yoy"])), step=0.5, help="Forecasted growth of company earnings over the next year.")
        market_breadth_pct = st.number_input("Market Breadth %", value=float(cfg.get("market_breadth_pct", DEFAULTS["market_breadth_pct"])), step=0.5, help="Measures what % of stocks are participating in the market's uptrend.")

    st.markdown("---")
    mark_ift = st.button("✅ Mark IFT Used Today", use_container_width=True, help="Click if you executed a real-life transfer today, keeping the monthly count synchronized.")
    reset_state_btn = st.button("♻️ Reset State File", use_container_width=True, help="Resets your transfer counters back to zero.")
    clear_logs_btn = st.button("🗑️ Clear Daily Log File", use_container_width=True, help="Removes the daily logs CSV file permanently.")
    save_config_btn = st.button("💾 Save Config Settings", use_container_width=True, help="Saves your current portfolio holdings and safety preferences permanently.")

if save_config_btn:
    cfg["current_alloc"] = current_alloc
    cfg["allow_second_ift"] = allow_second_ift
    cfg["normal_drift_threshold_pct"] = float(normal_drift_threshold_pct)
    cfg["score_change_threshold"] = int(score_change_threshold)
    cfg["confirmation_days"] = int(confirmation_days)
    cfg["cooldown_days"] = int(cooldown_days)
    cfg["core_pce_yoy"] = float(core_pce_yoy)
    cfg["ism_pmi"] = float(ism_pmi)
    cfg["shiller_cape"] = float(shiller_cape)
    cfg["fwd_eps_growth_yoy"] = float(fwd_eps_growth_yoy)
    cfg["market_breadth_pct"] = float(market_breadth_pct)
    cfg["use_live_macro"] = bool(use_live_macro)
    save_config(cfg)
    st.sidebar.success("Config saved.")

if mark_ift:
    state["ift_count_this_month"] += 1
    state["last_ift_date"] = today.isoformat()
    save_state(state)
    st.sidebar.success("IFT marked for today.")

if reset_state_btn:
    state = default_state()
    save_state(state)
    st.sidebar.warning("State reset.")

if clear_logs_btn:
    try:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
            st.sidebar.success("Log file successfully deleted.")
        else:
            st.sidebar.info("No log file exists to delete.")
    except Exception as e:
        st.sidebar.error(f"Error deleting log file: {e}")


# ==============================================================================
# MAIN ENGINE EXECUTION (Robust Session Persistence Enabled)
# ==============================================================================

if "engine_ran" not in st.session_state:
    st.session_state["engine_ran"] = False
    st.session_state["engine_results"] = {}

run = st.button("🚀 Fetch & Run Engine", use_container_width=True)

if run:
    with st.spinner("Loading live data and running engine..."):
        try:
            snapshot = get_market_snapshot()
            market_data = snapshot["market_data"]
            market_sources = snapshot["market_sources"]
        except Exception as e:
            st.error(f"Could not connect to live feeds. Using system offline baselines. (Info: {e})")
            market_data = DEFAULTS.copy()
            market_data["vix_spot"] = DEFAULTS["vix_spot"]
            market_data["pct_dist_200_sma"] = 1.2
            market_data["drawdown_pct"] = 2.5
            market_data["vix_3d_panic"] = False
            market_data["vix_last_3"] = [19.0, 19.1, 19.0]
            market_data["spx_3d_panic"] = False
            market_data["spx_dist_last_3"] = [1.1, 1.2, 1.2]
            market_data["spx_spot"] = 5000.0
            market_sources = {k: "OFFLINE FALLBACK" for k in DEFAULTS.keys()}

        # Core logic: Prioritize automated live data OR revert to manual inputs
        if not use_live_macro:
            market_data["core_pce_yoy"] = core_pce_yoy
            market_data["shiller_cape"] = shiller_cape
            market_data["market_breadth_pct"] = market_breadth_pct
            
            market_sources["core_pce_yoy"] = "MANUAL OVERRIDE"
            market_sources["shiller_cape"] = "MANUAL OVERRIDE"
            market_sources["market_breadth_pct"] = "MANUAL OVERRIDE"
        else:
            # Revert only if live calculation returned None
            if market_data.get("core_pce_yoy") is None:
                market_data["core_pce_yoy"] = core_pce_yoy
                market_sources["core_pce_yoy"] = "MANUAL OVERRIDE (Live Fetch Failed)"
            if market_data.get("shiller_cape") is None:
                market_data["shiller_cape"] = shiller_cape
                market_sources["shiller_cape"] = "MANUAL OVERRIDE (Live Fetch Failed)"
            if market_data.get("market_breadth_pct") is None:
                market_data["market_breadth_pct"] = market_breadth_pct
                market_sources["market_breadth_pct"] = "MANUAL OVERRIDE (Live Fetch Failed)"

        # Set variables that do not have automated feeds
        market_data["ism_pmi"] = ism_pmi
        market_data["fwd_eps_growth_yoy"] = fwd_eps_growth_yoy

        allocations, factor_scores, total_score, regime, baseline, vol_t, dxy_t = execute_tsp_allocation_engine_final(market_data)

    emergency_triggered = (total_score == -50)
    state = update_signal_history(state, regime, total_score, allocations)
    last_ift_date = date.fromisoformat(state["last_ift_date"]) if state["last_ift_date"] else None

    use_ift, reason = should_use_tsp_ift(
        today=today,
        current_alloc=current_alloc,
        target_alloc=allocations,
        recent_regimes=state["recent_regimes"],
        recent_scores=state["recent_scores"],
        emergency_triggered=emergency_triggered,
        ift_count_this_month=state["ift_count_this_month"],
        last_ift_date=last_ift_date,
        allow_second_ift=allow_second_ift,
        normal_drift_threshold_pct=float(normal_drift_threshold_pct),
        score_change_threshold=int(score_change_threshold),
        confirmation_days=int(confirmation_days),
        cooldown_days=int(cooldown_days),
    )

    action = "SUBMIT IFT" if use_ift else "HOLD"
    if use_ift:
        state["ift_count_this_month"] += 1
        state["last_ift_date"] = today.isoformat()

    save_state(state)

    cfg["current_alloc"] = current_alloc
    cfg["allow_second_ift"] = allow_second_ift
    cfg["normal_drift_threshold_pct"] = float(normal_drift_threshold_pct)
    cfg["score_change_threshold"] = int(score_change_threshold)
    cfg["confirmation_days"] = int(confirmation_days)
    cfg["cooldown_days"] = int(cooldown_days)
    cfg["core_pce_yoy"] = float(core_pce_yoy)
    cfg["ism_pmi"] = float(ism_pmi)
    cfg["shiller_cape"] = float(shiller_cape)
    cfg["fwd_eps_growth_yoy"] = float(fwd_eps_growth_yoy)
    cfg["market_breadth_pct"] = float(market_breadth_pct)
    cfg["use_live_macro"] = bool(use_live_macro)
    save_config(cfg)

    append_log_row({
        "date": today.isoformat(),
        "action": action,
        "reason": reason,
        "regime": regime,
        "total_score": total_score,
        "ift_count_this_month": state["ift_count_this_month"],
        "current_alloc": json.dumps(current_alloc),
        "target_alloc": json.dumps(allocations),
        "vix": market_data["vix_spot"],
        "spx_200sma_dist": market_data["pct_dist_200_sma"],
        "drawdown_pct": market_data["drawdown_pct"],
    })

    # Save outputs to memory to protect against resetting during user clicks
    st.session_state["engine_results"] = {
        "market_data": market_data,
        "market_sources": market_sources,
        "allocations": allocations,
        "factor_scores": factor_scores,
        "total_score": total_score,
        "regime": regime,
        "baseline": baseline,
        "action": action,
        "reason": reason,
    }
    st.session_state["engine_ran"] = True


# ==============================================================================
# DASHBOARD LAYOUT & TABS
# ==============================================================================

if st.session_state["engine_ran"]:
    # Retrieve active outputs from persistent session memory
    res = st.session_state["engine_results"]
    market_data = res["market_data"]
    market_sources = res["market_sources"]
    allocations = res["allocations"]
    factor_scores = res["factor_scores"]
    total_score = res["total_score"]
    regime = res["regime"]
    baseline = res["baseline"]
    action = res["action"]
    reason = res["reason"]

    render_metric_cards(total_score, regime, action, state["ift_count_this_month"], reason)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Allocation", "🧠 Factors", "📊 Proxy Charts", "🕒 History", "📁 Logs & State"])

    with tab1:
        st.markdown("### Allocation Comparison")
        alloc_df = make_alloc_chart(allocations, current_alloc)

        for _, row in alloc_df.iterrows():
            fund = row["Fund"]
            current = float(row["Current"])
            target = float(row["Target"])
            drift = target - current

            c1, c2, c3, c4 = st.columns([0.5, 1.1, 1.1, 0.6])

            with c1:
                st.markdown(f"**{fund}**")

            with c2:
                st.markdown(f"Current: **{current:.1f}%**")
                st.progress(min(max(current / 100.0, 0.0), 1.0))

            with c3:
                st.markdown(f"Target: **{target:.1f}%**")
                st.progress(min(max(target / 100.0, 0.0), 1.0))

            with c4:
                color = "#16a34a" if drift > 0 else "#dc2626" if drift < 0 else "#64748b"
                st.markdown(
                    f"<div style='color:{color}; font-weight:700; padding-top:0.9rem;'>{drift:+.1f}%</div>",
                    unsafe_allow_html=True,
                )

        st.caption("Left = current allocation. Right = target allocation. Drift shown at far right.")

        st.markdown("---")
        st.markdown("### Baseline Allocation")
        
        # Display baseline metrics side-by-side using Streamlit columns
        base_cols = st.columns(5)
        for idx, fund in enumerate(["G", "C", "I", "S", "F"]):
            val = float(baseline.get(fund, 0.0))
            with base_cols[idx]:
                st.metric(label=f"Baseline {fund}", value=f"{val:.1f}%")
        
        # Display a bar chart for the baseline allocation
        baseline_df = pd.DataFrame({
            "Fund": ["G", "C", "I", "S", "F"],
            "Baseline Allocation (%)": [float(baseline.get(f, 0.0)) for f in ["G", "C", "I", "S", "F"]]
        }).set_index("Fund")
        
        st.bar_chart(baseline_df, y="Baseline Allocation (%)")

    with tab2:
        # Panic Valve Auditing & Verification Displays
        st.markdown("### 🚨 Panic Valve & Emergency Dispatch Diagnostic")
        pv_cols = st.columns(3)
        with pv_cols[0]:
            vix_status = "🔴 TRIGGERED (VIX >= 30)" if market_data.get("vix_3d_panic") else "🟢 Normal"
            vix_hist_str = ", ".join(map(str, market_data.get("vix_last_3", []))) if market_data.get("vix_last_3") else "N/A"
            st.markdown(
                score_card_html("VIX 3-Day State", vix_status, f"Last 3 closes: [{vix_hist_str}]", "#dc2626" if market_data.get("vix_3d_panic") else "#16a34a", "⚠️"),
                unsafe_allow_html=True,
            )
        with pv_cols[1]:
            spx_status = "🔴 TRIGGERED (SMA Dist <= -5%)" if market_data.get("spx_3d_panic") else "🟢 Normal"
            spx_hist_str = ", ".join(map(str, market_data.get("spx_dist_last_3", []))) if market_data.get("spx_dist_last_3") else "N/A"
            st.markdown(
                score_card_html("SPX 200SMA 3-Day State", spx_status, f"Last 3 dist %: [{spx_hist_str}]", "#dc2626" if market_data.get("spx_3d_panic") else "#16a34a", "⚠️"),
                unsafe_allow_html=True,
            )
        with pv_cols[2]:
            breadth_val = market_data.get("market_breadth_pct", 0.0)
            override_active = breadth_val > 60.0
            breadth_status = "🟢 ACTIVE (Breadth > 60%)" if override_active else "🔴 INACTIVE"
            st.markdown(
                score_card_html("Breadth Override State", breadth_status, f"Current Breadth: {breadth_val}%", "#16a34a" if override_active else "#dc2626", "🛡️"),
                unsafe_allow_html=True,
            )

        st.markdown("### Factor Scores")
        score_order = [
            ("inflation", "Inflation"),
            ("growth", "Growth"),
            ("liquidity", "Liquidity"),
            ("credit_spreads", "Credit Spreads"),
            ("valuation", "Valuation"),
            ("market_stress", "Market Stress"),
            ("momentum", "Momentum"),
            ("drawdown", "Drawdown"),
        ]
        factor_cols = st.columns(4)
        for i, (key, label) in enumerate(score_order):
            val = factor_scores.get(key, 0)
            color = "#16a34a" if val > 0 else "#dc2626" if val < 0 else "#64748b"
            icon = "▲" if val > 0 else "▼" if val < 0 else "●"
            with factor_cols[i % 4]:
                st.markdown(
                    score_card_html(label, val, "Factor contribution", color, icon),
                    unsafe_allow_html=True,
                )

        st.markdown("### Market Snapshot")
        market_items = [
            ("Core PCE YoY", market_data.get("core_pce_yoy"), market_sources.get("core_pce_yoy")),
            ("ISM PMI", market_data.get("ism_pmi"), market_sources.get("ism_pmi")),
            ("SLOOS Net %", market_data.get("sloos_net_pct"), market_sources.get("sloos_net_pct")),
            ("HY OAS", market_data.get("hy_oas"), market_sources.get("hy_oas")),
            ("Shiller CAPE", market_data.get("shiller_cape"), market_sources.get("shiller_cape")),
            ("Fwd EPS Growth YoY", market_data.get("fwd_eps_growth_yoy"), market_sources.get("fwd_eps_growth_yoy")),
            ("VIX Spot", market_data.get("vix_spot"), market_sources.get("vix_spot")),
            ("SPX vs 200SMA %", market_data.get("pct_dist_200_sma"), market_sources.get("pct_dist_200_sma")),
            ("Drawdown %", market_data.get("drawdown_pct"), market_sources.get("drawdown_pct")),
            ("STLFSI", market_data.get("stlfsi_index"), market_sources.get("stlfsi_index")),
            ("10Y Yield", market_data.get("bond_yield_10y"), market_sources.get("bond_yield_10y")),
            ("DXY Spot", market_data.get("dxy_spot"), market_sources.get("dxy_spot")),
            ("Breadth %", market_data.get("market_breadth_pct"), market_sources.get("market_breadth_pct")),
            ("SPX Spot", market_data.get("spx_spot"), market_sources.get("spx_spot")),
        ]
        market_cols = st.columns(4)
        for i, (label, value, source) in enumerate(market_items):
            with market_cols[i % 4]:
                st.markdown(
                    f"""
                    <div class="small-kpi" style="margin-bottom:0.6rem;">
                        <div class="small-kpi-title">{label}</div>
                        <div class="small-kpi-value">{value if value is not None else 'N/A'}</div>
                        <div class="small-kpi-note">{source_pill_html(source)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("### Regime Summary")
        regime_summary_df = make_regime_summary_df(regime)
        st.dataframe(regime_summary_df, use_container_width=True, hide_index=True)
        st.markdown("---")
        
        st.subheader("🔍 Engine Explanation")
        st.write(f"**Composite Score:** {total_score}")
        
        # Colored visual indicators for the current engine regime
        if regime == "RISK-ON OVERRIDE":
            st.success(f"🟢 Current Regime: {regime}")
        elif regime == "OPTIMIZED NEUTRAL":
            st.info(f"🟡 Current Regime: {regime}")
        elif regime == "DEFENSIVE ALLOCATION":
            st.warning(f"🟠 Current Regime: {regime}")
        elif regime == "EMERGENCY DISPATCH":
            st.error(f"🔴 Current Regime: {regime}")
        else:
            st.write(f"Current Regime: {regime}")

    with tab3:
        st.markdown("### Live TSP Fund Proxy Price Tracking")
        st.write(
            "The Federal Retirement Thrift Investment Board does not provide direct tickers. "
            "The charts below plot standard liquid exchange-traded funds (ETFs) that closely proxy "
            "each TSP asset class. The **I Fund** tracks its transition to its broad global "
            "MSCI ACWI ex USA ex China ex HK index using **ACWX**."
        )

        col_chart_1, col_chart_2 = st.columns([1, 3])
        with col_chart_1:
            fund_selected = st.selectbox(
                "Select TSP Fund to Plot",
                options=list(PROXIES.keys())
            )
            timeframe_selected = st.selectbox(
                "Select Performance Chart Timeframe",
                options=["1 Month", "3 Months", "6 Months", "1 Year", "5 Years", "10 Years"],
                index=3
            )

        ticker = PROXIES[fund_selected]
        period_map = {
            "1 Month": "1mo",
            "3 Months": "3mo",
            "6 Months": "6mo",
            "1 Year": "1y",
            "5 Years": "5y",
            "10 Years": "10y"
        }
        period = period_map[timeframe_selected]

        with st.spinner(f"Loading live price history for {ticker}..."):
            proxy_df = get_cached_proxy_df(ticker, period)

        if not proxy_df.empty:
            dates = proxy_df["Date"].tolist()
            prices = proxy_df["Price"].tolist()

            start_price = prices[0]
            end_price = prices[-1]
            perf_pct = ((end_price - start_price) / start_price) * 100.0

            p_high = max(prices)
            p_low = min(prices)

            with col_chart_1:
                st.markdown("---")
                st.metric(
                    label=f"Latest Close ({ticker})",
                    value=f"${end_price:.2f}",
                    delta=f"{perf_pct:+.2f}% over {timeframe_selected}"
                )
                st.markdown(f"**Period High:** `${p_high:.2f}`")
                st.markdown(f"**Period Low:** `${p_low:.2f}`")

            with col_chart_2:
                plot_data = proxy_df.set_index("Date")
                st.line_chart(plot_data, y="Price")
        else:
            st.error(f"Failed to fetch market data for proxy ticker: {ticker}. Please try again later.")
        
    with tab4:
        st.markdown("### Score History")
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")

        st.markdown("---")
        st.markdown("### Recent State Overview")
        
        # Display meta metrics side-by-side using Streamlit columns
        state_cols = st.columns(3)
        with state_cols[0]:
            st.metric(label="Current Tracking Month", value=state.get("month") or "N/A")
        with state_cols[1]:
            st.metric(label="IFTs Used This Month", value=f"{state.get('ift_count_this_month', 0)} / 2")
        with state_cols[2]:
            last_date = state.get("last_ift_date")
            st.metric(label="Last IFT Date", value=str(last_date) if last_date else "None")
            
        st.markdown("### Run History Log")
        
        # Combine historical tracking lists into a readable chronological table
        regimes = state.get("recent_regimes", [])
        scores = state.get("recent_scores", [])
        allocations_list = state.get("recent_allocations", [])
        
        if regimes and scores:
            while len(allocations_list) < len(regimes):
                allocations_list.append({})
                
            history_data = []
            for idx in range(len(regimes)):
                alloc = allocations_list[idx]
                alloc_str = " / ".join([f"{k} {alloc.get(k, 0.0):.1f}%" for k in ["G", "C", "I", "S", "F"]]) if alloc else "N/A"
                
                history_data.append({
                    "Run #": idx + 1,
                    "Regime Status": regimes[idx],
                    "Engine Score": scores[idx],
                    "Target Portfolio": alloc_str
                })
            
            # Reverse so that the most recent execution appears at the top
            history_df = pd.DataFrame(history_data).iloc[::-1]
            
            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Run #": st.column_config.NumberColumn("Run ID", format="%d"),
                    "Regime Status": st.column_config.TextColumn("Regime Status"),
                    "Engine Score": st.column_config.NumberColumn("Engine Score"),
                    "Target Portfolio": st.column_config.TextColumn("Target Portfolio Allocation Summary")
                }
            )
        else:
            st.info("No historical runs tracked yet.")

    with tab5:
        st.markdown("### Log Viewer")
        if LOG_FILE.exists():
            log_df = pd.read_csv(LOG_FILE)
            st.dataframe(log_df.tail(25), use_container_width=True, hide_index=True)

            export_col1, export_col2, export_col3 = st.columns(3)
            with export_col1:
                st.download_button(
                    "Download Log CSV",
                    data=df_to_csv_bytes(log_df),
                    file_name="tsp_daily_log.csv",
                    mime="text/csv",
                )
            with export_col2:
                st.download_button(
                    "Download Log JSON",
                    data=df_to_json_bytes(log_df),
                    file_name="tsp_daily_log.json",
                    mime="application/json",
                )
            with export_col3:
                st.download_button(
                    "Download Latest Snapshot JSON",
                    data=json.dumps({
                        "market_data": market_data,
                        "market_sources": market_sources,
                        "factor_scores": factor_scores,
                        "regime": regime,
                        "total_score": total_score,
                        "action": action,
                        "reason": reason,
                        "current_alloc": current_alloc,
                        "target_alloc": allocations,
                        "state": state,
                    }, indent=2).encode("utf-8"),
                    file_name="tsp_snapshot.json",
                    mime="application/json",
                )
        else:
            st.info("No log file yet.")

else:
    st.info("Use the sidebar to set allocations and policy, then click **Fetch & Run Engine**.")
