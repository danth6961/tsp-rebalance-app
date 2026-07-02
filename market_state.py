"""
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
    # Derive panic condition from short-horizon volatility metrics and market breadth.
    vix_3d_panic: bool = bool(data.get("vix_3d_panic", False))
    spx_3d_panic: bool = bool(data.get("spx_3d_panic", False))
    market_breadth = safe_float(data.get("market_breadth_pct"), 100.0)
    panic = (vix_3d_panic or spx_3d_panic) and (market_breadth <= 60.0)
    
    # Calculate asymmetric volatility or stress based on pre-computed scores.
    # It is assumed that the scoring module has already computed a value for 'market_stress' and 'momentum'
    scores = data.get("scores", {})  # Expecting a dict containing numeric scores.
    asymmetric_vol = (scores.get("market_stress", 0) <= -3) or (scores.get("momentum", 0) <= -3)
    
    # Technical unlock flag: based on bond yield against inflation and a technical move index.
    bond_yield = safe_float(data.get("bond_yield_10y"), 0.0)
    move_index = safe_float(data.get("move_index"), 0.0)
    f_unlock = (bond_yield - pce) >= 1.5 and (move_index < 120.0)
    
    # Determine DXY strength trigger based on the current foreign exchange indicator.
    dxy_spot = safe_float(data.get("dxy_spot"), 0.0)
    dxy_trend_up = bool(data.get("dxy_trend_up", False))
    dxy_strong = dxy_spot >= DXY_TILT_THRESHOLD and dxy_trend_up

    # Classify the yield curve inversion.
    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    if treasury_10y_3m_spread < -0.5:
        curve = "deeply_inverted"
    elif treasury_10y_3m_spread < 0.0:
        curve = "inverted"
    else:
        curve = "normal"

    # Determine central bank policy stance categorically.
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    if central_bank_stance <= -3.0:
        policy = "aggressive"
    elif central_bank_stance <= -2.0:
        policy = "restrictive"
    else:
        policy = "neutral"

    # Define liquidity conditions.
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)
    if liquidity_pressure >= 4.0:
        liquidity = "very_tight"
    elif liquidity_pressure >= 3.0:
        liquidity = "tight"
    else:
        liquidity = "normal"

    # Categorize inflation regime based on PCE and an auxiliary shock parameter.
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    if inflation_shock > 0.2:
        inflation = "shocked"
    elif pce > 2.3:
        inflation = "hot"
    else:
        inflation = "cooling"

    # Interpret growth using the growth score already computed.
    growth_score = scores.get("growth", 0)
    if growth_score >= 1:
        growth = "expanding"
    elif growth_score <= -3:
        growth = "contracting"
    else:
        growth = "mixed"

    # Market stress overall categorization.
    stress_score = scores.get("market_stress", 0)
    stress = "elevated" if stress_score <= -3 else "normal"

    # Momentum-based trend.
    momentum_score = scores.get("momentum", 0)
    if momentum_score >= 1:
        trend = "bullish"
    elif momentum_score <= -3:
        trend = "bearish"
    else:
        trend = "neutral"

    # Credit and valuation status (simplified for demonstration).
    credit_score = scores.get("credit_spreads", 0)
    credit = "tight" if credit_score <= -3 else "normal"
    
    valuation_score = scores.get("valuation", 0)
    valuation = "expensive" if valuation_score <= -3 else "fair"

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
