"""Unit tests for Accounting Engine."""

import pytest
from eigencapital.backtest.accounting import AccountingEngine


class TestAccountingEngine:
    def test_initial_state(self):
        acc = AccountingEngine(initial_cash=100_000)
        assert acc.current_cash == 100_000
        assert acc.position.is_flat

    def test_buy_position(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        assert acc.position.quantity == 1
        assert acc.position.average_entry_price == 4500
        assert acc.current_cash == 100_000 - 4500 * 1 * 50

    def test_sell_position(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="SELL", multiplier=50)
        assert acc.position.quantity == -1
        assert acc.position.average_entry_price == 4500
        assert acc.current_cash == 100_000 + 4500 * 1 * 50

    def test_close_position(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        acc.apply_fill(fill_price=4510, quantity=1, side="SELL", multiplier=50)
        assert acc.position.is_flat
        assert acc.position.average_entry_price == 0.0

    def test_unrealized_pnl_long(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=2, side="BUY", multiplier=50)
        unrealized = acc.compute_unrealized_pnl(current_price=4510)
        assert unrealized == 10 * 2 * 50  # 10 points * 2 qty * 50 mult

    def test_unrealized_pnl_short(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=2, side="SELL", multiplier=50)
        unrealized = acc.compute_unrealized_pnl(current_price=4490)
        assert unrealized == 10 * 2 * 50  # Short profits when price drops

    def test_commission_tracking(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50,
                       commission=2.50, fees=1.25)
        assert acc.total_commission == 2.50
        assert acc.total_fees == 1.25

    def test_equity_computation(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        equity = acc.compute_equity(current_price=4510)
        expected = acc.current_cash + (4510 - 4500) * 1 * 50
        assert equity == expected

    def test_invalid_side(self):
        acc = AccountingEngine()
        with pytest.raises(ValueError, match="side must be BUY or SELL"):
            acc.apply_fill(fill_price=4500, quantity=1, side="HOLD")

    def test_invalid_quantity(self):
        acc = AccountingEngine()
        with pytest.raises(ValueError, match="quantity must be > 0"):
            acc.apply_fill(fill_price=4500, quantity=0, side="BUY")

    def test_add_to_position(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        acc.apply_fill(fill_price=4510, quantity=1, side="BUY", multiplier=50)
        assert acc.position.quantity == 2
        # Average entry should be (4500*1 + 4510*1) / 2 = 4505
        assert abs(acc.position.average_entry_price - 4505) < 0.01

    def test_fill_history(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50)
        assert len(acc.fill_history) == 1
        assert acc.fill_history[0].side == "BUY"

    def test_summary(self):
        acc = AccountingEngine(initial_cash=100_000)
        acc.apply_fill(fill_price=4500, quantity=1, side="BUY", multiplier=50,
                       commission=2.50)
        s = acc.summary()
        assert s["initial_cash"] == 100_000
        assert s["total_fills"] == 1
        assert s["total_commission"] == 2.50
