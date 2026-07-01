"""
tests/test_regime_consistency.py

Protects the project against drift between constants.py, engine.py,
storage.py, ui.py, validation.py, and ift_state_machine.py.

Run via pytest before deploy or wire into CI.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from constants import REGIME_DEFINITIONS, REGIME_ORDER, BASELINE_ALLOCATIONS, DXY_TILT_THRESHOLD
from engine import _regime_alloc, determine_allocation, score_market_data, BASELINE_ALLOCATIONS as engine_baseline
from ift_state_machine import is_pure_g_move, IFTStateMachine, MONTHLY_IFT_LIMIT
from storage import default_config, load_state, load_state_for_today, save_state
from validation import validate_market_data, validate_allocation_sums_to_100


class TestRegimeDefinitionSync:
    """Regime names, allocations, and UI metadata must stay in sync."""

    def test_all_regime_order_entries_exist_in_definitions(self):
        for name in REGIME_ORDER:
            assert name in REGIME_DEFINITIONS, f"'{name}' in REGIME_ORDER but missing from REGIME_DEFINITIONS"

    def test_all_regime_order_entries_resolve_in_engine(self):
        """engine._regime_alloc() must resolve every displayed regime."""
        for name in REGIME_ORDER:
            alloc = _regime_alloc(name)
            assert alloc, f"engine._regime_alloc('{name}') returned empty allocation"

    def test_engine_and_constants_share_the_same_baseline_values(self):
        """engine.py must import BASELINE_ALLOCATIONS from constants.py."""
        for name in REGIME_ORDER:
            assert engine_baseline[name] == BASELINE_ALLOCATIONS[name], (
                f"engine.py's BASELINE_ALLOCATIONS['{name}'] diverges from constants.py"
            )

    @pytest.mark.parametrize("name", REGIME_ORDER)
    def test_each_regime_allocation_sums_to_100(self, name):
        alloc = REGIME_DEFINITIONS[name]["allocation"]
        errors = validate_allocation_sums_to_100(alloc)
        assert not errors, f"{name}: {errors}"

    def test_ui_required_fields_present_for_every_regime(self):
        """ui._render_single_regime_card reads these keys directly."""
        required_keys = {"icon", "score_label", "profile", "allocation", "description", "color", "bg"}
        for name in REGIME_ORDER:
            info = REGIME_DEFINITIONS[name]
            missing = required_keys - info.keys()
            assert not missing, f"{name} missing UI-required keys: {missing}"


class TestDxyThresholdSync:
    """Guard against DXY threshold drift."""

    def test_dxy_threshold_matches_documented_value(self):
        assert DXY_TILT_THRESHOLD == 103.5

    def test_dxy_tilt_triggers_at_documented_threshold_not_old_hardcode(self):
        scores = score_market_data({})
        _, _, _, _, _, _, dxy_strong = determine_allocation(
            {
                "dxy_spot": 104.0,
                "dxy_trend_up": True,
                "bond_yield_10y": 4.5,
                "core_pce_yoy": 2.0,
            },
            scores,
        )
        assert dxy_strong is True, "DXY tilt should trigger at 104.0 per the documented 103.5 threshold"


class TestIftStateMachine:
    """Covers pure-G safety behavior and monthly-cap enforcement."""

    def test_pure_g_move_exact(self):
        assert is_pure_g_move({"G": 100.0, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.0})

    def test_pure_g_move_with_rounding_drift(self):
        """Normalize-to-100 rounding should still count as a pure G move."""
        assert is_pure_g_move({"G": 99.9, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.1})

    def test_neutral_allocation_is_not_a_g_move(self):
        assert not is_pure_g_move({"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})

    def test_monthly_cap_blocks_normal_ift_but_not_safety_move(self, tmp_path, monkeypatch):
        import storage

        monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")

        today = date.today()
        machine = IFTStateMachine.load(today)
        machine.state["ift_count_this_month"] = MONTHLY_IFT_LIMIT

        normal = machine.can_confirm({"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})
        safety = machine.can_confirm({"G": 100.0, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.0})

        assert not normal.allowed
        assert safety.allowed
        assert safety.is_safety_move


class TestStorageDefaultsAndRollover:
    """Storage defaults and month rollover must remain centralized."""

    def test_default_config_uses_optimized_neutral(self):
        cfg = default_config()
        expected = {k: float(v) for k, v in BASELINE_ALLOCATIONS["OPTIMIZED NEUTRAL"].items()}
        assert cfg["current_alloc"] == expected
        assert cfg["manual_regime"] == "OPTIMIZED NEUTRAL"

    def test_load_state_for_today_rolls_month_and_resets_history(self, tmp_path, monkeypatch):
        import storage

        monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")

        old_state = {
            "month": "2000-01",
            "ift_count_this_month": 2,
            "last_ift_date": "2000-01-15",
            "last_run_date": "2000-01-15",
            "recent_regimes": ["DEFENSIVE ALLOCATION"],
            "recent_scores": [-3],
            "recent_allocations": [{"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}],
        }
        save_state(old_state)

        rolled = load_state_for_today(date.today())
        assert rolled["month"] == date.today().strftime("%Y-%m")
        assert rolled["ift_count_this_month"] == 0
        assert rolled["recent_regimes"] == []
        assert rolled["recent_scores"] == []
        assert rolled["recent_allocations"] == []

    def test_load_state_does_not_apply_rollover_by_itself(self, tmp_path, monkeypatch):
        import storage

        monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")

        old_state = {
            "month": "2000-01",
            "ift_count_this_month": 2,
            "last_ift_date": "2000-01-15",
            "last_run_date": "2000-01-15",
            "recent_regimes": ["DEFENSIVE ALLOCATION"],
            "recent_scores": [-3],
            "recent_allocations": [{"G": 70, "C": 15, "I": 10, "S": 5, "F": 0}],
        }
        save_state(old_state)

        raw = load_state()
        assert raw["month"] == "2000-01"
        assert raw["ift_count_this_month"] == 2


class TestValidationHelpers:
    """Validation should warn on implausible values without raising."""

    def test_validate_market_data_returns_warnings_for_bad_values(self):
        warnings = validate_market_data({"vix_spot": -1, "dxy_spot": "bad"})
        assert warnings
        assert any("vix_spot" in w for w in warnings)
        assert any("dxy_spot" in w for w in warnings)

    def test_validate_allocation_sums_to_100_accepts_reasonable_total(self):
        errors = validate_allocation_sums_to_100({"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})
        assert not errors

    def test_validate_allocation_sums_to_100_rejects_bad_total(self):
        errors = validate_allocation_sums_to_100({"G": 50.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})
        assert errors
