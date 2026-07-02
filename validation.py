"""
Author: Donald J Anthony
Date: Today's Date

validation.py — Domain-range validation for market inputs.

Owns plausibility checks only. This module answers whether a value is
plausible, not whether it is numeric.

Warnings are returned as data (strings), not raised as exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from constants import REGIME_DEFINITIONS


# -----------------------------------------------------------------------------
# Validation Result Contract
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ValidationWarning:
    """
    Structured warning emitted by validation helpers.

    Attributes
    ----------
    field : str
        The field name that the warning is associated with.
    message : str
        Explanation of the warning.
    severity : str
        Level of severity (e.g., "info", "warning", or "error").
    """
    field: str
    message: str
    severity: str = "warning"


# -----------------------------------------------------------------------------
# Range Validation Contract
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class RangeRule:
    """
    Plausible range for one market input field.

    Attributes
    ----------
    field : str
        The market input field name.
    lo : float
        Lower bound for plausibility.
    hi : float
        Upper bound for plausibility.
    rationale : str
        Explanation of why this range is chosen.
    """
    field: str
    lo: float
    hi: float
    rationale: str


# Wide bands catch broken feeds and unit errors without filtering out
# genuine tail-risk market conditions.
RANGE_RULES: tuple[RangeRule, ...] = (
    RangeRule(
        "vix_spot",
        5.0,
        150.0,
        "VIX has historically traded roughly 9-90; wider band for margin",
    ),
    RangeRule(
        "shiller_cape",
        5.0,
        80.0,
        "CAPE has ranged roughly from single digits to the 40s historically",
    ),
    RangeRule(
        "core_pce_yoy",
        -5.0,
        20.0,
        "Core PCE YoY is a bounded inflation rate, not a raw index level",
    ),
    RangeRule(
        "hy_oas",
        0.0,
        30.0,
        "HY OAS is a credit spread in percentage points and cannot be negative",
    ),
    RangeRule(
        "dxy_spot",
        50.0,
        200.0,
        "DXY index has historically traded roughly 70-165",
    ),
    RangeRule(
        "bond_yield_10y",
        -1.0,
        20.0,
        "10Y yield; allows for rare negative-yield regimes",
    ),
    RangeRule(
        "bond_yield_3m",
        -1.0,
        20.0,
        "3M yield; allows for rare negative-yield regimes",
    ),
    RangeRule(
        "drawdown_pct",
        0.0,
        100.0,
        "Drawdown from peak is bounded 0-100% by definition",
    ),
    RangeRule(
        "market_breadth_pct",
        0.0,
        100.0,
        "Breadth is a percentage of names above threshold",
    ),
    RangeRule(
        "sloos_net_pct",
        -100.0,
        100.0,
        "SLOOS net tightening % is bounded by survey definition",
    ),
    RangeRule(
        "real_yield_10y",
        -5.0,
        10.0,
        "10Y real yield; wide band to allow deep negative-real-rate regimes",
    ),
    RangeRule(
        "move_index",
        20.0,
        400.0,
        "MOVE rarely trades outside this band even in crises",
    ),
    RangeRule(
        "initial_claims",
        100.0,
        3000.0,
        "Initial claims in thousands; 3M+ would suggest a unit error",
    ),
)


# -----------------------------------------------------------------------------
# Market Validation Functions
# -----------------------------------------------------------------------------
def validate_market_data(data: dict[str, Any]) -> list[str]:
    """
    Return a list of warning messages for market fields outside plausible ranges.

    Checks that each field in the provided market snapshot is within its defined range.
    Non-numeric values generate warnings instead of exceptions.

    Parameters
    ----------
    data : dict[str, Any]
        Raw or normalized market snapshot.

    Returns
    -------
    list[str]
        List of human-readable warning messages.
    """
    warnings: list[str] = []

    for rule in RANGE_RULES:
        if rule.field not in data:
            continue

        raw_value = data[rule.field]
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            warnings.append(
                f"{rule.field}: non-numeric value '{raw_value}' ({rule.rationale})"
            )
            continue

        # Generate warning if the value is out of the acceptable range.
        if not (rule.lo <= value <= rule.hi):
            warnings.append(
                f"{rule.field}: {value:g} is outside the plausible range "
                f"[{rule.lo:g}, {rule.hi:g}] — {rule.rationale}"
            )

    return warnings


# -----------------------------------------------------------------------------
# Allocation Validation Functions
# -----------------------------------------------------------------------------
def validate_allocation_sums_to_100(
    alloc: dict[str, float],
    tolerance_pct: float = 0.5,
) -> list[str]:
    """
    Return warnings if an allocation does not sum to approximately 100%.

    Allows a small tolerance to handle rounding drift after normalization.

    Parameters
    ----------
    alloc : dict[str, float]
        Allocation mapping, typically fund percentages for G, C, I, S, and F.
    tolerance_pct : float, optional
        Acceptable absolute deviation from 100.0, by default 0.5.

    Returns
    -------
    list[str]
        Empty list if valid; otherwise, a list containing one warning message.
    """
    total = sum(float(v) for v in alloc.values())
    if abs(total - 100.0) > tolerance_pct:
        return [f"Allocation sums to {total:.1f}%, expected 100.0% (±{tolerance_pct}%)"]
    return []


def validate_allocation_keys(
    alloc: dict[str, float],
    expected_keys: tuple[str, ...] = ("G", "C", "I", "S", "F"),
) -> list[str]:
    """
    Check that an allocation contains the expected fund keys.

    This helps identify malformed configurations or partial data.

    Parameters
    ----------
    alloc : dict[str, float]
        Allocation mapping.
    expected_keys : tuple[str, ...], optional
        Expected fund keys, by default ("G", "C", "I", "S", "F").

    Returns
    -------
    list[str]
        Warning messages for missing or extra keys.
    """
    missing = [key for key in expected_keys if key not in alloc]
    extra = [key for key in alloc.keys() if key not in expected_keys]

    warnings: list[str] = []
    if missing:
        warnings.append(f"Missing allocation keys: {missing}")
    if extra:
        warnings.append(f"Unexpected allocation keys: {extra}")
    return warnings


# -----------------------------------------------------------------------------
# Snapshot Quality Validation
# -----------------------------------------------------------------------------
def validate_snapshot_quality(snapshot: dict[str, Any]) -> list[str]:
    """
    Validate basic snapshot quality flags.

    Expected optional fields:
      - source_quality
      - is_fallback
      - freshness_days

    The function warns if these fields exist and appear suspicious, but does not mandate them.

    Parameters
    ----------
    snapshot : dict[str, Any]
        Snapshot dictionary which may include quality metrics.

    Returns
    -------
    list[str]
        List of warning messages.
    """
    warnings: list[str] = []

    if "source_quality" in snapshot:
        try:
            quality = float(snapshot["source_quality"])
            if not (0.0 <= quality <= 1.0):
                warnings.append("source_quality should be between 0.0 and 1.0")
        except (TypeError, ValueError):
            warnings.append("source_quality is not numeric")

    if "freshness_days" in snapshot:
        try:
            freshness_days = float(snapshot["freshness_days"])
            if freshness_days < 0.0:
                warnings.append("freshness_days cannot be negative")
        except (TypeError, ValueError):
            warnings.append("freshness_days is not numeric")

    if "is_fallback" in snapshot and not isinstance(snapshot["is_fallback"], bool):
        warnings.append("is_fallback should be a boolean")

    return warnings


# -----------------------------------------------------------------------------
# Regime Definition Validation
# -----------------------------------------------------------------------------
def validate_regime_definitions() -> list[str]:
    """
    Validate that regime definitions include the expected UI fields.

    This lightweight check ensures that each regime in REGIME_DEFINITIONS contains
    all metadata keys required by the UI.

    Returns
    -------
    list[str]
        List of warning messages for regimes missing required fields.
    """
    required_keys = {"icon", "score_label", "profile", "allocation", "description", "color", "bg"}
    warnings: list[str] = []

    for name, info in REGIME_DEFINITIONS.items():
        missing = required_keys - set(info.keys())
        if missing:
            warnings.append(f"{name} missing regime metadata keys: {sorted(missing)}")

    return warnings


__all__ = [
    "ValidationWarning",
    "RangeRule",
    "RANGE_RULES",
    "validate_market_data",
    "validate_allocation_sums_to_100",
    "validate_allocation_keys",
    "validate_snapshot_quality",
    "validate_regime_definitions",
]
