"""
Author: Donald J Anthony
Date: Today's Date

data_sources.py — Module responsible for fetching market and economic data from various external providers.

Provides:
    - Functions to fetch data from FRED, DBNomics, Trading Economics, Yahoo Finance, Multpl.com, and Barchart.
    - Helper functions for computing derived market overlays and snapshot indicators.
    - Caching utilities and retry logic for robust network operations.

NOTE:
    Some functions use broad exception handling for simplicity.
    Consider using more specific exception types in a production environment.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

from constants import DEFAULTS, MAX_RETRIES, RETRY_SLEEP_SEC
from utils import clean_and_parse_float


def retry_call(func: Any, *args: Any, retries: int = MAX_RETRIES, sleep_sec: int = RETRY_SLEEP_SEC, **kwargs: Any) -> Any:
    """
    Execute a function and retry if an exception occurs.

    Args:
        func: The function to call.
        *args: Positional arguments for the function.
        retries (int): Maximum number of retries.
        sleep_sec (int): Seconds to sleep between retries.
        **kwargs: Keyword arguments for the function.

    Returns:
        Any: The result of the function if successful.

    Raises:
        Exception: The last exception raised if all retries fail.
    """
    last_err = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(sleep_sec)
    raise last_err


def fetch_via_fred_api(series_id: str, api_key: str, limit: int = 1) -> List[Tuple[str, float]]:
    """
    Fetch data points from FRED via API.

    Args:
        series_id (str): The FRED series identifier.
        api_key (str): API key required to access FRED data.
        limit (int): Maximum number of data points to fetch.

    Returns:
        List[Tuple[str, float]]: A list of tuples with date and value.
    """
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
    """
    Fetch data points from DBNomics API.

    Args:
        series_id (str): The series identifier.

    Returns:
        List[Tuple[str, float]]: A list of tuples with date and value.
    """
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
    """
    Fetch the latest data point from FRED using API or fallback options.

    Args:
        series_id (str): The FRED series identifier.
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: The latest data value or None if unavailable.
    """
    if api_key:
        try:
            data_points = fetch_via_fred_api(series_id, api_key, limit=5)
            if data_points:
                return data_points[-1][1]
        except Exception:
            pass  # Fallback to alternative source

    try:
        data_points = fetch_from_dbnomics(series_id)
        if data_points:
            return data_points[-1][1]
    except Exception:
        pass

    def _load_fred() -> Optional[float]:
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


def fetch_fred_series_latest_points(series_id: str, api_key: Optional[str] = None, limit: int = 10) -> List[Tuple[str, float]]:
    """
    Fetch the latest N points of a FRED series.

    Args:
        series_id (str): The FRED series identifier.
        api_key (Optional[str]): API key for FRED.
        limit (int): Number of latest points to return.

    Returns:
        List[Tuple[str, float]]: A list of data point tuples.
    """
    if api_key:
        try:
            pts = fetch_via_fred_api(series_id, api_key, limit=limit)
            if pts:
                return pts
        except Exception:
            pass

    try:
        pts = fetch_from_dbnomics(series_id)
        if pts:
            return pts[-limit:]
    except Exception:
        pass

    def _load() -> List[Tuple[str, float]]:
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id={urllib.parse.quote(series_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)
        if df.empty or len(df.columns) < 2:
            return []
        value_col = df.columns[1]
        series_data = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if series_data.empty:
            return []
        result = []
        tail = series_data.tail(limit)
        for idx, val in tail.items():
            result.append((str(idx), float(val)))
        return result

    try:
        return retry_call(_load)
    except Exception:
        return []


def fetch_fred_core_pce_yoy(api_key: Optional[str] = None) -> Optional[float]:
    """
    Fetch the year-over-year percentage change in the Core PCE Price Index.

    Args:
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: Yield percentage value or None if not available.
    """
    def calc_yoy(points: List[Tuple[str, float]]) -> Optional[float]:
        if len(points) < 13:
            return None
        latest_val = points[-1][1]
        past_val = points[-13][1]
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    if api_key:
        try:
            data_points = fetch_via_fred_api("PCEPILFE", api_key, limit=20)
            val = calc_yoy(data_points)
            if val is not None:
                return val
        except Exception:
            pass

    try:
        data_points = fetch_from_dbnomics("PCEPILFE")
        val = calc_yoy(data_points)
        if val is not None:
            return val
    except Exception:
        pass

    def _load_fred_yoy() -> Optional[float]:
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id=PCEPILFE"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)
        if df.empty or len(df.columns) < 2:
            return None
        value_col = df.columns[1]
        series_data = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if len(series_data) < 13:
            return None
        latest_val = float(series_data.iloc[-1])
        past_val = float(series_data.iloc[-13])
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    try:
        return retry_call(_load_fred_yoy)
    except Exception:
        return None


def fetch_fed_assets_yoy_growth(api_key: Optional[str] = None) -> Optional[float]:
    """
    Fetch the year-over-year growth rate of Fed assets.

    Args:
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: The calculated growth rate percentage or None.
    """
    def calc_yoy(points: List[Tuple[str, float]]) -> Optional[float]:
        if len(points) < 53:
            return None
        latest_val = points[-1][1]
        past_val = points[-53][1]
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    if api_key:
        try:
            data_points = fetch_via_fred_api("WALCL", api_key, limit=60)
            val = calc_yoy(data_points)
            if val is not None:
                return val
        except Exception:
            pass

    try:
        data_points = fetch_from_dbnomics("WALCL")
        val = calc_yoy(data_points)
        if val is not None:
            return val
    except Exception:
        pass

    def _load() -> Optional[float]:
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id=WALCL"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)
        if df.empty or len(df.columns) < 2:
            return None
        value_col = df.columns[1]
        series_data = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if len(series_data) < 53:
            return None
        latest_val = float(series_data.iloc[-1])
        past_val = float(series_data.iloc[-53])
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    try:
        return retry_call(_load)
    except Exception:
        return None


def _extract_te_indicator_from_html(html: str) -> Dict[str, Optional[float]]:
    """
    Extract key economic indicators from the Trading Economics HTML content.

    Args:
        html (str): HTML content from the Trading Economics indicators page.

    Returns:
        Dict[str, Optional[float]]: A dictionary with keys "core_pce_yoy", "ism_pmi", "services_pmi".
    """
    results: Dict[str, Optional[float]] = {"core_pce_yoy": None, "ism_pmi": None, "services_pmi": None}

    try:
        # Attempt to parse tables from HTML
        dfs = pd.read_html(html)
        for df in dfs:
            if df.empty or len(df.columns) < 2:
                continue
            col_name = df.columns[0]
            for _, row in df.iterrows():
                indicator_text = str(row[col_name]).strip()
                if "Core PCE Price Index" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["core_pce_yoy"] = val
                if "ISM Manufacturing PMI" in indicator_text or "Manufacturing PMI" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["ism_pmi"] = val
                if "ISM Services PMI" in indicator_text or "Services PMI" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["services_pmi"] = val
    except Exception:
        pass

    try:
        # Fallback: Use BeautifulSoup to search in plain text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        if results["ism_pmi"] is None:
            for label in ["ISM Manufacturing PMI", "Manufacturing PMI"]:
                if label in text:
                    match = re.search(rf"{re.escape(label)}.*?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
                    if match:
                        results["ism_pmi"] = clean_and_parse_float(match.group(1))
                        break
        if results["services_pmi"] is None:
            for label in ["ISM Services PMI", "Services PMI"]:
                if label in text:
                    match = re.search(rf"{re.escape(label)}.*?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
                    if match:
                        results["services_pmi"] = clean_and_parse_float(match.group(1))
                        break
        if results["core_pce_yoy"] is None and "Core PCE Price Index" in text:
            match = re.search(r"Core PCE Price Index.*?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
            if match:
                results["core_pce_yoy"] = clean_and_parse_float(match.group(1))
    except Exception:
        pass

    return results


def fetch_indicators_from_te_indicators_page() -> Dict[str, Optional[float]]:
    """
    Fetch core economic indicators from the Trading Economics indicators page.

    Returns:
        Dict[str, Optional[float]]: Dictionary with indicator keys and their float values.
    """
    url = "https://tradingeconomics.com/united-states/indicators"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")
        return _extract_te_indicator_from_html(html)
    except Exception:
        return {"core_pce_yoy": None, "ism_pmi": None, "services_pmi": None}


def fetch_shiller_cape_live() -> Optional[float]:
    """
    Fetch the current Shiller CAPE value from Multpl.com.

    Returns:
        Optional[float]: The Shiller CAPE ratio or None if not available.
    """
    def _load() -> Optional[float]:
        url = "https://www.multpl.com/shiller-pe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")
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


def fetch_multpl_earnings_growth() -> Optional[float]:
    """
    Fetch the S&P 500 earnings growth rate from Multpl.com.

    Returns:
        Optional[float]: The percentage growth rate or None.
    """
    def _load() -> Optional[float]:
        url = "https://www.multpl.com/s-p-500-earnings-growth"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")
        match = re.search(r'class=["\']num["\']>\s*([0-9\-\.\%]+)\s*<', html)
        if match:
            val_str = match.group(1).replace("%", "").strip()
            return float(val_str)
        match_alt = re.search(r'Current S&P 500 Earnings Growth Rate is\s+([0-9\-\.\%]+)', html, re.IGNORECASE)
        if match_alt:
            val_str = match_alt.group(1).replace("%", "").strip()
            return float(val_str)
        return None

    try:
        return retry_call(_load)
    except Exception:
        return None


def fetch_barchart_s5th_fallback() -> Optional[float]:
    """
    Fallback method to fetch the S5TH value from Barchart.

    Returns:
        Optional[float]: The price value or None.
    """
    url = "https://www.barchart.com/stocks/quotes/$S5TH"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")
        for pattern in [
            r'"lastPrice"\s*:\s*"?([0-9\.]+)"?',
            r'"last"\s*:\s*"?([0-9\.]+)"?',
            r'class="[^"]*price[^"]*"\s*>\s*([0-9\.]+)\s*<'
        ]:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                if 0.0 <= val <= 100.0:
                    return val
    except Exception:
        pass
    return None


def fetch_yfinance_closes(ticker: str, period: str = "1y", interval: str = "1d") -> List[float]:
    """
    Fetch historical closing prices for a ticker using yfinance.

    Args:
        ticker (str): Stock or index ticker.
        period (str): Time period (e.g., "1y").
        interval (str): Data interval (e.g., "1d").

    Returns:
        List[float]: List of closing prices.
    """
    def _load() -> List[float]:
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
                close = df[close_candidates[0]] if close_candidates else pd.Series(dtype=float)
        else:
            close = df.get("Close", pd.Series(dtype=float))
        closes_list = pd.to_numeric(close, errors="coerce").dropna().astype(float).tolist()
        return closes_list

    try:
        return retry_call(_load)
    except Exception:
        return []


def fetch_yfinance_dataframe(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Download historical data for a ticker and return a DataFrame with Date and Price.

    Args:
        ticker (str): Stock or index ticker.
        period (str): Time period (e.g., "1y").

    Returns:
        pd.DataFrame: DataFrame containing Date and Price columns.
    """
    def _load() -> pd.DataFrame:
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
        return pd.DataFrame({
            "Date": close_series.index,
            "Price": pd.to_numeric(close_series.values, errors="coerce")
        }).dropna()

    try:
        return retry_call(_load)
    except Exception:
        return pd.DataFrame()


