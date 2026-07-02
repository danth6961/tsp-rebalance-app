from __future__ import annotations
from typing import Any
from constants import DXY_TILT_THRESHOLD, DEFAULTS
from models import MarketState
from utils import safe_float

def build_market_state(data: dict[str, Any], scores: dict[str, float]) -> MarketState:
    """
    Convert raw market inputs and factor scores into a categorical MarketState.
    This function interprets indicators and does not select a regime.
    """
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    bond_yield = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    dxy_spot = safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"])
    dxy_trend_up = bool(data.get("dxy_trend_up", False))
    market_breadth = safe_float(data.get("market_breadth_pct"), DEFAULTS["market_breadth_pct"])

    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)

    vix_3d_panic = bool(data.get("vix_3d_panic", False))
    spx_3d_panic = bool(data.get("spx_3d_panic", False))

    panic = (vix_3d_panic or spx_3d_panic) and market_breadth <= 60.0
    asymmetric_vol = scores.get("market_stress", 0) <= -3 or scores.get("momentum", 0) <= -3
    f_unlock = (bond_yield - pce) >= 1.5 and move_index < 120.0
    dxy_strong = dxy_spot >= DXY_TILT_THRESHOLD and dxy_trend_up

    if treasury_10y_3m_spread < -0.5:
        curve = "deeply_inverted"
    elif treasury_10y_3m_spread < 0.0:
        curve = "inverted"
    else:
        curve = "normal"

    if central_bank_stance <= -3.0:
        policy = "aggressive"
    elif central_bank_stance <= -2.0:
        policy = "restrictive"
    else:
        policy = "neutral"

    if liquidity_pressure >= 4.0:
        liquidity = "very_tight"
    elif liquidity_pressure >= 3.0:
        liquidity = "tight"
    else:
        liquidity = "normal"

    if inflation_shock > 0.2:
        inflation = "shocked"
    elif pce > 2.3:
        inflation = "hot"
    else:
        inflation = "cooling"

    growth_score = scores.get("growth", 0)
    if growth_score >= 1:
        growth = "expanding"
    elif growth_score <= -3:
        growth = "contracting"
    else:
        growth = "mixed"

    stress_score = scores.get("market_stress", 0)
    stress = "elevated" if stress_score <= -3 else "normal"

    momentum_score = scores.get("momentum", 0)
    if momentum_score >= 1:
        trend = "bullish"
    elif momentum_score <= -3:
        trend = "bearish"
    else:
        trend = "neutral"

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
