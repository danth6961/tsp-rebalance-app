"""
engine.py — Tactical scoring and age-55 allocation integration.

This version keeps your regime/flag contract intact for the UI and tests,
while building the target allocation from the new age-55 engine using the
composite score. It also enforces a minimum 5% IFT hurdle (protection zone).

Notes:
- Baseline regime allocations remain sourced from constants.py for metadata/tests.
- DXY tilt remains a flag only; no allocation change is applied here.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD
from market_state import build_market_state
from models import EngineResult, FundsAlloc, Scores
from scoring import score_all_factors, composite_score
from utils import safe_float
from allocation_age55 import age55_target_allocations, to_percent_0_100

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _regime_alloc(name: str) -> FundsAlloc:
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)
    return total_abs_diff / 2.0


def score_market_data(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Adapter retained for tests that call engine.score_market_data().
    """
    return score_all_factors(data)


def determine_allocation(
    data: Dict[str, Any],
    previous_regime: Optional[str] = None,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
) -> Tuple[FundsAlloc, Dict[str, float], int, str, FundsAlloc, bool, bool]:
    """
    Build the target allocation via the age-55 interpolator while preserving
    the regime/flag contract used by the UI.
    """
    # Manual override preserves legacy behavior.
    if override_active:
        if override_regime == "RISK-ON OVERRIDE":
            base_alloc = _regime_alloc("RISK-ON OVERRIDE")
            return base_alloc, {}, 5, "RISK-ON OVERRIDE", base_alloc, False, False
        if override_regime == "OPTIMIZED NEUTRAL":
            base_alloc = _regime_alloc("OPTIMIZED NEUTRAL")
            return base_alloc, {}, 0, "OPTIMIZED NEUTRAL", base_alloc, False, False
        if override_regime == "DEFENSIVE ALLOCATION":
            base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")
            return base_alloc, {}, -5, "DEFENSIVE ALLOCATION", base_alloc, False, False
        base_alloc = _regime_alloc("EMERGENCY DISPATCH")
        return base_alloc, {}, -50, "EMERGENCY DISPATCH", base_alloc, False, False

    # 1) Factor scoring and composite score (your weights remain in scoring/ constants).
    scores: Scores = score_all_factors(data)
    comp_score_raw: float = float(composite_score(scores))
    logger.info("Composite score (raw): %.4f", comp_score_raw)

    # 2) Build interpreted market state for flags (no allocation change from DXY here).
    pce: float = safe_float(data.get("core_pce_yoy"), DEFAULTS.get("core_pce_yoy", 2.0))
    cape: float = safe_float(data.get("shiller_cape"), DEFAULTS.get("shiller_cape", 25.0))
    market_state = build_market_state(data, pce, cape)

    # Simple precedence for regime label (metadata only) — you can extend to Option B later:
    # emergency -> defensive -> risk-on gates -> neutral. Here we label neutral by default.
    if getattr(market_state, "panic", False):
        regime_name = "EMERGENCY DISPATCH"
    elif getattr(market_state, "asymmetric_vol", False):
        regime_name = "DEFENSIVE ALLOCATION"
    else:
        regime_name = "OPTIMIZED NEUTRAL"

    base_alloc: FundsAlloc = _regime_alloc(regime_name)

    # 3) Age-55 target allocation from score using smooth interpolation.
    #    Clamp the score to [-4.0, +1.0] as required (handled internally by the allocator, too).
    smooth_target = age55_target_allocations(comp_score_raw)  # fractions 0..1
    smooth_target_pct = to_percent_0_100(smooth_target)      # convert to 0..100 for app/UI

    # Map to TSP fund keys and include F=0 to preserve the engine API.
    allocs: FundsAlloc = {
        "C": float(smooth_target_pct["C_Fund_Pct"]),
        "S": float(smooth_target_pct["S_Fund_Pct"]),
        "I": float(smooth_target_pct["I_Fund_Pct"]),
        "G": float(smooth_target_pct["G_Fund_Pct"]),
        "F": 0.0,
    }

    # Flags: DXY strong only; overlays are flag-only per current policy.
    vol_trigger: bool = bool(getattr(market_state, "asymmetric_vol", False))
    dxy_trigger: bool = bool((float(data.get("dxy_spot", 0.0)) >= float(DXY_TILT_THRESHOLD)) and data.get("dxy_trend_up", True))

    comp_score_int: int = int(round(comp_score_raw))
    return allocs, scores, comp_score_int, regime_name, base_alloc, vol_trigger, dxy_trigger


def build_engine_result(
    market_data: Dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: Optional[str] = None,
) -> EngineResult:
    allocs, scores, comp_score, regime, baseline_alloc, vol_trigger, dxy_trigger = determine_allocation(
        market_data,
        previous_regime=previous_regime,
        override_active=override_active,
        override_regime=override_regime,
    )
    emergency_triggered = (regime == "EMERGENCY DISPATCH")
    return EngineResult(
        allocations=allocs,
        scores=scores,
        composite_score=comp_score,
        regime=regime,
        base_alloc=baseline_alloc,
        asymmetric_vol_trigger=vol_trigger,
        dxy_strong=dxy_trigger,
        emergency_triggered=emergency_triggered,
    )


def latest_regime_from_history(recent_regimes: List[str]) -> Optional[str]:
    return recent_regimes[-1] if recent_regimes else None


def should_use_tsp_ift(
    today: date,
    current_alloc: Dict[str, float],
    target_alloc: Dict[str, float],
    recent_regimes: List[str],
    recent_scores: List[float],
    emergency_triggered: bool,
    ift_count_this_month: int,
    last_ift_date: Optional[date],
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
    confirmation_days: int,
    cooldown_days: int,
) -> Tuple[bool, str]:
    """
    IFT protection zone:
    - Enforce a minimum 5.0% cumulative drift hurdle (allocation_hurdle) regardless of user config.
    - If the configured normal_drift_threshold_pct is higher than 5.0, the higher value rules.

    This preserves the two unrestricted IFTs/month by filtering out micro-churn.
    """
    drift = cumulative_alloc_drift(current_alloc, target_alloc)  # measured in pct points (0..100 scale)
    effective_threshold = max(float(normal_drift_threshold_pct), 5.0)  # 5% minimum hurdle
    reason = f"Cumulative drift is {drift:.2f}% (effective threshold: {effective_threshold:.2f}%)."
    if drift >= effective_threshold:
        return True, f"Drift exceeds threshold. {reason}"
    else:
        return False, f"Drift below threshold. {reason}"