def calc_spx_metrics_from_closes(closes: List[float]) -> Tuple[float, float, float]:
    """
    Calculate SPX metrics: % distance from 200-day SMA, drawdown percentage, and current SPX spot.

    Args:
        closes (List[float]): List of SPX closing prices.

    Returns:
        Tuple[float, float, float]: (distance from SMA, drawdown %, current SPX spot)
    """
    if len(closes) < 200:
        return 0.0, 0.0, 0.0
    current_spot = closes[-1]
    peak = max(closes)
    drawdown_pct = ((peak - current_spot) / peak) * 100.0
    sma_200 = sum(closes[-200:]) / 200.0
    dist_200sma = ((current_spot - sma_200) / sma_200) * 100.0
    return round(dist_200sma, 2), round(drawdown_pct, 2), round(current_spot, 2)


def derive_macro_overlays(market: Dict[str, Any]) -> Dict[str, float]:
    """
    Derive macro overlay metrics from the market snapshot.

    Args:
        market (Dict[str, Any]): Market data dictionary with various indicators.

    Returns:
        Dict[str, float]: Derived overlay metrics including treasury spread, inflation shock, etc.
    """
    pce = clean_and_parse_float(market.get("core_pce_yoy")) or DEFAULTS["core_pce_yoy"]
    fed_assets = clean_and_parse_float(market.get("fed_assets_growth_yoy")) or DEFAULTS["fed_assets_growth_yoy"]
    real_yield = clean_and_parse_float(market.get("real_yield_10y")) or DEFAULTS["real_yield_10y"]
    sloos = clean_and_parse_float(market.get("sloos_net_pct")) or DEFAULTS["sloos_net_pct"]
    move = clean_and_parse_float(market.get("move_index")) or DEFAULTS["move_index"]
    stlfsi = clean_and_parse_float(market.get("stlfsi_index")) or DEFAULTS["stlfsi_index"]

    bond_yield_10y = clean_and_parse_float(market.get("bond_yield_10y")) or DEFAULTS["bond_yield_10y"]
    bond_yield_3m = clean_and_parse_float(market.get("bond_yield_3m"))
    if bond_yield_3m is None:
        bond_yield_3m = fetch_fred_latest("DGS3MO", market.get("fred_api_key"))
    if bond_yield_3m is not None:
        treasury_10y_3m_spread = round(bond_yield_10y - bond_yield_3m, 3)
    else:
        treasury_10y_3m_spread = round(bond_yield_10y - real_yield, 3)

    inflation_anchor = DEFAULTS["core_pce_yoy"]
    inflation_shock = round(pce - inflation_anchor, 2)

    central_bank_stance = 0.0
    if fed_assets > 0 and real_yield < 1.0 and treasury_10y_3m_spread > 0.5:
        central_bank_stance = 2.0
    elif fed_assets > 0:
        central_bank_stance = 1.0
    elif real_yield > 2.0 or treasury_10y_3m_spread < 0.0:
        central_bank_stance = -2.0
    elif real_yield > 1.0 or stlfsi > 1.0:
        central_bank_stance = -1.0

    liquidity_pressure = 0.0
    if sloos > 5.0:
        liquidity_pressure += 1.0
    if fed_assets <= 0.0:
        liquidity_pressure += 1.0
    if stlfsi > 1.0:
        liquidity_pressure += 1.0
    if real_yield > 2.0:
        liquidity_pressure += 1.0
    if move > 120.0:
        liquidity_pressure += 1.0

    return {
        "treasury_10y_3m_spread": treasury_10y_3m_spread,
        "inflation_shock": inflation_shock,
        "central_bank_stance": central_bank_stance,
        "liquidity_pressure": min(liquidity_pressure, 5.0),
    }


