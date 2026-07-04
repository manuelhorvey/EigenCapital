import pytest
from paper_trading.entry.decision import PositionIntent
from paper_trading.position.manager import PositionManager


class TestPositionManager:
    @pytest.fixture
    def pm(self):
        return PositionManager(initial_capital=10000, position_size=0.95)

    def test_initial_state(self, pm):
        assert pm.initial_capital == 10000
        assert pm.current_value == 10000
        assert pm.peak_value == 10000
        assert pm.position is None
        assert pm.trade_log == []
        assert not pm.has_position()
        assert pm.current_side() is None

    def test_open_long(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        assert pm.has_position()
        assert pm.current_side() == "long"
        assert pm.position.entry_price == 100.0

    def test_open_short(self, pm):
        intent = PositionIntent(side="short", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=105.0, take_profit=95.0, vol=0.02)
        pm.open(intent)
        assert pm.current_side() == "short"

    def test_close_long_profitable(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.close(exit_price=110.0, exit_date="2026-06-10", reason="tp")
        assert trade is not None
        assert trade["side"] == "long"
        assert trade["return"] == pytest.approx(0.10)
        assert trade["pnl"] == pytest.approx(10000 * 0.10 * 0.95)
        assert not pm.has_position()
        assert pm.current_value == pytest.approx(10000 + 10000 * 0.10 * 0.95)

    def test_close_short_profitable(self, pm):
        intent = PositionIntent(side="short", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=105.0, take_profit=95.0, vol=0.02)
        pm.open(intent)
        trade = pm.close(exit_price=95.0, exit_date="2026-06-10", reason="tp")
        assert trade is not None
        assert trade["side"] == "short"
        assert trade["return"] == pytest.approx(100 / 95 - 1)

    def test_close_no_position(self, pm):
        trade = pm.close(100.0, "2026-06-10", "test")
        assert trade is None

    def test_close_twice_no_op(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        pm.close(110.0, "2026-06-10", "tp")
        trade = pm.close(110.0, "2026-06-11", "tp")
        assert trade is None

    def test_check_sl_tp_long_stop_hit(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        hit = pm.check_sl_tp(94.0)
        assert hit is not None
        assert hit[0] == "sl"

    def test_check_sl_tp_long_tp_hit(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        hit = pm.check_sl_tp(111.0)
        assert hit is not None
        assert hit[0] == "tp"

    def test_check_sl_tp_long_no_hit(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        hit = pm.check_sl_tp(105.0)
        assert hit is None

    def test_check_sl_tp_short_stop_hit(self, pm):
        intent = PositionIntent(side="short", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=105.0, take_profit=95.0, vol=0.02)
        pm.open(intent)
        hit = pm.check_sl_tp(106.0)
        assert hit is not None
        assert hit[0] == "sl"

    def test_check_sl_tp_short_tp_hit(self, pm):
        intent = PositionIntent(side="short", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=105.0, take_profit=95.0, vol=0.02)
        pm.open(intent)
        hit = pm.check_sl_tp(94.0)
        assert hit is not None
        assert hit[0] == "tp"

    def test_check_sl_tp_no_position(self, pm):
        hit = pm.check_sl_tp(100.0)
        assert hit is None

    def test_position_pnl_long(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        assert pm.position_pnl(110.0) == pytest.approx(10.0)
        assert pm.position_pnl(90.0) == pytest.approx(-10.0)

    def test_position_pnl_short(self, pm):
        intent = PositionIntent(side="short", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=105.0, take_profit=95.0, vol=0.02)
        pm.open(intent)
        expected = (100.0 / 90.0 - 1) * 100
        assert pm.position_pnl(90.0) == pytest.approx(expected, rel=1e-3)

    def test_position_pnl_no_position(self, pm):
        assert pm.position_pnl(100.0) == 0.0

    def test_compute_daily_pnl_long(self, pm):
        pnl = pm.compute_daily_pnl(direction=1, ret=0.01, pos_size=1.0)
        assert pnl == pytest.approx(10000 * 1 * 0.01 * 0.95 * 1.0)

    def test_compute_daily_pnl_short(self, pm):
        pnl = pm.compute_daily_pnl(direction=-1, ret=0.01, pos_size=0.8)
        assert pnl == pytest.approx(10000 * (-1) * 0.01 * 0.95 * 0.8)

    def test_apply_pnl(self, pm):
        pm.apply_pnl(500)
        assert pm.current_value == 10500
        assert pm.peak_value == 10500

    def test_apply_pnl_negative_does_not_update_peak(self, pm):
        pm.apply_pnl(-500)
        assert pm.current_value == 9500
        assert pm.peak_value == 10000

    def test_trade_log_after_close(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        pm.close(110.0, "2026-06-10", "tp")
        assert len(pm.trade_log) == 1
        assert pm.trade_log[0]["reason"] == "tp"

    def test_reset(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        pm.close(110.0, "2026-06-10", "tp")
        pm.reset(capital=20000)
        assert pm.initial_capital == 20000
        assert pm.current_value == 20000
        assert pm.position is None
        assert pm.trade_log == []

    @pytest.mark.parametrize("exit_price", [0, -1])
    def test_close_with_invalid_price(self, pm, exit_price):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.close(exit_price, "2026-06-10", "invalid")
        assert trade is None
        assert pm.has_position()


class TestPartialClose:
    @pytest.fixture
    def pm(self):
        return PositionManager(initial_capital=10000, position_size=0.95)

    def test_partial_close_half(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.partial_close(0.5, 110.0, "2026-06-10", "tp_partial")
        assert trade is not None
        assert trade["fraction"] == 0.5
        assert trade["pnl"] > 0

    def test_partial_close_zero_fraction_returns_none(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.partial_close(0.0, 110.0, "2026-06-10", "tp_partial")
        assert trade is None

    def test_partial_close_full_fraction_returns_trade(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.partial_close(1.0, 110.0, "2026-06-10", "tp_partial")
        assert trade is not None
        assert trade["fraction"] == 1.0
        assert pm._remaining_fraction == pytest.approx(0.0)

    def test_partial_close_excess_fraction_returns_none(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        trade = pm.partial_close(1.5, 110.0, "2026-06-10", "tp_partial")
        assert trade is None

    def test_partial_close_no_position_returns_none(self, pm):
        trade = pm.partial_close(0.5, 110.0, "2026-06-10", "tp_partial")
        assert trade is None

    def test_activate_breakeven_then_check_sl_hits(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        pm.activate_breakeven_stop()
        result = pm.check_sl_tp(99.9)
        assert result is not None
        reason, price = result
        assert reason == "breakeven"
        assert price == 100.0

    def test_breakeven_only_used_when_position_is_open(self, pm):
        intent = PositionIntent(side="long", entry_price=100.0, entry_date="2026-06-01",
                                stop_loss=95.0, take_profit=110.0, vol=0.02)
        pm.open(intent)
        pm.activate_breakeven_stop()
        pm.close(110.0, "2026-06-10", "tp")
        result = pm.check_sl_tp(99.9)
        assert result is None
