"""
scoring.py — Normalized and weighted scoring functions for portfolio allocation.

This module scores various macroeconomic and market factors using piecewise linear interpolations.
Each function uses robust type hints, clear docstrings, and inline documentation to explain financial adjustments.
"""

from typing import Any, Dict, List
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


def piecewise_linear(x: float, breakpoints: List[float], values: List[float],
                     min_val: float = None, max_val: float = None) -> float:
    """
    Perform piecewise linear interpolation on input x.

    For values lower than the first breakpoint, returns min_val (if defined) or the first value;
    for x above the last breakpoint, returns max_val (if defined) or the last value.

    Parameters
    ----------
    x : float
        Input value to be interpolated.
    breakpoints : List[float]
        A strictly increasing list of breakpoint thresholds.
    values : List[float]
        Values corresponding to each breakpoint.
    min_val : float, optional
        Minimum return value.
    max_val : float, optional
        Maximum return value.

    Returns
    -------
    float
        Interpolated value using linear segments.
    """
    if min_val is None:
        min_val = values[0]
    if max_val is None:
        max_val = values[-1]

    if x <= breakpoints[0]:
        return min_val
    if x >= breakpoints[-1]:
        return max_val

    # Identify the correct segment and interpolate linearly.
    for i in range(1, len(breakpoints)):
        if x < breakpoints[i]:
            x0, x1 = breakpoints[i - 1], breakpoints[i]
            y0, y1 = values[i - 1], values[i]
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return max_val


def cap_adjustment(value: float) -> float:
    """
    Adjust overlay value to be capped within the allowable range.

    Parameters
    ----------
    value : float
        The raw overlay adjustment value.

    Returns
    -------
    float
        The capped adjustment.
    """
    if value > OVERLAY_ADJUSTMENT_CAP:
        return OVERLAY_ADJUSTMENT_CAP
    if value < -OVERLAY_ADJUSTMENT_CAP:
        return -OVERLAY_ADJUSTMENT_CAP
    return value


