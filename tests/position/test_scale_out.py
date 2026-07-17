from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from paper_trading.position.scale_out import (
    ScaleOutEngine,
    build_scale_out_from_config,
)


# ── Shared tier specs used by multiple test classes ────────────────

_TIERS_4 = [(0.25, 0.25), (0.25, 0.50), (0.25, 0.75), (0.25, 1.0)]
_TIERS_2 = [(0.5, 0.5), (0.5, 1.0)]
_TIERS_3 = [(1 / 3, 0.50), (1 / 3, 1.00), (1 / 3, 1.50)]
_TIERS_1 = [(1.0, 1.0)]


class TestBuildPlan:
    def test_build_plan_long(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        assert len(plan.tiers) == 4
        assert plan.remaining_fraction == 1.0
        assert plan.tiers[0].price == pytest.approx(102.5)
        assert plan.tiers[1].price == pytest.approx(105.0)
        assert plan.tiers[2].price == pytest.approx(107.5)
        assert plan.tiers[3].price == pytest.approx(110.0)

    def test_build_plan_short(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("short", entry_price=100.0, take_profit=90.0, tier_specs=_TIERS_4)
        assert len(plan.tiers) == 4
        assert plan.tiers[0].price == pytest.approx(97.5)
        assert plan.tiers[1].price == pytest.approx(95.0)
        assert plan.tiers[2].price == pytest.approx(92.5)
        assert plan.tiers[3].price == pytest.approx(90.0)

    def test_build_plan_default_tiers(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0)
        assert len(plan.tiers) == 3
        assert plan.tiers[0].price == pytest.approx(105.0)
        assert plan.tiers[1].price == pytest.approx(110.0)
        assert plan.tiers[2].price == pytest.approx(115.0)

    def test_tiers_have_correct_fractions(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan(
            "long", entry_price=100.0, take_profit=110.0, tier_specs=[(0.5, 0.5), (0.3, 1.0), (0.2, 1.5)]
        )
        assert plan.tiers[0].fraction == 0.5
        assert plan.tiers[1].fraction == 0.3
        assert plan.tiers[2].fraction == 0.2

    def test_tiers_start_unfilled(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        assert not plan.tiers[0].filled


class TestCheckTiers:
    def test_no_fills_when_price_below_first_tier(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=101.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert fills == []
        assert all(not t.filled for t in plan.tiers)
        assert plan.remaining_fraction == pytest.approx(1.0)

    def test_first_tier_fills(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=103.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 1
        assert fills[0]["fraction"] == 0.25
        assert fills[0]["reason"] == "scale_out_tier_1"
        assert plan.tiers[0].filled
        assert plan.remaining_fraction == pytest.approx(0.75)

    def test_multiple_tiers_fill_at_once(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=108.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 3
        filled_indices = [i for i, t in enumerate(plan.tiers) if t.filled]
        assert filled_indices == [0, 1, 2]
        assert plan.remaining_fraction == pytest.approx(0.25)

    def test_all_tiers_fill(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=111.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 4
        assert plan.remaining_fraction == pytest.approx(0.0)

    def test_idempotent_no_double_fill(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        engine.check_tiers(
            plan, "long", current_price=103.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        fills2 = engine.check_tiers(
            plan, "long", current_price=103.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert fills2 == []
        assert plan.remaining_fraction == pytest.approx(0.75)

    def test_short_position_fills(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("short", entry_price=100.0, take_profit=90.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "short", current_price=96.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 1
        assert fills[0]["reason"] == "scale_out_tier_1"
        assert plan.tiers[0].filled
        assert plan.remaining_fraction == pytest.approx(0.75)

    def test_partial_fill_then_more(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        engine.check_tiers(
            plan, "long", current_price=103.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        fills = engine.check_tiers(
            plan, "long", current_price=106.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 1
        assert plan.tiers[1].filled
        assert plan.remaining_fraction == pytest.approx(0.50)

    def test_fill_price_recorded(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        engine.check_tiers(
            plan, "long", current_price=103.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert plan.tiers[0].fill_price == 103.0

    def test_fill_pnl(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=102.5, current_value=10000.0, position_size=0.5, exposure_mult=0.8
        )
        expected_pnl = 10000.0 * (102.5 / 100.0 - 1) * 0.5 * 0.8 * 0.25
        assert fills[0]["pnl"] == pytest.approx(expected_pnl)


class TestBreakeven:
    def test_breakeven_activated_after_tier_1(self):
        engine = ScaleOutEngine(activate_breakeven_after=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "breakeven_stop_activated" in reasons
        assert plan.breakeven_activated
        assert plan.breakeven_price == 100.0

    def test_breakeven_not_activated_before_threshold(self):
        engine = ScaleOutEngine(activate_breakeven_after=2)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "breakeven_stop_activated" not in reasons

    def test_breakeven_activated_at_tier_2(self):
        engine = ScaleOutEngine(activate_breakeven_after=1)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_3)
        engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "breakeven_stop_activated" in reasons
        assert plan.breakeven_activated

    def test_breakeven_only_activates_once(self):
        engine = ScaleOutEngine(activate_breakeven_after=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        bev = [f for f in fills if f["reason"] == "breakeven_stop_activated"]
        assert len(bev) == 0

    def test_breakeven_not_activated_when_no_remaining(self):
        engine = ScaleOutEngine(activate_breakeven_after=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "breakeven_stop_activated" not in reasons


class TestRemainingTargets:
    def test_all_targets_before_fill(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        targets = engine.remaining_targets(plan)
        assert targets == [105.0, 110.0]

    def test_some_remaining_after_partial_fill(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        targets = engine.remaining_targets(plan)
        assert targets == [110.0]

    def test_no_remaining_when_all_filled(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert engine.remaining_targets(plan) == []


class TestValidation:
    def test_rejects_tiers_not_summing_to_one(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            ScaleOutEngine(tier_specs=[(0.5, 0.5), (0.3, 1.0)])

    def test_single_tier_allowed(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        assert plan.remaining_fraction == 1.0

    def test_default_tiers_sum_to_one(self):
        plan = ScaleOutEngine().build_plan("long", entry_price=100.0, take_profit=110.0)
        assert sum(t.fraction for t in plan.tiers) == pytest.approx(1.0)


class TestTrailingAfterTier:
    def test_trailing_not_emitted_when_not_configured(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "trailing_activated" not in reasons

    def test_trailing_not_emitted_before_tier(self):
        engine = ScaleOutEngine(trailing_after_tier=1)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "trailing_activated" not in reasons

    def test_trailing_emitted_after_tier(self):
        engine = ScaleOutEngine(trailing_after_tier=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "trailing_activated" in reasons

    def test_trailing_emitted_even_with_breakeven_active(self):
        engine = ScaleOutEngine(activate_breakeven_after=0, trailing_after_tier=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "trailing_activated" in reasons

    def test_trailing_not_emitted_when_nothing_remains(self):
        engine = ScaleOutEngine(trailing_after_tier=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "trailing_activated" not in reasons

    def test_trailing_from_config(self):
        engine = build_scale_out_from_config(
            {
                "scale_out": {
                    "enabled": True,
                    "tiers": [{"fraction": 1.0, "multiplier": 0.5}],
                    "trailing_after_tier": 0,
                },
            }
        )
        assert engine is not None
        assert engine.trailing_after_tier == 0


class TestBuildFromConfig:
    def test_build_enabled(self):
        engine = build_scale_out_from_config(
            {
                "scale_out": {
                    "enabled": True,
                    "tiers": [{"fraction": 0.5, "multiplier": 0.5}, {"fraction": 0.5, "multiplier": 1.0}],
                    "activate_breakeven_after": 0,
                },
            }
        )
        assert engine is not None
        assert engine.activate_breakeven_after == 0

    def test_build_disabled_returns_none(self):
        engine = build_scale_out_from_config({"scale_out": {"enabled": False}})
        assert engine is None

    def test_build_missing_config_returns_none(self):
        engine = build_scale_out_from_config({})
        assert engine is None

    def test_build_default_tiers(self):
        engine = build_scale_out_from_config(
            {
                "scale_out": {"enabled": True},
            }
        )
        assert engine is not None


class TestEdgeCases:
    def test_zero_position_size_no_fill_pnl(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=0.0, exposure_mult=1.0
        )
        assert fills[0]["pnl"] == 0.0

    def test_zero_exposure_mult_no_fill_pnl(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_1)
        fills = engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=0.0
        )
        assert fills[0]["pnl"] == 0.0

    def test_all_tiers_fill_then_no_remaining(self):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        engine.check_tiers(
            plan, "long", current_price=110.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert plan.remaining_fraction == pytest.approx(0.0)
        assert engine.remaining_targets(plan) == []

    def test_partial_fill_then_price_reverses_no_additional_fills(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        f1 = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(f1) == 1
        assert plan.remaining_fraction == pytest.approx(0.5)
        f2 = engine.check_tiers(
            plan, "long", current_price=102.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(f2) == 0
        assert plan.remaining_fraction == pytest.approx(0.5)

    def test_tier_1_and_2_fill_same_bar_breakeven_activates(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_4)
        fills = engine.check_tiers(
            plan, "long", current_price=106.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        assert len(fills) == 2
        assert plan.tiers[0].filled
        assert plan.tiers[1].filled
        assert not plan.tiers[2].filled
        assert plan.remaining_fraction == pytest.approx(0.5)

    def test_breakeven_race_tier1_fills_exactly_at_price(self):
        engine = ScaleOutEngine(activate_breakeven_after=0)
        plan = engine.build_plan("long", entry_price=100.0, take_profit=110.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "long", current_price=105.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "scale_out_tier_1" in reasons
        assert "breakeven_stop_activated" in reasons

    def test_breakeven_race_tier1_and_2_same_bar_short(self):
        engine = ScaleOutEngine(activate_breakeven_after=99)
        plan = engine.build_plan("short", entry_price=100.0, take_profit=90.0, tier_specs=_TIERS_2)
        fills = engine.check_tiers(
            plan, "short", current_price=89.0, current_value=10000.0, position_size=1.0, exposure_mult=1.0
        )
        reasons = [f["reason"] for f in fills]
        assert "scale_out_tier_1" in reasons
        assert "scale_out_tier_2" in reasons


class TestHypothesisScaleOut:
    @given(
        entry=st.floats(min_value=10.0, max_value=1000.0),
        tp_pct=st.floats(min_value=0.01, max_value=0.5),
        side=st.sampled_from(["long", "short"]),
    )
    def test_build_plan_prices_are_monotonic(self, entry, tp_pct, side):
        engine = ScaleOutEngine()
        target = entry * (1 + tp_pct) if side == "long" else entry * (1 - tp_pct)
        plan = engine.build_plan(side, entry_price=entry, take_profit=target, tier_specs=_TIERS_4)
        assert len(plan.tiers) == 4
        assert plan.remaining_fraction == 1.0
        prices = [t.price for t in plan.tiers]
        if side == "long":
            assert all(prices[i] <= prices[i + 1] for i in range(len(prices) - 1))
        else:
            assert all(prices[i] >= prices[i + 1] for i in range(len(prices) - 1))
        assert all(t.filled is False for t in plan.tiers)

    @given(
        entry=st.floats(min_value=10.0, max_value=1000.0),
        tp_pct=st.floats(min_value=0.01, max_value=0.5),
    )
    def test_default_tiers_always_valid(self, entry, tp_pct):
        engine = ScaleOutEngine()
        plan = engine.build_plan("long", entry_price=entry, take_profit=entry * (1 + tp_pct))
        assert abs(sum(t.fraction for t in plan.tiers) - 1.0) < 1e-6
        assert plan.remaining_fraction == pytest.approx(1.0)
        assert all(not t.filled for t in plan.tiers)
        assert all(t.price > entry for t in plan.tiers)
