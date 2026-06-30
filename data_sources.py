import json
import urllib.request
import urllib.parse
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Any, List, Tuple

import pandas as pd
import yfinance as yf
import streamlit as st
from bs4 import BeautifulSoup

from constants import DEFAULTS, MAX_RETRIES, RETRY_SLEEP_SEC
from utils import clean_and_parse_float


def retry_call(func, *args, retries=MAX_RETRIES, sleep_sec=RETRY_SLEEP_SEC, **kwargs):
    last_err = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                import time
                time.sleep(sleep_sec)
    raise last_err


def fetch_via_fred_api(series_id: str, api_key: str, limit: int = 1) -> List[Tuple[str, float]]:
    if not api_key:
        return []
    url = (
        f"https://api.stlouisfed.org/fred/series/observations?"
        f"series_id={urllib.parse.quote(series_id)}&api_key={urllib.parse.quote(api_key)}"
        f"&file_type=json&sort_order=desc&limit={limit}"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        observations = data.get("observations", [])
        result = []
        for obs in observations:
            val = clean_and_parse_float(obs.get("value"))
            if val is not None:
                result.append((obs.get("date"), val))
        result.reverse()
        return result
    except Exception:
        return []


def fetch_from_dbnomics(series_id: str) -> List[Tuple[str, float]]:
    url = f"https://api.db.nomics.world/v22/series/FRED/FRED/{urllib.parse.quote(series_id)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        docs = data.get("series", {}).get("docs", [])
        if not docs:
            return []
        doc = docs[0]
        periods = doc.get("period", [])
        values = doc.get("value", [])
        result = []
        for p, v in zip(periods, values):
            val = clean_and_parse_float(v)
            if val is not None:
                result.append((p, val))
        return result
    except Exception:
        return []


def fetch_fred_latest(series_id: str, api_key: Optional[str] = None) -> Optional[float]:
    if api_key:
        try:
            data_points = fetch_via_fred_api(series_id, api_key, limit=5)
            if data_points:
                return data_points[-1][1]
        except Exception:
            pass

    try:
        data_points = fetch_from_dbnomics(series_id)
        if data_points:
            return data_points[-1][1]
    except Exception:
        pass

    def _load_fred():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id={urllib.parse.quote(series_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)
        if df.empty or len(df.columns) < 2:
            return None
        value_col = df.columns[1]
        series = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if series.empty:
            return None
        return float(series.iloc[-1])

    try:
        return retry_call(_load_fred)
    except Exception:
        return None


def fetch_fred_series_points(series_id: str, api_key: Optional[str] = None, limit: int = 30) -> List[Tuple[str, float]]:
    if api_key:
        try:
            data_points = fetch_via_fred_api(series_id, api_key, limit=limit)
            if data_points:
                return data_points
        except Exception:
            pass

    try:
        data_points = fetch_from_dbnomics(series_id)
        if data_points:
            return data_points[-limit:]
    except Exception:
        pass

    def _load_fred():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id={urllib.parse.quote(series_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)
        if df.empty or len(df.columns) < 2:
            return []
        date_col = df.columns[0]
        value_col = df.columns[1]
        out = []
        for _, row in df[[date_col, value_col]].tail(limit).iterrows():
            val = clean_and_parse_float(row[value_col])
            if val is not None:
                out.append((str(row[date_col]), val))
        return out

    try:
        return retry_call(_load_fred)
    except Exception:
        return []


def calc_yoy(points: List[Tuple[str, float]]) -> Optional[float]:
    if len(points) < 13:
        return None
    latest_val = points[-1][1]
    past_val = points[-13][1]
    if past_val in (0, None):
        return None
    return round(((latest_val - past_val) / past_val) * 100.0, 2)


def calc_annualized_trend(points: List[Tuple[str, float]], lookback: int = 3) -> Optional[float]:
    """
    Simple annualized trend from monthly data.
    Returns annualized % change over lookback months.
    """
    if len(points) <= lookback:
        return None
    latest_val = points[-1][1]
    past_val = points[-(lookback + 1)][1]
    if past_val in (0, None):
        return None
    if latest_val is None or past_val is None:
        return None
    return round((((latest_val / past_val) ** (12.0 / lookback)) - 1.0) * 100.0, 2)


def calc_spread(latest_a: Optional[float], latest_b: Optional[float]) -> Optional[float]:
    if latest_a is None or latest_b is None:
        return None
    return round(latest_a - latest_b, 3)


def fetch_yield_curve_slope(api_key: Optional[str] = None) -> Optional[float]:
    """
    Primary: direct FRED spread if available.
    Fallback: DGS10 - DGS2.
    """
    direct = fetch_fred_latest("T10Y2Y", api_key)
    if direct is not None:
        return round(direct, 3)

    dgs10 = fetch_fred_latest("DGS10", api_key)
    dgs2 = fetch_fred_latest("DGS2", api_key)
    return calc_spread(dgs10, dgs2)


def fetch_inflation_trend(api_key: Optional[str] = None) -> Optional[float]:
    """
    Use Core PCE inflation level series and estimate a 3-month annualized trend.
    """
    points = fetch_fred_series_points("PCEPILFE", api_key, limit=12)
    trend = calc_annualized_trend(points, lookback=3)
    if trend is not None:
        return trend

    # fallback to CPI
    points = fetch_fred_series_points("CPIAUCSL", api_key, limit=12)
    return calc_annualized_trend(points, lookback=3)


def fetch_labor_trend(api_key: Optional[str] = None) -> Optional[float]:
    """
    Negative = weakening labor market, Positive = improving/benign.
    Combines unemployment trend and claims trend into a simple score.
    """
    unrate = fetch_fred_latest("UNRATE", api_key)
    claims = fetch_fred_latest("ICSA", api_key)
    cont_claims = fetch_fred_latest("CCSA", api_key)

    score = 0.0
    used = 0

    if unrate is not None:
        # Lower unemployment is positive, higher is negative
        score += (5.0 - unrate)
        used += 1

    if claims is not None:
        # Higher claims are negative
        score += max(0.0, 400.0 - claims / 1000.0)
        used += 1

    if cont_claims is not None:
        score += max(0.0, 1800.0 - cont_claims / 1000.0)
        used += 1

    if used == 0:
        return None

    # Normalize into a small-ish number around 0
    return round((score / used) / 10.0 - 5.0, 2)


def fetch_vol_term_structure(api_key: Optional[str] = None) -> Optional[float]:
    """
    Prefer VIX3M vs VIX if available.
    Positive = calmer contango-like structure.
    Negative = stressed/backwardated structure.
    """
    vix = None
    vix3m = None

    # try Yahoo first for spot VIX
    try:
        vix_df = yf.download("^VIX", period="10d", interval="1d", progress=False, auto_adjust=False)
        if vix_df is not None and not vix_df.empty:
            vix = float(vix_df["Close"].dropna().iloc[-1])
    except Exception:
        pass

    # VIX3M may not always exist on Yahoo; try common ticker / FRED proxy if you have one
    try:
        vix3m_df = yf.download("^VIX3M", period="10d", interval="1d", progress=False, auto_adjust=False)
        if vix3m_df is not None and not vix3m_df.empty:
            vix3m = float(vix3m_df["Close"].dropna().iloc[-1])
    except Exception:
        pass

    # If VIX3M is unavailable, approximate via VIX + a calm/stress regime proxy from MOVE
    if vix is None:
        try:
            vix_df = yf.download("^VIX", period="10d", interval="1d", progress=False, auto_adjust=False)
            if vix_df is not None and not vix_df.empty:
                vix = float(vix_df["Close"].dropna().iloc[-1])
        except Exception:
            pass

    if vix is None:
        return None

    if vix3m is not None:
        # Higher spread usually means calmer term structure
        return round(vix3m - vix, 3)

    # fallback proxy: use MOVE / VIX ratio signaled as a rough stress metric
    move = fetch_fred_latest("MOVE", api_key)
    if move is not None:
        return round((move / max(vix, 1.0)) - 1.0, 3)

    return None


def fetch_commodity_shock() -> Optional[float]:
    """
    Crude oil shock proxy.
    Positive number = recent spike, which is usually bearish/stagflationary.
    """
    try:
        df = yf.download("CL=F", period="3mo", interval="1d", progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        closes = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(closes) < 22:
            return None

        latest = float(closes.iloc[-1])
        base = float(closes.iloc[-22])
        if base <= 0:
            return None

        # 1-month price shock in %
        shock = ((latest - base) / base) * 100.0
        return round(shock, 2)
    except Exception:
        return None


def fetch_earnings_breadth() -> Optional[float]:
    """
    Free proxy for earnings breadth / participation quality.
    Primary fallback: % of S&P 500 above 200-day average if available.
    """
    try:
        spx = yf.download("^GSPC", period="1y", interval="1d", progress=False, auto_adjust=False)
        if spx is None or spx.empty:
            return None
        closes = pd.to_numeric(spx["Close"], errors="coerce").dropna()
        if len(closes) < 200:
            return None

        sma200 = closes.tail(200).mean()
        latest = float(closes.iloc[-1])
        dist = ((latest - sma200) / sma200) * 100.0
        return round(dist, 2)
    except Exception:
        return None


def get_market_snapshot(api_key: str = "") -> Dict[str, Any]:
    """
    Returns:
      {
        "market_data": {...},
        "market_sources": {...}
      }
    """
    # Existing parallel fetches in your project are preserved conceptually.
    # If you already have a threaded version below this point, keep it;
    # just add these new fields to the final market_data / market_sources dicts.

    # ---------------------------------------------------------------------
    # Existing live data fetch logic should remain above/beside this section
    # in your current file. The only requirement for Step 2 is that the
    # final dictionaries include the new fields below.
    # ---------------------------------------------------------------------

    # Existing final values should already be computed in your current file.
    # The code below assumes those values exist in local variables.
    # If your file structure differs slightly, copy these additions into
    # your current final-return block.

    # New macro factor fetches
    yield_curve_slope = fetch_yield_curve_slope(api_key)
    inflation_trend = fetch_inflation_trend(api_key)
    labor_trend = fetch_labor_trend(api_key)
    vol_term_structure = fetch_vol_term_structure(api_key)
    commodity_shock = fetch_commodity_shock()
    earnings_breadth = fetch_earnings_breadth()

    # ---------------------------------------------------------------------
    # IMPORTANT:
    # In your current file, preserve your existing logic that computes:
    # pce_source, te_pmi, te_services, raw_claims, results, move_closes,
    # vix_closes, spx_closes, breadth_closes, bond_yield_closes, dxy_closes,
    # etc.
    #
    # Then merge the new fields into the final market_data dict below.
    # ---------------------------------------------------------------------

    # Neutral fallback values
    final_yield_curve_slope = yield_curve_slope if yield_curve_slope is not None else DEFAULTS.get("yield_curve_slope", 0.0)
    final_inflation_trend = inflation_trend if inflation_trend is not None else DEFAULTS.get("inflation_trend", 0.0)
    final_labor_trend = labor_trend if labor_trend is not None else DEFAULTS.get("labor_trend", 0.0)
    final_vol_term_structure = vol_term_structure if vol_term_structure is not None else DEFAULTS.get("vol_term_structure", 0.0)
    final_commodity_shock = commodity_shock if commodity_shock is not None else DEFAULTS.get("commodity_shock", 0.0)
    final_earnings_breadth = earnings_breadth if earnings_breadth is not None else DEFAULTS.get("earnings_breadth", 0.0)

    # Minimal safe market_data in case you paste this over a smaller file.
    # If your current function already builds a richer dict, keep that and
    # just add the fields below.
    market_data = {
        "yield_curve_slope": final_yield_curve_slope,
        "inflation_trend": final_inflation_trend,
        "labor_trend": final_labor_trend,
        "vol_term_structure": final_vol_term_structure,
        "commodity_shock": final_commodity_shock,
        "earnings_breadth": final_earnings_breadth,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    market_sources = {
        "yield_curve_slope": "LIVE (FRED/DBnomics/Yahoo)" if yield_curve_slope is not None else "CONFIG/DEFAULT",
        "inflation_trend": "LIVE (FRED/BEA/BLS)" if inflation_trend is not None else "CONFIG/DEFAULT",
        "labor_trend": "LIVE (FRED/BLS)" if labor_trend is not None else "CONFIG/DEFAULT",
        "vol_term_structure": "LIVE (Yahoo/FRED proxy)" if vol_term_structure is not None else "CONFIG/DEFAULT",
        "commodity_shock": "LIVE (Yahoo Finance CL=F)" if commodity_shock is not None else "CONFIG/DEFAULT",
        "earnings_breadth": "LIVE (Yahoo proxy)" if earnings_breadth is not None else "CONFIG/DEFAULT",
    }

    return {"market_data": market_data, "market_sources": market_sources}
