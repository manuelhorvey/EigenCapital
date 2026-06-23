from unittest.mock import MagicMock

from paper_trading.entry.decision import PositionSide, TradeDecision
from paper_trading.execution.decision_pipeline import DecisionContext, manage_position
from quantforge.domain.entities.position import PositionIntent, StackLayer


def _mock_engine(current_price=100.0, config=None, pnl=5.0, has_position=True):
    engine = MagicMock()
    engine.name = "TEST"
    engine.current_price = current_price
    engine.config = config or {}
    engine.pos_mgr.has_position.return_value = has_position
    engine.pos_mgr.position_pnl.return_value = pnl
    engine.pos_mgr.stack_layer_count.return_value = 0
    engine._close_position = MagicMock()
    engine._can_enter.return_value = (True, "ok")
    # Provide a real PositionIntent so _update_position_protection doesn't fail
    engine.pos_mgr.position = (
        PositionIntent(
            side=PositionSide.LONG,
            entry_price=current_price or 100.0,
            entry_date="2026-06-22",
            stop_loss=(current_price or 100.0) * 0.98,
            take_profit=(current_price or 100.0) * 1.05,
            vol=0.02,
            layers=[StackLayer(entry_price=current_price or 100.0, size=0.02, timestamp="t0")],
            base_entry_size=0.02,
        )
        if has_position
        else None
    )
    return engine


def _decision(signal="BUY"):
    return TradeDecision(
        asset="TEST",
        signal=signal,
        label=2,
        confidence=80.0,
        prob_long=0.80,
        prob_short=0.10,
        prob_neutral=0.10,
        close_price=100.0,
        timestamp="2026-06-17",
        position_size=1.0,
    )


class TestProfitLockGate:
    def test_blocks_flip_when_pnl_exceeds_threshold(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()

    def test_allows_flip_when_pnl_below_threshold(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=5.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_called_once()

    def test_allows_flip_when_no_position_exists(self):
        engine = _mock_engine(has_position=False)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_not_called()

    def test_noop_when_new_side_matches_current(self):
        engine = _mock_engine(pnl=20.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.LONG,
        )
        manage_position(ctx)
        assert ctx.new_side is None  # same-side suppressed
        engine._close_position.assert_not_called()

    def test_noop_when_new_side_is_none(self):
        engine = _mock_engine(pnl=20.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=None,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()

    def test_default_threshold_15_percent(self):
        engine = _mock_engine(config={}, pnl=20.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side is None

    def test_allows_flip_when_pnl_below_default(self):
        engine = _mock_engine(config={}, pnl=10.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_proceeds_when_current_price_is_none(self):
        engine = _mock_engine(current_price=None, config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_called_once()

    def test_proceeds_when_current_price_is_zero(self):
        engine = _mock_engine(current_price=0.0, config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG
        engine._close_position.assert_called_once()

    def test_respects_per_asset_threshold_override(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 25.0}, pnl=20.0)
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side == PositionSide.LONG

    def test_blocked_flip_does_not_enter_new_position(self):
        engine = _mock_engine(config={"profit_lock_threshold_pct": 10.0}, pnl=15.0)
        engine._can_enter.return_value = (True, "ok")
        ctx = DecisionContext(
            engine=engine,
            decision=_decision(),
            df=MagicMock(),
            new_side=PositionSide.LONG,
            flip_allowed=True,
            current_side=PositionSide.SHORT,
        )
        manage_position(ctx)
        assert ctx.new_side is None
        engine._close_position.assert_not_called()
