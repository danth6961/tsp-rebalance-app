"""
tests/test_regime_consistency.py

Enforces the #1 risk flagged in module_weakness_review.md: that
constants.py, engine.py, and ui.py never silently drift apart on regime
names or baseline allocations. Run via `pytest` before every deploy, or
wire into CI.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from constants import REGIME_DEFINITIONS, REGIME_ORDER, BASELINE_ALLOCATIONS, DXY_TILT_THRESHOLD
from engine import _regime_alloc, determine_allocation, score_market_data, BASELINE_ALLOCATIONS as engine_baseline
from ift_state_machine import is_pure_g_move, IFTStateMachine, MONTHLY_IFT_LIMIT
from validation import validate_market_data, validate_allocation_sums_to_100


class TestRegimeDefinitionSync:
    """constants.py is the documented single source of truth (see its own
    module docstring). These tests assert engine.py and BASELINE_ALLOCATIONS
    actually derive from it rather than drifting independently."""

    def test_all_regime_order_entries_exist_in_definitions(self):
        for name in REGIME_ORDER:
            assert name in REGIME_DEFINITIONS, f"'{name}' in REGIME_ORDER but missing from REGIME_DEFINITIONS"

    def test_all_regime_order_entries_resolve_in_engine(self):
        """engine._regime_alloc() must not KeyError for any displayed regime."""
        for name in REGIME_ORDER:
            alloc = _regime_alloc(name)
            assert alloc, f"engine._regime_alloc('{name}') returned empty allocation"

    def test_engine_and_constants_share_the_same_baseline_object_values(self):
        """engine.py imports BASELINE_ALLOCATIONS from constants.py rather
        than hardcoding its own copy -- this test fails if that import is
        ever replaced with a local literal that can drift."""
        for name in REGIME_ORDER:
            assert engine_baseline[name] == BASELINE_ALLOCATIONS[name], (
                f"engine.py's BASELINE_ALLOCATIONS['{name}'] diverges from constants.py"
            )

    @pytest.mark.parametrize("name", REGIME_ORDER)
    def test_each_regime_allocation_sums_to_100(self, name):
        alloc = REGIME_DEFINITIONS[name]["allocation"]
        errors = validate_allocation_sums_to_100(alloc)
        assert not errors, f"{name}: {errors}"

    def test_emergency_f_unlocked_variant_present_and_sums_to_100(self):
        key = "EMERGENCY DISPATCH (F-Unlocked)"
        assert key in BASELINE_ALLOCATIONS, "F-unlocked emergency overlay missing from BASELINE_ALLOCATIONS"
        errors = validate_allocation_sums_to_100(BASELINE_ALLOCATIONS[key])
        assert not errors, errors

    def test_ui_required_fields_present_for_every_regime(self):
        """ui._render_single_regime_card reads these keys directly; a
        missing key would crash rendering, not fail silently."""
        required_keys = {"icon", "score_label", "profile", "allocation", "description", "color", "bg"}
        for name in REGIME_ORDER:
            info = REGIME_DEFINITIONS[name]
            missing = required_keys - info.keys()
            assert not missing, f"{name} missing UI-required keys: {missing}"


class TestDxyThresholdSync:
    """Regression test for the spec/code drift caught in the prior audit
    (engine.py hardcoded 105.0 while the docs said 103.5)."""

    def test_dxy_threshold_matches_documented_value(self):
        assert DXY_TILT_THRESHOLD == 103.5

    def test_dxy_tilt_triggers_at_documented_threshold_not_old_hardcode(self):
        scores = score_market_data({})
        _, _, _, _, _, _, dxy_strong = determine_allocation(
            {
                "dxy_spot": 104.0,  # between the old wrong 105.0 and the correct 103.5
                "dxy_trend_up": True,
                "bond_yield_10y": 4.5,
                "core_pce_yoy": 2.0,
            },
            scores,
        )
        assert dxy_strong is True, "DXY tilt should trigger at 104.0 per the documented 103.5 threshold"


class TestIftStateMachine:
    """Covers the pure-G-move tolerance fix and the single-writer guarantee."""

    def test_pure_g_move_exact(self):
        assert is_pure_g_move({"G": 100.0, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.0})

    def test_pure_g_move_with_rounding_drift(self):
        """Regression test: normalize-to-100 rounding can yield 99.9/0.1
        for an intended pure-G allocation; exact equality used to fail this."""
        assert is_pure_g_move({"G": 99.9, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.1})

    def test_neutral_allocation_is_not_a_g_move(self):
        assert not is_pure_g_move({"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})

    def test_monthly_cap_blocks_normal_ift_but_not_safety_move(self, tmp_path, monkeypatch):
        import storage
        monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")

        from datetime import date
        today = date.today()
        machine = IFTStateMachine.load(today)
        machine.state["ift_count_this_month"] = MONTHLY_IFT_LIMIT

        normal_decision = machine.can_confirm({"G": 40.0, "C": 30.0, "I": 20.0, "S": 10.0, "F": 0.0})
        assert not normal_decision.allowed

        safety_decision = machine.can_confirm({"G": 100.0, "C": 0.0, "I": 0.0, "S": 0.0, "F": 0.0})
        assert safety_decision.allowed
        assert safety_decision.is_safety_move


class TestValidation:
    def test_flags_implausible_vix(self):
        warnings = validate_market_data({"vix_spot": -50.0})
        assert any("vix_spot" in w for w in warnings)

    def test_passes_plausible_snapshot(self):
        warnings = validate_market_data({"vix_spot": 19.0, "shiller_cape": 30.0, "dxy_spot": 105.0})
        assert warnings == []

    def test_allocation_sum_check(self):
        assert validate_allocation_sums_to_100({"G": 50.0, "C": 40.0}) != []
        assert validate_allocation_sums_to_100({"G": 60.0, "C": 40.0}) == []
