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

from constants import BASELINE_ALLOCATIONS, DEFAULTS, DXY_TILT_THRESHOLD, REGIME_ORDER
from market_state import build_market_state
from models import EngineResult, FundsAlloc, Scores
from utils import safe_float


# -----------------------------------------------------------------------------
# Allocation helpers
# -----------------------------------------------------------------------------
# These helpers always return fresh copies so callers cannot mutate the
# canonical allocations stored in constants.py.
# -----------------------------------------------------------------------------


def _regime_alloc(name: str) -> FundsAlloc:
    """Return a fresh copy of a regime allocation from constants.py."""
    return dict(BASELINE_ALLOCATIONS[name])


def max_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """Return the maximum per-fund absolute drift in percentage points."""
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    return max(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )


def cumulative_alloc_drift(current_alloc: FundsAlloc, target_alloc: FundsAlloc) -> float:
    """Return half the L1 distance between two allocations.

    Since allocation weights sum to 100, dividing the total absolute
    difference by 2 gives the minimum turnover-style drift in percentage points.
    """
    funds = set(current_alloc.keys()) | set(target_alloc.keys())
    total_abs_diff = sum(
        abs(float(current_alloc.get(fund, 0.0)) - float(target_alloc.get(fund, 0.0)))
        for fund in funds
    )
    return total_abs_diff / 2.0


# -----------------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------------
# score_market_data() converts a raw market snapshot into factor scores.
# The engine is rule-based and deterministic; it does not learn weights live.
# -----------------------------------------------------------------------------


def score_market_data(data: dict[str, Any]) -> Scores:
    """Convert raw snapshot inputs into factor scores.

    Parameters
    ----------
    data:
        Raw market snapshot dictionary. Missing values are filled with
        documented defaults from constants.py.

    Returns
    -------
    Scores
        A dict of factor name -> integer score.
    """
    scores: Scores = {}

    # Core macro inputs
    pce = safe_float(data.get("core_pce_yoy"), DEFAULTS["core_pce_yoy"])
    pmi = safe_float(data.get("ism_pmi"), DEFAULTS["ism_pmi"])
    services_pmi = safe_float(data.get("services_pmi"), DEFAULTS["services_pmi"])
    initial_claims = safe_float(data.get("initial_claims"), DEFAULTS["initial_claims"])
    breakeven_inflation = safe_float(
        data.get("breakeven_inflation"), DEFAULTS["breakeven_inflation"]
    )
    fed_assets_growth_yoy = safe_float(
        data.get("fed_assets_growth_yoy"), DEFAULTS["fed_assets_growth_yoy"]
    )
    real_yield_10y = safe_float(data.get("real_yield_10y"), DEFAULTS["real_yield_10y"])
    sloos = safe_float(data.get("sloos_net_pct"), DEFAULTS["sloos_net_pct"])
    hy_spread = safe_float(data.get("hy_oas"), DEFAULTS["hy_oas"])
    cape = safe_float(data.get("shiller_cape"), DEFAULTS["shiller_cape"])
    fwd_eps = safe_float(data.get("fwd_eps_growth_yoy"), DEFAULTS["fwd_eps_growth_yoy"])
    vix = safe_float(data.get("vix_spot"), DEFAULTS["vix_spot"])
    sma_dist = safe_float(data.get("pct_dist_200_sma"), 0.0)
    drawdown = safe_float(data.get("drawdown_pct"), 0.0)
    stlfsi = safe_float(data.get("stlfsi_index"), DEFAULTS["stlfsi_index"])

    # Macro overlays
    treasury_10y_3m_spread = safe_float(data.get("treasury_10y_3m_spread"), 0.0)
    inflation_shock = safe_float(data.get("inflation_shock"), 0.0)
    central_bank_stance = safe_float(data.get("central_bank_stance"), 0.0)
    liquidity_pressure = safe_float(data.get("liquidity_pressure"), 0.0)

    # Inflation
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

    # Growth
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

    # Liquidity
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

    # Credit spreads
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

    # Valuation
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

    # Market stress
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

    # Momentum
    if sma_dist > 5.0:
        scores["momentum"] = 3
    elif sma_dist >= 0.0:
        scores["momentum"] = 1
    elif sma_dist >= -5.0:
        scores["momentum"] = -3
    else:
        scores["momentum"] = -5

    # Drawdown
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

    # Yield curve
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

    # Inflation shock overlay
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

    # Central bank stance overlay
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

    # Liquidity pressure overlay
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

    # Overlay adjustments
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


