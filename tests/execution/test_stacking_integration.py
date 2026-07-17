"""Integration tests for stacking flow — full gate evaluation and execution."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from paper_trading.execution.stacking import StackingGate


class MockPosition:
    def __init__(self, **kwargs):
        self.entry_price = kwargs.get("entry_price", 100.0)
        self.stop_loss = kwargs.get("stop_loss", 98.0)
        self.avg_price = kwargs.get("avg_price", 100.0)
        self.vol = kwargs.get("vol", 0.01)
        self._is_long = kwargs.get("is_long", True)
        self.base_entry_size = kwargs.get("base_entry_size", 1.0)
        self._total_size = kwargs.get("total_size", 1.0)
        self.layers = kwargs.get("layers", [])
        self.last_stack_bar_id = kwargs.get("last_stack_bar_id", 0)
        self.effective_sl = kwargs.get("effective_sl", self.stop_loss)
        self.risk_floor = kwargs.get("risk_floor", 0.0)

    @property
    def is_long(self) -> bool:
        return self._is_long

    @property
    def total_size(self) -> float:
        return self._total_size

    def notional_risk(self, current_price):
        if self.is_long:
            return self.total_size * max(current_price - self.effective_sl, 0)
        return self.total_size * max(self.effective_sl - current_price, 0)


class MockPosMgr:
    def __init__(self, position=None):
        self._position = position

    @property
    def position(self):
        return self._position

    def stack_layer_count(self):
        return len(self._position.layers) if self._position and self._position.layers else 0

    def max_layers_reached(self, max_layers):
        return self.stack_layer_count() >= max_layers

    def has_position(self):
        return self._position is not None


class MockDecision:
    def __init__(self, confidence=0.8, close_price=102.0, side="buy"):
        self.confidence = confidence
        self.close_price = close_price
        self.side = side
        self.timestamp = "2026-06-28T12:00:00"


class MockEngine:
    def __init__(self, **kwargs):
        self.current_price = kwargs.get("current_price", 102.0)
        self.capital_base = kwargs.get("capital_base", 100000.0)
        self.name = kwargs.get("name", "TEST")
        self.config = kwargs.get("config", {})
        self._pending_entries = kwargs.get("_pending_entries", {})
        self._cycle_counter = kwargs.get("_cycle_counter", 10)
        self._last_stop_out_cycle = kwargs.get("_last_stop_out_cycle", None)
        self._bar_counter = kwargs.get("_bar_counter", 5)
        self._realized_volatility = kwargs.get("_realized_volatility", 0.15)
        self.pos_mgr = kwargs.get("pos_mgr", MockPosMgr())


class MockContext:
    def __init__(self, **kwargs):
        self.engine = kwargs.get("engine", MockEngine())
        self.decision = kwargs.get("decision", MockDecision())
        self.new_side = kwargs.get("new_side", "buy")
        self.df = kwargs.get("df", pd.DataFrame({"adx": [25.0]}))


def _make_context(**overrides):
    ctx_kwargs = {}
    engine_kwargs = overrides.pop("engine", {})
    pos_kwargs = engine_kwargs.pop("position", overrides.pop("position", {}))
    decision_kwargs = overrides.pop("decision", {})

    pos = MockPosition(**pos_kwargs)
    pos_mgr = MockPosMgr(position=pos)
    if "capital_base" not in engine_kwargs:
        engine_kwargs["capital_base"] = 100.0  # small cap so min_entry floor ≈ 0.5
    engine = MockEngine(pos_mgr=pos_mgr, **engine_kwargs)
    decision = MockDecision(**decision_kwargs)
    ctx = MockContext(engine=engine, decision=decision, **overrides)
    return ctx


DEFAULT_CONFIG = {
    "min_stack_r": 0.5,
    "min_confidence": 0.6,
    "max_layers": 3,
    "stack_spacing_r": 0.5,
    "adx_threshold": 25,
    "stack_sl_tighten": 0.5,
    "dry_run": True,
    "layer_multipliers": [0.8, 0.5, 0.3],
}


class TestStackingGateIntegration:
    def test_all_gates_pass(self):
        ctx = _make_context(
            engine={"current_price": 105.0},
            decision={"confidence": 0.85, "close_price": 105.0},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert result.should_stack
        assert result.reason == "all_gates_passed"

    def test_not_enough_profit(self):
        ctx = _make_context(
            engine={"current_price": 100.4},
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
            position={"entry_price": 100.0, "avg_price": 100.0, "vol": 0.01},
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "unrealized_r" in result.reason

    def test_low_confidence_fails(self):
        ctx = _make_context(
            engine={"current_price": 105.0, "position": {"entry_price": 100.0}},
            decision={"confidence": 0.4},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "confidence" in result.reason

    def test_max_layers_reached(self):
        ctx = _make_context(
            engine={"current_price": 105.0},
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        # Simulate max layers by giving position 3 existing layers
        ctx.engine.pos_mgr = MockPosMgr(
            position=MockPosition(
                layers=[1, 2, 3],
                entry_price=100.0,
            )
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "max_layers" in result.reason

    def test_no_price_returns_false(self):
        ctx = _make_context(
            engine={"current_price": None},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert result.reason == "no_price"

    def test_non_trending_rejected(self):
        ctx = _make_context(
            engine={"current_price": 105.0},
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [15.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "adx" in result.reason

    def test_spacing_too_tight(self):
        last_layer = MagicMock()
        last_layer.entry_price = 100.0
        ctx = _make_context(
            # avg_price=99 so unrealized_r passes, but gap from last_layer at 100 fails
            engine={"current_price": 100.4},
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
            position={
                "avg_price": 99.0,
                "entry_price": 99.0,
                "vol": 0.01,
                "layers": [last_layer],
            },
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "stack_spacing" in result.reason

    def test_pending_entry_conflict(self):
        ctx = _make_context(
            engine={"current_price": 105.0, "_pending_entries": {"buy": "exists"}},
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "pending_entry" in result.reason

    def test_stopout_cooldown_active(self):
        ctx = _make_context(
            engine={
                "current_price": 105.0,
                "_last_stop_out_cycle": 9,
                "_cycle_counter": 9,
                "config": {"stopout_cross_side_cooldown_cycles": 1},
            },
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "stopout_cooldown" in result.reason

    def test_stopout_cooldown_expired(self):
        ctx = _make_context(
            engine={
                "current_price": 105.0,
                "_last_stop_out_cycle": 5,
                "_cycle_counter": 10,
                "config": {"stopout_cross_side_cooldown_cycles": 1},
            },
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert result.should_stack
        assert result.reason == "all_gates_passed"

    def test_stack_size_diminishing_multipliers(self):
        """First layer uses full multiplier, second uses half."""
        ctx = _make_context(
            engine={"current_price": 105.0},
            df=pd.DataFrame({"adx": [30.0]}),
            position={
                "base_entry_size": 1.0,
                "layers": [],
            },
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        size1 = gate._compute_stack_size(ctx)

        ctx.engine.pos_mgr = MockPosMgr(
            position=MockPosition(
                base_entry_size=1.0,
                layers=[MockPosition()],
                entry_price=100.0,
            )
        )
        size2 = gate._compute_stack_size(ctx)
        assert size1 > size2
        assert abs(size1 / size2 - 0.8 / 0.5) < 0.01

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_execute_stack(self, dry_run):
        cfg = dict(DEFAULT_CONFIG)
        cfg["dry_run"] = dry_run
        engine = MockEngine(
            current_price=105.0,
            pos_mgr=MockPosMgr(position=MockPosition(base_entry_size=1.0, layers=[], entry_price=100.0)),
        )
        engine._open_position = MagicMock()
        decision = MockDecision(confidence=0.85, close_price=105.0)
        ctx = MockContext(
            engine=engine,
            decision=decision,
            new_side="buy",
            df=pd.DataFrame({"adx": [30.0]}),
        )
        gate = StackingGate(cfg)
        gate.execute_stack(ctx)
        if dry_run:
            engine._open_position.assert_not_called()
        else:
            engine._open_position.assert_called_once()

    def test_duplicate_bar_blocks_stack(self):
        ml = MagicMock()
        ml.entry_price = 100.0
        ctx = _make_context(
            engine={
                "current_price": 105.0,
                "_bar_counter": 5,
            },
            decision={"confidence": 0.85},
            df=pd.DataFrame({"adx": [30.0]}),
            position={
                "last_stack_bar_id": 5,
                "layers": [ml],
                "entry_price": 100.0,
                "avg_price": 100.0,
                "vol": 0.01,
            },
        )
        gate = StackingGate(dict(DEFAULT_CONFIG))
        result = gate.should_stack(ctx)
        assert not result.should_stack
        assert "duplicate_bar" in result.reason
