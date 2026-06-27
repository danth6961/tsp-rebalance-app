from __future__ import annotations

from datetime import datetime, date
import re
import csv
import json
import os
import math
import time
import shutil
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import pandas as pd
import yfinance as yf
import streamlit as st


# ==============================================================================
# GLOBAL RUN STATE INITIALIZATION
# ==============================================================================
run = False


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
    "services_pmi": 53.5,
    "initial_claims": 215.0,
    "breakeven_inflation": 2.25,
    "fed_assets_growth_yoy": -4.5,
    "real_yield_10y": 2.00,
    "move_index": 105.0,
    "sloos_net_pct": 6.6,
    "hy_oas": 2.76,
    "shiller_cape": 39.66,
    "fwd_eps_growth_yoy": 11.8,
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
    "G Fund (Short-Term U.S. Treasury Bills)": "BIL"
}


# ==============================================================================
# SECRETS DECRYPTION UTILITY
# ==============================================================================

def load_fred_api_secret() -> str:
    """Attempts to pull the FRED API Key from Streamlit Secrets securely."""
    try:
        if "fred_api_key" in st.secrets:
            return str(st.secrets["fred_api_key"])
        elif "FRED_API_KEY" in st.secrets:
            return str(st.secrets["FRED_API_KEY"])
    except Exception:
        pass
    return ""


# ==============================================================================
# AUTOMATED BACKUP AND SAFE I/O UTILITIES
# ==============================================================================

