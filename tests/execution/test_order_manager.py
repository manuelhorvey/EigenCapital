"""Tests for OrderManager."""
import pytest

from paper_trading.execution.order_manager import OrderManager


class TestOrderManager:
    def test_submit_order_tracked(self):
        om = OrderManager()
        order_id = om.submit("EURUSD", "long", 1_000, 1.10)
        order = om.get_order(order_id)
        assert order is not None
        assert order["asset"] == "EURUSD"
        assert order["side"] == "long"

    def test_duplicate_idempotency_key_rejected(self):
        om = OrderManager()
        first = om.submit("EURUSD", "long", 1_000, 1.10)
        second = om.submit("EURUSD", "long", 1_000, 1.10)
        assert first == second

    def test_get_nonexistent_order(self):
        om = OrderManager()
        assert om.get_order("nonexistent") is None
