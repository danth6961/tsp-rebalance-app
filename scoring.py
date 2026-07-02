"""
scoring.py — Normalized & weighted scoring functions for portfolio allocation.

Each factor is scored using a piecewise linear interpolation based on centralized thresholds.
Overlay adjustments are applied with a cap to prevent any one adjustment from dominating.
"""

from typing import Dict, Any
from constants import (
    DEFAULTS,
    INFLATION_BREAKPOINTS, INFLATION_SCORES, INFLATION_MIN_SCORE,
    GROWTH_BREAKPOINTS, GROWTH_SCORES, GROWTH_MAX_SCORE,
    LIQUIDITY_BREAKPOINTS, LIQUIDITY_SCORES, LIQUIDITY_MIN_SCORE,
    CREDIT_BREAKPOINTS, CREDIT_SCORES, CREDIT_MIN_SCORE,
    VALUATION_BREAKPOINTS, VALUATION_MIN_SCORE, BASE_CAPE_CEILING, HIGH_EPS_CAPE_CEILING, REAL_YIELD_THRESHOLD,
    STRESS_BREAKPOINTS, STRESS_SCORES, STRESS_MIN_SCORE,
    MOMENTUM_BREAKPOINTS, MOMENTUM_SCORES, MOMENTUM_MAX_SCORE,
    DRAWDOWN_BREAKPOINTS, DRAWDOWN_SCORES, DRAWDOWN_MIN_SCORE,
    OVERLAY_ADJUSTMENT_CAP,
    FACTOR_WEIGHTS,
)
from utils import safe_float


def piecewise_linear(x: float, breakpoints: list[float], values: list[float], min_val: float = None, max_val: float = None) -> float:
    """
    Generic piecewise linear interpolation.
    x: input value
    breakpoints: increasing list of breakpoints (at which function value changes)
    values: corresponding values at those breakpoints
    For x below the first breakpoint, the function returns values[0] (unless min_val is defined).
    For x above the last breakpoint, returns values[-1] (unless max_val is defined).
    """
    if min_val is None:
        min_val = values[0]
    if max_val is None:
        max_val = values[-1]

    if x <= breakpoints[0]:
        return min_val
    if x >= breakpoints[-1]:
        return max_val

    # Find the segment containing x
    for i in range(1, len(breakpoints)):
        if x < breakpoints[i]:
            # Linear interpolation between breakpoints[i-1] and breakpoints[i]
            x0, x1 = breakpoints[i - 1], breakpoints[i]
            y0, y1 = values[i - 1], values[i]
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return max_val


def cap_adjustment(value: float) -> float:
    """Cap an overlay adjustment value by OVERLAY_ADJUSTMENT_CAP."""
    if value > OVERLAY_ADJUSTMENT_CAP:
        return OVERLAY_ADJUSTMENT_CAP
    if value < -OVERLAY_ADJUSTMENT_CAP:
        return -OVERLAY_ADJUSTMENT_CAP
    return value


# ----------------------------
# Scoring functions for core factors.
# ----------------------------