def derive_dxy_overlay(dxy_closes: List[float]) -> Dict[str, Any]:
    """
    Derive DXY-related overlays from historical DXY closing prices.

    Args:
        dxy_closes (List[float]): List of DXY closing prices.

    Returns:
        Dict[str, Any]: A dictionary with DXY SMA values, trend status, and regime.
    """
    if not dxy_closes:
        return {
            "dxy_sma_5": 0.0,
            "dxy_sma_20": 0.0,
            "dxy_trend_up": False,
            "dxy_range_regime": "UNKNOWN",
        }
    latest = float(dxy_closes[-1])
    sma_5 = sum(dxy_closes[-5:]) / min(len(dxy_closes), 5)
    sma_20 = sum(dxy_closes[-20:]) / min(len(dxy_closes), 20)
    trend_up = sma_5 > sma_20
    if latest < 95:
        regime = "WEAK"
    elif latest < 101:
        regime = "NORMAL"
    elif latest < 105:
        regime = "STRONG"
    elif latest < 110:
        regime = "VERY STRONG"
    else:
        regime = "EXTREME"
    return {
        "dxy_sma_5": round(sma_5, 2),
        "dxy_sma_20": round(sma_20, 2),
        "dxy_trend_up": trend_up,
        "dxy_range_regime": regime,
    }


