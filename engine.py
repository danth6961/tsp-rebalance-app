"""
engine.py — tactical scoring and allocation logic.

Owns:
- factor scoring
- regime selection
- allocation construction
- macro overlays
- IFT recommendation logic

Does not own:
- UI code
- persistence
- external data fetching
"""

from __future__ import annotations

from datetime import date
from typing import Any

from constants import (
    BASELINE_ALLOCATIONS,
    COMPOSITE_NEUTRAL,
    COMPOSITE_RISK_ON,
    DEFAULTS,
    DXY_TILT_THRESHOLD,
    FACTOR_WEIGHTS,
    NORMALIZED_SCORE_MAX,
    NORMALIZED_SCORE_MIN,
    OVERLAY_CAPS,
    REGIME_ORDER,
)
from models import EngineResult, FundsAlloc, MarketData, Scores
from utils import safe_float

# Local import to avoid changing public API surface elsewhere
from constants import THRESHOLDS
from market_state import MarketState, market_state_from_data


def _regime_alloc(name: str) -> FundsAlloc:
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0))) for fund in funds)


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0))) for fund in funds)
    return total_abs_diff / 2.0


def _normalize(x: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, x))


def _qual_score(label: str) -> float:
    mapping = {
        "very_positive": 100.0,
        "positive": 75.0,
        "neutral": 50.0,
        "negative": 25.0,
        "very_negative": 0.0,
    }
    return mapping[label]


def score_market_data(data: dict[str, Any]) -> Scores:
    state = market_state_from_data(data if isinstance(data, MarketData) else data)
    d = state.details

    pce = d["pce"]
    breakeven = d["breakeven"]
    pmi = d["pmi"]
    services_pmi = d["services_pmi"]
    claims = d["claims"]
    sloos = d["sloos"]
    fed_assets = d["fed_assets"]
    hy_oas = d["hy_oas"]
    vix = d["vix"]
    stlfsi = d["stlfsi"]
    sma_dist = d["sma_dist"]
    drawdown = d["drawdown"]
    cape = d["cape"]
    real_yield = d["real_yield"]
    curve = d["curve"]

    raw: dict[str, float] = {}

    composite_pmi = 0.2 * pmi + 0.8 * services_pmi
    raw["growth"] = 100.0 if composite_pmi >= 55 else 75.0 if composite_pmi >= 51.5 else 50.0 if composite_pmi >= 50 else 25.0 if composite_pmi >= 48 else 0.0
    if claims > 280:
        raw["growth"] = max(0.0, raw["growth"] - 20.0)
    elif claims > 250:
        raw["growth"] = max(0.0, raw["growth"] - 10.0)

    raw["liquidity"] = 100.0 if sloos < -15 else 50.0 if sloos <= 5 else 0.0
    raw["liquidity"] = _normalize(raw["liquidity"] + (20.0 if fed_assets > 0 else -20.0))

    raw["credit"] = 100.0 if hy_oas < 3 else 75.0 if hy_oas < 4 else 50.0 if hy_oas <= 5 else 25.0 if hy_oas <= 6 else 0.0
    raw["stress"] = 100.0 if vix < 12 and stlfsi < 1 else 75.0 if vix < 15 else 50.0 if vix <= 22 else 25.0 if vix <= 30 else 0.0
    raw["inflation"] = 100.0 if pce < 1.8 else 75.0 if pce < 2.0 else 50.0 if pce <= 2.3 else 25.0 if pce <= 3.0 else 0.0
    if breakeven > 2.6:
        raw["inflation"] = _normalize(raw["inflation"] - 10.0)
    elif breakeven < 1.8:
        raw["inflation"] = _normalize(max(raw["inflation"], 50.0))

    raw["momentum"] = 100.0 if sma_dist > 5 else 75.0 if sma_dist >= 0 else 25.0 if sma_dist >= -5 else 0.0
    raw["valuation"] = 100.0 if cape < 20 else 50.0 if cape <= 25 else 25.0 if cape <= (35.0 if safe_float(d.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"]) >= 15.0 else 30.0) else 0.0
    raw["drawdown"] = 100.0 if drawdown < 5 else 75.0 if drawdown < 10 else 50.0 if drawdown <= 15 else 25.0 if drawdown <= 20 else 0.0

    scores: Scores = {k: int(round(_normalize(v))) for k, v in raw.items()}
    return scores


def _weighted_composite(scores: Scores) -> int:
    total_w = sum(FACTOR_WEIGHTS.values())
    weighted = sum(float(scores.get(k, 50)) * FACTOR_WEIGHTS[k] for k in FACTOR_WEIGHTS) / total_w
    return int(round(_normalize(weighted)))


def determine_allocation(
    data: dict[str, Any],
    scores: Scores,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> tuple[FundsAlloc, Scores, int, str, FundsAlloc, bool, bool]:
    state = market_state_from_data(data if isinstance(data, MarketData) else data)
    composite_score = _weighted_composite(scores)

    panic_valve_triggered = bool(
        safe_float(data.get("vix_spot"), 0.0) > 30.0
        or bool(data.get("vix_3d_panic", False))
        or bool(data.get("spx_3d_panic", False))
    )
    asymmetric_vol_trigger = bool(safe_float(data.get("move_index"), 0.0) > 105.0 and safe_float(data.get("vix_spot"), 0.0) > 22.0)
    dxy_strong = bool(safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"]) >= DXY_TILT_THRESHOLD and bool(data.get("dxy_trend_up", False)))

    if override_active:
        regime_name = override_regime if override_regime in BASELINE_ALLOCATIONS else "OPTIMIZED NEUTRAL"
    elif panic_valve_triggered:
        regime_name = "EMERGENCY DISPATCH"
    elif state.growth == "expanding" and state.policy != "restrictive" and composite_score >= COMPOSITE_RISK_ON:
        regime_name = "RISK-ON OVERRIDE"
    elif composite_score >= COMPOSITE_NEUTRAL and state.stress == "normal" and state.liquidity == "loose":
        regime_name = "OPTIMIZED NEUTRAL"
    else:
        regime_name = "DEFENSIVE ALLOCATION"

    base_alloc = _regime_alloc(regime_name)

    if asymmetric_vol_trigger:
        trim = min(base_alloc.get("S", 0.0), OVERLAY_CAPS["asymmetric_vol_max_shift_pct"])
        base_alloc["S"] -= trim
        base_alloc["G"] += trim

    if dxy_strong and regime_name in ("RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL"):
        shift = min(base_alloc.get("I", 0.0), OVERLAY_CAPS["dxy_max_shift_pct"])
        base_alloc["I"] -= shift
        base_alloc["C"] += shift

    if state.stress == "high" or state.policy == "restrictive":
        shift = min(base_alloc.get("C", 0.0) + base_alloc.get("S", 0.0), OVERLAY_CAPS["macro_defensive_max_shift_pct"])
        c_trim = min(base_alloc.get("C", 0.0), shift / 2.0)
        s_trim = min(base_alloc.get("S", 0.0), shift - c_trim)
        base_alloc["C"] -= c_trim
        base_alloc["S"] -= s_trim
        base_alloc["G"] += c_trim + s_trim

    total = sum(base_alloc.values()) or 100.0
    final_alloc = {k: round(v / total * 100.0, 1) for k, v in base_alloc.items()}
    return final_alloc, scores, composite_score, regime_name, dict(base_alloc), asymmetric_vol_trigger, dxy_strong


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
