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
        snap = builder.build(engine, 1, 0.0, peak_value=0.0)
        assert snap.total_equity == 0.0
        assert snap.open_position_count == 0
        # No equity, no peak — drawdown is 0
        assert snap.drawdown_pct == 0.0

    def test_build_one_long_position(self, builder):
        eng = MockEngine()
        eng.mtm_value = 10_000.0
        eng.peak_value = 10_000.0
        actor = MockActor(eng, has_pos=True)
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, peak_value=10_000.0)
        assert snap.total_equity == 10_000.0
        assert snap.open_position_count == 1
        assert len(snap.positions) == 1
        assert snap.positions[0].side == "long"
        assert snap.positions[0].notional == 10_000.0

    def test_build_factor_exposures_signed_short(self, builder):
        # Verify signed factor exposures: short positions contribute negative weight
        class ShortPos:
            side = "short"
            entry_price = 1.10
            stop_loss = 1.11
            take_profit = 1.08

        class ShortPosMgr(MockPosMgr):
            def __init__(self):
                self.position = ShortPos()
                self._has_pos = True

            def has_position(self):
                return True

            def position_pnl(self, cp):
                return 0.0

        eng = MockEngine()
        eng.mtm_value = 10_000.0
        eng.pos_mgr = ShortPosMgr()
        # Build actor manually without overwriting pos_mgr
        actor = type("A", (), {"_engine": eng})()
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, peak_value=10_000.0)
        usd_exposure = [v for f, v in snap.factor_exposures if f == "USD"]
        assert len(usd_exposure) > 0
        assert usd_exposure[0] < 0, f"Short position should produce negative USD exposure, got {usd_exposure[0]}"
        # Also verify total_short_notional got populated
        assert snap.total_short_notional > 0
        assert snap.total_long_notional == 0

    def test_build_missing_attributes_graceful(self, builder):
        class BareActor:
            _engine = None
        engine = MockEngineContainer({"TEST": BareActor()})
        # Should not raise
        snap = builder.build(engine, 1, 0.0, peak_value=100_000.0)
        assert snap.total_equity == 0.0

    def test_build_with_drawdown(self, builder):
        eng = MockEngine()
        eng.mtm_value = 80_000.0
        eng.peak_value = 80_000.0
        actor = MockActor(eng, has_pos=True)
        engine = MockEngineContainer({"EURUSD": actor})
        # peak is higher than equity → drawdown
        snap = builder.build(engine, 1, 0.0, peak_value=100_000.0)
        assert snap.drawdown_pct < 0
        assert snap.drawdown_pct > -1.0

    def test_zero_equity_returns_safe_defaults(self, builder):
        eng = MockEngine()
        eng.mtm_value = 0.0
        eng._last_spread_bps = 10.0  # provide real spread data
        actor = MockActor(eng, has_pos=False)
        engine = MockEngineContainer({"EURUSD": actor})
        snap = builder.build(engine, 1, 0.0, 0.0)
        # When both peak and equity are 0, drawdown is 0
        assert snap.drawdown_pct == 0.0
        assert snap.open_position_count == 0
