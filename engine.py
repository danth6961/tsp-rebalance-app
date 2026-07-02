"""
Author: Donald J Anthony
Date: Today's Date

engine.py — Tactical scoring and allocation logic for regime selection.

Owns:
    - Factor scoring via scoring.py, risk overlays, and regime selection (using MarketState)
    - Allocation construction and drift calculations
    - IFT recommendation logic for state persistence and order execution
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Tuple

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

    Parameters
    ----------
    name : str
        Regime name whose allocation is to be retrieved.

    Returns
    -------
    FundsAlloc
        Dictionary representing fund allocations.
    """
    # Create a copy of the allocation defined in the constants.
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """
    Calculate the maximum absolute drift (in percentage points) for any single fund.

    Parameters
    ----------
    current_alloc : FundsAlloc
        The current fund allocation.
    target_alloc : FundsAlloc
        The target fund allocation.

    Returns
    -------
    float
        Maximum per-fund drift.
    """
    # Use the union of all funds in both dictionaries.
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    # Compute the absolute difference for each fund and return the maximum.
    return max(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """
    Calculate the cumulative allocation drift between the current and target allocations.

    This is computed as half the L1 distance between the two allocation vectors.

    Parameters
    ----------
    current_alloc : FundsAlloc
        Current allocation dictionary.
    target_alloc : FundsAlloc
        Target allocation dictionary.

    Returns
    -------
    float
        The cumulative drift value.
    """
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )
    return total_abs_diff / 2.0


def determine_allocation(
    data: Dict[str, Any],
    previous_regime: str | None = None,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
) -> Tuple[FundsAlloc, Dict[str, float], int, str, FundsAlloc, bool, bool]:
    """
    Determine the regime and corresponding allocation based on market data and override settings.

    This function first checks for manual override. If an override is active, it simply returns
    the pre-defined allocation for the override regime. Otherwise, it computes continuous factor
    scores using external scoring functions and derives a composite score. Then, it builds a
    market state from raw macro indicators and selects a regime based on that state. Finally, it
    returns the target allocation along with additional decision metrics.

    Parameters
    ----------
    data : Dict[str, Any]
        Market and macro snapshot data.
    previous_regime : str | None, optional
        Previously active regime (if any), by default None.
    override_active : bool, optional
        Flag to activate manual override, by default False.
    override_regime : str, optional
        Regime to force if override is active, by default "OPTIMIZED NEUTRAL".

    Returns
    -------
    Tuple[FundsAlloc, Dict[str, float], int, str, FundsAlloc, bool, bool]
        A tuple containing:
          - final target allocation (FundsAlloc)
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
        # For any other value assume emergency dispatch.
        base_alloc = _regime_alloc("EMERGENCY DISPATCH")
        return base_alloc, {}, -50, "EMERGENCY DISPATCH", base_alloc, False, False

    # Compute continuous factor scores from market data.
    scores: Scores = score_all_factors(data)
    comp_score: int = int(round(composite_score(scores)))
    logger.info("Composite score computed: %d", comp_score)

    # Extract core macro indicators using safe conversion with fallback defaults.
    pce: float = safe_float(
        data.get("core_pce_yoy"),
        DEFAULTS.get("core_pce_yoy", 2.0)
    )
    cape: float = safe_float(
        data.get("shiller_cape"),
        DEFAULTS.get("shiller_cape", 25.0)
    )
    # TODO: Process additional macro overlays and financial metrics as needed.

    # Build market state – this helper returns an object with categorized market conditions.
    market_state = build_market_state(data, pce, cape)
    # As an example, we use the 'dxy' field of the market state to determine the regime.
    regime_name: str = market_state.dxy  # This can be updated to a more nuanced regime selection logic.
    logger.info("Determined regime: %s", regime_name)

    # Retrieve the baseline allocation for the determined regime.
    base_alloc: FundsAlloc = _regime_alloc(regime_name)

    # Determine risk trigger flags.
    vol_trigger: bool = False  # Placeholder for asymmetric volatility logic; update if implemented.
    dxy_trigger: bool = (data.get("dxy_spot", 0) >= DXY_TILT_THRESHOLD)
    
    # In this simple implementation, the final target allocation is the baseline.
    allocs: FundsAlloc = base_alloc

    # Return a tuple of the target allocation, detailed factor scores, composite score,
    # regime name, baseline allocation, volatility trigger flag, and DXY trigger flag.
    return (
        allocs,
        scores,
        comp_score,
        regime_name,
        base_alloc,
        vol_trigger,
        dxy_trigger,
    )