# -----------------------------------------------------------------------------
# Allocation and regime selection
# -----------------------------------------------------------------------------


def _apply_f_unlock(alloc: FundsAlloc, unlocked: bool) -> FundsAlloc:
    """Apply the conditional F Fund overlay to a baseline allocation."""
    alloc = dict(alloc)
    if unlocked and alloc.get("G", 0.0) >= 10.0:
        alloc["G"] -= 10.0
        alloc["F"] = alloc.get("F", 0.0) + 10.0
    return alloc


def determine_allocation(
    data: dict[str, Any],
    scores: Scores,
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> tuple[FundsAlloc, Scores, int, str, FundsAlloc, bool, bool]:
    """Select a regime and build the target allocation.

    Returns
    -------
    tuple
        (final_alloc, scores, composite_score, regime_name,
         base_alloc, asymmetric_vol_trigger, dxy_strong)
    """
    if override_active:
        if override_regime == "RISK-ON OVERRIDE":
            base_alloc = _regime_alloc("RISK-ON OVERRIDE")
            return base_alloc, scores, 5, "RISK-ON OVERRIDE", base_alloc, False, False
        if override_regime == "OPTIMIZED NEUTRAL":
            base_alloc = _regime_alloc("OPTIMIZED NEUTRAL")
            return base_alloc, scores, 0, "OPTIMIZED NEUTRAL", base_alloc, False, False
        if override_regime == "DEFENSIVE ALLOCATION":
            base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")
            return base_alloc, scores, -5, "DEFENSIVE ALLOCATION", base_alloc, False, False

        base_alloc = _regime_alloc("EMERGENCY DISPATCH")
        return base_alloc, scores, -50, "EMERGENCY DISPATCH", base_alloc, False, False

    market = build_market_state(data, scores)

    composite_score = sum(scores.values())
    momentum_breaker = scores.get("momentum", 0) <= -3

    asymmetric_vol_trigger = market.asymmetric_vol
    f_fund_unlocked = market.f_unlock
    dxy_strong = market.dxy_strong

    curve_inverted = market.curve in ("inverted", "deeply_inverted")
    curve_deeply_inverted = market.curve == "deeply_inverted"
    inflation_shock_up = market.inflation == "shocked"
    policy_restrictive = market.policy == "restrictive"
    policy_aggressive = market.policy == "aggressive"
    liquidity_tight = market.liquidity in ("tight", "very_tight")
    liquidity_very_tight = market.liquidity == "very_tight"

    # Emergency dispatch has highest priority.
    if market.panic:
        regime_name = "EMERGENCY DISPATCH"
        composite_score = -50
        base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)
        final_alloc = dict(base_alloc)
        total = sum(final_alloc.values()) or 100.0
        final_alloc = {k: round(v / total * 100.0, 1) for k, v in final_alloc.items()}
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Macro defensive guardrail.
    macro_defensive_trigger = (
        (curve_deeply_inverted and inflation_shock_up)
        or (policy_aggressive and liquidity_very_tight)
        or (curve_inverted and policy_restrictive and liquidity_tight)
    )

    if macro_defensive_trigger:
        regime_name = "DEFENSIVE ALLOCATION"
        base_alloc = _apply_f_unlock(_regime_alloc(regime_name), f_fund_unlocked)

        alloc = dict(base_alloc)
        if asymmetric_vol_trigger:
            s_weight = alloc["S"]
            alloc["S"] = 0.0
            alloc["G"] += s_weight

        total = sum(alloc.values()) or 100.0
        final_alloc = {k: round((v / total) * 100.0, 1) for k, v in alloc.items()}
        composite_score = min(composite_score, -5)
        return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong

    # Default regime selection.
    candidate_regime = "DEFENSIVE ALLOCATION"
    if (
        composite_score >= 7
        and pce < 2.0
        and cape < 26.0
        and not momentum_breaker
        and not curve_inverted
        and not inflation_shock_up
        and not policy_restrictive
        and not liquidity_tight
    ):
        candidate_regime = "RISK-ON OVERRIDE"
    elif composite_score >= 0 and not curve_deeply_inverted and not policy_aggressive:
        candidate_regime = "OPTIMIZED NEUTRAL"

    # Hysteresis / stickiness rules.
    if previous_regime == "RISK-ON OVERRIDE" and candidate_regime == "OPTIMIZED NEUTRAL":
        if composite_score >= 4 and not curve_inverted and not policy_restrictive and not liquidity_tight:
            candidate_regime = "RISK-ON OVERRIDE"

    if previous_regime == "OPTIMIZED NEUTRAL" and candidate_regime == "DEFENSIVE ALLOCATION":
        if composite_score >= -1 and not curve_deeply_inverted and not policy_aggressive:
            candidate_regime = "OPTIMIZED NEUTRAL"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "OPTIMIZED NEUTRAL":
        if composite_score < 3 or liquidity_tight or policy_restrictive:
            candidate_regime = "DEFENSIVE ALLOCATION"

    if previous_regime == "DEFENSIVE ALLOCATION" and candidate_regime == "RISK-ON OVERRIDE":
        if composite_score < 9 or curve_inverted or inflation_shock_up or policy_restrictive or liquidity_tight:
            candidate_regime = "OPTIMIZED NEUTRAL"

    regime_name = candidate_regime

    if regime_name == "RISK-ON OVERRIDE":
        base_alloc = _regime_alloc("RISK-ON OVERRIDE")
    elif regime_name == "OPTIMIZED NEUTRAL":
        base_alloc = _regime_alloc("OPTIMIZED NEUTRAL")
    else:
        base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")

    # Valuation / stress override.
    if scores.get("valuation") == -5 and safe_float(data.get("vix_spot"), 0.0) > 24.0:
        base_alloc = _regime_alloc("DEFENSIVE ALLOCATION")
        regime_name = "DEFENSIVE ALLOCATION"

    base_alloc = _apply_f_unlock(base_alloc, f_fund_unlocked)

    alloc = dict(base_alloc)

    # Asymmetric volatility trims S and reallocates to G.
    if asymmetric_vol_trigger:
        s_weight = alloc["S"]
        alloc["S"] = 0.0
        alloc["G"] += s_weight

    # Strong DXY tilt reduces international exposure in constructive regimes.
    if dxy_strong and regime_name in ("RISK-ON OVERRIDE", "OPTIMIZED NEUTRAL") and alloc["I"] >= 5:
        alloc["I"] -= 5
        alloc["C"] += 5

    total = sum(alloc.values()) or 100.0
    final_alloc = {k: round((v / total) * 100.0, 1) for k, v in alloc.items()}
    return final_alloc, scores, composite_score, regime_name, base_alloc, asymmetric_vol_trigger, dxy_strong


