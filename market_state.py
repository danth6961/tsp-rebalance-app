"""
Author: Donald J Anthony
Date: Today's Date

market_state.py — Interpret raw market indicators into categorical market states.

This module provides the abstraction of MarketState, a structured output that translates
raw numerical and boolean market data into qualitative market conditions used for tactical
allocation. Enhanced inline documentation and type hints ensure clarity and avoidance of
common pitfalls like look-ahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from constants import DXY_TILT_THRESHOLD
from models import MarketState
from utils import safe_float


def build_market_state(data: Dict[str, Any], pce: float, cape: float) -> MarketState:
    """
    Build a MarketState object from raw market data and pre-computed scores.
    
    This function interprets various market indicators such as volatility (panic),
    economic growth, policy stance, and technical metrics into categorical states.
    
    Parameters
    ----------
    data : Dict[str, Any]
        Raw market and macroeconomic data.
    pce : float
        Core PCE YoY value.
    cape : float
        Shiller CAPE value.
    
    Returns
    -------
    MarketState
        A dataclass instance capturing the qualitative market state, including flags
        for panic, asymmetric volatility, and DXY strength.
    
    Notes
    -----
    The categorical labels (for instance, for inflation, growth, liquidity, etc.) are derived from
    thresholds that help to prevent transient changes from driving frequent state changes.
    """
    # Determine panic condition by combining short-term volatility flags and market breadth.
    vix_3d_panic: bool = bool(data.get("vix_3d_panic", False))
    spx_3d_panic: bool = bool(data.get("spx_3d_panic", False))
    market_breadth: float = safe_float(data.get("market_breadth_pct"), 100.0)
    panic: bool = (vix_3d_panic or spx_3d_panic) and (market_breadth <= 60.0)
    
    # Calculate asymmetric volatility based on pre-computed scores.
    # Expected that the scores dictionary contains values for market_stress and momentum.
    scores: Dict[str, float] = data.get("scores", {})
    asymmetric_vol: bool = (scores.get("market_stress", 0) <= -3) or (scores.get("momentum", 0) <= -3)
    
    # Technical unlock flag: indicates if an alternative allocation logic could trigger using bonds.
    bond_yield: float = safe_float(data.get("bond_yield_10y"), 0.0)
    move_index: float = safe_float(data.get("move_index"), 0.0)
    f_unlock: bool = (bond_yield - pce) >= 1.5 and (move_index < 120.0)
    
    # Determine DXY strength trigger based on the current DXY value and its trend.
    dxy_spot: float = safe_float(data.get("dxy_spot"), 0.0)
    dxy_trend_up: bool = bool(data.get("dxy_trend_up", False))
    dxy_strong: bool = dxy_spot >= DXY_TILT_THRESHOLD and dxy_trend_up

    # Classify the yield curve based on the 10Y-3M spread.
    treasury_10y_3m_spread: float = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    if treasury_10y_3m_spread < -0.5:
        curve: str = "deeply_inverted"
    elif treasury_10y_3m_spread < 0.0:
        curve = "inverted"
    else:
        curve = "normal"

    # Categorize the central bank policy stance.
    central_bank_stance: float = safe_float(data.get("central_bank_stance"), 0.0)
    if central_bank_stance <= -3.0:
        policy: str = "aggressive"
    elif central_bank_stance <= -2.0:
        policy = "restrictive"
    else:
        policy = "neutral"

    # Define liquidity based on liquidity pressure.
    liquidity_pressure: float = safe_float(data.get("liquidity_pressure"), 0.0)
    if liquidity_pressure >= 4.0:
        liquidity: str = "very_tight"
    elif liquidity_pressure >= 3.0:
        liquidity = "tight"
    else:
        liquidity = "normal"

    # Categorize the inflation regime.
    inflation_shock: float = safe_float(data.get("inflation_shock"), 0.0)
    if inflation_shock > 0.2:
        inflation: str = "shocked"
    elif pce > 2.3:
        inflation = "hot"
    else:
        inflation = "cooling"

    # Interpret growth based on the growth score.
    growth_score: float = scores.get("growth", 0)
    if growth_score >= 1:
        growth: str = "expanding"
    elif growth_score <= -3:
        growth = "contracting"
    else:
        growth = "mixed"

    # Determine overall market stress.
    stress_score: float = scores.get("market_stress", 0)
    stress: str = "elevated" if stress_score <= -3 else "normal"

    # Assess momentum in the market.
    momentum_score: float = scores.get("momentum", 0)
    if momentum_score >= 1:
        trend: str = "bullish"
    elif momentum_score <= -3:
        trend = "bearish"
    else:
        trend = "neutral"

    # Evaluate credit conditions.
    credit_score: float = scores.get("credit_spreads", 0)
    credit: str = "tight" if credit_score <= -3 else "normal"
    
    # Assess valuation conditions.
    valuation_score: float = scores.get("valuation", 0)
    valuation: str = "expensive" if valuation_score <= -3 else "fair"

    # Build and return the MarketState dataclass instance.
    return MarketState(
        inflation=inflation,
        growth=growth,
        liquidity=liquidity,
        credit=credit,
        stress=stress,
        trend=trend,
        policy=policy,
        valuation=valuation,
        dxy="strong" if dxy_strong else "normal",
        curve=curve,
        panic=panic,
        asymmetric_vol=asymmetric_vol,
        f_unlock=f_unlock,
        dxy_strong=dxy_strong,
    )