def score_inflation(data: dict[str, Any]) -> float:
    """
    Score inflation based on core PCE YoY. Then adjust based on breakeven inflation.
    Returns a continuous score.
    """
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    base_score = piecewise_linear(pce, INFLATION_BREAKPOINTS, INFLATION_SCORES, min_val=INFLATION_SCORES[0], max_val=INFLATION_MIN_SCORE)
    
    # Adjustment based on breakeven inflation
    breakeven = safe_float(data.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    if breakeven > 2.6:
        # Force score to be at least as low as -3 then subtract an extra 1 (capped)
        adjusted = min(base_score, -3.0) - 1.0
        base_score = cap_adjustment(adjusted)
    elif breakeven < 1.8:
        # Do not allow a negative score; raise to at least 0
        base_score = max(base_score, 0.0)
    
    return base_score


def score_growth(data: dict[str, Any]) -> float:
    """
    Score growth on the composite PMI = 0.2*ISM_PMI + 0.8*services_PMI,
    with adjustments for initial claims.
    """
    pmi = safe_float(data.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(data.get("services_pmi"), DEFAULTS["services_pmi"])
    composite_pmi = 0.2 * pmi + 0.8 * services_pmi
    base_score = piecewise_linear(composite_pmi, GROWTH_BREAKPOINTS, GROWTH_SCORES, min_val=GROWTH_SCORES[0], max_val=GROWTH_MAX_SCORE)
    
    # Adjustment for initial claims
    initial_claims = safe_float(data.get("initial_claims"), DEFAULTS["initial_claims"])
    if initial_claims > 280.0:
        # If claims are very high, push the score further down
        base_score = min(base_score, -3.0) - 1.0
    elif initial_claims > 250.0:
        base_score -= 1.0
    return base_score


def score_liquidity(data: dict[str, Any]) -> float:
    """
    Score liquidity based on sloos_net_pct and fed_assets_growth_yoy.
    """
    sloos = safe_float(data.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    base_score = piecewise_linear(sloos, LIQUIDITY_BREAKPOINTS, LIQUIDITY_SCORES, min_val=LIQUIDITY_SCORES[0], max_val=LIQUIDITY_MIN_SCORE)
    
    fed_growth = safe_float(data.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    if fed_growth > 0.0:
        base_score += 2.0
    else:
        base_score -= 2.0
    return base_score


def score_credit_spreads(data: dict[str, Any]) -> float:
    """
    Score credit spreads based on hy_oas.
    """
    hy_spread = safe_float(data.get("hy_oas"), DEFAULTS["hy_oas"])
    base_score = piecewise_linear(hy_spread, CREDIT_BREAKPOINTS, CREDIT_SCORES, min_val=CREDIT_SCORES[0], max_val=CREDIT_MIN_SCORE)
    return base_score


def score_valuation(data: dict[str, Any]) -> float:
    """
    Score valuation using shiller_cape with adjustments from fwd_eps and real_yield_10y.
    """
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    fwd_eps = safe_float(data.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"])
    real_yield = safe_float(data.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    
    # Set the base ceiling based on fwd_eps
    base_ceiling = HIGH_EPS_CAPE_CEILING if fwd_eps >= 15.0 else BASE_CAPE_CEILING
    # Adjust ceiling based on real yield
    if real_yield > REAL_YIELD_THRESHOLD:
        active_ceiling = base_ceiling - 5.0
    elif real_yield < 0.5:
        active_ceiling = base_ceiling + 3.0
    else:
        active_ceiling = base_ceiling
    
    # For simplicity, we use two segments: if cape < 20 then best, if between 20 and 25 then mid,
    # if between 25 and active_ceiling then falling to -3, else worst is -5.
    if cape < 20.0:
        return 3.0
    elif cape <= 25.0:
        # Linear from 3.0 to 0.0 between 20 and 25:
        t = (cape - 20.0) / (25.0 - 20.0)
        return 3.0 * (1 - t)
    elif cape <= active_ceiling:
        # From 0 to -3
        t = (cape - 25.0) / (active_ceiling - 25.0) if active_ceiling > 25.0 else 1.0
        return -3.0 * t
    else:
        return VALUATION_MIN_SCORE


def score_market_stress(data: dict[str, Any]) -> float:
    """
    Score market stress based on vix_spot.
    """
    vix = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    base_score = piecewise_linear(vix, STRESS_BREAKPOINTS, STRESS_SCORES, min_val=STRESS_SCORES[0], max_val=STRESS_MIN_SCORE)
    return base_score


def score_momentum(data: dict[str, Any]) -> float:
    """
    Score momentum based on sma_dist (percent difference from 200 SMA).
    """
    sma_dist = safe_float(data.get("pct_dist_200_sma"), 0.0)
    # If sma_dist is greater than the top breakpoint, assign maximum score.
    if sma_dist > MOMENTUM_BREAKPOINTS[-1]:
        return MOMENTUM_MAX_SCORE
    base_score = piecewise_linear(sma_dist, MOMENTUM_BREAKPOINTS, MOMENTUM_SCORES, min_val=MOMENTUM_SCORES[0], max_val=MOMENTUM_MAX_SCORE)
    return base_score


def score_drawdown(data: dict[str, Any]) -> float:
    """
    Score drawdown based on drawdown_pct.
    """
    drawdown = safe_float(data.get("drawdown_pct"), 0.0)
    base_score = piecewise_linear(drawdown, DRAWDOWN_BREAKPOINTS, DRAWDOWN_SCORES, min_val=DRAWDOWN_SCORES[0], max_val=DRAWDOWN_MIN_SCORE)
    return base_score


# ----------------------------
# Overlay adjustment functions.
# These apply extra adjustments to certain factors with a capped absolute value.
# ----------------------------

def overlay_yield_curve(data: dict[str, Any]) -> float:
    """
    Overlay based on treasury_10y_3m_spread.
    """
    spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    if spread > 1.0:
        return cap_adjustment(2.0)
    elif spread > 0.5:
        return cap_adjustment(1.0)
    elif spread >= 0.0:
        return 0.0
    elif spread >= -0.5:
        return cap_adjustment(-2.0)
    else:
        return cap_adjustment(-4.0)


def overlay_inflation_shock(data: dict[str, Any]) -> float:
    """
    Overlay adjustment from inflation_shock.
    """
    shock = safe_float(data.get("inflation_shock"), 0.0)
    if shock <= -0.2:
        return cap_adjustment(2.0)
    elif shock <= 0.0:
        return 0.0
    elif shock <= 0.2:
        return cap_adjustment(-1.0)
    elif shock <= 0.3:
        return cap_adjustment(-3.0)
    else:
        return cap_adjustment(-4.0)


def overlay_central_bank(data: dict[str, Any]) -> float:
    """
    Overlay adjustment from central_bank_stance.
    """
    stance = safe_float(data.get("central_bank_stance"), 0.0)
    if stance >= 2.0:
        return cap_adjustment(2.0)
    elif stance >= 1.0:
        return cap_adjustment(1.0)
    elif stance <= -3.0:
        return cap_adjustment(-4.0)
    elif stance <= -2.0:
        return cap_adjustment(-3.0)
    elif stance < 0.0:
        return cap_adjustment(-1.0)
    else:
        return 0.0


def overlay_liquidity_pressure(data: dict[str, Any]) -> float:
    """
    Overlay adjustment from liquidity_pressure.
    """
    pressure = safe_float(data.get("liquidity_pressure"), 0.0)
    if pressure <= 0.5:
        return cap_adjustment(1.0)
    elif pressure <= 1.5:
        return 0.0
    elif pressure <= 2.5:
        return cap_adjustment(-1.0)
    elif pressure <= 3.5:
        return cap_adjustment(-3.0)
    else:
        return cap_adjustment(-5.0)


def overlay_stlfsi(data: dict[str, Any]) -> Dict[str, float]:
    """
    Overlay from stlfsi_index. Adjusts market_stress and momentum.
    Returns a dict with adjustments for 'market_stress' and 'momentum'.
    """
    stlfsi = safe_float(data.get("stlfsi_index"), DEFAULTS["stlfsi_index"])
    adjustments = {"market_stress": 0.0, "momentum": 0.0}
    if 0.0 <= stlfsi <= 1.0:
        adjustments["market_stress"] = -1.0
        adjustments["momentum"] = -1.0
    elif 1.0 < stlfsi <= 2.0:
        adjustments["market_stress"] = -3.0
        adjustments["momentum"] = -3.0
    elif stlfsi > 2.0:
        adjustments["market_stress"] = -10.0
        adjustments["momentum"] = -10.0
    # Cap the adjustments
    adjustments["market_stress"] = cap_adjustment(adjustments["market_stress"])
    adjustments["momentum"] = cap_adjustment(adjustments["momentum"])
    return adjustments


# ----------------------------
# Main function: compute all scores.
# ----------------------------

def score_all_factors(data: dict[str, Any]) -> Dict[str, float]:
    """
    Compute the continuous score for each factor, apply overlays,
    and return a dict of all factor scores.
    """
    scores = {}
    scores["inflation"] = score_inflation(data)
    scores["growth"] = score_growth(data)
    scores["liquidity"] = score_liquidity(data)
    scores["credit_spreads"] = score_credit_spreads(data)
    scores["valuation"] = score_valuation(data)
    scores["market_stress"] = score_market_stress(data)
    scores["momentum"] = score_momentum(data)
    scores["drawdown"] = score_drawdown(data)

    # Apply overlay adjustments (only additive, with capping)
    scores["yield_curve"] = overlay_yield_curve(data)
    scores["inflation_shock"] = overlay_inflation_shock(data)
    scores["central_bank"] = overlay_central_bank(data)
    scores["liquidity_pressure"] = overlay_liquidity_pressure(data)
    stl_adjust = overlay_stlfsi(data)
    # Adjust market_stress and momentum by stlfsi overlay:
    scores["market_stress"] += stl_adjust.get("market_stress", 0.0)
    scores["momentum"] += stl_adjust.get("momentum", 0.0)
    
    # Optional: Cap final factor scores if needed (not shown here).

    return scores


def composite_score(scores: Dict[str, float]) -> float:
    """
    Calculate the weighted composite score from the individual factor scores.
    Only the primary factors are used.
    """
    comp = 0.0
    for factor, weight in FACTOR_WEIGHTS.items():
        comp += scores.get(factor, 0.0) * weight
    return comp
