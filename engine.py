"""
Author: Donald J Anthony
Date: 2026-07-02

engine.py — Tactical scoring and allocation logic for regime selection.

Owns:
    - Factor scoring via scoring.py, risk overlays, and regime selection (using MarketState)
    - Allocation construction and drift calculations
    - IFT recommendation logic for state persistence and order execution

Public Functions (unchanged external API):
    • build_engine_result(market_data: dict, override_active: bool, override_regime: str, previous_regime: Optional[str]) -> EngineResult
    • cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float
    • latest_regime_from_history(recent_regimes: List[str]) -> Optional[str]
    • should_use_tsp_ift(**kwargs) -> Tuple[bool, str]
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD
from market_state import build_market_state  # MarketState factory; interprets raw indicators.
from models import EngineResult, FundsAlloc, Scores
from scoring import score_all_factors, composite_score
from utils import safe_float

# Configure logging to capture debugging information and decision flow.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _regime_alloc(name: str) -> FundsAlloc:
    """
    Return a fresh copy of the regime allocation from the baseline constants.
    """
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """
    Calculate the maximum absolute drift (in percentage points) for any single fund.
    """
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """
    Calculate the cumulative allocation drift between the current and target allocations.
    Computed as half the L1 distance between the two allocation vectors.
    """
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )
    return total_abs_diff / 2.0


def determine_allocation(
    data: Dict[str, Any],
    previous_regime: Optional[str] = None,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
) -> Tuple[FundsAlloc, Dict[str, float], int, str, FundsAlloc, bool, bool]:
    """
    Determine the regime and corresponding allocation based on market data and override settings.
    Returns a tuple containing:
        - target allocation (FundsAlloc)
        - factor scores (dict[str, float])
        - composite score (int)
        - regime name (str)
        - baseline allocation (FundsAlloc)
        - asymmetric volatility trigger (bool)
        - DXY strength trigger (bool)
    """
    # If manual override is active, return the forced regime allocation immediately.
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
        # Any other value assumes emergency dispatch.
        base_alloc = _regime_alloc("EMERGENCY DISPATCH")
        return base_alloc, {}, -50, "EMERGENCY DISPATCH", base_alloc, False, False

    # Compute continuous factor scores via scoring functions.
    scores: Scores = score_all_factors(data)
    comp_score: int = int(round(composite_score(scores)))
    logger.info("Composite score computed: %d", comp_score)

    # Extract core macro indicators using safe conversion.
    pce: float = safe_float(data.get("core_pce_yoy"), DEFAULTS.get("core_pce_yoy", 2.0))
    cape: float = safe_float(data.get("shiller_cape"), DEFAULTS.get("shiller_cape", 25.0))

    # Build market state from raw data.
    market_state = build_market_state(data, pce, cape)
    # Use the 'dxy' field of market_state to decide the regime.
    regime_name: str = market_state.dxy
    logger.info("Market state returned regime (%s)", regime_name)

    # Ensure regime_name is a valid key in BASELINE_ALLOCATIONS.
    # If not, default to "OPTIMIZED NEUTRAL".
    if regime_name not in BASELINE_ALLOCATIONS:
        logger.warning("Regime '%s' not recognized. Defaulting to OPTIMIZED NEUTRAL.", regime_name)
        regime_name = "OPTIMIZED NEUTRAL"

    base_alloc: FundsAlloc = _regime_alloc(regime_name)

    # Determine risk trigger flags.
    vol_trigger: bool = False  # Placeholder for asymmetric volatility logic.
    dxy_trigger: bool = (data.get("dxy_spot", 0) >= DXY_TILT_THRESHOLD)

    # For now, final allocation is the baseline.
    allocs: FundsAlloc = base_alloc

    return (
        allocs,
        scores,
        comp_score,
        regime_name,
        base_alloc,
        vol_trigger,
        dxy_trigger,
    )


def build_engine_result(
    market_data: Dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: Optional[str] = None,
) -> EngineResult:
    """
    Build the engine result from market data by calling determine_allocation.
    Returns an EngineResult instance with the following attributes:
        - allocations
        - scores
        - composite_score
        - regime
        - base_alloc (baseline allocation)
        - asymmetric_vol_trigger (flag from determine_allocation)
        - dxy_strong (flag from determine_allocation)
        - emergency_triggered (True if regime is 'EMERGENCY DISPATCH', else False)
    """
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
    """
    Return the most recent regime from the history list.
    If the history is empty, return None.
    """
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
    Decide whether to submit an IFT (Inter-Fund Transfer) order based on multiple criteria.
    Returns a tuple (use_ift: bool, reason: str).
    
    This simple implementation compares the cumulative allocation drift against a threshold.
    You may extend this logic with additional risk controls.
    """
    drift = cumulative_alloc_drift(current_alloc, target_alloc)
    reason = f"Cumulative drift is {drift:.2f}% (threshold: {normal_drift_threshold_pct:.2f}%)."
    if drift >= normal_drift_threshold_pct:
        return True, f"Drift exceeds threshold. {reason}"
    else:
        return False, f"Drift below threshold. {reason}"