def score_inflation(data: Dict[str, Any]) -> float:
    """
    Score inflation using core PCE YoY.
    
    Incorporates additional adjustments based on breakeven inflation.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Dictionary containing inflation indicators.
    
    Returns
    -------
    float
        Continuous inflation score.
    """
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    # Calculate base score via piecewise interpolation.
    base_score = piecewise_linear(pce, INFLATION_BREAKPOINTS, INFLATION_SCORES,
                                  min_val=INFLATION_SCORES[0], max_val=INFLATION_MIN_SCORE)
    
    # Adjust score based on breakeven inflation.
    breakeven = safe_float(data.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    if breakeven > 2.6:
        adjusted = min(base_score, -3.0) - 1.0
        base_score = cap_adjustment(adjusted)
    elif breakeven < 1.8:
        base_score = max(base_score, 0.0)
    return base_score


def score_growth(data: Dict[str, Any]) -> float:
    """
    Score growth using a composite PMI measure.

    Composite PMI is calculated as 0.2 * ISM_PMI + 0.8 * services_PMI,
    and then adjusted based on initial jobless claims.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Market data containing PMI and initial claims.
    
    Returns
    -------
    float
        Growth score reflecting expansion/contraction conditions.
    """
    pmi = safe_float(data.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(data.get("services_pmi"), DEFAULTS["services_pmi"])
    composite_pmi = 0.2 * pmi + 0.8 * services_pmi
    base_score = piecewise_linear(composite_pmi, GROWTH_BREAKPOINTS, GROWTH_SCORES,
                                  min_val=GROWTH_SCORES[0], max_val=GROWTH_MAX_SCORE)
    
    initial_claims = safe_float(data.get("initial_claims"), DEFAULTS["initial_claims"])
    if initial_claims > 280.0:
        base_score = min(base_score, -3.0) - 1.0
    elif initial_claims > 250.0:
        base_score -= 1.0
    return base_score


def score_liquidity(data: Dict[str, Any]) -> float:
    """
    Score liquidity based on market and regulatory pressure indicators.

    Uses sloos_net_pct and adjusts the score based on fed assets growth.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Dictionary containing liquidity indicators.
    
    Returns
    -------
    float
        A score indicating liquidity conditions.
    """
    sloos = safe_float(data.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    base_score = piecewise_linear(sloos, LIQUIDITY_BREAKPOINTS, LIQUIDITY_SCORES,
                                  min_val=LIQUIDITY_SCORES[0], max_val=LIQUIDITY_MIN_SCORE)
    
    fed_growth = safe_float(data.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    base_score += 2.0 if fed_growth > 0.0 else -2.0
    return base_score


def score_credit_spreads(data: Dict[str, Any]) -> float:
    """
    Score credit spreads using hy_oas data.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Contains the credit spread indicator.
    
    Returns
    -------
    float
        Credit spread score.
    """
    hy_spread = safe_float(data.get("hy_oas"), DEFAULTS["hy_oas"])
    base_score = piecewise_linear(hy_spread, CREDIT_BREAKPOINTS, CREDIT_SCORES,
                                  min_val=CREDIT_SCORES[0], max_val=CREDIT_MIN_SCORE)
    return base_score


def score_valuation(data: Dict[str, Any]) -> float:
    """
    Score valuation based on Shiller CAPE with modifications from forward EPS and real yield.
    
    The function determines a dynamic ceiling based on earnings growth and adjusts the score accordingly.

    Parameters
    ----------
    data : Dict[str, Any]
        Dictionary containing valuation-related metrics.
    
    Returns
    -------
    float
        Valuation score.
    """
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    fwd_eps = safe_float(data.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"])
    real_yield = safe_float(data.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    
    # Determine the appropriate CAPE ceiling based on earnings growth.
    base_ceiling = HIGH_EPS_CAPE_CEILING if fwd_eps >= 15.0 else BASE_CAPE_CEILING
    if real_yield > REAL_YIELD_THRESHOLD:
        active_ceiling = base_ceiling - 5.0
    elif real_yield < 0.5:
        active_ceiling = base_ceiling + 3.0
    else:
        active_ceiling = base_ceiling
    
    if cape < 20.0:
        return 3.0
    elif cape <= 25.0:
        t = (cape - 20.0) / (25.0 - 20.0)
        return 3.0 * (1 - t)
    elif cape <= active_ceiling:
        t = (cape - 25.0) / (active_ceiling - 25.0) if active_ceiling > 25.0 else 1.0
        return -3.0 * t
    else:
        return VALUATION_MIN_SCORE


def score_market_stress(data: Dict[str, Any]) -> float:
    """
    Score market stress based on spot VIX levels.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Must include 'vix_spot' as an indicator.
    
    Returns
    -------
    float
        Stress score adjusted via piecewise interpolation.
    """
    vix = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    base_score = piecewise_linear(vix, STRESS_BREAKPOINTS, STRESS_SCORES,
                                  min_val=STRESS_SCORES[0], max_val=STRESS_MIN_SCORE)
    return base_score


def score_momentum(data: Dict[str, Any]) -> float:
    """
    Score market momentum based on the percentage distance from the 200-day SMA.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Must have a key 'pct_dist_200_sma'.
    
    Returns
    -------
    float
        Momentum score capped by predefined limits.
    """
    sma_dist = safe_float(data.get("pct_dist_200_sma"), 0.0)
    if sma_dist > MOMENTUM_BREAKPOINTS[-1]:
        return MOMENTUM_MAX_SCORE
    base_score = piecewise_linear(sma_dist, MOMENTUM_BREAKPOINTS, MOMENTUM_SCORES,
                                  min_val=MOMENTUM_SCORES[0], max_val=MOMENTUM_MAX_SCORE)
    return base_score


def score_drawdown(data: Dict[str, Any]) -> float:
    """
    Score drawdown risk based on drawdown percentage.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Must include 'drawdown_pct'.
    
    Returns
    -------
    float
        A drawdown score as an adjustment factor.
    """
    drawdown = safe_float(data.get("drawdown_pct"), 0.0)
    base_score = piecewise_linear(drawdown, DRAWDOWN_BREAKPOINTS, DRAWDOWN_SCORES,
                                  min_val=DRAWDOWN_SCORES[0], max_val=DRAWDOWN_MIN_SCORE)
    return base_score


def overlay_yield_curve(data: Dict[str, Any]) -> float:
    """
    Calculate an overlay adjustment based on the treasury 10y-3m spread.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Should include 'treasury_10y_3m_spread'.
    
    Returns
    -------
    float
        Yield curve overlay adjustment, capped at maximum size.
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


def overlay_inflation_shock(data: Dict[str, Any]) -> float:
    """
    Determine an overlay adjustment from an inflation shock indicator.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Should include 'inflation_shock'.
    
    Returns
    -------
    float
        Adjustment value that is capped by the defined limit.
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
