import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

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
