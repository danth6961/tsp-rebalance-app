"""
engine.py — tactical scoring and allocation logic.

Owns:
- factor scoring via scoring.py (from continuous scores)
- regime selection (now leveraging MarketState)
- allocation construction
- macro overlays
- IFT recommendation logic
"""

from __future__ import annotations

from datetime import date
from typing import Any

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD
from market_state import build_market_state
from models import EngineResult, FundsAlloc
from scoring import score_all_factors, composite_score
from utils import safe_float


# -----------------------------------------------------------------------------
# Allocation helpers
# -----------------------------------------------------------------------------

def _regime_alloc(name: str) -> FundsAlloc:
    """Return a fresh copy of a regime allocation from constants.py."""
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """Return the maximum per-fund absolute drift in percentage points."""
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """Return half the L1 distance between two allocations."""
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )
    return total_abs_diff / 2.0


# -----------------------------------------------------------------------------
# Allocation and regime selection
# -----------------------------------------------------------------------------

def determine_allocation(
    data: dict[str, Any],
    previous_regime: str | None = None,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
) -> tuple[FundsAlloc, dict[str, float], float, str, FundsAlloc, bool, bool]:
    """
    Select a regime and build the target allocation.
    Returns:
        (final_alloc, scores, composite_score, regime_name,
         base_alloc, asymmetric_vol_trigger, dxy_strong)
    """
    # Check for override
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

    # Compute continuous factor scores
    scores = score_all_factors(data)
    comp_score = composite_score(scores)

    # For some overlays and regime logic, also extract raw values.
    pce = safe_float(data.get("core_pce_yoy"),  DEFAULTS["core_pce_yoy"] if "core_pce_yoy" in DEFAULTS else 2.0)
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"] if "shiller_cape" in DEFAULTS else 25.0)

    # Build market state using MarketState abstraction.
    market = build_market_state(data, scores)

    momentum_breaker = scores.get("momentum", 0.0) <= -3.0
    asymmetric_vol_trigger = market.asymmetric_vol
    f_fund_unlocked = market.f_unlock
    dxy_strong = market.dxy_strong

    curve_inverted = market.curve in ("inverted", "deeply_inverted")
    curve_deeply_inverted = market.curve == "deeply_inverted"
    inflation_shock_up = market.inflation == "shocked"
    policy_restrictive = market.policy == "restrictive"
    policy_aggressive = market.policy == "aggressive"
    liquidity_tight = market.liquidity in ("tight", "very_tight")
    liquidity_very_tight = market.liquidity == "very_tight"

    # Emergency dispatch has highest priority.
    if market.panic:
        regime_name = "EMERGENCY DISPATCH"
        comp_score = -50
        base_alloc = _regime_alloc(regime_name)
        base_alloc = _apply_f_unlock(base_alloc, f_fund_unlocked)
        final_alloc = normalize_allocation(base_alloc)
        return final_alloc, scores, comp_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Macro defensive trigger.
    macro_defensive_trigger = (
        (curve_deeply_inverted and inflation_shock_up)
        or (policy_aggressive and liquidity_very_tight)
        or (curve_inverted and policy_restrictive and liquidity_tight)
    )
    if macro_defensive_trigger:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = _regime_alloc(regime_name)
        base_alloc = _apply_f_unlock(base_alloc, f_fund_unlocked)
        # If asymmetric volatility is triggered, reallocate S to G.
        if asymmetric_vol_trigger:
            s_weight = base_alloc.get("S", 0.0)
            base_alloc["S"] = 0.0
            base_alloc["G"] += s_weight
        final_alloc = normalize_allocation(base_alloc)
        comp_score = min(comp_score, -5)
        return final_alloc, scores, comp_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Default regime selection logic.
    candidate_regime = "DEFENSIVE ALLOCATION"
    if (
        comp_score >= 7.0
        and pce < 2.0
        and cape < 26.0
        and not momentum_breaker
        and not curve_inverted
        and not inflation_shock_up
        and not policy_restrictive
        and not liquidity_tight
    ):
        candidate_regime = "RISK-ON OVERRIDE"
    elif comp_score >= 0 and not curve_deeply_inverted and not policy_aggressive:
        candidate_regime = "OPTIMIZED NEUTRAL"

    # Hysteresis rules.
    if previous_regime == "RISK-ON OVERRIDE" and candidate_regime == "OPTIMIZED NEUTRAL":
        if comp_score >= 4 and not curve_inverted and not policy_restrictive and not liquidity_tight:
            candidate_regime = "RISK-ON OVERRIDE"

    if previous_regime == "OPTIMIZED NEUTRAL" and candidate_regime == "DEFENSIVE ALLOCATION":
        if comp_score >= -1 and not curve_deeply_inverted and not policy_aggressive:
            candidate_regime = "OPTIMIZED NEUTRAL"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "OPTIMIZED NEUTRAL":
        if comp_score < 3 or liquidity_tight or policy_restrictive:
            candidate_regime = "DEFENSIVE ALLOCATION"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "RISK-ON OVERRIDE":
        if comp_score < 9 or curve_inverted or inflation_shock_up or policy_restrictive or liquidity_tight:
            candidate_regime = "OPTIMIZED NEUTRAL"

    regime_name = candidate_regime

    if regime_name == "RISK-ON OVERRIDE":
        base_alloc = _regime_alloc("RISK-ON OVERRIDE")
    elif regime_name == "OPTIMIZED NEUTRAL":
        base_alloc = _regime_alloc("OPTIMIZED NEUTRAL")
    else:
        base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")

    # Valuation / stress override.
    if scores.get("valuation", 0.0) == -5 and safe_float(data.get("vix_spot"), 0.0) > 24.0:
        base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")
        regime_name = "DEFENSIVE ALLOCATION"

    base_alloc = _apply_f_unlock(base_alloc, f_fund_unlocked)

    # Asymmetric volatility adjustment.
    if asymmetric_vol_trigger:
        s_weight = base_alloc.get("S", 0.0)
        base_alloc["S"] = 0.0
        base_alloc["G"] += s_weight

    # Strong DXY tilt reduces international exposure.
    if dxy_strong and regime_name in ("RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL") and base_alloc.get("I", 0.0) >= 5:
        base_alloc["I"] -= 5
        base_alloc["C"] += 5

    final_alloc = normalize_allocation(base_alloc)
    return final_alloc, scores, comp_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def _apply_f_unlock(alloc: dict[str, float], unlocked: bool) -> dict[str, float]:
    """
    Apply the F Fund overlay to a baseline allocation if conditions are met.
    """
    alloc = dict(alloc)
    if unlocked and alloc.get("G", 0.0) >= 10.0:
        alloc["G"] -= 10.0
        alloc["F"] = alloc.get("F", 0.0) + 10.0
    return alloc


