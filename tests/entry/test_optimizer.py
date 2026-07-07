"""Tests for paper_trading/entry/optimizer.py."""

from __future__ import annotations

import pytest

from paper_trading.entry.decision import EntryAction, MarketStructureState, SignalType
from paper_trading.entry.optimizer import EntryOptimizer


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


class TestEntryOptimizer:
    def test_flat_signal_skips(self, structure):
        optimizer = EntryOptimizer()
        action = optimizer.evaluate(SignalType.FLAT, "MOMENTUM_IGNITION", structure)
        assert action == EntryAction.SKIP

    def test_momentum_defers_on_high_pressure(self, structure):
        optimizer = EntryOptimizer()
        s = MarketStructureState(
            trend_strength=0.8,
            compression_score=0.01,
            distance_to_swing_high=0.1,
            distance_to_swing_low=0.9,
            volatility_regime=0.5,
            breakout_pressure=0.95,  # > 0.90 threshold → DEFER
        )
        action = optimizer.evaluate(SignalType.BUY, "MOMENTUM_IGNITION", s)
        assert action == EntryAction.DEFER

    def test_momentum_enters_on_low_pressure(self, structure):
        optimizer = EntryOptimizer()
        s = MarketStructureState(
            trend_strength=0.5,
            compression_score=0.01,
            distance_to_swing_high=0.3,
            distance_to_swing_low=0.4,
            volatility_regime=0.5,
            breakout_pressure=0.5,  # below 0.90 → ENTER
        )
        action = optimizer.evaluate(SignalType.BUY, "MOMENTUM_IGNITION", s)
        assert action == EntryAction.ENTER

    def test_mean_reversion_defers_outside_extremes(self, structure):
        optimizer = EntryOptimizer()
        action = optimizer.evaluate(SignalType.BUY, "MEAN_REVERSION", structure)
        # breakout_pressure=0.5 > extreme_low=0.15 → DEFER
        assert action == EntryAction.DEFER

    def test_breakout_enters_when_compressed(self, structure):
        optimizer = EntryOptimizer()
        s = MarketStructureState(
            trend_strength=0.5,
            compression_score=0.01,  # < 0.05 threshold → ENTER
            distance_to_swing_high=0.5,
            distance_to_swing_low=0.5,
            volatility_regime=0.5,
            breakout_pressure=0.5,
        )
        action = optimizer.evaluate(SignalType.BUY, "BREAKOUT_TEST", s)
        assert action == EntryAction.ENTER

    def test_breakout_defers_when_not_compressed(self, structure):
        optimizer = EntryOptimizer()
        s = MarketStructureState(
            trend_strength=0.5,
            compression_score=0.10,  # > 0.05 threshold → DEFER
            distance_to_swing_high=0.5,
            distance_to_swing_low=0.5,
            volatility_regime=0.5,
            breakout_pressure=0.5,
        )
        action = optimizer.evaluate(SignalType.BUY, "BREAKOUT_TEST", s)
        assert action == EntryAction.DEFER

    def test_unknown_archetype_uses_default(self, structure):
        optimizer = EntryOptimizer()
        action = optimizer.evaluate(SignalType.BUY, "UNKNOWN", structure)
        assert action == EntryAction.ENTER

    def test_vol_expansion_always_enters(self, structure):
        optimizer = EntryOptimizer()
        action = optimizer.evaluate(SignalType.BUY, "VOL_EXPANSION", structure)
        assert action == EntryAction.ENTER

    def test_custom_config_passed_to_policy(self, structure):
        optimizer = EntryOptimizer()
        s = MarketStructureState(
            trend_strength=0.5,
            compression_score=0.01,
            distance_to_swing_high=0.3,
            distance_to_swing_low=0.4,
            volatility_regime=0.5,
            breakout_pressure=0.8,
        )
        # With mom_max_pressure=0.70, pressure 0.8 > 0.70 → DEFER
        action = optimizer.evaluate(SignalType.BUY, "MOMENTUM_IGNITION", s, {"mom_max_pressure": 0.70})
        assert action == EntryAction.DEFER
