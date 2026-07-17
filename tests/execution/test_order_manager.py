"""Tests for OrderManager."""

import pytest
from unittest.mock import MagicMock

from paper_trading.execution.order_manager import OrderManager
from paper_trading.execution.broker_interface import BrokerInterface


class MockBroker(BrokerInterface):
    def __init__(self):
        self._next_id = 1
        self._orders: dict[str, dict] = {}
        self.cancelled: list[str] = []

    def connect(self) -> bool:
        return True

    def disconnect(self) -> bool:
        return True

    def get_account_summary(self):
        return None

    def place_order(self, order) -> str:
        order_id = f"MOCK-{self._next_id}"
        self._next_id += 1
        self._orders[order_id] = {"status": "pending", "order": order}
        return order_id

    def place_filled_order(self, order, fill_price) -> str:
        order_id = f"MOCK-{self._next_id}"
        self._next_id += 1
        self._orders[order_id] = {"status": "filled", "order": order}
        return order_id

    def cancel_order(self, order_id) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            self.cancelled.append(order_id)
            return True
        return False

    def get_order_status(self, order_id):
        return self._orders.get(order_id, {}).get("status")

    def get_positions(self):
        return []

    def close_position(self, asset: str, position_id: str) -> bool:
        return True

    def modify_position(self, asset: str, position_id: str, sl: float | None = None, tp: float | None = None) -> bool:
        return True

    def get_current_price(self, asset: str) -> float:
        return 1.0


@pytest.fixture
def om():
    return OrderManager(MockBroker())


class TestOrderManager:
    def test_submit_market_order_tracked(self, om):
        order_id = om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        assert order_id in om.pending_orders
        assert om.pending_orders[order_id].asset == "EURUSD"
        assert om.pending_orders[order_id].side == "buy"

    def test_two_submissions_get_different_ids(self, om):
        first = om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        second = om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        assert first != second
        assert len(om.pending_orders) == 2

    def test_cancel_order(self, om):
        order_id = om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        ok = om.cancel_order(order_id)
        assert ok is True
        assert order_id not in om.pending_orders

    def test_cancel_nonexistent_order(self, om):
        ok = om.cancel_order("nonexistent")
        assert ok is False

    def test_get_open_quantity(self, om):
        om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        qty = om.get_open_quantity("EURUSD")
        assert qty == 1_000

    def test_has_pending(self, om):
        assert om.has_pending is False
        om.submit_market_order("EURUSD", "buy", 1_000, fill_price=1.10)
        assert om.has_pending is True
