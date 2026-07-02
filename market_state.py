from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from constants import DXY_TILT_THRESHOLD, DEFAULTS
from utils import safe_float


@dataclass(frozen=True)
class MarketState:
    """
    Interpreted macro state used by the tactical engine.

    This abstraction separates raw indicator inputs from allocation policy.
    The engine should reason about these categorical states instead of repeatedly
    re-evaluating raw indicators.
    """

    inflation: str
    growth: str
    liquidity: str
    credit: str
    stress: str
    trend: str
    policy: str
    valuation: str
    dxy: str
    curve: str
    panic: bool
    asymmetric_vol: bool
    f_unlock: bool
    dxy_strong: bool


def build_market_state(data: dict[str, Any], scores: dict[str, int]) -> MarketState:
    """
    Build a MarketState from raw inputs and already-computed factor scores.

    This function does not select a portfolio allocation. It only interprets
    market conditions into consistent macro labels.
    """
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    bond_yield = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
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

    curve = "deeply_inverted" if treasury_10y_3m_spread < -0.5 else (
        "inverted" if treasury_10y_3m_spread < 0.0 else "normal"
    )

    policy = "aggressive" if central_bank_stance <= -3.0 else (
        "restrictive" if central_bank_stance <= -2.0 else "neutral"
    )

    liquidity = "very_tight" if liquidity_pressure >= 4.0 else (
        "tight" if liquidity_pressure >= 3.0 else "normal"
    )

    inflation = "shocked" if inflation_shock > 0.2 else (
        "hot" if pce > 2.3 else "cooling"
    )

    growth = "expanding" if scores.get("growth", 0) >= 1 else (
        "contracting" if scores.get("growth", 0) <= -3 else "mixed"
    )

    stress = "elevated" if scores.get("market_stress", 0) <= -3 else "normal"

    trend = "bullish" if scores.get("momentum", 0) >= 1 else (
        "bearish" if scores.get("momentum", 0) <= -3 else "neutral"
    )

    credit = "tight" if scores.get("credit_spreads", 0) <= -3 else "normal"
    valuation = "expensive" if scores.get("valuation", 0) <= -3 else "fair"

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
