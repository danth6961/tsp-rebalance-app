from __future__ import annotations

from dataclasses import dataclass, field

from constants import DEFAULTS, THRESHOLDS
from models import MarketData
from utils import safe_float


@dataclass(frozen=True)
class MarketState:
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

    # Helpful diagnostics for auditability
    details: dict[str, float] = field(default_factory=dict)


def _bucket(value: float, rules: list[tuple[float, str]], default: str) -> str:
    for threshold, label in rules:
        if value <= threshold:
            return label
    return default


def market_state_from_data(data: MarketData | dict[str, object]) -> MarketState:
    if isinstance(data, MarketData):
        d = data.__dict__
    else:
        d = data

    pce = safe_float(d.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    breakeven = safe_float(d.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    pmi = safe_float(d.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(d.get("services_pmi"), DEFAULTS["services_pmi"])
    claims = safe_float(d.get("initial_claims"), DEFAULTS["initial_claims"])
    sloos = safe_float(d.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    fed_assets = safe_float(d.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    hy_oas = safe_float(d.get("hy_oas"), DEFAULTS["hy_oas"])
    vix = safe_float(d.get("vix_spot"), DEFAULTS["vix_spot"])
    stlfsi = safe_float(d.get("stlfsi_index"), DEFAULTS["stlfsi_index"])
    sma_dist = safe_float(d.get("pct_dist_200_sma"), 0.0)
    drawdown = safe_float(d.get("drawdown_pct"), 0.0)
    cape = safe_float(d.get("shiller_cape"), DEFAULTS["shiller_cape"])
    real_yield = safe_float(d.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    curve = safe_float(d.get("treasury_10y_3m_spread"), 0.0)
    dxy = safe_float(d.get("dxy_spot"), DEFAULTS["dxy_spot"])

    inflation = _bucket(
        pce,
        [
            (THRESHOLDS["inflation_cooling"], "cooling"),
            (THRESHOLDS["inflation_stable"], "stable"),
            (THRESHOLDS["inflation_rising"], "rising"),
        ],
        "hot",
    )
    growth = "expanding" if ((0.2 * pmi) + (0.8 * services_pmi)) >= THRESHOLDS["pmi_flat"] else "contracting"
    liquidity = "loose" if (sloos <= THRESHOLDS["sloos_neutral"] and fed_assets > THRESHOLDS["fed_assets_expanding"]) else "tight"
    credit = "healthy" if hy_oas < THRESHOLDS["hy_spread_stress"] else "stressed"
    stress = "normal" if vix <= THRESHOLDS["vix_stress"] and stlfsi <= THRESHOLDS["stlfsi_moderate"] else "high"
    trend = "bullish" if sma_dist >= THRESHOLDS["sma_neutral"] else "bearish"
    policy = "accommodative" if curve >= THRESHOLDS["curve_inverted"] and real_yield <= 2.2 else "restrictive"
    valuation = "cheap" if cape < 20 else "fair" if cape <= 25 else "expensive"
    drawdown_state = "contained" if drawdown < THRESHOLDS["drawdown_elevated"] else "damaged"
    dxy_state = "strong" if dxy >= THRESHOLDS["dxy_tilt_threshold"] else "normal"

    return MarketState(
        inflation=inflation,
        growth=growth,
        liquidity=liquidity,
        credit=credit,
        stress=stress,
        trend=trend,
        policy=policy,
        valuation=valuation,
        drawdown=drawdown_state,
        dxy=dxy_state,
        details={
            "pce": pce,
            "breakeven": breakeven,
            "pmi": pmi,
            "services_pmi": services_pmi,
            "claims": claims,
            "sloos": sloos,
            "fed_assets": fed_assets,
            "hy_oas": hy_oas,
            "vix": vix,
            "stlfsi": stlfsi,
            "sma_dist": sma_dist,
            "drawdown": drawdown,
            "cape": cape,
            "real_yield": real_yield,
            "curve": curve,
            "dxy": dxy,
        },
    )
