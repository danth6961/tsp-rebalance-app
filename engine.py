"""
engine.py — Tactical scoring and allocation logic for regime selection.

Owns:
- Factor scoring via scoring.py, risk overlays, and regime selection (using MarketState)
- Allocation construction and drift calculations
- IFT recommendation logic for state persistence and order execution
"""

from __future__ import annotations
from datetime import date
from typing import Any, Dict, Tuple

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD
from market_state import build_market_state  # MarketState factory
from models import EngineResult, FundsAlloc, Scores
from scoring import score_all_factors, composite_score
from utils import safe_float
import logging

# Configure logging to capture debugging and decision flow.
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
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
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
    
    This function first checks for manual override. If no override applies, it calculates
    continuous factor scores and computes a composite score. The regime is then selected, and
    a target allocation is derived accordingly.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Market and macro snapshot data.
    previous_regime : Optional[str]
        Previously active regime (if any).
    override_active : bool
        Flag to activate manual override.
    override_regime : str
        Regime to force if override is active.
    
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
    # Check for manual override first.
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

    # Compute continuous factor scores using external scoring module.
    scores: Scores = score_all_factors(data)
    comp_score = int(round(composite_score(scores)))
    logger.info("Composite score computed: %d", comp_score)

    # Extract key market indicators safely using fallback defaults.
    pce = safe_float(
        data.get("core_pce_yoy"),
        DEFAULTS.get("core_pce_yoy", 2.0)
    )
    cape = safe_float(
        data.get("shiller_cape"),
        DEFAULTS.get("shiller_cape", 25.0)
    )
    # Additional macro overlays and financial indicators would be processed here.
    #
    # For clarity, the regime determination logic calls an external helper (build_market_state)
    # to interpret raw indicators into a categorical MarketState.
    market_state = build_market_state(data, pce, cape)
    regime_name = market_state.dxy  # Example: using dxy field to determine regime (update as needed)
    logger.info("Determined regime: %s", regime_name)

    # Retrieve baseline allocation from pre-defined constants.
    base_alloc = _regime_alloc(regime_name)

    # Risk trigger flags based on allocation drifts and market overlays.
    vol_trigger = False  # Example placeholder for asymmetric volatility logic.
    dxy_trigger = (data.get("dxy_spot", 0) >= DXY_TILT_THRESHOLD)
    
    # Final target allocation is computed (could be further refined by overlay logic).
    allocs = base_alloc

    return (
        allocs,
        scores,
        comp_score,
        regime_name,
        base_alloc,
        vol_trigger,
        dxy_trigger,
    )