@st.cache_data(ttl=3600)
def cached_fred(series_id: str, api_key: Optional[str] = None) -> Optional[float]:
    """
    Cached fetch for the latest FRED series value.

    Args:
        series_id (str): FRED series identifier.
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: Latest value or None.
    """
    return fetch_fred_latest(series_id, api_key)


@st.cache_data(ttl=3600)
def cached_fred_core_pce_yoy(api_key: Optional[str] = None) -> Optional[float]:
    """
    Cached fetch for Core PCE YoY from FRED.

    Args:
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: Latest Core PCE YoY value.
    """
    return fetch_fred_core_pce_yoy(api_key)


@st.cache_data(ttl=3600)
def cached_fred_fed_assets_yoy(api_key: Optional[str] = None) -> Optional[float]:
    """
    Cached fetch for Fed Assets YoY growth.

    Args:
        api_key (Optional[str]): API key for FRED.

    Returns:
        Optional[float]: Growth percentage.
    """
    return fetch_fed_assets_yoy_growth(api_key)


@st.cache_data(ttl=3600)
def get_te_live_data() -> Dict[str, Optional[float]]:
    """
    Cached fetch for live indicators from Trading Economics.

    Returns:
        Dict[str, Optional[float]]: Dictionary of indicators.
    """
    return fetch_indicators_from_te_indicators_page()