def safe_save_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Writes a JSON file atomically and maintains a backup version."""
    try:
        # Create a backup of the previous configuration if it exists and is valid
        if file_path.exists() and file_path.stat().st_size > 0:
            shutil.copy(file_path, file_path.with_suffix(".json.bak"))
            
        # Atomic Write: write to a temporary file first, then replace the original
        temp_file = file_path.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=4)
            
        if temp_file.exists():
            temp_file.replace(file_path)
    except Exception as e:
        print(f"❌ Error safely writing JSON data to {file_path}: {e}")


def safe_load_json(file_path: Path, default_factory) -> Dict[str, Any]:
    """Loads a JSON file. Automatically heals and restores from backup if corrupted."""
    if file_path.exists():
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Main file '{file_path}' failed to parse: {e}. Attempting backup restore...")
            
    # Try reading the backup file if the main file is missing or corrupted
    bak_path = file_path.with_suffix(".json.bak")
    if bak_path.exists():
        try:
            with open(bak_path, "r") as f:
                data = json.load(f)
            # Restore the parsed data to recover the environment
            shutil.copy(bak_path, file_path)
            print(f"ℹ️ Successfully recovered configuration for '{file_path}' from local backup.")
            return data
        except Exception as e:
            print(f"❌ Backup file '{bak_path}' also failed to parse: {e}")
            
    return default_factory()


# ==============================================================================
# STATE & CONFIG LOAD / SAVE
# ==============================================================================

def default_state() -> Dict[str, Any]:
    return {
        "month": date.today().strftime("%Y-%m"),
        "ift_count_this_month": 0,
        "last_ift_date": None,
        "last_run_date": None,
        "recent_regimes": [],
        "recent_scores": [],
        "recent_allocations": []
    }

def load_state() -> Dict[str, Any]:
    return safe_load_json(STATE_FILE, default_state)

def load_config() -> Dict[str, Any]:
    default_config = {
        "current_alloc": {"G": 40.0, "C": 30.0, "I": 20.0, "S": 5.0, "F": 5.0},
        "allow_second_ift": False,
        "normal_drift_threshold_pct": 7.5,
        "score_change_threshold": 3,
        "confirmation_days": 3,
        "cooldown_days": 5,
        "core_pce_yoy": DEFAULTS["core_pce_yoy"],
        "ism_pmi": DEFAULTS["ism_pmi"],
        "services_pmi": DEFAULTS["services_pmi"],
        "initial_claims": DEFAULTS["initial_claims"],
        "breakeven_inflation": DEFAULTS["breakeven_inflation"],
        "fed_assets_growth_yoy": DEFAULTS["fed_assets_growth_yoy"],
        "real_yield_10y": DEFAULTS["real_yield_10y"],
        "move_index": DEFAULTS["move_index"],
        "shiller_cape": DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "bond_yield_10y": DEFAULTS["bond_yield_10y"],
        "market_breadth_pct": DEFAULTS["market_breadth_pct"],
        "sloos_net_pct": DEFAULTS["sloos_net_pct"],
        "hy_oas": DEFAULTS["hy_oas"],
        "stlfsi_index": DEFAULTS["stlfsi_index"],
        "vix_spot": DEFAULTS["vix_spot"],
        "dxy_spot": DEFAULTS["dxy_spot"],
        "spx_spot": DEFAULTS["spx_spot"],
        "use_live_macro": True,
        "fred_api_key": ""
    }
    return safe_load_json(CONFIG_FILE, lambda: default_config)

def save_config(config_data: Dict[str, Any]) -> None:
    safe_save_json(CONFIG_FILE, config_data)

def save_state(state_data: Dict[str, Any]) -> None:
    safe_save_json(STATE_FILE, state_data)

def reset_monthly_if_needed(state_data: Dict[str, Any], today_date: date) -> Dict[str, Any]:
    current_month_str = today_date.strftime("%Y-%m")
    if state_data.get("month") != current_month_str:
        state_data["month"] = current_month_str
        state_data["ift_count_this_month"] = 0
    return state_data

def update_signal_history(state_data: Dict[str, Any], regime: str, score: int, alloc: Dict[str, float]) -> Dict[str, Any]:
    if "recent_regimes" not in state_data:
        state_data["recent_regimes"] = []
    if "recent_scores" not in state_data:
        state_data["recent_scores"] = []
    if "recent_allocations" not in state_data:
        state_data["recent_allocations"] = []
        
    today_str = date.today().isoformat()
    
    # Intraday Run Safeguard: update current index rather than appending on multi-clicks
    if state_data.get("last_run_date") == today_str and state_data["recent_regimes"]:
        state_data["recent_regimes"][-1] = regime
        state_data["recent_scores"][-1] = score
        state_data["recent_allocations"][-1] = alloc
    else:
        state_data["last_run_date"] = today_str
        state_data["recent_regimes"].append(regime)
        state_data["recent_scores"].append(score)
        state_data["recent_allocations"].append(alloc)
    
    # Prevent bloat
    state_data["recent_regimes"] = state_data["recent_regimes"][-30:]
    state_data["recent_scores"] = state_data["recent_scores"][-30:]
    state_data["recent_allocations"] = state_data["recent_allocations"][-30:]
    return state_data


# ==============================================================================
# STYLE CSS
# ==============================================================================

def inject_custom_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 5rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 1450px;
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
        .pill-failed { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }

        .small-kpi {
            padding: 1rem;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            background-color: rgba(248, 250, 252, 0.5);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.04), 0 2px 4px -2px rgba(0, 0, 0, 0.04);
            margin-top: 6px;
            margin-bottom: 0.6rem;
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .small-kpi:hover {
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.07), 0 4px 6px -4px rgba(0, 0, 0, 0.07);
            transform: translateY(-2px);
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

        /* Fully aligns the design elements of the Market Snapshot cards to match the Factor Scores */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.card-live) {
            border: 1px solid rgba(148, 163, 184, 0.15) !important;
            border-left: 5px solid #10b981 !important;
            border-radius: 12px !important;
            background-color: rgba(248, 250, 252, 0.5) !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.04), 0 2px 4px -2px rgba(0, 0, 0, 0.04) !important;
            padding: 1rem !important;
            margin-top: 6px !important;
            margin-bottom: 0.6rem !important;
            transition: transform 0.18s ease, box-shadow 0.18s ease !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.card-live):hover {
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.07), 0 4px 6px -4px rgba(0, 0, 0, 0.07) !important;
            transform: translateY(-2px) !important;
        }

        div[data-testid="stVerticalBlockBorderWrapper"]:has(.card-failed) {
            border: 1px solid rgba(148, 163, 184, 0.15) !important;
            border-left: 5px solid #dc2626 !important;
            border-radius: 12px !important;
            background-color: rgba(248, 250, 252, 0.5) !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.04), 0 2px 4px -2px rgba(0, 0, 0, 0.04) !important;
            padding: 1rem !important;
            margin-top: 6px !important;
            margin-bottom: 0.6rem !important;
            transition: transform 0.18s ease, box-shadow 0.18s ease !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.card-failed):hover {
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.07), 0 4px 6px -4px rgba(0, 0, 0, 0.07) !important;
            transform: translateY(-2px) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_custom_css()


# ==============================================================================
# UTILITIES
# ==============================================================================

def clean_html(raw_html: str) -> str:
    return " ".join([line.strip() for line in raw_html.split("\n") if line.strip()])


def is_finite_number(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except Exception:
        return False


def safe_float(x, default=None):
    return float(x) if is_finite_number(x) else default


def clean_and_parse_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            if math.isfinite(val):
                return float(val)
            return None
        
        val_str = str(val).strip().replace("%", "").replace(",", "")
        match = re.search(r'^([-+]?[0-9]*\.?[0-9]+)', val_str)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None


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
# DATA HELPERS & ADVANCED SCRAPING LOGIC
# ==============================================================================

def fetch_via_fred_api(series_id: str, api_key: str, limit: int = 1) -> List[Tuple[str, float]]:
    """Direct fetch tool for FRED API endpoints utilizing standard JSON queries."""
    if not api_key:
        return []
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={urllib.parse.quote(series_id)}&api_key={urllib.parse.quote(api_key)}&file_type=json&sort_order=desc&limit={limit}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        observations = data.get("observations", [])
        result = []
        for obs in observations:
            val = clean_and_parse_float(obs.get("value"))
            if val is not None:
                result.append((obs.get("date"), val))
        result.reverse()  # chronological order
        return result
    except Exception as e:
        print(f"❌ FRED API request failed for '{series_id}': {e}")
        return []


def fetch_from_dbnomics(series_id: str) -> List[Tuple[str, float]]:
    url = f"https://api.db.nomics.world/v22/series/FRED/FRED/{urllib.parse.quote(series_id)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            
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
    except Exception as e:
        print(f"❌ DBnomics API request failed for '{series_id}': {e}")
        return []


def fetch_fred_latest(series_id: str, api_key: Optional[str] = None) -> Optional[float]:
    # 1. Try Live FRED API first
    if api_key:
        try:
            data_points = fetch_via_fred_api(series_id, api_key, limit=5)
            if data_points:
                return data_points[-1][1]
        except Exception as err:
            print(f"⚠️ FRED API fetch failed for '{series_id}' ({err}). Falling back...")

    # 2. Try DBnomics mirror
    try:
        data_points = fetch_from_dbnomics(series_id)
        if data_points:
            return data_points[-1][1]
    except Exception as err:
        print(f"⚠️ DBnomics mirror fetch failed for '{series_id}' ({err}). Falling back to standard FRED...")

    # 3. Fallback to standard FRED CSV
    def _load_fred():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id={urllib.parse.quote(series_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
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
    except Exception as e:
        print(f"❌ Both DBnomics and FRED CSV failed for series '{series_id}': {e}")
        
    return None


def fetch_fred_core_pce_yoy(api_key: Optional[str] = None) -> Optional[float]:
    # 1. Try Live FRED API
    if api_key:
        try:
            data_points = fetch_via_fred_api("PCEPILFE", api_key, limit=20)
            if len(data_points) >= 13:
                latest_val = data_points[-1][1]
                past_val = data_points[-13][1]
                return round(((latest_val - past_val) / past_val) * 100.0, 2)
        except Exception as err:
            print(f"⚠️ FRED API YoY PCE fetch failed ({err}). Falling back...")

    # 2. Try DBnomics mirror
    try:
        data_points = fetch_from_dbnomics("PCEPILFE")
        if len(data_points) >= 13:
            latest_val = data_points[-1][1]
            past_val = data_points[-13][1]
            return round(((latest_val - past_val) / past_val) * 100.0, 2)
    except Exception as err:
        print(f"⚠️ DBnomics mirror YoY PCE fetch failed ({err}). Falling back to standard FRED...")

    # 3. Fallback to standard FRED CSV
    def _load_fred_yoy():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id=PCEPILFE"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=3) as response:
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
        return retry_call(_load_fred_yoy)
    except Exception as e:
        print(f"❌ Both DBnomics and FRED failed for Core PCE YoY: {e}")

    return None


def fetch_fed_assets_yoy_growth(api_key: Optional[str] = None) -> Optional[float]:
    # 1. Try Live FRED API
    if api_key:
        try:
            data_points = fetch_via_fred_api("WALCL", api_key, limit=60)
            if len(data_points) >= 53:
                latest_val = data_points[-1][1]
                past_val = data_points[-53][1]
                return round(((latest_val - past_val) / past_val) * 100.0, 2)
        except Exception as err:
            print(f"⚠️ FRED API WALCL fetch failed ({err}). Falling back...")

    # 2. Try DBnomics mirror
    try:
        data_points = fetch_from_dbnomics("WALCL")
        if len(data_points) >= 53:
            latest_val = data_points[-1][1]
            past_val = data_points[-53][1]
            return round(((latest_val - past_val) / past_val) * 100.0, 2)
    except Exception as err:
        print(f"⚠️ DBnomics mirror WALCL fetch failed ({err}). Falling back to standard FRED...")

    def _load_fred():
        base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        url = f"{base_url}?id=WALCL"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=3) as response:
            df = pd.read_csv(response)

        if df.empty or len(df.columns) < 2:
            return None

        value_col = df.columns[1]
        series = pd.to_numeric(df[value_col], errors="coerce").dropna()
        if len(series) < 53:
            return None
        
        latest_val = float(series.iloc[-1])
        past_val = float(series.iloc[-53])
        return round(((latest_val - past_val) / past_val) * 100.0, 2)

    try:
        return retry_call(_load_fred)
    except Exception as e:
        print(f"❌ Both DBnomics and FRED failed for Fed Assets YoY growth: {e}")

    return None


def fetch_indicators_from_te_indicators_page() -> Dict[str, Optional[float]]:
    url = "https://tradingeconomics.com/united-states/indicators"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    results = {
        "core_pce_yoy": None,
        "ism_pmi": None,
        "services_pmi": None
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
            
        dfs = pd.read_html(html)
        for df in dfs:
            if df.empty or len(df.columns) < 2:
                continue
            
            col_name = df.columns[0]
            for _, row in df.iterrows():
                indicator_text = str(row[col_name]).strip()
                
                if "Core PCE Price Index YoY" in indicator_text or "Core PCE Price Index Annual Change" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["core_pce_yoy"] = val
                        
                if "ISM Manufacturing PMI" in indicator_text or "Manufacturing PMI" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["ism_pmi"] = val
                        
                if "ISM Services PMI" in indicator_text or "Services PMI" in indicator_text or "Non Manufacturing PMI" in indicator_text:
                    val = clean_and_parse_float(row.iloc[1])
                    if val is not None:
                        results["services_pmi"] = val
    except Exception as e:
        print(f"Error scraping indicators from Trading Economics: {e}")
        pass
    
    return results


def fetch_shiller_cape_live() -> Optional[float]:
    def _load():
        url = "https://www.multpl.com/shiller-pe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
        
        match = re.search(r'class=["\']num["\']>\s*([0-9\.]+)\s*<', html)
        if match:
            return float(match.group(1))
        
        match_alt = re.search(r'Current Shiller PE Ratio is\s+([0-9\.]+)', html, re.IGNORECASE)
        if match_alt:
            return float(match_alt.group(1))
            
        return None

    try:
        return retry_call(_load)
    except Exception as e:
        print(f"Error fetching Shiller CAPE: {e}")
        return None


def fetch_barchart_s5th_fallback() -> Optional[float]:
    url = "https://www.barchart.com/stocks/quotes/$S5TH"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
            
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
    except Exception as e:
        print(f"Error scraping Barchart $S5TH: {e}")
        pass
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
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                if ("Close", ticker) in df.columns:
                    close = df[("Close", ticker)]
                else:
                    close_candidates = [c for c in df.columns if c[0] == "Close"]
                    if close_candidates:
                        close = df[close_candidates[0]]
                    else:
                        close = pd.Series()
            else:
                close = df.get("Close", pd.Series())
            
            closes_list = pd.to_numeric(close, errors="coerce").dropna().astype(float).tolist()
            if closes_list:
                return closes_list
                
        try:
            t = yf.Ticker(ticker)
            history_df = t.history(period=period, interval=interval)
            if history_df is not None and not history_df.empty:
                close_series = history_df.get("Close")
                if close_series is not None and not close_series.empty:
                    closes_list = pd.to_numeric(close_series, errors="coerce").dropna().astype(float).tolist()
                    if closes_list:
                        return closes_list
        except Exception:
            pass
            
        return []

    try:
        return retry_call(_load)
    except Exception as e:
        print(f"Live closes fetch for {ticker} failed: {e}")
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
    except Exception as e:
        print(f"Dataframe fetch for {ticker} failed: {e}")
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
# CACHED SNAPSHOTS (Optimized to 1-hour cache duration)
# ==============================================================================

@st.cache_data(ttl=3600)
def cached_fred(series_id: str, api_key: Optional[str] = None) -> Optional[float]:
    return fetch_fred_latest(series_id, api_key)


@st.cache_data(ttl=3600)
def cached_fred_core_pce_yoy(api_key: Optional[str] = None) -> Optional[float]:
    return fetch_fred_core_pce_yoy(api_key)


@st.cache_data(ttl=3600)
def cached_fred_fed_assets_yoy(api_key: Optional[str] = None) -> Optional[float]:
    return fetch_fed_assets_yoy_growth(api_key)


@st.cache_data(ttl=3600)
def get_te_live_data() -> Dict[str, Optional[float]]:
    return fetch_indicators_from_te_indicators_page()


@st.cache_data(ttl=3600)
def cached_shiller_cape_live() -> Optional[float]:
    return fetch_shiller_cape_live()


@st.cache_data(ttl=3600)
def cached_barchart_s5th() -> Optional[float]:
    return fetch_barchart_s5th_fallback()


@st.cache_data(ttl=3600)
def cached_yahoo_closes(ticker: str, period: str, interval: str) -> List[float]:
    return fetch_yfinance_closes(ticker, period=period, interval=interval)


@st.cache_data(ttl=3600)
def get_cached_proxy_df(ticker: str, period: str) -> pd.DataFrame:
    return fetch_yfinance_dataframe(ticker, period)


@st.cache_data(ttl=3600)
def fetch_ytd_return(ticker: str) -> Optional[float]:
    df = get_cached_proxy_df(ticker, "1y")
    if df.empty:
        return None
    
    current_year = date.today().year
    ytd_df = df[df["Date"].dt.year == current_year]
    
    if ytd_df.empty:
        return None
        
    start_price = ytd_df["Price"].iloc[0]
    end_price = ytd_df["Price"].iloc[-1]
    
    ytd_return = ((end_price - start_price) / start_price) * 100.0
    return round(ytd_return, 2)


@st.cache_data(ttl=3600)
def get_market_snapshot(api_key: Optional[str] = None) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
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
            executor.submit(cached_yahoo_closes, "^TNX", "1mo", "1d"): "bond_yield_closes",
            executor.submit(cached_fred, "ICSA", api_key): "initial_claims_val",
            executor.submit(cached_fred, "T10YIE", api_key): "breakeven_inflation_val",
            executor.submit(cached_fred_fed_assets_yoy, api_key): "fed_assets_growth_val",
            executor.submit(cached_fred, "DFII10", api_key): "real_yield_10y_val",
            executor.submit(cached_yahoo_closes, "^MOVE", "1mo", "1d"): "move_closes",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"⚠️ Live download task failed for key '{key}': {e}")
                results[key] = None

    vix_closes = results.get("vix_closes") or []
    dxy_closes = results.get("dxy_closes") or []
    spx_closes = results.get("spx_closes") or []
    breadth_closes = results.get("breadth_closes") or []
    bond_yield_closes = results.get("bond_yield_closes") or []
    move_closes = results.get("move_closes") or []
    
    sma_dist_live, drawdown_live, spx_spot = calc_spx_metrics_from_closes(spx_closes)
    
    te_live = results.get("te_live") or {"core_pce_yoy": None, "ism_pmi": None, "services_pmi": None}
    te_pce = te_live.get("core_pce_yoy")
    te_pmi = te_live.get("ism_pmi")
    te_services = te_live.get("services_pmi")
    
    shiller_cape = results.get("shiller_cape_val")
    live_breadth = None
    breadth_source = "CONFIG/DEFAULT"
    
    # Core PCE YoY
    if te_pce is not None:
        final_pce = te_pce
        pce_source = "LIVE (Trading Economics)"
    else:
        fred_pce_yoy = fetch_fred_core_pce_yoy(api_key)
        if fred_pce_yoy is not None:
            final_pce = fred_pce_yoy
            pce_source = "LIVE (FRED API PCE)" if api_key else "LIVE (FRED PCEPILFE Mirror)"
        else:
            final_pce = DEFAULTS["core_pce_yoy"]
            pce_source = "CONFIG/DEFAULT"

    # ISM PMI
    if te_pmi is not None:
        final_pmi = te_pmi
        pmi_source = "LIVE (Trading Economics)"
    else:
        final_pmi = DEFAULTS["ism_pmi"]
        pmi_source = "CONFIG/DEFAULT"

    # Services PMI
    if te_services is not None:
        final_services = te_services
        services_source = "LIVE (Trading Economics Services)"
    else:
        final_services = DEFAULTS["services_pmi"]
        services_source = "CONFIG/DEFAULT"

    # Initial Jobless Claims
    raw_claims = results.get("initial_claims_val")
    if raw_claims is not None:
        final_claims = round(raw_claims / 1000.0, 2)
        claims_source = "LIVE (FRED API ICSA)" if api_key else "LIVE (FRED ICSA Mirror)"
    else:
        final_claims = DEFAULTS["initial_claims"]
        claims_source = "CONFIG/DEFAULT"

    # 10Y Breakeven Inflation Rate
    if results.get("breakeven_inflation_val") is not None:
        final_breakeven = results.get("breakeven_inflation_val")
        breakeven_source = "LIVE (FRED API T10YIE)" if api_key else "LIVE (FRED T10YIE Mirror)"
    else:
        final_breakeven = DEFAULTS["breakeven_inflation"]
        breakeven_source = "CONFIG/DEFAULT"

    # Fed Net Assets YoY Growth
    if results.get("fed_assets_growth_val") is not None:
        final_assets_growth = results.get("fed_assets_growth_val")
        assets_source = "LIVE (FRED API WALCL YoY)" if api_key else "LIVE (FRED WALCL Mirror)"
    else:
        final_assets_growth = DEFAULTS["fed_assets_growth_yoy"]
        assets_source = "CONFIG/DEFAULT"

    # 10-Year Real Yield
    if results.get("real_yield_10y_val") is not None:
        final_real_yield = results.get("real_yield_10y_val")
        real_yield_source = "LIVE (FRED API DFII10)" if api_key else "LIVE (FRED DFII10 Mirror)"
    else:
        final_real_yield = DEFAULTS["real_yield_10y"]
        real_yield_source = "CONFIG/DEFAULT"

    # Implied Volatility (MOVE Index)
    if move_closes:
        final_move = move_closes[-1]
        move_source = "LIVE (Yahoo Finance ^MOVE)"
    else:
        final_move = DEFAULTS["move_index"]
        move_source = "CONFIG/DEFAULT"

    # Breadth Logic
    if breadth_closes:
        live_breadth = breadth_closes[-1]
        breadth_source = "LIVE (Yahoo Finance ^S5TH)"
    else:
        b_breadth = results.get("barchart_breadth")
        if b_breadth is not None:
            live_breadth = b_breadth
            breadth_source = "LIVE (Barchart $S5TH Scraping)"
        else:
            live_breadth = DEFAULTS["market_breadth_pct"]
            breadth_source = "CONFIG/DEFAULT"

    # 10Y Yield
    if bond_yield_closes:
        live_bond_yield = round(bond_yield_closes[-1] / 10.0, 3)
        bond_source = "LIVE (Yahoo Finance ^TNX)"
    else:
        fred_dgs10 = fetch_fred_latest("DGS10", api_key)
        if fred_dgs10 is not None:
            live_bond_yield = fred_dgs10
            bond_source = "LIVE (FRED API DGS10)" if api_key else "LIVE (FRED DGS10 Mirror)"
        else:
            live_bond_yield = DEFAULTS["bond_yield_10y"]
            bond_source = "CONFIG/DEFAULT"

    # 3-day Panic Valve Logic
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

    def determine_source(series_id, label, default_src):
        if results.get(label) is not None:
            return f"{default_src} (FRED API)" if api_key else default_src
        val_fetched = fetch_fred_latest(series_id, api_key)
        if val_fetched is not None:
            return f"LIVE (FRED API {series_id})" if api_key else f"LIVE (DBnomics {series_id} Mirror)"
        return "CONFIG/DEFAULT"

    sloos_source = determine_source("DRTSCIS", "sloos_val", "LIVE (FRED DRTSCIS)")
    hy_source = determine_source("BAMLH0A0HYM2", "hy_val", "LIVE (FRED BAMLH0A0HYM2)")
    stlfsi_source = determine_source("STLFSI4", "stlfsi_val", "LIVE (FRED STLFSI4)")

    market_data = {
        "core_pce_yoy": final_pce,
        "ism_pmi": final_pmi,
        "services_pmi": final_services,
        "initial_claims": final_claims,
        "breakeven_inflation": final_breakeven,
        "fed_assets_growth_yoy": final_assets_growth,
        "real_yield_10y": final_real_yield,
        "move_index": final_move,
        "sloos_net_pct": results.get("sloos_val") if results.get("sloos_val") is not None else fetch_fred_latest("DRTSCIS", api_key),
        "hy_oas": results.get("hy_val") if results.get("hy_val") is not None else fetch_fred_latest("BAMLH0A0HYM2", api_key),
        "shiller_cape": shiller_cape if shiller_cape is not None else DEFAULTS["shiller_cape"],
        "fwd_eps_growth_yoy": DEFAULTS["fwd_eps_growth_yoy"],
        "vix_spot": vix_closes[-1] if vix_closes else DEFAULTS["vix_spot"],
        "pct_dist_200_sma": sma_dist_live,
        "drawdown_pct": drawdown_live,
        "stlfsi_index": results.get("stlfsi_val") if results.get("stlfsi_val") is not None else fetch_fred_latest("STLFSI4", api_key),
        "bond_yield_10y": live_bond_yield,
        "dxy_spot": dxy_closes[-1] if dxy_closes else DEFAULTS["dxy_spot"],
        "market_breadth_pct": live_breadth,
        "spx_spot": spx_spot,
        "vix_3d_panic": vix_3d_panic,
        "vix_last_3": vix_last_3,
        "spx_3d_panic": spx_3d_panic,
        "spx_dist_last_3": spx_dist_last_3,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    if market_data["sloos_net_pct"] is None:
        market_data["sloos_net_pct"] = DEFAULTS["sloos_net_pct"]
    if market_data["hy_oas"] is None:
        market_data["hy_oas"] = DEFAULTS["hy_oas"]
    if market_data["stlfsi_index"] is None:
        market_data["stlfsi_index"] = DEFAULTS["stlfsi_index"]

    market_sources = {
        "core_pce_yoy": pce_source,
        "ism_pmi": pmi_source,
        "services_pmi": services_source,
        "initial_claims": claims_source,
        "breakeven_inflation": breakeven_source,
        "fed_assets_growth_yoy": assets_source,
        "real_yield_10y": real_yield_source,
        "move_index": move_source,
        "sloos_net_pct": sloos_source,
        "hy_oas": hy_source,
        "shiller_cape": "LIVE (Multpl.com CAPE)" if shiller_cape is not None else "CONFIG/DEFAULT",
        "fwd_eps_growth_yoy": "CONFIG/DEFAULT",
        "vix_spot": "LIVE" if vix_closes else "DEFAULT",
        "pct_dist_200_sma": "LIVE" if spx_closes else "DEFAULT",
        "drawdown_pct": "LIVE" if spx_closes else "DEFAULT",
        "stlfsi_index": stlfsi_source,
        "bond_yield_10y": bond_source,
        "dxy_spot": "LIVE" if dxy_closes else "DEFAULT",
        "market_breadth_pct": breadth_source,
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
    services_pmi = safe_float(data.get("services_pmi"), DEFAULTS["services_pmi"])
    initial_claims = safe_float(data.get("initial_claims"), DEFAULTS["initial_claims"])
    breakeven_inflation = safe_float(data.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    fed_assets_growth_yoy = safe_float(data.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    real_yield_10y = safe_float(data.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    
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

    # 1. Inflation Score
    if pce < 1.8: scores["inflation"] = 3
    elif pce < 2.0: scores["inflation"] = 1
    elif pce <= 2.3: scores["inflation"] = 0
    elif pce <= 3.0: scores["inflation"] = -3
    else: scores["inflation"] = -5
    
    if breakeven_inflation > 2.6:
        scores["inflation"] = min(scores["inflation"], -3) - 1
    elif breakeven_inflation < 1.8:
        scores["inflation"] = max(scores["inflation"], 0)

    # 2. Growth Score
    composite_pmi = (0.20 * pmi) + (0.80 * services_pmi)
    if composite_pmi > 55.0: scores["growth"] = 3
    elif composite_pmi >= 51.5: scores["growth"] = 1
    elif composite_pmi >= 50.0: scores["growth"] = 0
    elif composite_pmi >= 48.0: scores["growth"] = -3
    else: scores["growth"] = -5
    
    if initial_claims > 250.0:
        scores["growth"] -= 1
    if initial_claims > 280.0:
        scores["growth"] = min(scores["growth"], -3) - 1

    # 3. Liquidity Score
    if sloos < -15.0: scores["liquidity"] = 3
    elif sloos <= 5.0: scores["liquidity"] = 0
    else: scores["liquidity"] = -5
    
    if fed_assets_growth_yoy > 0.0:
        scores["liquidity"] += 2
    else:
        scores["liquidity"] -= 2

    # 4. Credit Spreads
    if hy_spread < 3.0: scores["credit_spreads"] = 3
    elif hy_spread < 4.0: scores["credit_spreads"] = 1
    elif hy_spread <= 5.0: scores["credit_spreads"] = 0
    elif hy_spread <= 6.0: scores["credit_spreads"] = -3
    else: scores["credit_spreads"] = -5

    # 5. Valuation
    base_cape_ceiling = 35.0 if fwd_eps >= 15.0 else 30.0
    if real_yield_10y > 2.2:
        active_cape_ceiling = base_cape_ceiling - 5.0
    elif real_yield_10y < 0.5:
        active_cape_ceiling = base_cape_ceiling + 3.0
    else:
        active_cape_ceiling = base_cape_ceiling

    if cape < 20.0: scores["valuation"] = 3
    elif cape <= 25.0: scores["valuation"] = 0
    elif cape <= active_cape_ceiling: scores["valuation"] = -3
    else: scores["valuation"] = -5

    # 6. Market Stress
    if vix < 12.0: scores["market_stress"] = 3
    elif vix < 15.0: scores["market_stress"] = 1
    elif vix <= 22.0: scores["market_stress"] = 0
    elif vix <= 30.0: scores["market_stress"] = -3
    else: scores["market_stress"] = -5

    # 7. Momentum
    if sma_dist > 5.0: scores["momentum"] = 3
    elif sma_dist >= 0.0: scores["momentum"] = 1
    elif sma_dist >= -5.0: scores["momentum"] = -3
    else: scores["momentum"] = -5

    # 8. Drawdown
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
    
    f_fund_unlocked = (bond_yield - pce) >= 1.5 and move_index < 120.0
    dxy_strong = dxy_spot >= 103.5

    panic_valve_triggered = False
    vix_3d_panic = data.get("vix_3d_panic", False)
    spx_3d_panic = data.get("spx_3d_panic", False)
    
    if market_breadth is not None:
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
        
    # Measures the transition amplitude across the confirmed regime boundary
    if len(recent_scores) >= confirmation_days + 1:
        score_change = abs(recent_scores[-1] - recent_scores[-confirmation_days - 1])
    else:
        score_change = score_change_threshold
        
    if score_change < score_change_threshold:
        return False, f"Score change not strong enough ({score_change} vs {score_change_threshold})"
        
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
            clean_html(f"""
            <div class="small-kpi" style="border-left: 5px solid #3b82f6;">
                <div class="small-kpi-title">Composite Score</div>
                <div class="small-kpi-value">{total_score}</div>
                <div class="small-kpi-note">Higher is more risk-on</div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with c2:
        action_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#22c55e" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            clean_html(f"""
            <div class="small-kpi" style="border-left: 5px solid {action_color};">
                <div class="small-kpi-title">Action</div>
                <div class="small-kpi-value" style="color:{action_color};">{action}</div>
                <div class="small-kpi-note">Decision recommendation</div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            clean_html(f"""
            <div class="small-kpi" style="border-left: 5px solid #f59e0b;">
                <div class="small-kpi-title">IFTs Used</div>
                <div class="small-kpi-value">{ift_used}/2</div>
                <div class="small-kpi-note">Monthly transfer count</div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            clean_html(f"""
            <div class="small-kpi" style="border-left: 5px solid #a78bfa;">
                <div class="small-kpi-title">Regime</div>
                <div class="small-kpi-value" style="font-size:1.0rem;">{regime}</div>
                <div class="small-kpi-note">Model state</div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with c5:
        reason_color = "#dc2626" if regime == "EMERGENCY DISPATCH" else ("#16a34a" if action == "SUBMIT IFT" else "#64748b")
        st.markdown(
            clean_html(f"""
            <div class="small-kpi" style="border-left: 5px solid {reason_color};">
                <div class="small-kpi-title">IFT Reason</div>
                <div class="small-kpi-value" style="font-size:0.95rem; color:{reason_color}; line-height:1.2;">
                    {reason}
                </div>
                <div class="small-kpi-note">Why this action was chosen</div>
            </div>
            """),
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


def score_card_html(label: str, value: Any, note: str, color: str, icon: str) -> str:
    return clean_html(f"""
    <div class="small-kpi" style="border-left: 5px solid {color}; margin-bottom:0.6rem;">
        <div class="small-kpi-title">{label}</div>
        <div class="small-kpi-value" style="color:{color};">{icon} {value}</div>
        <div class="small-kpi-note">{note}</div>
    </div>
    """)


def source_pill_html(source: str) -> str:
    source_upper = str(source).upper()
    if "FAILED" in source_upper or "DEFAULT" in source_upper or "FALLBACK" in source_upper:
        cls = "pill-failed"
    elif "LIVE" in source_upper:
        cls = "pill-live"
    else:
        cls = "pill-default"
    return f"<span class='pill {cls}'>{source}</span>"


# ==============================================================================
# APP STATE INITIALIZATION
# ==============================================================================

today = date.today()
state = load_state()
cfg = load_config()
state = reset_monthly_if_needed(state, today)

# Read from secure Streamlit Secrets first
secrets_api_key = load_fred_api_secret()

INDICATOR_KEYS = [
    "core_pce_yoy", "ism_pmi", "services_pmi", "initial_claims",
    "breakeven_inflation", "fed_assets_growth_yoy", "real_yield_10y", "move_index",
    "sloos_net_pct", "hy_oas", "shiller_cape", "fwd_eps_growth_yoy",
    "stlfsi_index", "bond_yield_10y", "market_breadth_pct", "vix_spot", "dxy_spot", "spx_spot"
]

DERIVED_KEYS = ["pct_dist_200_sma", "drawdown_pct", "vix_3d_panic", "spx_3d_panic"]

# Synchronize local Streamlit session state from file system config
for key in INDICATOR_KEYS:
    if key not in st.session_state:
        st.session_state[key] = float(cfg.get(key, DEFAULTS.get(key, 0.0)))
    if f"{key}_source" not in st.session_state:
        st.session_state[f"{key}_source"] = "CONFIG/DEFAULT"

for key in DERIVED_KEYS:
    if key not in st.session_state:
        st.session_state[key] = 0.0 if "pct" in key or "dist" in key else False


# ==============================================================================
# SIDEBAR
# ==============================================================================

with st.sidebar:
    st.markdown(
        clean_html(f"""
        <div style="padding-bottom: 1rem; border-bottom: 1px solid rgba(148,163,184,0.18); margin-bottom: 1rem;">
            <div style="font-size: 1.38rem; font-weight: 800; line-height: 1.2;">🏛️ TSP Rebalance Engine</div>
            <div style="color: #64748b; font-size: 0.8rem; margin-top: 0.4rem; line-height: 1.35;">Decision support dashboard for TSP allocation management and IFT discipline.</div>
        </div>
        """),
        unsafe_allow_html=True
    )

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
        allow_second_ift = st.checkbox("Allow second IFT", value=bool(cfg.get("allow_second_ift", False)), help="Allows making a second transfer in normal regimes if conditions are favorable.")
        normal_drift_threshold_pct = st.number_input("Normal drift threshold %", value=float(cfg.get("normal_drift_threshold_pct", 7.5)), step=0.5, help="Required drift threshold to trigger rebalances.")
        score_change_threshold = st.number_input("Score change threshold", value=int(cfg.get("score_change_threshold", 3)), step=1, help="Required boundary point variance to qualify as a strong trend adjustment.")
        confirmation_days = st.number_input("Confirmation days", value=int(cfg.get("confirmation_days", 3)), step=1, help="Consecutive days a signal must hold inside a new regime to trigger.")
        cooldown_days = st.number_input("Cooldown days", value=int(cfg.get("cooldown_days", 5)), step=1, help="Minimum days between consecutive transfers.")
        st.markdown("---")
        use_live_macro = st.checkbox("Use Live Macro Data where available", value=bool(cfg.get("use_live_macro", True)), help="Fetches live data from public APIs and fallback mirrors.")

    # Moved Mark IFT button directly under the Transfer Rules expander
    mark_ift = st.button("✅ Mark IFT Used Today", use_container_width=True)

    st.markdown("---")
    reset_state_btn = st.button("♻️ Reset State File", use_container_width=True)
    clear_logs_btn = st.button("🗑️ Clear Daily Log File", use_container_width=True)
    
    # Moved API Keys expander to sit exactly between Clear Daily Log and Save Config buttons
    with st.expander("🔑 API Keys & Settings", expanded=False):
        active_api_key_default = secrets_api_key if secrets_api_key else cfg.get("fred_api_key", "")
        fred_api_key = st.text_input(
            "FRED API Key", 
            value=active_api_key_default, 
            type="password", 
            help="Your private 32-character FRED API key is used to query real-time federal indicators."
        )
        if secrets_api_key:
            st.caption("🔒 *Configured securely via encrypted Streamlit Secrets.*")
            
    save_config_btn = st.button("💾 Save Config Settings", use_container_width=True)
    
    # Added vertical spacer to pad the main launch button down visually
    st.markdown("<div style='padding-top: 1.5rem;'></div>", unsafe_allow_html=True)
    run = st.button("🚀 Fetch & Run Engine", use_container_width=True, type="primary")

if save_config_btn:
    cfg["current_alloc"] = current_alloc
    cfg["allow_second_ift"] = allow_second_ift
    cfg["normal_drift_threshold_pct"] = float(normal_drift_threshold_pct)
    cfg["score_change_threshold"] = int(score_change_threshold)
    cfg["confirmation_days"] = int(confirmation_days)
    cfg["cooldown_days"] = int(cooldown_days)
    cfg["use_live_macro"] = bool(use_live_macro)
    
    # Save manually edited key only if not overridden by secure system secrets
    if not secrets_api_key:
        cfg["fred_api_key"] = fred_api_key
        
    for key in INDICATOR_KEYS:
        cfg[key] = float(st.session_state[key])
    save_config(cfg)
    st.sidebar.success("Config and overrides saved.")

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
# MAIN ENGINE EXECUTION
# ==============================================================================

if "engine_ran" not in st.session_state:
    st.session_state["engine_ran"] = False

if run:
    with st.spinner("Loading live macroeconomic datasets..."):
        try:
            snapshot = get_market_snapshot(fred_api_key)
            fetched_data = snapshot["market_data"]
            fetched_sources = snapshot["market_sources"]
        except Exception as e:
            st.error(f"Could not connect to live feeds. Using system offline baselines. (Info: {e})")
            fetched_data = DEFAULTS.copy()
            fetched_data["vix_spot"] = DEFAULTS["vix_spot"]
            fetched_data["pct_dist_200_sma"] = 1.2
            fetched_data["drawdown_pct"] = 2.5
            fetched_data["vix_3d_panic"] = False
            fetched_data["vix_last_3"] = [19.0, 19.1, 19.0]
            fetched_data["spx_3d_panic"] = False
            fetched_data["spx_dist_last_3"] = [1.1, 1.2, 1.2]
            fetched_data["spx_spot"] = DEFAULTS["spx_spot"]
            fetched_sources = {k: "OFFLINE FALLBACK" for k in DEFAULTS.keys()}

        for key in INDICATOR_KEYS:
            src = fetched_sources.get(key, "CONFIG/DEFAULT")
            val = fetched_data.get(key, DEFAULTS[key])
            
            if use_live_macro and "DEFAULT" not in str(src).upper() and "FAILED" not in str(src).upper():
                st.session_state[key] = float(val)
                st.session_state[f"{key}_source"] = src
            else:
                st.session_state[key] = float(cfg.get(key, DEFAULTS.get(key, 0.0)))
                st.session_state[f"{key}_source"] = "CONFIG/DEFAULT" if not use_live_macro else "FETCH FAILED (FALLBACK)"

        st.session_state["pct_dist_200_sma"] = fetched_data.get("pct_dist_200_sma", 0.0)
        st.session_state["drawdown_pct"] = fetched_data.get("drawdown_pct", 0.0)
        st.session_state["vix_3d_panic"] = fetched_data.get("vix_3d_panic", False)
        st.session_state["spx_3d_panic"] = fetched_data.get("spx_3d_panic", False)
        st.session_state["vix_last_3"] = fetched_data.get("vix_last_3", [])
        st.session_state["spx_dist_last_3"] = fetched_data.get("spx_dist_last_3", [])

        allocations, factor_scores, total_score, regime, baseline, vol_t, dxy_t = execute_tsp_allocation_engine_final(fetched_data)
        
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

        append_log_row({
            "date": today.isoformat(),
            "action": action,
            "reason": reason,
            "regime": regime,
            "total_score": total_score,
            "ift_count_this_month": state["ift_count_this_month"],
            "current_alloc": json.dumps(current_alloc),
            "target_alloc": json.dumps(allocations),
            "vix": fetched_data.get("vix_spot", DEFAULTS["vix_spot"]),
            "spx_200sma_dist": fetched_data.get("pct_dist_200_sma", 0.0),
            "drawdown_pct": fetched_data.get("drawdown_pct", 0.0),
        })

        st.session_state["engine_ran"] = True
        st.rerun()


# ==============================================================================
# DASHBOARD LAYOUT & TABS
# ==============================================================================

if st.session_state["engine_ran"]:
    market_data = {key: st.session_state[key] for key in INDICATOR_KEYS}
    market_data["pct_dist_200_sma"] = st.session_state["pct_dist_200_sma"]
    market_data["drawdown_pct"] = st.session_state["drawdown_pct"]
    market_data["vix_3d_panic"] = st.session_state["vix_3d_panic"]
    market_data["spx_3d_panic"] = st.session_state["spx_3d_panic"]
    market_data["vix_last_3"] = st.session_state.get("vix_last_3", [])
    market_data["spx_dist_last_3"] = st.session_state.get("spx_dist_last_3", [])

    allocations, factor_scores, total_score, regime, baseline, vol_t, dxy_t = execute_tsp_allocation_engine_final(market_data)

    emergency_triggered = (total_score == -50)
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

    render_metric_cards(total_score, regime, action, state["ift_count_this_month"], reason)

    st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Allocation", "🧠 Factors", "📊 Proxy Charts", "🕒 History", "📁 Logs & State"])

    with tab1:
        # Dynamic, Step-by-Step IFT Order Guide Panel
        if action == "SUBMIT IFT":
            st.markdown("### 📋 TSP.gov Interfund Transfer (IFT) Action Plan")
            st.warning("⚠️ **Action Required**: The engine has confirmed a strategic regime shift. Execute this exact rebalance on your TSP.gov portal.")
            
            rebalance_instructions = []
            for fund in ["G", "C", "I", "S", "F"]:
                curr_val = current_alloc.get(fund, 0.0)
                targ_val = allocations.get(fund, 0.0)
                delta_val = targ_val - curr_val
                
                if delta_val != 0.0:
                    sign_prefix = "+" if delta_val > 0 else ""
                    rebalance_instructions.append(
                        f"Set **{fund} Fund** to **{targ_val:.1f}%** (Adjustment: `{sign_prefix}{delta_val:+.1f}%`)"
                    )
            
            if rebalance_instructions:
                plan_cols = st.columns(len(rebalance_instructions))
                for step_idx, step_text in enumerate(rebalance_instructions):
                    with plan_cols[step_idx]:
                        st.markdown(
                            clean_html(f"""
                            <div class="small-kpi" style="border-left: 5px solid #22c55e; background-color: rgba(34, 197, 94, 0.05); min-height: 120px;">
                                <div class="small-kpi-title">STEP {step_idx + 1}</div>
                                <div class="small-kpi-value" style="font-size: 0.98rem; line-height: 1.35; font-weight: 700; color: #15803d; margin-top: 4px;">
                                    {step_text}
                                </div>
                            </div>
                            """),
                            unsafe_allow_html=True
                        )
            st.markdown("---")

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

        st.markdown("<div style='margin: 2.6rem 0; border-bottom: 1px solid rgba(148,163,184,0.12);'></div>", unsafe_allow_html=True)
        st.markdown("### 🧭 Strategic Regime Directory")
        st.caption("The engine maps the overall composite score to one of the four policy regimes below to determine baseline targets:")
        
        regimes_info = [
            {
                "name": "RISK-ON OVERRIDE",
                "icon": "🚀",
                "score": "Score: ≥ +5",
                "profile": "Aggressive Profile",
                "alloc": "Base: G 35% / C 45% / I 15% / S 5% / F 0%",
                "desc": "Strong macroeconomic backdrop and solid upward price momentum.",
                "color": "#10b981",
                "bg": "rgba(16, 185, 129, 0.08)"
            },
            {
                "name": "OPTIMIZED NEUTRAL",
                "icon": "⚖️",
                "score": "Score: 0 to +4",
                "profile": "Balanced Profile",
                "alloc": "Base: G 45% / C 35% / I 10% / S 10% / F 0%",
                "desc": "Default balanced state when market signals are constructive but mixed.",
                "color": "#3b82f6",
                "bg": "rgba(59, 130, 246, 0.08)"
            },
            {
                "name": "DEFENSIVE ALLOCATION",
                "icon": "🛡️",
                "score": "Score: < 0",
                "profile": "Defensive Profile",
                "alloc": "Base: G 65% / C 20% / I 10% / S 5% / F 0%",
                "desc": "Used when risk rises or the composite turns negative.",
                "color": "#f59e0b",
                "bg": "rgba(245, 158, 11, 0.08)"
            },
            {
                "name": "EMERGENCY DISPATCH",
                "icon": "🚨",
                "score": "Score: -50",
                "profile": "Maximum Defense",
                "alloc": "Base: G 90% / F 10% (or G 100% / F 0%)",
                "desc": "3-day panic valve breach.",
                "color": "#ef4444",
                "bg": "rgba(239, 68, 68, 0.08)"
            }
        ]

        regime_cols = st.columns(4)
        for idx, info in enumerate(regimes_info):
            is_active = (regime == info["name"])
            border_css = f"border: 2px solid {info['color']}; background-color: {info['bg']}; box-shadow: 0 8px 16px rgba(0,0,0,0.06);" if is_active else "border: 1px solid rgba(148, 163, 184, 0.15);"
            active_badge = f"<div style='color: {info['color']}; font-weight: 800; font-size: 0.72rem; text-transform: uppercase; margin-bottom: 0.35rem;'>★ ACTIVE ENVIRONMENT</div>" if is_active else ""
            color_val = info['color'] if is_active else '#0f172a'
            
            with regime_cols[idx]:
                st.markdown(
                    clean_html(f"""
                    <div class="small-kpi" style="{border_css} height: 100%; min-height: 250px;">
                        {active_badge}
                        <div style="font-weight: 800; font-size: 0.95rem; color: {color_val};">{info['icon']} {info['name']}</div>
                        <div style="font-size: 0.75rem; font-weight: 600; color: #64748b; margin-bottom: 0.6rem;">{info['profile']} • {info['score']}</div>
                        <div style="font-size: 0.8rem; font-weight: 700; margin-bottom: 0.6rem; color: {color_val};">{info['alloc']}</div>
                        <div style="font-size: 0.78rem; color: #64748b; line-height: 1.35;">{info['desc']}</div>
                    </div>
                    """),
                    unsafe_allow_html=True
                )

    with tab2:
        st.markdown("### 🚨 Panic Valve & Emergency Dispatch Diagnostic")
        pv_cols = st.columns(3)
        with pv_cols[0]:
            vix_triggered = market_data.get("vix_3d_panic", False)
            vix_status = "🔴 TRIGGERED (VIX >= 30)" if vix_triggered else "🟢 Normal"
            vix_hist_str = ", ".join(map(str, market_data.get("vix_last_3", []))) if market_data.get("vix_last_3") else "N/A"
            st.markdown(
                score_card_html(
                    "VIX 3-Day State", 
                    vix_status, 
                    f"Last 3 closes: [{vix_hist_str}]", 
                    "#dc2626" if vix_triggered else "#16a34a", 
                    "⚠️" if vix_triggered else "✅"
                ),
                unsafe_allow_html=True,
            )
        with pv_cols[1]:
            spx_triggered = market_data.get("spx_3d_panic", False)
            spx_status = "🔴 TRIGGERED (SMA Dist <= -5%)" if spx_triggered else "🟢 Normal"
            spx_hist_str = ", ".join(map(str, market_data.get("spx_dist_last_3", []))) if market_data.get("spx_dist_last_3") else "N/A"
            st.markdown(
                score_card_html(
                    "SPX 200SMA 3-Day State", 
                    spx_status, 
                    f"Last 3 closes: [{spx_hist_str}]", 
                    "#dc2626" if spx_triggered else "#16a34a", 
                    "⚠️" if spx_triggered else "✅"
                ),
                unsafe_allow_html=True,
            )
        with pv_cols[2]:
            breadth_val = market_data.get("market_breadth_pct")
            override_active = breadth_val > 60.0 if breadth_val is not None else False
            breadth_status = f"🟢 ACTIVE (Breadth: {breadth_val:.2f}% > 60%)" if override_active else "🔴 INACTIVE"
            st.markdown(
                score_card_html(
                    "Breadth Override State", 
                    breadth_status, 
                    f"Current Breadth: {f'{breadth_val:.2f}%' if breadth_val is not None else 'N/A'}", 
                    "#16a34a" if override_active else "#dc2626", 
                    "🛡️" if override_active else "⚠️"
                ),
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin: 2.5rem 0; border-bottom: 1px solid rgba(148,163,184,0.08);'></div>", unsafe_allow_html=True)
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

        st.markdown("<div style='margin: 2.5rem 0; border-bottom: 1px solid rgba(148,163,184,0.08);'></div>", unsafe_allow_html=True)
        st.markdown("### Market Snapshot (Fully Editable)")
        st.caption("Review current indicators below. Feel free to override any value directly inside its card; changes will instantly recompute the rules engine allocations and factor scores.")
        
        market_items = [
            ("Core PCE YoY", "core_pce_yoy", st.session_state.get("core_pce_yoy_source")),
            ("ISM Manufacturing PMI", "ism_pmi", st.session_state.get("ism_pmi_source")),
            ("ISM Services PMI", "services_pmi", st.session_state.get("services_pmi_source")),
            ("Initial Claims (K)", "initial_claims", st.session_state.get("initial_claims_source")),
            ("10Y Breakeven Inflation", "breakeven_inflation", st.session_state.get("breakeven_inflation_source")),
            ("Fed Assets Growth YoY", "fed_assets_growth_yoy", st.session_state.get("fed_assets_growth_yoy_source")),
            ("10Y Real Yield", "real_yield_10y", st.session_state.get("real_yield_10y_source")),
            ("MOVE Volatility", "move_index", st.session_state.get("move_index_source")),
            ("SLOOS Net %", "sloos_net_pct", st.session_state.get("sloos_net_pct_source")),
            ("HY OAS", "hy_oas", st.session_state.get("hy_oas_source")),
            ("Shiller CAPE", "shiller_cape", st.session_state.get("shiller_cape_source")),
            ("Fwd EPS Growth YoY", "fwd_eps_growth_yoy", st.session_state.get("fwd_eps_growth_yoy_source")),
            ("VIX Spot", "vix_spot", st.session_state.get("vix_spot_source")),
            ("SPX vs 200SMA %", "pct_dist_200_sma", "DERIVED"),
            ("Drawdown %", "drawdown_pct", "DERIVED"),
            ("STLFSI", "stlfsi_index", st.session_state.get("stlfsi_index_source")),
            ("10Y Yield", "bond_yield_10y", st.session_state.get("bond_yield_10y_source")),
            ("DXY Spot", "dxy_spot", st.session_state.get("dxy_spot_source")),
            ("Breadth %", "market_breadth_pct", st.session_state.get("market_breadth_pct_source")),
            ("SPX Spot", "spx_spot", st.session_state.get("spx_spot_source")),
        ]
        
        market_cols = st.columns(4)
        for i, (label, key, source) in enumerate(market_items):
            source_str = str(source).upper()
            is_failed = "FAILED" in source_str or "DEFAULT" in source_str or "FALLBACK" in source_str or "OFFLINE" in source_str
            
            # Selector hook class based on data source state
            cls_name = "card-failed" if is_failed else "card-live"
            
            step_val = 0.1
            format_val = "%.2f"
            if "PMI" in label or "Index" in label or "VIX" in label or "Volatility" in label:
                step_val = 0.5
            elif "Claims" in label or "Spot" in label or "Yield" in label:
                step_val = 1.0
                format_val = "%.2f"
            elif "Assets" in label or "SLOOS" in label:
                step_val = 1.0
                format_val = "%.2f"
                
            card_key = f"container_{key}"
            
            with market_cols[i % 4]:
                with st.container(border=True):
                    # Zero-height target hook div for the global stylesheet selector
                    st.markdown(f'<div class="{cls_name}" style="display:none;"></div>', unsafe_allow_html=True)
                    
                    st.markdown(
                        clean_html(f"""
                        <div class="small-kpi-title" style="margin-bottom: 2px;">
                            {label}
                        </div>
                        """),
                        unsafe_allow_html=True
                    )
                    
                    st.number_input(
                        label=label,
                        value=float(st.session_state[key]),
                        step=step_val,
                        format=format_val,
                        key=key,
                        label_visibility="collapsed"
                    )
                    
                    st.markdown(
                        clean_html(f"""
                        <div style="margin-top: 4px;">
                            {source_pill_html(source)}
                        </div>
                        """),
                        unsafe_allow_html=True
                    )

        st.markdown("<div style='margin: 1.0rem 0; border-bottom: 1px solid rgba(148,163,184,0.08);'></div>", unsafe_allow_html=True)
        st.subheader("🔍 Engine Decision Breakdown")
        
        with st.expander("📖 Detailed Decision Trace & Factor Attribution", expanded=True):
            st.markdown("#### 1. Macro & Stress Factor Scoring")
            
            pos_factors = []
            neg_factors = []
            neu_factors = []
            
            for k, label in score_order:
                val = factor_scores.get(k, 0)
                if val > 0:
                    pos_factors.append(f"{label} (+{val} pts)")
                elif val < 0:
                    neg_factors.append(f"{label} ({val} pts)")
                else:
                    neu_factors.append(label)
            
            attr_c1, attr_c2, attr_c3 = st.columns(3)
            with attr_c1:
                st.markdown("**🟢 Positive Drivers**")
                if pos_factors:
                    for f in pos_factors: st.markdown(f"- {f}")
                else:
                    st.markdown("*None*")
            with attr_c2:
                st.markdown("**⚪ Neutral Factors**")
                if neu_factors:
                    for f in neu_factors: st.markdown(f"- {f}")
                else:
                    st.markdown("*None*")
            with attr_c3:
                st.markdown("**🔴 Negative Drags**")
                if neg_factors:
                    for f in neg_factors: st.markdown(f"- {f}")
                else:
                    st.markdown("*None*")
                    
            st.markdown("#### 2. Allocation Evolution Trace")
            st.markdown(f"**Step A: Initial Score Evaluation**  \nRaw Composite Score of **{total_score}** maps the engine to the **{regime}** regime base allocation.")
            
            st.markdown("**Step B: Overlay Adjustments & Filter Logic**")
            asymmetric_vol_trigger = factor_scores.get("market_stress", 0) <= -3 or factor_scores.get("momentum", 0) <= -3
            if asymmetric_vol_trigger:
                st.markdown("* ⚠️ **Asymmetric Volatility Filter Active:** Market stress or price momentum has weakened below critical levels. The engine has automatically removed S Fund holdings.")
            else:
                st.markdown("* ✅ **Asymmetric Volatility Filter Inactive:** Markets exhibit stable volatility metrics; standard S Fund allocations remain intact.")
                
            dxy_strong = market_data.get("dxy_spot", 0) >= 103.5
            if dxy_strong:
                st.markdown("* 💵 **Strong USD Modifier Active:** Dollar Index is trading above historical resistance ($\ge 103.5$). Shifted 5% from International (I Fund) to domestic US large-caps (C Fund).")
            else:
                st.markdown("* 🌐 **USD Modifier Inactive:** Dollar strength is within standard limits.")
                
            bond_unlocked = (market_data.get("bond_yield_10y", 0) - market_data.get("core_pce_yoy", 0)) >= 1.5 and market_data.get("move_index", 105.0) < 120.0
            if bond_unlocked:
                st.markdown("* 📈 **F Fund Yield Unlock Active:** 10-Year Real Yield is highly attractive ($\ge 1.5\%$ above Core PCE inflation) and Sovereign Volatility (MOVE Index) is stable under 120.")
            else:
                st.markdown("* 🔒 **F Fund Yield Unlock Inactive:** F Fund holdings remain locked in favor of G Fund cash capital protections.")

    with tab3:
        st.markdown("### Live TSP Fund Proxy Price Tracking")
        st.write(
            "The Federal Retirement Thrift Investment Board does not provide direct tickers. "
            "The cards and charts below plot standard liquid exchange-traded funds (ETFs) that closely proxy "
            "each TSP asset class."
        )

        st.markdown("#### YTD Performance Overview")
        ytd_cols = st.columns(5)
        
        fund_short_names = [
            "C Fund (S&P 500)",
            "S Fund (Mid/Small)",
            "I Fund (Intl ACWX)",
            "F Fund (Bonds)",
            "G Fund (T-Bills)"
        ]
        
        for idx, (fund_label, ticker) in enumerate(PROXIES.items()):
            short_label = fund_short_names[idx]
            with ytd_cols[idx]:
                with st.spinner(f"Loading {ticker}..."):
                    ytd_val = fetch_ytd_return(ticker)
                if ytd_val is not None:
                    st.metric(
                        label=f"{short_label} ({ticker})",
                        value=f"{ytd_val:+.2f}%",
                    )
                else:
                    st.metric(label=f"{short_label} ({ticker})", value="N/A")

        st.markdown("---")

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
        
        state_cols = st.columns(3)
        with state_cols[0]:
            st.metric(label="Current Tracking Month", value=state.get("month") or "N/A")
        with state_cols[1]:
            st.metric(label="IFTs Used This Month", value=f"{state.get('ift_count_this_month', 0)} / 2")
        with state_cols[2]:
            last_date = state.get("last_ift_date")
            st.metric(label="Last IFT Date", value=str(last_date) if last_date else "None")
            
        st.markdown("### Run History Log")
        
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
                        "market_sources": {k: st.session_state.get(f"{k}_source") for k in INDICATOR_KEYS},
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
    st.info("Use the sidebar to set allocations and policy, then click **Fetch & Run Engine** to initialize the data panels.")
