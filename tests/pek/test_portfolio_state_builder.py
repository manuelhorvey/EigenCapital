"""Tests for PortfolioStateBuilder — snapshot construction from live engine state."""
import pytest

from paper_trading.pek.state.portfolio_state_builder import PortfolioStateBuilder


class MockPosition:
    side = "long"
    entry_price = 1.10
    stop_loss = 1.09
    take_profit = 1.12


class MockPosMgr:
    def __init__(self, has_pos=True):
        self._has_pos = has_pos
        self.position = MockPosition() if has_pos else None

    def has_position(self):
        return self._has_pos

    def position_pnl(self, current_price):
        return 0.0


class MockEngine:
    mtm_value = 10_000.0
    current_price = 1.105
    _last_entry_notional = 10_000.0
    _last_spread_bps = None
    _last_confidence = 100.0
    _risk_off = False
    _last_gates_trace = {}
    _spread_tier = "fx_major"


class MockActor:
    def __init__(self, engine=None, has_pos=True):
        self._engine = engine or MockEngine()
        self._engine.pos_mgr = MockPosMgr(has_pos)


class MockEngineContainer:
    def __init__(self, actors=None):
        self._actors = actors or {}


@pytest.fixture
def builder():
    return PortfolioStateBuilder({"name": "production", "max_daily_loss_pct": 0.01, "max_drawdown_pct": -0.15})


class TestPortfolioStateBuilder:
    def test_build_no_actors(self, builder):
        engine = MockEngineContainer({})
        snap = builder.build(engine, 1, 0.0, 100_000.0)
        assert snap.total_equity == 0.0
        assert snap.open_position_count == 0
        assert snap.drawdown_pct == 0.0

    def test_build_one_long_position(self, builder):
        eng = MockEngine()
        actor = MockActor(eng, has_pos=True)
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, 100_000.0)
        assert snap.total_equity == 10_000.0
        assert snap.open_position_count == 1
        assert len(snap.positions) == 1
        assert snap.positions[0].side == "long"
        assert snap.positions[0].notional == 10_000.0

    def test_build_factor_exposures_signed_short(self, builder):
        eng = MockEngine()
        eng.mtm_value = 10_000.0
        eng._last_entry_notional = 10_000.0
        # Override position side
        class ShortPos:
            side = "short"
            entry_price = 1.10
            stop_loss = 1.11
            take_profit = 1.08

        class ShortPosMgr:
            def has_position(self):
                return True
            def position_pnl(self, current_price):
                return 0.0
            position = ShortPos()

        eng.pos_mgr = ShortPosMgr()
        actor = MockActor(eng, has_pos=True)
        actor._engine.pos_mgr = ShortPosMgr()
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, 100_000.0)
        # EURUSD is in USD factor group; weight should be -10K/10K = -1.0
        usd_exposure = [v for f, v in snap.factor_exposures if f == "USD"]
        assert len(usd_exposure) > 0
        assert usd_exposure[0] < 0

    def test_build_missing_attributes_graceful(self, builder):
        class BareActor:
            _engine = None
        engine = MockEngineContainer({"TEST": BareActor()})
        snap = builder.build(engine, 1, 0.0, 100_000.0)
        assert snap.total_equity == 0.0

    def test_build_with_drawdown(self, builder):
        eng = MockEngine()
        actor = MockActor(eng, has_pos=True)
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, peak_value=200_000.0)
        assert snap.drawdown_pct < 0

    def test_zero_equity_safe_budgets(self, builder):
        eng = MockEngine()
        eng.mtm_value = 0.0
        actor = MockActor(eng, has_pos=False)
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, 100_000.0)
        assert snap.daily_loss_remaining == float("inf")