def normalize_allocation(alloc: dict[str, float]) -> dict[str, float]:
    """
    Normalize allocation so that fund percentages sum to 100.
    """
    total = sum(alloc.values()) or 100.0
    return {k: round((v / total) * 100.0, 1) for k, v in alloc.items()}


def latest_regime_from_history(recent_regimes: list[str] | None) -> str | None:
    """Return the most recent regime from run history (for hysteresis)."""
    if not recent_regimes:
        return None
    return recent_regimes[-1]


def build_engine_result(
    data: dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> EngineResult:
    """
    Build the full engine result as a typed dataclass.
    """
    allocs, scores, comp_score, regime_name, base_alloc, vol_trigger, dxy_trigger = determine_allocation(
        data,
        previous_regime=previous_regime,
        override_active=override_active,
        override_regime=override_regime,
    )

    from models import EngineResult  # Local import to avoid circular dependency
    return EngineResult(
        allocations=allocs,
        scores=scores,
        composite_score=comp_score,
        regime=regime_name,
        base_alloc=base_alloc,
        asymmetric_vol_trigger=vol_trigger,
        dxy_strong=dxy_trigger,
        emergency_triggered=(regime_name == "EMERGENCY DISPATCH"),
    )


# -----------------------------------------------------------------------------
# IFT recommendation logic (unchanged from previous logic)
# -----------------------------------------------------------------------------

def should_use_tsp_ift(
    today: date,
    current_alloc: dict[str, float],
    target_alloc: dict[str, float],
    recent_regimes: list[str],
    recent_scores: list[int],
    emergency_triggered: bool,
    ift_count_this_month: int,
    last_ift_date: date | None,
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
    confirmation_days: int,
    cooldown_days: int,
) -> tuple[bool, str]:
    """
    Evaluate whether an IFT submission should be recommended.
    """
    if ift_count_this_month >= 2:
        return False, "No IFTs remaining this month"

    if last_ift_date is not None and (today - last_ift_date).days < cooldown_days:
        return False, f"Cooldown active ({cooldown_days} days)"

    if emergency_triggered:
        return True, "Emergency trigger activated"

    if ift_count_this_month >= 1 and not allow_second_ift:
        return False, "Preserving final IFT reserve"

    if len(recent_regimes) < confirmation_days + 1 or len(recent_scores) < confirmation_days + 1:
        return False, "Insufficient confirmation history"

    if len(set(recent_regimes[-confirmation_days:])) != 1:
        return False, "Regime not yet confirmed"

    current_confirmed_regime = recent_regimes[-1]

    drift = cumulative_alloc_drift(current_alloc, target_alloc)
    if drift < normal_drift_threshold_pct:
        return False, f"Cumulative portfolio drift too small ({drift:.1f}% vs {normal_drift_threshold_pct}%)"

    score_change = abs(recent_scores[-1] - recent_scores[-confirmation_days - 1])
    if score_change < score_change_threshold:
        return False, f"Score change not strong enough ({score_change} vs {score_change_threshold})"

    # Using baseline allocations as a proxy for regime stability:
    from constants import BASELINE_ALLOCATIONS
    implied_regime = min(
        BASELINE_ALLOCATIONS.keys(),
        key=lambda name: max_alloc_drift(current_alloc, BASELINE_ALLOCATIONS[name]),
    )
    if "EMERGENCY" in implied_regime:
        implied_norm = "EMERGENCY DISPATCH"
    elif "DEFENSIVE" in implied_regime:
        implied_norm = "DEFENSIVE ALLOCATION"
    else:
        implied_norm = implied_regime

    if implied_norm != current_confirmed_regime:
        return False, f"Regime not yet stable ({current_confirmed_regime} vs {implied_norm})"

    return True, f"Confirmed regime shift with {drift:.1f}% cumulative drift"


__all__ = [
    "_regime_alloc",
    "max_alloc_drift",
    "cumulative_alloc_drift",
    "determine_allocation",
    "latest_regime_from_history",
    "build_engine_result",
    "should_use_tsp_ift",
]
