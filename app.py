from __future__ import annotations

from datetime import datetime, date
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
# FILES / CONFIG
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


# ==============================================================================
# STYLE
# ==============================================================================

def inject_custom_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 3.4rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 1450px;
        }

        .app-header {
            padding: 0.2rem 0 0.8rem 0;
            margin-bottom: 0.8rem;
            border-bottom: 1px solid rgba(148,163,184,0.22);
        }

        .app-title {
            font-size: 2.35rem;
            font-weight: 800;
            line-height: 1.15;
            margin: 0;
            padding-top: 0.15rem;
        }

        .app-subtitle {
            color: #64748b;
            font-size: 0.98rem;
            margin-top: 0.25rem;
        }

        .pill {
            display: inline-block;
            padding: 0.22rem 0.55rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            border: 1px solid rgba(148,163,184,0.18);
        }

        .pill-live { background: #dcfce7; color: #166534; border-color: #86efac; }
        .pill-default { background: #e5e7eb; color: #374151; border-color: #cbd5e1; }

        div[data-testid="metric-container"] {
            background: #ffffff;
            border: 1px solid rgba(148,163,184,0.22);
            padding: 0.85rem 1rem;
            border-radius: 16px;
            box-shadow: 0 4px 14px rgba(15,23,42,0.05);
        }

        .small-kpi {
            padding: 0.8rem 0.9rem;
            border-radius: 14px;
            border: 1px solid rgba(148,163,184,0.18);
            background: #ffffff;
            box-shadow: 0 3px 10px rgba(15,23,42,0.04);
        }

        .small-kpi-title {
            font-size: 0.78rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.3rem;
            font-weight: 700;
        }

        .small-kpi-value {
            font-size: 1.28rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.15;
            word-break: break-word;
        }

        .small-kpi-note {
            font-size: 0.82rem;
            color: #64748b;
            margin-top: 0.2rem;
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
            border-radius: 12px 12px 0 0;
            padding: 0.65rem 1rem;
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
        <div style="display:flex; align-items:center; gap:0.75rem; margin-top:0.85rem;">
            <div style="font-size:2.2rem; line-height:1;">🏛️</div>
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
    file_exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


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
    if not STATE_FILE.exists():
        return default_state()
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return default_state()
    base = default_state()
    base.update(state)
    return base


def save_state(state: Dict[str, Any]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True, default=str)


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
        "current_alloc": {"G": 40, "C": 30, "I": 20, "S": 5, "F": 5},
        "allow_second_ift": False,
        "normal_drift_threshold_pct": 7.5,
        "score_change_threshold": 3,
        "confirmation_days": 3,
        "cooldown_days": 5,
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
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True, default=str)


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
# CACHED MARKET SNAPSHOT
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

    market_data = {
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

    market_sources = {
        "core_pce_yoy": "DEFAULT",
        "ism_pmi": "DEFAULT",
        "sloos_net_pct": "LIVE" if results.get("sloos_val") is not None else "DEFAULT",
        "hy_oas": "LIVE" if results.get("hy_val") is not None else "DEFAULT",
        "shiller_cape": "DEFAULT",
        "fwd_eps_growth_yoy": "DEFAULT",
        "vix_spot": "LIVE" if vix_closes else "DEFAULT",
        "pct_dist_200_sma": "LIVE" if spx_closes else "DEFAULT",
        "drawdown_pct": "LIVE" if spx_closes else "DEFAULT",
        "stlfsi_index": "LIVE" if results.get("stlfsi_val") is not None else "DEFAULT",
        "bond_yield_10y": "LIVE" if results.get("bond_val") is not None else "DEFAULT",
        "dxy_spot": "LIVE" if dxy_closes else "DEFAULT",
        "market_breadth_pct": "DEFAULT",
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
        action_color = "#22c55e" if action == "SUBMIT IFT" else "#64748b"
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
        reason_color = "#16a34a" if action == "SUBMIT IFT" else "#64748b"
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
            "Base Allocation": "G 90 / C 0 / I 0 / S 0 / F 10",
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
    cls = "pill-live" if source == "LIVE" else "pill-default"
    return f"<span class='pill {cls}'>{source}</span>"


# ==============================================================================
# APP STATE
# ==============================================================================

today = date.today()
state = reset_monthly_if_needed(load_state(), today)
cfg = load_config()


# ==============================================================================
# SIDEBAR
# ==============================================================================

with st.sidebar:
    st.markdown("## ⚙️ Controls")

    st.header("Current Allocation")
    current_alloc = {
        "G": st.number_input("G %", value=float(cfg.get("current_alloc", {}).get("G", 40.0)), step=1.0),
        "C": st.number_input("C %", value=float(cfg.get("current_alloc", {}).get("C", 30.0)), step=1.0),
        "I": st.number_input("I %", value=float(cfg.get("current_alloc", {}).get("I", 20.0)), step=1.0),
        "S": st.number_input("S %", value=float(cfg.get("current_alloc", {}).get("S", 5.0)), step=1.0),
        "F": st.number_input("F %", value=float(cfg.get("current_alloc", {}).get("F", 5.0)), step=1.0),
    }

    st.header("IFT Policy")
    allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg.get("allow_second_ift", False)))
    normal_drift_threshold_pct = st.number_input("Normal drift threshold %", value=float(cfg.get("normal_drift_threshold_pct", 7.5)), step=0.5)
    score_change_threshold = st.number_input("Score change threshold", value=int(cfg.get("score_change_threshold", 3)), step=1)
    confirmation_days = st.number_input("Confirmation days", value=int(cfg.get("confirmation_days", 3)), step=1)
    cooldown_days = st.number_input("Cooldown days", value=int(cfg.get("cooldown_days", 5)), step=1)

    st.header("State Controls")
    mark_ift = st.button("✅ Mark IFT Used Today")
    reset_state_btn = st.button("♻️ Reset State File")
    save_config_btn = st.button("💾 Save Config")

if save_config_btn:
    cfg["current_alloc"] = current_alloc
    cfg["allow_second_ift"] = allow_second_ift
    cfg["normal_drift_threshold_pct"] = float(normal_drift_threshold_pct)
    cfg["score_change_threshold"] = int(score_change_threshold)
    cfg["confirmation_days"] = int(confirmation_days)
    cfg["cooldown_days"] = int(cooldown_days)
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


# ==============================================================================
# MAIN
# ==============================================================================

run = st.button("🚀 Fetch & Run Engine")

if run:
    with st.spinner("Loading live data and running engine..."):
        snapshot = get_market_snapshot()
        market_data = snapshot["market_data"]
        market_sources = snapshot["market_sources"]
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
    save_config(cfg)

    render_metric_cards(total_score, regime, action, state["ift_count_this_month"], reason)

    tab1, tab2, tab3, tab4 = st.tabs(["📈 Allocation", "🧠 Factors", "🕒 History", "📁 Logs & State"])

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

        st.markdown("### Baseline Allocation")
        st.json(baseline)

    with tab2:
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
        st.write(f"**Current Regime:** {regime}")
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
                    
        st.write("This section will explain why the engine made its decision.")

    with tab3:
        st.markdown("### Score History")
        score_df = make_score_chart(state)
        if score_df is not None:
            st.line_chart(score_df)
        else:
            st.info("No score history yet.")

        st.markdown("### Recent State")
        st.json({
            "month": state["month"],
            "ift_count_this_month": state["ift_count_this_month"],
            "last_ift_date": state["last_ift_date"],
            "recent_regimes": state["recent_regimes"],
            "recent_scores": state["recent_scores"],
        })

    with tab4:
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

else:
    st.info("Use the sidebar to set allocations and policy, then click **Fetch & Run Engine**.")
