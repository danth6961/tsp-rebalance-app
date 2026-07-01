"""
test_factor_scoring.py

Unit tests for score_market_data() factor bands and regime hysteresis wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from engine import (
    build_engine_result,
    determine_allocation,
    latest_regime_from_history,
    score_market_data,
)

# Neutral snapshot: avoids STLFSI / macro interaction penalties so each factor
# can be tested in isolation.
NEUTRAL_BASE: dict[str, float | bool] = {
    "core_pce_yoy": 2.15,
    "breakeven_inflation": 2.0,
    "ism_pmi": 50.0,
    "services_pmi": 50.0,
    "initial_claims": 200.0,
    "fed_assets_growth_yoy": 0.0,
    "sloos_net_pct": 0.0,
    "hy_oas": 4.5,
    "shiller_cape": 22.0,
    "fwd_eps_growth_yoy": 10.0,
    "real_yield_10y": 1.0,
    "vix_spot": 18.0,
    "pct_dist_200_sma": 0.0,
    "drawdown_pct": 12.0,
    "stlfsi_index": -1.0,
    "treasury_10y_3m_spread": 0.75,
    "inflation_shock": 0.0,
    "central_bank_stance": 0.0,
    "liquidity_pressure": 0.0,
    "bond_yield_10y": 4.0,
    "move_index": 100.0,
    "dxy_spot": 100.0,
    "dxy_trend_up": False,
    "market_breadth_pct": 70.0,
    "vix_3d_panic": False,
    "spx_3d_panic": False,
}


def _score(**overrides: float | bool) -> dict[str, int]:
    data = {**NEUTRAL_BASE, **overrides}
    return score_market_data(data)


class TestLatestRegimeFromHistory:
    def test_empty_history_returns_none(self):
        assert latest_regime_from_history([]) is None
        assert latest_regime_from_history(None) is None

    def test_returns_last_entry(self):
        assert latest_regime_from_history(["A", "B", "C"]) == "C"


class TestInflationBands:
    @pytest.mark.parametrize(
        ("pce", "expected"),
        [
            (1.7, 3),
            (1.9, 1),
            (2.15, 0),
            (2.5, -3),
            (3.5, -5),
        ],
    )
    def test_core_pce_bands(self, pce: float, expected: int):
        assert _score(core_pce_yoy=pce)["inflation"] == expected

    def test_high_breakeven_worsens_inflation(self):
        assert _score(core_pce_yoy=2.15, breakeven_inflation=2.7)["inflation"] == -4

    def test_low_breakeven_floors_inflation_at_zero(self):
        assert _score(core_pce_yoy=2.5, breakeven_inflation=1.7)["inflation"] == 0


class TestGrowthBands:
    @pytest.mark.parametrize(
        ("pmi", "services", "expected"),
        [
            (56.0, 56.0, 3),
            (52.0, 52.0, 1),
            (50.0, 50.0, 0),
            (49.0, 49.0, -3),
            (47.0, 47.0, -5),
        ],
    )
    def test_pmi_composite_bands(self, pmi: float, services: float, expected: int):
        assert _score(ism_pmi=pmi, services_pmi=services)["growth"] == expected

    def test_claims_above_250_penalizes_growth(self):
        assert _score(initial_claims=260.0)["growth"] == -1

    def test_claims_above_280_strongly_penalizes_growth(self):
        assert _score(initial_claims=290.0)["growth"] == -4


class TestLiquidityBands:
    @pytest.mark.parametrize(
        ("sloos", "fed_assets", "expected"),
        [
            (-16.0, 0.0, 1),
            (0.0, 1.0, 2),
            (0.0, 0.0, -2),  # fed_assets <= 0 always applies -2
            (6.0, 0.0, -7),
        ],
    )
    def test_sloos_and_fed_assets(self, sloos: float, fed_assets: float, expected: int):
        assert _score(sloos_net_pct=sloos, fed_assets_growth_yoy=fed_assets)["liquidity"] == expected


class TestCreditSpreadBands:
    @pytest.mark.parametrize(
        ("hy_oas", "expected"),
        [(2.5, 3), (3.5, 1), (4.5, 0), (5.5, -3), (7.0, -5)],
    )
    def test_hy_oas_bands(self, hy_oas: float, expected: int):
        assert _score(hy_oas=hy_oas)["credit_spreads"] == expected


class TestValuationBands:
    @pytest.mark.parametrize(
        ("cape", "expected"),
        [(18.0, 3), (22.0, 0), (28.0, -3), (40.0, -5)],
    )
    def test_cape_bands_with_low_eps_ceiling(self, cape: float, expected: int):
        assert _score(shiller_cape=cape, fwd_eps_growth_yoy=10.0)["valuation"] == expected

    def test_high_real_yield_lowers_cape_ceiling(self):
        # Ceiling 25 with fwd_eps < 15 and real_yield > 2.2; CAPE 26 is above ceiling.
        assert _score(shiller_cape=26.0, real_yield_10y=2.5, fwd_eps_growth_yoy=10.0)["valuation"] == -5


class TestMarketStressBands:
    @pytest.mark.parametrize(
        ("vix", "expected"),
        [(11.0, 3), (14.0, 1), (18.0, 0), (25.0, -3), (35.0, -5)],
    )
    def test_vix_bands(self, vix: float, expected: int):
        assert _score(vix_spot=vix)["market_stress"] == expected


class TestMomentumBands:
    @pytest.mark.parametrize(
        ("dist", "expected"),
        [(6.0, 3), (2.0, 1), (-2.0, -3), (-6.0, -5)],
    )
    def test_sma_distance_bands(self, dist: float, expected: int):
        assert _score(pct_dist_200_sma=dist)["momentum"] == expected


class TestDrawdownBands:
    @pytest.mark.parametrize(
        ("drawdown", "expected"),
        [(3.0, 3), (8.0, 1), (12.0, 0), (18.0, -3), (25.0, -5)],
    )
    def test_drawdown_bands(self, drawdown: float, expected: int):
        assert _score(drawdown_pct=drawdown)["drawdown"] == expected


class TestYieldCurveBands:
    @pytest.mark.parametrize(
        ("spread", "expected"),
        [(1.5, 2), (0.75, 1), (0.25, 0), (-0.25, -2), (-1.0, -4)],
    )
    def test_treasury_spread_bands(self, spread: float, expected: int):
        assert _score(treasury_10y_3m_spread=spread)["yield_curve"] == expected


class TestInflationShockBands:
    @pytest.mark.parametrize(
        ("shock", "expected"),
        [(-0.3, 2), (0.0, 0), (0.15, -1), (0.25, -3), (0.35, -4)],
    )
    def test_inflation_shock_bands(self, shock: float, expected: int):
        assert _score(inflation_shock=shock)["inflation_shock"] == expected


class TestCentralBankBands:
    @pytest.mark.parametrize(
        ("stance", "expected"),
        [(2.0, 2), (1.0, 1), (0.0, 0), (-1.0, -1), (-2.0, -3), (-3.0, -4)],
    )
    def test_central_bank_stance_bands(self, stance: float, expected: int):
        assert _score(central_bank_stance=stance)["central_bank"] == expected


class TestLiquidityPressureBands:
    @pytest.mark.parametrize(
        ("pressure", "expected"),
        [(0.0, 1), (1.0, 0), (2.0, -1), (3.0, -3), (4.0, -5)],
    )
    def test_liquidity_pressure_bands(self, pressure: float, expected: int):
        assert _score(liquidity_pressure=pressure)["liquidity_pressure"] == expected


class TestStlfsiOverlayAdjustments:
    def test_elevated_stlfsi_penalizes_stress_and_momentum(self):
        scores = _score(stlfsi_index=0.5)
        assert scores["market_stress"] == -1
        assert scores["momentum"] == 0

    def test_extreme_stlfsi_forces_deep_negative_stress_and_momentum(self):
        scores = _score(stlfsi_index=2.5)
        assert scores["market_stress"] == -10
        assert scores["momentum"] == -10


class TestRegimeHysteresis:
    """Verify previous_regime stickiness in determine_allocation / build_engine_result."""

    def _neutral_candidate_snapshot(self) -> dict[str, float | bool]:
        """Composite ~4: candidate NEUTRAL, not strong enough for fresh Risk-On (>= 7)."""
        return {**NEUTRAL_BASE, "core_pce_yoy": 1.7}

    def test_without_hysteresis_selects_neutral(self):
        data = self._neutral_candidate_snapshot()
        scores = score_market_data(data)
        _, _, composite, regime, _, _, _ = determine_allocation(data, scores, previous_regime=None)
        assert composite >= 0
        assert regime == "OPTIMIZED NEUTRAL"

    def test_hysteresis_holds_risk_on_when_previous_was_risk_on(self):
        data = self._neutral_candidate_snapshot()
        scores = score_market_data(data)
        _, _, composite, regime, _, _, _ = determine_allocation(
            data,
            scores,
            previous_regime="RISK-ON OVERRIDE",
        )
        assert composite >= 4
        assert regime == "RISK-ON OVERRIDE"

    def test_build_engine_result_accepts_previous_regime(self):
        data = self._neutral_candidate_snapshot()
        without = build_engine_result(data, previous_regime=None)
        with_hyst = build_engine_result(data, previous_regime="RISK-ON OVERRIDE")
        assert without.regime == "OPTIMIZED NEUTRAL"
        assert with_hyst.regime == "RISK-ON OVERRIDE"
