"""
validation.py — Domain-range validation for market inputs.

Owns: plausibility range checks only. This is intentionally separate
from utils.py's type-coercion helpers (safe_float, clean_and_parse_float):
those answer "is this a number?"; this answers "is this a number that
could plausibly be true in a live market?"

Should NOT contain: business/scoring logic, I/O, UI code, persistence.

Design choice: warnings are returned as data, not raised as exceptions.
This is a manual-confirmation tool (per project_handoff.md) — the right
behavior for an out-of-range input is a loud, specific warning the user
can evaluate, not a hard stop that blocks them from seeing a real
tail-risk event (e.g. VIX genuinely spiking to 90 during a crash should
warn, not crash the app).
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class RangeRule:
    """A plausibility band for one market input field.

    Attributes:
        field: key into the market_data dict (matches utils.FIELD_LABELS).
        lo: minimum plausible value.
        hi: maximum plausible value.
        rationale: short human-readable justification, surfaced in warnings
            so the user understands *why* a value looks wrong, not just that
            it does.
    """
    field: str
    lo: float
    hi: float
    rationale: str


# Generous bounds meant to catch fat-finger manual edits and broken
# scrapers (e.g. a percent sign left in a scraped string, or a decimal
# point dropped), not to encode "normal" market ranges. A genuine crisis
# reading (VIX 80, HY OAS 12) should still pass through -- these bounds
# are wide on purpose.
RANGE_RULES: Tuple[RangeRule, ...] = (
    RangeRule("vix_spot", 5.0, 150.0, "VIX has never traded outside ~9-90 historically; wider band for margin"),
    RangeRule("shiller_cape", 5.0, 80.0, "CAPE has ranged roughly 5 (1920 crash lows) to 44 (dot-com peak)"),
    RangeRule("core_pce_yoy", -5.0, 20.0, "Core PCE YoY is a bounded inflation rate, not a raw index level"),
    RangeRule("hy_oas", 0.0, 30.0, "HY OAS is a credit spread in percentage points, cannot be negative"),
    RangeRule("dxy_spot", 50.0, 200.0, "DXY index has historically traded roughly 70-165"),
    RangeRule("bond_yield_10y", -1.0, 20.0, "10Y yield; allows for rare negative-yield regimes"),
    RangeRule("bond_yield_3m", -1.0, 20.0, "3M yield; allows for rare negative-yield regimes"),
    RangeRule("drawdown_pct", 0.0, 100.0, "Drawdown from peak is bounded 0-100% by definition"),
    RangeRule("market_breadth_pct", 0.0, 100.0, "Breadth is a percentage of names above threshold"),
    RangeRule("sloos_net_pct", -100.0, 100.0, "SLOOS net tightening % is bounded by survey definition"),
    RangeRule("real_yield_10y", -5.0, 10.0, "10Y real yield; wide band to allow deep negative-real-rate regimes"),
    RangeRule("move_index", 20.0, 400.0, "MOVE (bond vol index) rarely trades outside this band even in crises"),
    RangeRule("initial_claims", 100.0, 3000.0, "Initial claims in thousands; 3M+ would imply a data-unit error"),
)


def validate_market_data(data: Dict[str, Any]) -> List[str]:
    """Return human-readable warnings for any field outside its plausible range.

    Args:
        data: market data dict as produced by data_sources.get_market_snapshot
            or app.load_editable_market_data. Missing fields are silently
            skipped -- this function validates what's present, it does not
            enforce completeness (that's a separate concern).

    Returns:
        A list of warning strings, empty if everything looks plausible.
        Side-effect-free by design: callers decide whether to display a
        warning, log it, or ignore it. This keeps the function trivially
        unit-testable without mocking Streamlit.
    """
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
    """Check that a fund allocation dict sums to ~100%.

    Used both for the user-editable "current allocation" sidebar inputs
    and for engine-produced target allocations, since a normalization bug
    in either path would silently misrepresent portfolio drift.
    """
    total = sum(float(v) for v in alloc.values())
    if abs(total - 100.0) > tolerance_pct:
        return [f"Allocation sums to {total:.1f}%, expected 100.0% (±{tolerance_pct}%)"]
    return []