@st.cache_data(ttl=3600)
def cached_shiller_cape_live() -> Optional[float]:
    """
    Cached fetch for the live Shiller CAPE ratio.

    Returns:
        Optional[float]: Shiller CAPE value.
    """
    return fetch_shiller_cape_live()


@st.cache_data(ttl=3600)
def cached_barchart_s5th() -> Optional[float]:
    """
    Cached fallback fetch for S5TH via Barchart.

    Returns:
        Optional[float]: S5TH price.
    """
    return fetch_barchart_s5th_fallback()


@st.cache_data(ttl=3600)
def cached_multpl_earnings_growth() -> Optional[float]:
    """
    Cached fetch for S&P 500 earnings growth from Multpl.com.

    Returns:
        Optional[float]: Earnings growth percentage.
    """
    return fetch_multpl_earnings_growth()


@st.cache_data(ttl=3600)
def cached_yahoo_closes(ticker: str, period: str, interval: str) -> List[float]:
    """
    Cached fetch for historical closing prices from Yahoo Finance.

    Args:
        ticker (str): Ticker symbol.
        period (str): Time period.
        interval (str): Data interval.

    Returns:
        List[float]: List of closing prices.
    """
    return fetch_yfinance_closes(ticker, period=period, interval=interval)


@st.cache_data(ttl=3600)
def get_cached_proxy_df(ticker: str, period: str) -> pd.DataFrame:
    """
    Cached fetch for a dataframe of proxy prices from Yahoo Finance.

    Args:
        ticker (str): Proxy ticker.
        period (str): Time period.

    Returns:
        pd.DataFrame: DataFrame with Date and Price.
    """
    return fetch_yfinance_dataframe(ticker, period)


