"""
validation.py — domain-range validation for market inputs.

Owns plausibility checks only. This module answers whether a value is
plausible, not whether it is numeric.

Warnings are returned as data, not raised as exceptions.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class RangeRule:
    """Plausible range for one market input field."""
    field: str
    lo: float
    hi: float
    rationale: str


# Wide bands catch bad inputs and broken scrapers, not normal market extremes.
# Genuine tail-risk readings should still pass through.
RANGE_RULES: Tuple[RangeRule, ...] = (
    RangeRule("vix_spot", 5.0, 150.0, "VIX has historically traded roughly 9-90; wider band for margin"),
    RangeRule("shiller_cape", 5.0, 80.0, "CAPE has ranged roughly from single digits to the 40s historically"),
    RangeRule("core_pce_yoy", -5.0, 20.0, "Core PCE YoY is a bounded inflation rate, not a raw index level"),
    RangeRule("hy_oas", 0.0, 30.0, "HY OAS is a credit spread in percentage points and cannot be negative"),
    RangeRule("dxy_spot", 50.0, 200.0, "DXY index has historically traded roughly 70-165"),
    RangeRule("bond_yield_10y", -1.0, 20.0, "10Y yield; allows for rare negative-yield regimes"),
    RangeRule("bond_yield_3m", -1.0, 20.0, "3M yield; allows for rare negative-yield regimes"),
    RangeRule("drawdown_pct", 0.0, 100.0, "Drawdown from peak is bounded 0-100% by definition"),
    RangeRule("market_breadth_pct", 0.0, 100.0, "Breadth is a percentage of names above threshold"),
    RangeRule("sloos_net_pct", -100.0, 100.0, "SLOOS net tightening % is bounded by survey definition"),
    RangeRule("real_yield_10y", -5.0, 10.0, "10Y real yield; wide band to allow deep negative-real-rate regimes"),
    RangeRule("move_index", 20.0, 400.0, "MOVE rarely trades outside this band even in crises"),
    RangeRule("initial_claims", 100.0, 3000.0, "Initial claims in thousands; 3M+ would suggest a unit error"),
)


def validate_market_data(data: Dict[str, Any]) -> List[str]:
    """Return warnings for market fields outside plausible ranges."""
    warnings: List[str] = []
    for rule in RANGE_RULES:
        if rule.field not in data:
            continue
        raw = data[rule.field]
        try:
            val = float(raw)
        except (TypeError, ValueError):
            warnings.append(f"{rule.field}: non-numeric value '{raw}' ({rule.rationale})")
            continue
        if not (rule.lo <= val <= rule.hi):
            warnings.append(
                f"{rule.field}: {val:g} is outside the plausible range "
                f"[{rule.lo:g}, {rule.hi:g}] — {rule.rationale}"
            )
    return warnings


def validate_allocation_sums_to_100(alloc: Dict[str, float], tolerance_pct: float = 0.5) -> List[str]:
    """Return a warning if an allocation does not sum to ~100%."""
    total = sum(float(v) for v in alloc.values())
    if abs(total - 100.0) > tolerance_pct:
        return [f"Allocation sums to {total:.1f}%, expected 100.0% (±{tolerance_pct}%)"]
    return []
