"""
Author: Donald J Anthony
Date: Today's Date

utils.py — Utility functions for common operations.

Provides:
  - Numerical sanity checks and safe conversions.
  - String cleaning and float parsing.
  - Mapping field names to display labels.
  - Data source classification.
  - Snapshot quality computation based on input sources.
  - Estimation of current time in EST.

These helper functions are used throughout the project to ensure robust data handling.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# -----------------------------------------------------------------------------
# Number Utilities
# -----------------------------------------------------------------------------
def is_finite_number(x: any) -> bool:
    """
    Check if the input x is a finite number.

    Parameters
    ----------
    x : any
        The value to check.

    Returns
    -------
    bool
        True if x is a finite number; otherwise, False.
    """
    try:
        return x is not None and math.isfinite(float(x))
    except Exception:
        return False


def safe_float(x: any, default: Optional[float] = None) -> Optional[float]:
    """
    Safely convert x to a float using a default if conversion fails.

    Parameters
    ----------
    x : any
        The value to convert.
    default : Optional[float], optional
        Default value if x is not a finite number, by default None.

    Returns
    -------
    Optional[float]
        Converted float or the default value.
    """
    return float(x) if is_finite_number(x) else default


def clean_and_parse_float(val: any) -> Optional[float]:
    """
    Clean and parse a value to a float, stripping unwanted characters.

    The function removes percentages and commas, then extracts the numerical
    component using regular expressions.

    Parameters
    ----------
    val : any
        The value to clean and parse.

    Returns
    -------
    Optional[float]
        Parsed float if extraction and conversion succeed; otherwise, None.
    """
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            # Return the float if the input is already numeric.
            return float(val) if math.isfinite(val) else None
        # Convert to string and remove percent signs and commas.
        val_str = str(val).strip().replace("%", "").replace(",", "")
        match = re.search(r'^([-+]?[0-9]*\.?[0-9]+)', val_str)
        return float(match.group(1)) if match else None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Field Labels Mapping
# -----------------------------------------------------------------------------
FIELD_LABELS: Dict[str, str] = {
    "core_pce_yoy": "Core PCE YoY",
    "ism_pmi": "ISM Manufacturing PMI",
    "services_pmi": "ISM Services PMI",
    "initial_claims": "Initial Claims (K)",
    "breakeven_inflation": "10Y Breakeven Inflation",
    "fed_assets_growth_yoy": "Fed Assets Growth YoY",
    "real_yield_10y": "10Y Real Yield",
    "move_index": "MOVE Volatility",
    "sloos_net_pct": "SLOOS Net %",
    "hy_oas": "HY OAS",
    "shiller_cape": "Shiller CAPE",
    "fwd_eps_growth_yoy": "Fwd EPS Growth YoY",
    "stlfsi_index": "STLFSI",
    "bond_yield_10y": "10Y Yield",
    "bond_yield_3m": "3M Yield",
    "market_breadth_pct": "Breadth %",
    "vix_spot": "VIX Spot",
    "dxy_spot": "DXY Spot",
    "spx_spot": "SPX Spot",
    "pct_dist_200_sma": "SPX vs 200SMA %",
    "drawdown_pct": "Drawdown %",
    "treasury_10y_3m_spread": "10Y-3M Spread",
    "inflation_shock": "Inflation Shock",
    "central_bank_stance": "Central Bank Stance",
    "liquidity_pressure": "Liquidity Pressure",
    "dxy_sma_5": "DXY SMA 5",
    "dxy_sma_20": "DXY SMA 20",
    "dxy_trend_up": "DXY Trend Up",
    "dxy_range_regime": "DXY Range Regime",
    "vix_3d_panic": "VIX 3-Day Panic",
    "spx_3d_panic": "SPX 3-Day Panic",
}


# -----------------------------------------------------------------------------
# Data Source Classification
# -----------------------------------------------------------------------------
def classify_data_source(source: Optional[str]) -> str:
    """
    Classify the data source as live, derived, or fallback.

    Parameters
    ----------
    source : Optional[str]
        The data source (as a string).

    Returns
    -------
    str
        "live" if source indicates live data, "derived" if generated, otherwise "fallback".
    """
    source_str = (source or "").upper()
    if "LIVE" in source_str:
        return "live"
    if "DERIVED" in source_str:
        return "derived"
    if any(token in source_str for token in ("DEFAULT", "CONFIG", "FAILED", "OFFLINE")):
        return "fallback"
    return "fallback"


def compute_snapshot_quality(sources: Dict[str, str]) -> dict:
    """
    Compute a snapshot quality summary based on the data source labels.

    The function classifies each field into live, derived, or fallback categories,
    then computes the percentage of live inputs and assigns a quality level with corresponding styling.

    Parameters
    ----------
    sources : Dict[str, str]
        Dictionary mapping field names to their data source labels.

    Returns
    -------
    dict
        Quality metrics including counts, percentages, and UI styling tokens.
    """
    live_fields: List[Tuple[str, str, str]] = []
    derived_fields: List[Tuple[str, str, str]] = []
    fallback_fields: List[Tuple[str, str, str]] = []

    # Classify each field based on its data source.
    for key, source in sources.items():
        label = FIELD_LABELS.get(key, key.replace("_", " ").title())
        category = classify_data_source(source)
        row = (key, label, source or "CONFIG/DEFAULT")
        if category == "live":
            live_fields.append(row)
        elif category == "derived":
            derived_fields.append(row)
        else:
            fallback_fields.append(row)

    total_count = len(sources)
    live_count = len(live_fields)
    derived_count = len(derived_fields)
    fallback_count = len(fallback_fields)
    live_pct = round(100.0 * live_count / total_count, 1) if total_count else 0.0

    # Determine quality level and styling based on the percent of live inputs.
    if live_pct >= 75:
        level = "high"
        headline = "Strong snapshot — most inputs are live"
        color = "#15803d"
        bg = "#dcfce7"
        border = "#bbf7d0"
    elif live_pct >= 50:
        level = "medium"
        headline = "Mixed snapshot — some inputs are placeholders"
        color = "#b45309"
        bg = "#fef3c7"
        border = "#fde68a"
    else:
        level = "low"
        headline = "Weak snapshot — mostly defaults; treat recommendation cautiously"
        color = "#991b1b"
        bg = "#fee2e2"
        border = "#fca5a5"

    return {
        "live_count": live_count,
        "derived_count": derived_count,
        "fallback_count": fallback_count,
        "total_count": total_count,
        "live_pct": live_pct,
        "level": level,
        "headline": headline,
        "color": color,
        "bg": bg,
        "border": border,
        "live_fields": live_fields,
        "derived_fields": derived_fields,
        "fallback_fields": fallback_fields,
    }


def get_est_now() -> datetime:
    """
    Return the current time estimated in Eastern Standard Time (EST).

    Tries to use zoneinfo (Python 3.9+) and falls back to pytz or manual calculation.

    Returns
    -------
    datetime
        Current time in the 'America/New_York' timezone.
    """
    try:
        # Use standard library zoneinfo if available.
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            # Fallback to pytz if installed.
            import pytz
            return datetime.now(pytz.timezone("America/New_York"))
        except Exception:
            # Final fallback: manually adjust UTC time based on DST assumption.
            utc_now = datetime.now(timezone.utc)
            # Simplistic DST assumption: DST from April to October.
            is_dst = 3 < utc_now.month < 11
            offset = 4 if is_dst else 5
            return utc_now - timedelta(hours=offset)
