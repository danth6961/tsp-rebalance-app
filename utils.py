import math
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

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
            return float(val) if math.isfinite(val) else None
        val_str = str(val).strip().replace("%", "").replace(",", "")
        match = re.search(r'^([-+]?[0-9]*\.?[0-9]+)', val_str)
        return float(match.group(1)) if match else None
    except Exception:
        return None

FIELD_LABELS = {
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


def classify_data_source(source: Optional[str]) -> str:
    source_str = (source or "").upper()
    if "LIVE" in source_str:
        return "live"
    if "DERIVED" in source_str:
        return "derived"
    if any(token in source_str for token in ("DEFAULT", "CONFIG", "FAILED", "OFFLINE")):
        return "fallback"
    return "fallback"


def compute_snapshot_quality(sources: Dict[str, str]) -> dict:
    live_fields: List[Tuple[str, str, str]] = []
    derived_fields: List[Tuple[str, str, str]] = []
    fallback_fields: List[Tuple[str, str, str]] = []

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
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            import pytz
            return datetime.now(pytz.timezone("America/New_York"))
        except Exception:
            utc_now = datetime.now(timezone.utc)
            is_dst = 3 < utc_now.month < 11
            offset = 4 if is_dst else 5
            return utc_now - timedelta(hours=offset)