def latest_regime_from_history(recent_regimes: list[str] | None) -> str | None:
    """Return the most recent regime from run history for hysteresis."""
    if not recent_regimes:
        return None
    return recent_regimes[-1]


def build_engine_result(
    data: dict[str, Any],
    override_active: bool = False,
    override_regime: str = "OPTIMIZED NEUTRAL",
    previous_regime: str | None = None,
) -> EngineResult:
    """Build the full engine result payload as a typed dataclass."""
    scores = score_market_data(data)
    (
        allocations,
        scores,
        composite_score,
        regime_name,
        base_alloc,
        vol_trigger,
        dxy_trigger,
    ) = determine_allocation(
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


# -----------------------------------------------------------------------------
# IFT recommendation logic
# -----------------------------------------------------------------------------
# This is the conservative decision gate used to decide whether the app should
# recommend submitting an IFT.
# -----------------------------------------------------------------------------


def should_use_tsp_ift(
    today: date,
    current_alloc: FundsAlloc,
    target_alloc: FundsAlloc,
    recent_regimes: list[str],
    recent_scores: list[int],
    emergency_triggered: bool,
    ift_count_this_month: int,
    last_ift_date: date | None,
    allow_second_ift: bool,
    normal_drift_threshold_pct: float,
    score_change_threshold: int,
    confirmation_days: int,
    cooldown_days: int,
) -> tuple[bool, str]:
    """Evaluate the conservative IFT gate."""
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
        key=lambda name: max_alloc_drift(current_alloc, BASELINE_ALLOCATIONS[name]),
    )
    implied_norm = (
        "EMERGENCY DISPATCH"
        if "EMERGENCY" in implied_regime
        else "DEFENSIVE ALLOCATION"
        if "DEFENSIVE" in implied_regime
        else implied_regime
    )

    if implied_norm != current_confirmed_regime:
        return False, f"Regime not yet stable ({current_confirmed_regime} vs {implied_norm})"

    return True, f"Confirmed regime shift with {cum_drift:.1f}% cumulative drift"


__all__ = [
    "_regime_alloc",
    "max_alloc_drift",
    "cumulative_alloc_drift",
    "score_market_data",
    "determine_allocation",
    "latest_regime_from_history",
    "build_engine_result",
    "should_use_tsp_ift",
]
