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

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD, FACTOR_WEIGHTS, THRESHOLDS
from market_state import MarketState, market_state_from_data
from models import EngineResult, FundsAlloc, Scores
from utils import safe_float


def _regime_alloc(name: str) -> FundsAlloc:
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)
    return total_abs_diff / 2.0


def _normalize_score(x: float) -> int:
    return int(round(max(0.0, min(100.0, x))))


def _factor_scores_from_state(state: MarketState, data: dict[str, Any]) -> Scores:
    scores: Scores = {}
    scores["growth"] = 100 if state.growth == "expanding" else 50 if state.growth == "steady" else 0
    scores["liquidity"] = 100 if state.liquidity == "loose" else 50 if state.liquidity == "neutral" else 0
    scores["credit"] = 100 if state.credit == "healthy" else 50 if state.credit == "stressed" else 0
    scores["stress"] = 100 if state.stress == "normal" else 0
    scores["inflation"] = 100 if state.inflation in {"cooling", "stable"} else 50 if state.inflation == "rising" else 0
    scores["momentum"] = 100 if state.trend == "bullish" else 50 if state.trend == "neutral" else 0
    scores["valuation"] = 100 if state.valuation == "cheap" else 50 if state.valuation == "fair" else 0
    scores["drawdown"] = 100 if state.drawdown == "contained" else 0
    return scores


def score_market_data(data: dict[str, Any]) -> Scores:
    state = market_state_from_data(data)
    return _factor_scores_from_state(state, data)


def _weighted_composite(scores: Scores) -> int:
    total_weight = sum(FACTOR_WEIGHTS.values())
    weighted = sum(float(scores.get(k, 50)) * FACTOR_WEIGHTS[k] for k in FACTOR_WEIGHTS) / total_weight
    return _normalize_score(weighted)


def determine_allocation(
    data: dict[str, Any],
    scores: Scores,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> tuple[FundsAlloc, Scores, int, str, FundsAlloc, bool, bool]:
    state = market_state_from_data(data)
    composite_score = _weighted_composite(scores)

    vix_spot = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    dxy_spot = safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"])
    dxy_trend_up = bool(data.get("dxy_trend_up", False))
    bond_yield_10y = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
    core_pce_yoy = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)
    market_breadth = safe_float(data.get("market_breadth_pct"), DEFAULTS["market_breadth_pct"])
    vix_3d_panic = bool(data.get("vix_3d_panic", False))
    spx_3d_panic = bool(data.get("spx_3d_panic", False))

    asymmetric_vol_trigger = vix_spot > 22.0 and move_index >= 105.0
    dxy_strong = dxy_spot >= DXY_TILT_THRESHOLD and dxy_trend_up
    panic_valve_triggered = (vix_3d_panic or spx_3d_panic) and market_breadth <= 60.0

    if panic_valve_triggered:
        regime_name = "EMERGENCY DISPATCH"
        base_alloc = _regime_alloc(regime_name)
        return dict(base_alloc), scores, 0, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    if override_active:
        regime_name = override_regime if override_regime in BASELINE_ALLOCATIONS else "OPTIMIZED NEUTRAL"
        base_alloc = _regime_alloc(regime_name)
        return dict(base_alloc), scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    macro_defensive_trigger = (
        treasury_10y_3m_spread < THRESHOLDS["curve_deep_inverted"]
        or (central_bank_stance <= THRESHOLDS["policy_aggressive"] and liquidity_pressure >= 4.0)
        or (treasury_10y_3m_spread < THRESHOLDS["curve_inverted"] and state.policy == "restrictive")
    )

    if macro_defensive_trigger:
        regime_name = "DEFENSIVE ALLOCATION"
    elif state.growth == "expanding" and state.policy != "restrictive" and composite_score >= 65 and core_pce_yoy < 2.5:
        regime_name = "RISK-ON OVERRIDE"
    elif composite_score >= 50 and state.stress == "normal" and state.liquidity != "tight":
        regime_name = "OPTIMIZED NEUTRAL"
    else:
        regime_name = "DEFENSIVE ALLOCATION"

    if previous_regime == "RISK-ON OVERRIDE" and regime_name == "OPTIMIZED NEUTRAL" and composite_score >= 60:
        regime_name = "RISK-ON OVERRIDE"
    if previous_regime == "OPTIMIZED NEUTRAL" and regime_name == "DEFENSIVE ALLOCATION" and composite_score >= 45:
        regime_name = "OPTIMIZED NEUTRAL"

    base_alloc = _regime_alloc(regime_name)
    alloc = dict(base_alloc)

    if asymmetric_vol_trigger:
        trim = min(alloc.get("S", 0.0), 10.0)
        alloc["S"] -= trim
        alloc["G"] += trim

    if dxy_strong and regime_name in {"RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL"}:
        shift = min(alloc.get("I", 0.0), 5.0)
        alloc["I"] -= shift
        alloc["C"] += shift

    if state.stress == "high" or state.policy == "restrictive":
        total_trim = min(alloc.get("C", 0.0) + alloc.get("S", 0.0), 15.0)
        c_trim = min(alloc.get("C", 0.0), total_trim / 2.0)
        s_trim = min(alloc.get("S", 0.0), total_trim - c_trim)
        alloc["C"] -= c_trim
        alloc["S"] -= s_trim
        alloc["G"] += c_trim + s_trim

    total = sum(alloc.values()) or 100.0
    final_alloc = {k: round(v / total * 100.0, 1) for k, v in alloc.items()}
    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def latest_regime_from_history(recent_regimes: list[str] | None) -> str | None:
    return recent_regimes[-1] if recent_regimes else None


def build_engine_result(
    data: dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> EngineResult:
    scores = score_market_data(data)
    allocations, scores, composite_score, regime_name, base_alloc, vol_trigger, dxy_trigger = determine_allocation(
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

    cum_drift = cumulative_alloc_drift(current_alloc, target_alloc)
    if cum_drift < normal_drift_threshold_pct:
        return False, f"Cumulative portfolio drift too small ({cum_drift:.1f}% vs {normal_drift_threshold_pct}%)"

    score_change = abs(recent_scores[-1] - recent_scores[-confirmation_days - 1])
    if score_change < score_change_threshold:
        return False, f"Score change not strong enough ({score_change} vs {score_change_threshold})"

    return True, f"Confirmed regime shift with {cum_drift:.1f}% cumulative drift"


__all__ = [
    "BASELINE_ALLOCATIONS",
    "_regime_alloc",
    "max_alloc_drift",
    "cumulative_alloc_drift",
    "score_market_data",
    "determine_allocation",
    "latest_regime_from_history",
    "build_engine_result",
    "should_use_tsp_ift",
]
