"""
engine.py — tactical scoring and allocation logic.

Architecture:
- market_state.py translates raw inputs into qualitative regimes
- engine.py scores the market and selects allocations
- constants.py owns thresholds, regime definitions, and baseline allocations

This module keeps the existing external API signatures stable.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from constants import (
    BASELINE_ALLOCATIONS,
    DEFAULTS,
    DXY_TILT_THRESHOLD,
    FACTOR_WEIGHTS,
    NORMALIZED_SCORE_MAX,
    REGIME_ORDER,
    THRESHOLDS,
)
from market_state import MarketState, market_state_from_data
from models import EngineResult, FundsAlloc, Scores
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
# Scoring helpers
# -----------------------------------------------------------------------------


def _normalize_score(x: float) -> int:
    return int(round(max(0.0, min(NORMALIZED_SCORE_MAX, x))))


def _score_bucket(value: float, positive: bool = True) -> float:
    """
    Convert a qualitative bucket into a normalized 0-100 score.
    Higher is better for risk assets.
    """
    if value >= 3:
        return 100.0
    if value == 2:
        return 75.0
    if value == 1:
        return 50.0
    if value == 0:
        return 25.0
    return 0.0


def _factor_score_from_state(state: MarketState) -> Scores:
    """
    Convert qualitative market state to normalized factor scores.
    All outputs are aligned to a 0-100 scale for comparability.
    """
    scores: Scores = {}

    scores["growth"] = 100 if state.growth == "expanding" else 50 if state.growth in {"steady", "neutral"} else 0
    scores["liquidity"] = 100 if state.liquidity == "loose" else 50 if state.liquidity == "neutral" else 0
    scores["credit"] = 100 if state.credit == "healthy" else 50 if state.credit == "stressed" else 0
    scores["stress"] = 100 if state.stress == "normal" else 0
    scores["inflation"] = 100 if state.inflation in {"cooling", "stable"} else 50 if state.inflation == "rising" else 0
    scores["momentum"] = 100 if state.trend == "bullish" else 50 if state.trend == "neutral" else 0
    scores["valuation"] = 100 if state.valuation == "cheap" else 50 if state.valuation == "fair" else 0
    scores["drawdown"] = 100 if state.drawdown == "contained" else 0

    return scores


def score_market_data(data: dict[str, Any]) -> Scores:
    """
    Convert a raw market snapshot into normalized factor scores.

    This function now depends on market_state.py rather than directly
    interpreting raw indicators in-line.
    """
    state = market_state_from_data(data)
    return _factor_score_from_state(state)


def _weighted_composite(scores: Scores) -> int:
    """Compute an explicit weighted composite on a 0-100 scale."""
    total_weight = sum(FACTOR_WEIGHTS.values())
    weighted = sum(float(scores.get(k, 50)) * FACTOR_WEIGHTS[k] for k in FACTOR_WEIGHTS) / total_weight
    return _normalize_score(weighted)


# -----------------------------------------------------------------------------
# Allocation and regime selection
# -----------------------------------------------------------------------------


def _apply_f_unlock(alloc: FundsAlloc, unlocked: bool) -> FundsAlloc:
    """Apply the conditional F Fund overlay to a baseline allocation."""
    alloc = dict(alloc)
    if unlocked and alloc.get("G", 0.0) >= 10.0:
        alloc["G"] -= 10.0
        alloc["F"] = alloc.get("F", 0.0) + 10.0
    return alloc


def determine_allocation(
    data: dict[str, Any],
    scores: Scores,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> tuple[FundsAlloc, Scores, int, str, FundsAlloc, bool, bool]:
    """
    Select a regime and build the target allocation.

    Returns:
        final_alloc, scores, composite_score, regime_name,
        base_alloc, asymmetric_vol_trigger, dxy_strong
    """
    state = market_state_from_data(data)
    composite_score = _weighted_composite(scores)

    # Raw overlay inputs kept here because they are operational triggers,
    # not regime semantics.
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    bond_yield = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
    dxy_spot = safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"])
    dxy_trend_up = bool(data.get("dxy_trend_up", False))
    market_breadth = safe_float(data.get("market_breadth_pct"), DEFAULTS["market_breadth_pct"])
    vix_3d_panic = bool(data.get("vix_3d_panic", False))
    spx_3d_panic = bool(data.get("spx_3d_panic", False))

    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)

    # Overlay flags
    momentum_breaker = scores.get("momentum", 0) <= 25
    asymmetric_vol_trigger = scores.get("stress", 0) == 0 or scores.get("momentum", 0) <= 25
    f_fund_unlocked = (bond_yield - pce) >= 1.5 and move_index < 120.0
    dxy_strong = dxy_spot >= DXY_TILT_THRESHOLD and dxy_trend_up
    panic_valve_triggered = (vix_3d_panic or spx_3d_panic) and market_breadth <= 60.0

    curve_inverted = treasury_10y_3m_spread < THRESHOLDS["curve_inverted"]
    curve_deeply_inverted = treasury_10y_3m_spread < THRESHOLDS["curve_deep_inverted"]
    inflation_shock_up = inflation_shock > 0.2
    policy_restrictive = central_bank_stance <= THRESHOLDS["policy_restrictive"]
    policy_aggressive = central_bank_stance <= THRESHOLDS["policy_aggressive"]
    liquidity_tight = liquidity_pressure >= 3.0
    liquidity_very_tight = liquidity_pressure >= 4.0

    # Emergency dispatch has highest priority.
    if panic_valve_triggered:
        regime_name = "EMERGENCY DISPATCH"
        composite_score = 0
        base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)
        final_alloc = dict(base_alloc)
        total = sum(final_alloc.values()) or 100.0
        final_alloc = {k: round(v / total * 100.0, 1) for k, v in final_alloc.items()}
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Macro defensive guardrail.
    macro_defensive_trigger = (
        (curve_deeply_inverted and inflation_shock_up)
        or (policy_aggressive and liquidity_very_tight)
        or (curve_inverted and policy_restrictive and liquidity_tight)
    )

    if macro_defensive_trigger:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)
        alloc = dict(base_alloc)

        if asymmetric_vol_trigger:
            s_weight = alloc["S"]
            alloc["S"] = 0.0
            alloc["G"] += s_weight

        total = sum(alloc.values()) or 100.0
        final_alloc = {k: round(v / total * 100.0, 1) for k, v in alloc.items()}
        composite_score = min(composite_score, 25)
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Manual override path.
    if override_active:
        if override_regime in BASELINE_ALLOCATIONS:
            regime_name = override_regime
        else:
            regime_name = "OPTIMIZED NEUTRAL"
        base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)
        final_alloc = dict(base_alloc)
        total = sum(final_alloc.values()) or 100.0
        final_alloc = {k: round(v / total * 100.0, 1) for k, v in final_alloc.items()}
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Default regime selection uses the abstract market state.
    candidate_regime = "DEFENSIVE ALLOCATION"

    if (
        state.growth == "expanding"
        and state.policy != "restrictive"
        and composite_score >= 65
        and not curve_inverted
        and not inflation_shock_up
        and not policy_restrictive
        and not liquidity_tight
        and not momentum_breaker
        and pce < 2.5
        and cape < 30.0
    ):
        candidate_regime = "RISK-ON OVERRIDE"
    elif (
        composite_score >= 50
        and state.stress == "normal"
        and state.liquidity != "tight"
        and not curve_deeply_inverted
        and not policy_aggressive
    ):
        candidate_regime = "OPTIMIZED NEUTRAL"

    # Hysteresis / stickiness rules.
    if previous_regime == "RISK-ON OVERRIDE" and candidate_regime == "OPTIMIZED NEUTRAL":
        if composite_score >= 60 and state.policy != "restrictive" and state.liquidity != "tight":
            candidate_regime = "RISK-ON OVERRIDE"

    if previous_regime == "OPTIMIZED NEUTRAL" and candidate_regime == "DEFENSIVE ALLOCATION":
        if composite_score >= 45 and not curve_deeply_inverted and not policy_aggressive:
            candidate_regime = "OPTIMIZED NEUTRAL"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "OPTIMIZED NEUTRAL":
        if composite_score < 55 or liquidity_tight or policy_restrictive:
            candidate_regime = "DEFENSIVE ALLOCATION"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "RISK-ON OVERRIDE":
        if composite_score < 70 or curve_inverted or inflation_shock_up or policy_restrictive or liquidity_tight:
            candidate_regime = "OPTIMIZED NEUTRAL"

    regime_name = candidate_regime
    base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)
    alloc = dict(base_alloc)

    # Valuation / stress override.
    if scores.get("valuation", 0) == 0 and safe_float(data.get("vix_spot"), 0.0) > 24.0:
        base_alloc = _apply_f_unlock(_regime_alloc("DEFENSIVE ALLOCATION"), f_fund_unlocked)
        alloc = dict(base_alloc)
        regime_name = "DEFENSIVE ALLOCATION"

    # Capped overlay adjustments.
    if asymmetric_vol_trigger:
        s_weight = min(alloc["S"], 10.0)
        alloc["S"] -= s_weight
        alloc["G"] += s_weight

    if dxy_strong and regime_name in ("RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL") and alloc.get("I", 0.0) >= 5:
        shift = min(5.0, alloc["I"])
        alloc["I"] -= shift
        alloc["C"] += shift

    if state.stress == "high" or state.policy == "restrictive":
        shift_cap = 15.0
        total_trim = min(alloc.get("C", 0.0) + alloc.get("S", 0.0), shift_cap)
        c_trim = min(alloc.get("C", 0.0), total_trim / 2.0)
        s_trim = min(alloc.get("S", 0.0), total_trim - c_trim)
        alloc["C"] -= c_trim
        alloc["S"] -= s_trim
        alloc["G"] += c_trim + s_trim

    total = sum(alloc.values()) or 100.0
    final_alloc = {k: round((v / total) * 100.0, 1) for k, v in alloc.items()}
    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def latest_regime_from_history(recent_regimes: list[str] | None) -> str | None:
    """Return the most recent regime from run history for hysteresis."""
    if not recent_regimes:
        return None
    return recent_regimes[-1]


def build_engine_result(
    data: dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> EngineResult:
    """Build the full engine result payload as a typed dataclass."""
    scores = score_market_data(data)
    (
        allocations,
        scores,
        composite_score,
        regime_name,
        base_alloc,
        vol_trigger,
        dxy_trigger,
    ) = determine_allocation(
        data,
        scores,
        override_active=override_active,
        override_regime=override_regime,
        previous_regime=previous_regime,
    )

    return EngineResult(
        allocations=allocations,
        scores=scores,
        composite_score=composite_score,
        regime=regime_name,
        base_alloc=base_alloc,
        asymmetric_vol_trigger=vol_trigger,
        dxy_strong=dxy_trigger,
        emergency_triggered=regime_name == "EMERGENCY DISPATCH",
    )


# -----------------------------------------------------------------------------
# IFT recommendation logic
# -----------------------------------------------------------------------------


def should_use_tsp_ift(
    today: date,
    current_alloc: FundsAlloc,
    target_alloc: FundsAlloc,
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
    """Evaluate the conservative IFT gate."""
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

    cum_drift = cumulative_alloc_drift(current_alloc, target_alloc)
    if cum_drift < normal_drift_threshold_pct:
        return False, f"Cumulative portfolio drift too small ({cum_drift:.1f}% vs {normal_drift_threshold_pct}%)"

    score_change = abs(recent_scores[-1] - recent_scores[-confirmation_days - 1])
    if score_change < score_change_threshold:
        return False, f"Score change not strong enough ({score_change} vs {score_change_threshold})"

    implied_regime = min(
        BASELINE_ALLOCATIONS.keys(),
        key=lambda name: max_alloc_drift(current_alloc, BASELINE_ALLOCATIONS[name]),
    )
    implied_norm = (
        "EMERGENCY DISPATCH"
        if "EMERGENCY" in implied_regime
        else "DEFENSIVE ALLOCATION"
        if "DEFENSIVE" in implied_regime
        else implied_regime
    )

    if implied_norm != current_confirmed_regime:
        return False, f"Regime not yet stable ({current_confirmed_regime} vs {implied_norm})"

    return True, f"Confirmed regime shift with {cum_drift:.1f}% cumulative drift"


__all__ = [
    "_regime_alloc",
    "max_alloc_drift",
    "cumulative_alloc_drift",
    "score_market_data",
    "determine_allocation",
    "latest_regime_from_history",
    "build_engine_result",
    "should_use_tsp_ift",
]
