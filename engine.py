from datetime import date
from typing import Dict, List, Optional, Any, Tuple

from constants import DEFAULTS, BASELINE_ALLOCATIONS
from utils import safe_float


def max_alloc_drift(current_alloc: Dict[str, float], target_alloc: Dict[str, float]) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)


def cumulative_alloc_drift(current_alloc: Dict[str, float], target_alloc: Dict[str, float]) -> float:
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(abs(float(current_alloc.get(f, 0.0)) - float(target_alloc.get(f, 0.0))) for f in funds)
    return total_abs_diff / 2.0


def score_market_data(data: Dict[str, Any]) -> Dict[str, int]:
    scores: Dict[str, int] = {}

    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    pmi = safe_float(data.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(data.get("services_pmi"), DEFAULTS["services_pmi"])
    initial_claims = safe_float(data.get("initial_claims"), DEFAULTS["initial_claims"])
    breakeven_inflation = safe_float(data.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"])
    fed_assets_growth_yoy = safe_float(data.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"])
    real_yield_10y = safe_float(data.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    sloos = safe_float(data.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    hy_spread = safe_float(data.get("hy_oas"), DEFAULTS["hy_oas"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    fwd_eps = safe_float(data.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"])
    vix = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    sma_dist = safe_float(data.get("pct_dist_200_sma"), 0.0)
    drawdown = safe_float(data.get("drawdown_pct"), 0.0)
    stlfsi = safe_float(data.get("stlfsi_index"), DEFAULTS["stlfsi_index"])

    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)

    if pce < 1.8:
        scores["inflation"] = 3
    elif pce < 2.0:
        scores["inflation"] = 1
    elif pce <= 2.3:
        scores["inflation"] = 0
    elif pce <= 3.0:
        scores["inflation"] = -3
    else:
        scores["inflation"] = -5

    if breakeven_inflation > 2.6:
        scores["inflation"] = min(scores["inflation"], -3) - 1
    elif breakeven_inflation < 1.8:
        scores["inflation"] = max(scores["inflation"], 0)

    composite_pmi = (0.20 * pmi) + (0.80 * services_pmi)
    if composite_pmi > 55.0:
        scores["growth"] = 3
    elif composite_pmi >= 51.5:
        scores["growth"] = 1
    elif composite_pmi >= 50.0:
        scores["growth"] = 0
    elif composite_pmi >= 48.0:
        scores["growth"] = -3
    else:
        scores["growth"] = -5

    if initial_claims > 280.0:
        scores["growth"] = min(scores["growth"], -3) - 1
    elif initial_claims > 250.0:
        scores["growth"] -= 1

    if sloos < -15.0:
        scores["liquidity"] = 3
    elif sloos <= 5.0:
        scores["liquidity"] = 0
    else:
        scores["liquidity"] = -5

    if fed_assets_growth_yoy > 0.0:
        scores["liquidity"] += 2
    else:
        scores["liquidity"] -= 2

    if hy_spread < 3.0:
        scores["credit_spreads"] = 3
    elif hy_spread < 4.0:
        scores["credit_spreads"] = 1
    elif hy_spread <= 5.0:
        scores["credit_spreads"] = 0
    elif hy_spread <= 6.0:
        scores["credit_spreads"] = -3
    else:
        scores["credit_spreads"] = -5

    base_cape_ceiling = 35.0 if fwd_eps >= 15.0 else 30.0
    if real_yield_10y > 2.2:
        active_cape_ceiling = base_cape_ceiling - 5.0
    elif real_yield_10y < 0.5:
        active_cape_ceiling = base_cape_ceiling + 3.0
    else:
        active_cape_ceiling = base_cape_ceiling

    if cape < 20.0:
        scores["valuation"] = 3
    elif cape <= 25.0:
        scores["valuation"] = 0
    elif cape <= active_cape_ceiling:
        scores["valuation"] = -3
    else:
        scores["valuation"] = -5

    if vix < 12.0:
        scores["market_stress"] = 3
    elif vix < 15.0:
        scores["market_stress"] = 1
    elif vix <= 22.0:
        scores["market_stress"] = 0
    elif vix <= 30.0:
        scores["market_stress"] = -3
    else:
        scores["market_stress"] = -5

    if sma_dist > 5.0:
        scores["momentum"] = 3
    elif sma_dist >= 0.0:
        scores["momentum"] = 1
    elif sma_dist >= -5.0:
        scores["momentum"] = -3
    else:
        scores["momentum"] = -5

    if drawdown < 5.0:
        scores["drawdown"] = 3
    elif drawdown < 10.0:
        scores["drawdown"] = 1
    elif drawdown <= 15.0:
        scores["drawdown"] = 0
    elif drawdown <= 20.0:
        scores["drawdown"] = -3
    else:
        scores["drawdown"] = -5

    if treasury_10y_3m_spread > 1.0:
        scores["yield_curve"] = 2
    elif treasury_10y_3m_spread > 0.5:
        scores["yield_curve"] = 1
    elif treasury_10y_3m_spread >= 0.0:
        scores["yield_curve"] = 0
    elif treasury_10y_3m_spread >= -0.5:
        scores["yield_curve"] = -2
    else:
        scores["yield_curve"] = -4

    if inflation_shock <= -0.2:
        scores["inflation_shock"] = 2
    elif inflation_shock <= 0.0:
        scores["inflation_shock"] = 0
    elif inflation_shock <= 0.2:
        scores["inflation_shock"] = -1
    elif inflation_shock <= 0.3:
        scores["inflation_shock"] = -3
    else:
        scores["inflation_shock"] = -4

    if central_bank_stance >= 2.0:
        scores["central_bank"] = 2
    elif central_bank_stance >= 1.0:
        scores["central_bank"] = 1
    elif central_bank_stance <= -3.0:
        scores["central_bank"] = -4
    elif central_bank_stance <= -2.0:
        scores["central_bank"] = -3
    elif central_bank_stance < 0.0:
        scores["central_bank"] = -1
    else:
        scores["central_bank"] = 0

    if liquidity_pressure <= 0.5:
        scores["liquidity_pressure"] = 1
    elif liquidity_pressure <= 1.5:
        scores["liquidity_pressure"] = 0
    elif liquidity_pressure <= 2.5:
        scores["liquidity_pressure"] = -1
    elif liquidity_pressure <= 3.5:
        scores["liquidity_pressure"] = -3
    else:
        scores["liquidity_pressure"] = -5

    if 0.0 <= stlfsi <= 1.0:
        scores["market_stress"] -= 1
        scores["momentum"] -= 1
    elif 1.0 < stlfsi <= 2.0:
        scores["market_stress"] -= 3
        scores["momentum"] -= 3
    elif stlfsi > 2.0:
        scores["market_stress"] = -10
        scores["momentum"] = -10
        scores["valuation"] = min(scores["valuation"], -5)

    if treasury_10y_3m_spread < 0.0 and inflation_shock > 0.2:
        scores["growth"] -= 1
        scores["market_stress"] -= 1
        scores["momentum"] -= 1

    if central_bank_stance <= -2.0 and liquidity_pressure >= 3.0:
        scores["market_stress"] -= 2
        scores["liquidity"] -= 2
        scores["valuation"] -= 1

    if treasury_10y_3m_spread < -0.5:
        scores["growth"] -= 1
        scores["valuation"] -= 1

    if inflation_shock > 0.3:
        scores["inflation"] -= 1

    return scores


def determine_allocation(
    data: Dict[str, Any],
    scores: Dict[str, int],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
):
    if override_active:
        if override_regime == "RISK-ON OVERRIDE":
            base_alloc = {"G": 30, "C": 40, "I": 25, "S": 10, "F": 0}
            return base_alloc, scores, 5, "RISK-ON OVERRIDE", base_alloc, False, False
        if override_regime == "OPTIMIZED NEUTRAL":
            base_alloc = {"G": 40, "C": 30, "I": 20, "S": 10, "F": 0}
            return base_alloc, scores, 0, "OPTIMIZED NEUTRAL", base_alloc, False, False
        if override_regime == "DEFENSIVE ALLOCATION":
            base_alloc = {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}
            return base_alloc, scores, -5, "DEFENSIVE ALLOCATION", base_alloc, False, False

        base_alloc = {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0}
        return base_alloc, scores, -50, "EMERGENCY DISPATCH", base_alloc, False, False

    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    move_index = safe_float(data.get("move_index"), DEFAULTS["move_index"])
    bond_yield = safe_float(data.get("bond_yield_10y"), DEFAULTS["bond_yield_10y"])
    dxy_spot = safe_float(data.get("dxy_spot"), DEFAULTS["dxy_spot"])
    dxy_trend_up = bool(data.get("dxy_trend_up", False))
    market_breadth = safe_float(data.get("market_breadth_pct"), DEFAULTS["market_breadth_pct"])
    vix_3d_panic = bool(data.get("vix_3d_panic", False))
    spx_3d_panic = bool(data.get("spx_3d_panic", False))

    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)

    composite_score = sum(scores.values())
    momentum_breaker = scores.get("momentum", 0) <= -3
    asymmetric_vol_trigger = scores.get("market_stress", 0) <= -3 or scores.get("momentum", 0) <= -3
    f_fund_unlocked = (bond_yield - pce) >= 1.5 and move_index < 120.0
    dxy_strong = dxy_spot >= 103.5 and dxy_trend_up
    panic_valve_triggered = (vix_3d_panic or spx_3d_panic) and (market_breadth is not None and market_breadth <= 60.0)

    curve_inverted = treasury_10y_3m_spread < 0.0
    curve_deeply_inverted = treasury_10y_3m_spread < -0.5
    inflation_shock_up = inflation_shock > 0.2
    policy_restrictive = central_bank_stance <= -2.0
    policy_aggressive = central_bank_stance <= -3.0
    liquidity_tight = liquidity_pressure >= 3.0
    liquidity_very_tight = liquidity_pressure >= 4.0

    if panic_valve_triggered:
        regime_name = "EMERGENCY DISPATCH"
        composite_score = -50
        alloc = {"G": 90, "C": 0, "I": 0, "S": 0, "F": 10} if f_fund_unlocked else {"G": 100, "C": 0, "I": 0, "S": 0, "F": 0}
        total = sum(alloc.values()) or 100
        final_alloc = {k: round(v / total * 100, 1) for k, v in alloc.items()}
        return final_alloc, scores, composite_score, regime_name, alloc, asymmetric_vol_trigger, dxy_strong

    macro_defensive_trigger = (
        (curve_deeply_inverted and inflation_shock_up)
        or (policy_aggressive and liquidity_very_tight)
        or (curve_inverted and policy_restrictive and liquidity_tight)
    )

    if macro_defensive_trigger:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}

        if f_fund_unlocked and base_alloc["G"] >= 10:
            base_alloc["G"] -= 10
            base_alloc["F"] += 10

        alloc = base_alloc.copy()
        if asymmetric_vol_trigger:
            s_w = alloc["S"]
            alloc["S"] = 0
            alloc["G"] += s_w

        total = sum(alloc.values()) or 100
        final_alloc = {k: round((v / total) * 100, 1) for k, v in alloc.items()}
        composite_score = min(composite_score, -5)
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    if (
        composite_score >= 5
        and pce < 2.0
        and cape < 26.0
        and not momentum_breaker
        and not curve_inverted
        and not inflation_shock_up
        and not policy_restrictive
        and not liquidity_tight
    ):
        regime_name = "RISK-ON OVERRIDE"
        base_alloc = {"G": 30, "C": 40, "I": 25, "S": 10, "F": 0}
    elif composite_score >= 0 and not curve_deeply_inverted and not policy_aggressive:
        regime_name = "OPTIMIZED NEUTRAL"
        base_alloc = {"G": 40, "C": 30, "I": 20, "S": 10, "F": 0}
    else:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}

    if scores.get("valuation") == -5 and safe_float(data.get("vix_spot"), 0.0) > 24.0:
        base_alloc = {"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}

    if f_fund_unlocked and base_alloc["G"] >= 10:
        base_alloc["G"] -= 10
        base_alloc["F"] += 10

    alloc = base_alloc.copy()
    if asymmetric_vol_trigger:
        s_w = alloc["S"]
        alloc["S"] = 0
        alloc["G"] += s_w
    if dxy_strong and regime_name in ("RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL") and alloc["I"] >= 5:
        alloc["I"] -= 5
        alloc["C"] += 5

    total = sum(alloc.values()) or 100
    final_alloc = {k: round((v / total) * 100, 1) for k, v in alloc.items()}
    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def build_engine_result(
    data: Dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED_NEUTRAL",
):
    scores = score_market_data(data)
    allocations, scores, composite_score, regime_name, base_alloc, vol_t, dxy_t = determine_allocation(
        data, scores, override_active=override_active, override_regime=override_regime
    )
    return {
        "allocations": allocations,
        "scores": scores,
        "composite_score": composite_score,
        "regime": regime_name,
        "base_alloc": base_alloc,
        "asymmetric_vol_trigger": vol_t,
        "dxy_strong": dxy_t,
        "emergency_triggered": regime_name == "EMERGENCY DISPATCH",
    }


def should_use_tsp_ift(
    today: date,
    current_alloc: Dict[str, float],
    target_alloc: Dict[str, float],
    recent_regimes: List[str],
    recent_scores: List[int],
    emergency_triggered: bool,
    ift_count_this_month: int,
    last_ift_date: Optional[date],
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
    confirmation_days: int,
    cooldown_days: int,
):
    """
    Conservative IFT gate.

    Rules:
    1) Emergency trigger is the only fast path.
    2) Normal IFT requires cooldown cleared.
    3) Normal IFT requires enough confirmation history.
    4) Normal IFT requires both meaningful drift and meaningful score change.
    5) The old "confirmed regime catch-up" shortcut is removed.
    """
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

    current_confirmed_regime = recent_regimes[-1]

    cum_drift = cumulative_alloc_drift(current_alloc, target_alloc)
    if cum_drift < normal_drift_threshold_pct:
        return False, f"Cumulative portfolio drift too small ({cum_drift:.1f}% vs {normal_drift_threshold_pct}%)"

    score_change = abs(recent_scores[-1] - recent_scores[-confirmation_days - 1])
    if score_change < score_change_threshold:
        return False, f"Score change not strong enough ({score_change} vs {score_change_threshold})"

    implied_regime = min(
        BASELINE_ALLOCATIONS.keys(),
        key=lambda name: max_alloc_drift(current_alloc, BASELINE_ALLOCATIONS[name])
    )
    implied_norm = (
        "EMERGENCY DISPATCH" if "EMERGENCY" in implied_regime
        else "DEFENSIVE ALLOCATION" if "DEFENSIVE" in implied_regime
        else implied_regime
    )

    if implied_norm != current_confirmed_regime:
        return False, f"Regime not yet stable ({current_confirmed_regime} vs {implied_norm})"

    return True, f"Confirmed regime shift with {cum_drift:.1f}% cumulative drift"
