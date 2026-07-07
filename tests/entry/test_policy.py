"""Tests for paper_trading/entry/policy.py."""

from __future__ import annotations

import pytest

from paper_trading.entry.decision import (
    EntryAction,
    MarketStructureState,
    PolicyDecision,
    TPGeometry,
    TradeDecision,
)
from paper_trading.entry.policy import BasePolicy, ExecutionPolicyLayer, MomentumPolicy


class _FakeDecision:
    def __init__(self, asset="EURUSD", signal="BUY"):
        self.asset = asset
        self.signal = signal
        self.timestamp = "2026-07-07T12:00:00"


@pytest.fixture
def decision():
    return _FakeDecision()


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


@pytest.fixture
def tp_geo():
    return TPGeometry(
        tp_distance=2.0,
        scale_out_tiers=[(0.5, 0.5), (0.3, 1.0), (0.2, 1.5)],
        convexity_score=3.0,
        metadata={},
    )


class TestBasePolicy:
    def test_enter_routing(self, decision, structure, tp_geo):
        result = BasePolicy.route(EntryAction.ENTER, decision, "BREAKOUT_TEST", structure, tp_geo, None)
        assert isinstance(result, PolicyDecision)
        assert result.action == EntryAction.ENTER
        assert result.exit_plan is tp_geo
        assert result.archetype == "BREAKOUT_TEST"

    def test_defer_routing(self, decision, structure, tp_geo):
        result = BasePolicy.route(EntryAction.DEFER, decision, "MEAN_REVERSION", structure, tp_geo, None)
        assert result.action == EntryAction.DEFER
        assert result.entry_plan is None  # no deferred entry passed
        assert result.exit_plan is None


class TestMomentumPolicy:
    def test_enter_with_convexity(self, decision, structure, tp_geo):
        result = MomentumPolicy.route(EntryAction.ENTER, decision, "MOMENTUM_IGNITION", structure, tp_geo, None)
        assert result.action == EntryAction.ENTER
        assert result.metadata.get("convexity") == 3.0


class TestExecutionPolicyLayer:
    def test_handle_momentum(self, decision, structure, tp_geo):
        layer = ExecutionPolicyLayer()
        result = layer.handle(EntryAction.ENTER, decision, "MOMENTUM_IGNITION", structure, tp_geo)
        assert isinstance(result, PolicyDecision)
        assert result.archetype == "MOMENTUM_IGNITION"
        assert result.metadata.get("source") == "MomentumPolicy"

    def test_handle_mean_reversion(self, decision, structure):
        layer = ExecutionPolicyLayer()
        result = layer.handle(EntryAction.ENTER, decision, "MEAN_REVERSION", structure, None)
        assert result.archetype == "MEAN_REVERSION"
        assert result.metadata.get("source") == "BasePolicy"

    def test_handle_unknown_archetype(self, decision, structure):
        layer = ExecutionPolicyLayer()
        result = layer.handle(EntryAction.ENTER, decision, "UNKNOWN", structure, None)
        assert result.archetype == "UNKNOWN"

    def test_handle_skip(self, decision, structure):
        layer = ExecutionPolicyLayer()
        result = layer.handle(EntryAction.SKIP, decision, "BREAKOUT_TEST", structure, None)
        assert result.action == EntryAction.SKIP