@st.cache_data(ttl=3600)
def fetch_ytd_return(ticker: str) -> Optional[float]:
    """
    Cached fetch for the Year-To-Date return for a given ticker.

    Args:
        ticker (str): Proxy ticker.

    Returns:
        Optional[float]: YTD return percentage or None.
    """
    df = get_cached_proxy_df(ticker, "1y")
    if df.empty:
        return None
    current_year = datetime.now().year
    ytd_df = df[df["Date"].dt.year == current_year]
    if ytd_df.empty:
        return None
    start_price = ytd_df["Price"].iloc[0]
    end_price = ytd_df["Price"].iloc[-1]
    return round(((end_price - start_price) / start_price) * 100.0, 2)


@st.cache_data(ttl=3600)
def get_market_snapshot(api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch a complete market snapshot, aggregating various sources.

    Args:
        api_key (Optional[str]): API key for FRED live data.

    Returns:
        Dict[str, Any]: A dictionary with "market_data" and "market_sources".
    """
    results: Dict[str, Any] = {}

    # Use a ThreadPool to fetch multiple data sources concurrently.
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(cached_fred, "DRTSCIS", api_key): "sloos_val",
            executor.submit(cached_fred, "BAMLH0A0HYM2", api_key): "hy_val",
            executor.submit(cached_fred, "STLFSI4", api_key): "stlfsi_val",
            executor.submit(get_te_live_data): "te_live",
            executor.submit(cached_shiller_cape_live): "shiller_cape_val",
            executor.submit(cached_yahoo_closes, "^VIX", "1mo", "1d"): "vix_closes",
            executor.submit(cached_yahoo_closes, "DX-Y.NYB", "1mo", "1d"): "dxy_closes",
            executor.submit(cached_yahoo_closes, "^GSPC", "1y", "1d"): "spx_closes",
            executor.submit(cached_yahoo_closes, "^S5TH", "1mo", "1d"): "breadth_closes",
            executor.submit(cached_barchart_s5th): "barchart_breadth",
            executor.submit(cached_multpl_earnings_growth): "fwd_eps_val",
            executor.submit(cached_yahoo_closes, "^TNX", "1mo", "1d"): "bond_yield_closes",
            executor.submit(cached_yahoo_closes, "^IRX", "1mo", "1d"): "bill_yield_closes",
            executor.submit(cached_fred, "ICSA", api_key): "initial_claims_val",
            executor.submit(cached_fred, "T10YIE", api_key): "breakeven_inflation_val",
            executor.submit(cached_fred_fed_assets_yoy, api_key): "fed_assets_growth_val",
            executor.submit(cached_fred, "DFII10", api_key): "real_yield_10y_val",
            executor.submit(cached_fred, "DGS10", api_key): "dgs10_val",
            executor.submit(cached_fred, "DGS3MO", api_key): "dgs3mo_val",
            executor.submit(cached_yahoo_closes, "^MOVE", "1mo", "1d"): "move_closes",
        }

        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = None

    # Extract the fetched time series data.
    vix_closes = results.get("vix_closes") or []
    dxy_closes = results.get("dxy_closes") or []
    spx_closes = results.get("spx_closes") or []
    breadth_closes = results.get("breadth_closes") or []
    bond_yield_closes = results.get("bond_yield_closes") or []
    bill_yield_closes = results.get("bill_yield_closes") or []
    move_closes = results.get("move_closes") or []

    sma_dist_live, drawdown_live, spx_spot = calc_spx_metrics_from_closes(spx_closes)
    te_live = results.get("te_live") or {"core_pce_yoy": None, "ism_pmi": None, "services_pmi": None}

    te_pce = te_live.get("core_pce_yoy")
    te_pmi = te_live.get("ism_pmi")
    te_services = te_live.get("services_pmi")

    if te_pce is not None:
        final_pce = te_pce
        pce_source = "LIVE (Trading Economics)"
    else:
        fred_pce_yoy = fetch_fred_core_pce_yoy(api_key)
        final_pce = fred_pce_yoy if fred_pce_yoy is not None else DEFAULTS["core_pce_yoy"]
        pce_source = "LIVE" if fred_pce_yoy is not None else "CONFIG/DEFAULT"

    final_pmi = te_pmi if te_pmi is not None else DEFAULTS["ism_pmi"]
    final_services = te_services if te_services is not None else DEFAULTS["services_pmi"]

    raw_claims = results.get("initial_claims_val")
    final_claims = round(raw_claims / 1000.0, 2) if raw_claims is not None else DEFAULTS["initial_claims"]

    final_breakeven = results.get("breakeven_inflation_val") if results.get("breakeven_inflation_val") is not None else DEFAULTS["breakeven_inflation"]
    final_assets_growth = results.get("fed_assets_growth_val") if results.get("fed_assets_growth_val") is not None else DEFAULTS["fed_assets_growth_yoy"]
    final_real_yield = results.get("real_yield_10y_val") if results.get("real_yield_10y_val") is not None else DEFAULTS["real_yield_10y"]
    final_move = move_closes[-1] if move_closes else DEFAULTS["move_index"]

    fwd_eps_live = results.get("fwd_eps_val")
    final_fwd_eps = fwd_eps_live if fwd_eps_live is not None else DEFAULTS["fwd_eps_growth_yoy"]
    fwd_eps_source = "LIVE (Multpl.com Earnings Growth)" if fwd_eps_live is not None else "CONFIG/DEFAULT"

    if breadth_closes:
        live_breadth = breadth_closes[-1]
    else:
        live_breadth = results.get("barchart_breadth") if results.get("barchart_breadth") is not None else DEFAULTS["market_breadth_pct"]

    if bond_yield_closes:
        live_bond_yield = round(bond_yield_closes[-1] / 10.0, 3)
    else:
        fred_dgs10 = results.get("dgs10_val")
        live_bond_yield = fred_dgs10 if fred_dgs10 is not None else DEFAULTS["bond_yield_10y"]

    fred_dgs3mo = results.get("dgs3mo_val")
    if fred_dgs3mo is not None:
        live_bond_yield_3m = fred_dgs3mo
    elif bill_yield_closes:
        live_bond_yield_3m = round(bill_yield_closes[-1] / 10.0, 3)
    else:
        live_bond_yield_3m = None

    vix_3d_panic = len(vix_closes) >= 3 and all(x >= 30.0 for x in vix_closes[-3:])
    vix_last_3 = [round(x, 2) for x in vix_closes[-3:]] if len(vix_closes) >= 3 else []

    spx_3d_panic = False
    spx_dist_last_3: List[float] = []
    if len(spx_closes) >= 202:
        sma_0 = sum(spx_closes[-200:]) / 200.0
        dist_0 = ((spx_closes[-1] - sma_0) / sma_0) * 100.0
        sma_1 = sum(spx_closes[-201:-1]) / 200.0
        dist_1 = ((spx_closes[-2] - sma_1) / sma_1) * 100.0
        sma_2 = sum(spx_closes[-202:-2]) / 200.0
        dist_2 = ((spx_closes[-3] - sma_2) / sma_2) * 100.0
        spx_dist_last_3 = [round(dist_2, 2), round(dist_1, 2), round(dist_0, 2)]
        spx_3d_panic = all(x <= -5.0 for x in [dist_2, dist_1, dist_0])

    market_data: Dict[str, Any] = {
        "core_pce_yoy": final_pce,
        "ism_pmi": final_pmi,
        "services_pmi": final_services,
        "initial_claims": final_claims,
        "breakeven_inflation": final_breakeven,
        "fed_assets_growth_yoy": final_assets_growth,
        "real_yield_10y": final_real_yield,
        "move_index": final_move,
        "sloos_net_pct": results.get("sloos_val") if results.get("sloos_val") is not None else DEFAULTS["sloos_net_pct"],
        "hy_oas": results.get("hy_val") if results.get("hy_val") is not None else DEFAULTS["hy_oas"],
        "shiller_cape": results.get("shiller_cape_val") if results.get("shiller_cape_val") is not None else DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": final_fwd_eps,
        "vix_spot": vix_closes[-1] if vix_closes else DEFAULTS["vix_spot"],
        "pct_dist_200_sma": sma_dist_live,
        "drawdown_pct": drawdown_live,
        "stlfsi_index": results.get("stlfsi_val") if results.get("stlfsi_val") is not None else DEFAULTS["stlfsi_index"],
        "bond_yield_10y": live_bond_yield,
        "bond_yield_3m": live_bond_yield_3m if live_bond_yield_3m is not None else DEFAULTS.get("bond_yield_3m", 0.0),
        "dxy_spot": dxy_closes[-1] if dxy_closes else DEFAULTS["dxy_spot"],
        "market_breadth_pct": live_breadth,
        "spx_spot": spx_spot,
        "vix_3d_panic": vix_3d_panic,
        "vix_last_3": vix_last_3,
        "spx_3d_panic": spx_3d_panic,
        "spx_dist_last_3": spx_dist_last_3,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    # Update with derived overlays.
    market_data.update(derive_macro_overlays(market_data))
    market_data.update(derive_dxy_overlay(dxy_closes))

    market_sources: Dict[str, str] = {
        "core_pce_yoy": pce_source,
        "ism_pmi": "LIVE (Trading Economics)" if te_pmi is not None else "CONFIG/DEFAULT",
        "services_pmi": "LIVE (Trading Economics)" if te_services is not None else "CONFIG/DEFAULT",
        "initial_claims": "LIVE" if raw_claims is not None else "CONFIG/DEFAULT",
        "breakeven_inflation": "LIVE" if results.get("breakeven_inflation_val") is not None else "CONFIG/DEFAULT",
        "fed_assets_growth_yoy": "LIVE" if results.get("fed_assets_growth_val") is not None else "CONFIG/DEFAULT",
        "real_yield_10y": "LIVE" if results.get("real_yield_10y_val") is not None else "CONFIG/DEFAULT",
        "move_index": "LIVE (Yahoo Finance ^MOVE)" if move_closes else "CONFIG/DEFAULT",
        "sloos_net_pct": "LIVE" if results.get("sloos_val") is not None else "CONFIG/DEFAULT",
        "hy_oas": "LIVE" if results.get("hy_val") is not None else "CONFIG/DEFAULT",
        "shiller_cape": "LIVE (Multpl.com CAPE)" if results.get("shiller_cape_val") is not None else "CONFIG/DEFAULT",
        "fwd_eps_growth_yoy": fwd_eps_source,
        "vix_spot": "LIVE (Yahoo Finance ^VIX)" if vix_closes else "CONFIG/DEFAULT",
        "pct_dist_200_sma": "LIVE" if spx_closes else "CONFIG/DEFAULT",
        "drawdown_pct": "LIVE" if spx_closes else "CONFIG/DEFAULT",
        "stlfsi_index": "LIVE" if results.get("stlfsi_val") is not None else "CONFIG/DEFAULT",
        "bond_yield_10y": "LIVE (Yahoo Finance ^TNX / FRED DGS10)" if bond_yield_closes or results.get("dgs10_val") is not None else "CONFIG/DEFAULT",
        "bond_yield_3m": "LIVE (FRED DGS3MO / Yahoo ^IRX fallback)" if results.get("dgs3mo_val") is not None or bill_yield_closes else "CONFIG/DEFAULT",
        "dxy_spot": "LIVE (Yahoo Finance DX-Y.NYB)" if dxy_closes else "CONFIG/DEFAULT",
        "market_breadth_pct": "LIVE" if breadth_closes or results.get("barchart_breadth") is not None else "CONFIG/DEFAULT",
        "spx_spot": "LIVE (Yahoo Finance ^GSPC)" if spx_closes else "CONFIG/DEFAULT",
        "treasury_10y_3m_spread": "DERIVED",
        "inflation_shock": "DERIVED",
        "central_bank_stance": "DERIVED",
        "liquidity_pressure": "DERIVED",
        "dxy_sma_5": "DERIVED",
        "dxy_sma_20": "DERIVED",
        "dxy_trend_up": "DERIVED",
        "dxy_range_regime": "DERIVED",
    }

    return {"market_data": market_data, "market_sources": market_sources}
