from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from constants import DEFAULTS, THRESHOLDS
from models import MarketData
from utils import safe_float


@dataclass(frozen=True)
class MarketState:
    """
    Qualitative abstraction of a raw market snapshot.

    Engine logic should reason over these regimes rather than raw indicators.
    """
    inflation: str
    growth: str
    liquidity: str
    credit: str
    stress: str
    trend: str
    policy: str
    valuation: str
    drawdown: str
    dxy: str
    details: dict[str, float] = field(default_factory=dict)


def _get_payload(data: MarketData | dict[str, Any]) -> dict[str, Any]:
    return data.__dict__ if isinstance(data, MarketData) else data


def _bucket(value: float, rules: list[tuple[float, str]], default: str) -> str:
    for threshold, label in rules:
        if value <= threshold:
            return label
    return default


def market_state_from_data(data: MarketData | dict[str, Any]) -> MarketState:
    """
    Translate raw market inputs into qualitative regimes.
    """
    d = _get_payload(data)

    core_pce_yoy = safe_float(d.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    ism_pmi = safe_float(d.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(d.get("services_pmi"), DEFAULTS["services_pmi"])
    initial_claims = safe_float(d.get("initial_claims"), DEFAULTS["initial_claims"])
    breakeven_inflation = safe_float(d.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    fed_assets_growth_yoy = safe_float(d.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    real_yield_10y = safe_float(d.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    sloos_net_pct = safe_float(d.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    hy_oas = safe_float(d.get("hy_oas"), DEFAULTS["hy_oas"])
    shiller_cape = safe_float(d.get("shiller_cape"), DEFAULTS["shiller_cape"])
    vix_spot = safe_float(d.get("vix_spot"), DEFAULTS["vix_spot"])
    pct_dist_200_sma = safe_float(d.get("pct_dist_200_sma"), 0.0)
    drawdown_pct = safe_float(d.get("drawdown_pct"), 0.0)
    stlfsi_index = safe_float(d.get("stlfsi_index"), DEFAULTS["stlfsi_index"])
    dxy_spot = safe_float(d.get("dxy_spot"), DEFAULTS["dxy_spot"])
    treasury_10y_3m_spread = safe_float(d.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(d.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(d.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(d.get("liquidity_pressure"), 0.0)

    inflation = _bucket(
        core_pce_yoy,
        [
            (THRESHOLDS["inflation_cooling"], "cooling"),
            (THRESHOLDS["inflation_stable"], "stable"),
            (THRESHOLDS["inflation_rising"], "rising"),
        ],
        "hot",
    )
    if inflation_shock > 0.5:
        inflation = "hot"

    growth_score = 0.2 * ism_pmi + 0.8 * services_pmi
    if growth_score >= THRESHOLDS["pmi_expanding"]:
        growth = "expanding"
    elif growth_score >= THRESHOLDS["pmi_ok"]:
        growth = "steady"
    elif growth_score >= THRESHOLDS["pmi_contracting"]:
        growth = "soft"
    else:
        growth = "contracting"

    if initial_claims >= THRESHOLDS["claims_severe_pressure"]:
        growth = "contracting"
    elif initial_claims >= THRESHOLDS["claims_mild_pressure"] and growth == "expanding":
        growth = "steady"

    liquidity = "loose" if sloos_net_pct <= THRESHOLDS["sloos_loose"] else "neutral"
    if fed_assets_growth_yoy > THRESHOLDS["fed_assets_expanding"]:
        liquidity = "loose"
    if liquidity_pressure > 0.5:
        liquidity = "tight"

    credit = "healthy" if hy_oas < THRESHOLDS["hy_spread_stress"] else "stressed"
    if hy_oas >= THRESHOLDS["hy_spread_high_stress"]:
        credit = "high_stress"

    stress = "normal" if (vix_spot <= THRESHOLDS["vix_stress"] and stlfsi_index <= THRESHOLDS["stlfsi_moderate"]) else "high"
    if vix_spot >= THRESHOLDS["vix_high_stress"]:
        stress = "extreme"

    trend = "bullish" if pct_dist_200_sma >= THRESHOLDS["sma_neutral"] else "bearish"
    if pct_dist_200_sma >= THRESHOLDS["sma_bullish"]:
        trend = "bullish"
    elif pct_dist_200_sma <= THRESHOLDS["sma_bearish"]:
        trend = "bearish"
    else:
        trend = "neutral"

    policy = "accommodative" if treasury_10y_3m_spread >= THRESHOLDS["curve_inverted"] and real_yield_10y <= 2.2 else "restrictive"
    if central_bank_stance <= THRESHOLDS["policy_aggressive"]:
        policy = "accommodative"
    elif central_bank_stance >= THRESHOLDS["policy_restrictive"]:
        policy = "restrictive"

    valuation = "cheap" if shiller_cape < 20 else "fair" if shiller_cape <= 25 else "expensive"
    drawdown = "contained" if drawdown_pct < THRESHOLDS["drawdown_moderate"] else "elevated"
    if drawdown_pct >= THRESHOLDS["drawdown_severe"]:
        drawdown = "severe"

    dxy = "strong" if dxy_spot >= THRESHOLDS["dxy_tilt_threshold"] else "normal"

    return MarketState(
        inflation=inflation,
        growth=growth,
        liquidity=liquidity,
        credit=credit,
        stress=stress,
        trend=trend,
        policy=policy,
        valuation=valuation,
        drawdown=drawdown,
        dxy=dxy,
        details={
            "core_pce_yoy": core_pce_yoy,
            "ism_pmi": ism_pmi,
            "services_pmi": services_pmi,
            "initial_claims": initial_claims,
            "breakeven_inflation": breakeven_inflation,
            "fed_assets_growth_yoy": fed_assets_growth_yoy,
            "real_yield_10y": real_yield_10y,
            "sloos_net_pct": sloos_net_pct,
            "hy_oas": hy_oas,
            "shiller_cape": shiller_cape,
            "vix_spot": vix_spot,
            "pct_dist_200_sma": pct_dist_200_sma,
            "drawdown_pct": drawdown_pct,
            "stlfsi_index": stlfsi_index,
            "dxy_spot": dxy_spot,
            "treasury_10y_3m_spread": treasury_10y_3m_spread,
            "inflation_shock": inflation_shock,
            "central_bank_stance": central_bank_stance,
            "liquidity_pressure": liquidity_pressure,
        },
    )
