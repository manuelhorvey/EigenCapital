"""Tests for paper_trading/entry/tp_compiler.py."""

from __future__ import annotations

import pytest

from paper_trading.entry.decision import MarketStructureState, TPGeometry, ValidityState
from paper_trading.entry.tp_compiler import MAX_RR, _generate_scale_out_profile, compute_take_profit


@pytest.fixture
def structure():
    return MarketStructureState(
        trend_strength=0.6,
        compression_score=0.02,
        distance_to_swing_high=0.3,
        distance_to_swing_low=0.2,
        volatility_regime=0.5,
        breakout_pressure=0.5,
    )


class TestGenerateScaleOutProfile:
    def test_mean_reversion_frontloaded(self):
        tiers = _generate_scale_out_profile("MEAN_REVERSION", 0.5)
        assert len(tiers) == 3
        assert tiers[0] == (0.50, 0.50)  # 50% early exit

    def test_high_convexity_backloaded(self):
        tiers = _generate_scale_out_profile("MOMENTUM_IGNITION", 3.0)
        assert len(tiers) == 3
        assert tiers[2] == (0.50, 1.50)  # 50% tail

    def test_balanced_convexity(self):
        # convexity=1.2 avoids the <1.1 low-convexity branch
        tiers = _generate_scale_out_profile("TREND_PULLBACK", 1.2)
        assert len(tiers) == 3
        for frac, _ in tiers:
            assert frac == pytest.approx(1 / 3, abs=0.01)


class TestComputeTakeProfit:
    def test_basic_tp_calculation(self, structure):
        tp = compute_take_profit(
            entry_price=100.0,
            sl_distance=1.0,
            regime="GREEN",
            archetype="BREAKOUT_TEST",
            structure=structure,
        )
        assert isinstance(tp, TPGeometry)
        assert tp.tp_distance > 0
        assert tp.convexity_score == 5.0  # BREAKOUT_TEST convexity

    def test_regime_multiplier_applied(self, structure):
        tp_green = compute_take_profit(100.0, 1.0, "GREEN", "BREAKOUT_TEST", structure)
        tp_red = compute_take_profit(100.0, 1.0, "RED", "BREAKOUT_TEST", structure)
        # GREEN mult=1.0, RED mult=0.8 → green distance should be >= red
        assert tp_green.tp_distance >= tp_red.tp_distance
        assert tp_green.tp_distance > 0

    def test_tp_mult_override(self, structure):
        tp_base = compute_take_profit(100.0, 1.0, "GREEN", "BREAKOUT_TEST", structure)
        tp_override = compute_take_profit(
            100.0, 1.0, "GREEN", "BREAKOUT_TEST", structure, tp_mult_override=2.0
        )
        # Override should increase TP distance (or at least not decrease it)
        assert tp_override.tp_distance >= tp_base.tp_distance
        assert tp_base.tp_distance > 0

    def test_tp_capped_at_max_rr(self, structure):
        # Use MOMENTUM_IGNITION (convexity 6.0) + GREEN (mult 1.0) + override
        # 1.0 * 6.0 * 1.0 * 1.0 = 6.0R, capped at MAX_RR=5.0R
        tp = compute_take_profit(
            entry_price=100.0,
            sl_distance=1.0,
            regime="GREEN",
            archetype="MOMENTUM_IGNITION",
            structure=structure,
        )
        assert tp.tp_distance <= MAX_RR

    def test_metadata_includes_breakdown(self, structure):
        tp = compute_take_profit(100.0, 1.0, "GREEN", "BREAKOUT_TEST", structure)
        assert tp.metadata["archetype"] == "BREAKOUT_TEST"
        assert tp.metadata["regime"] == "green"
        assert tp.metadata["reg_mult"] == 1.0
        assert tp.metadata["base_sl_dist"] == 1.0

    def test_custom_archetype_convexity(self, structure):
        # UNKNOWN archetype has convexity 3.0
        tp = compute_take_profit(100.0, 1.0, "GREEN", "UNKNOWN", structure)
        assert tp.convexity_score == 3.0
