"""Tests for MT5Broker using MockMT5Client.

Covers the full BrokerInterface contract via the real MT5 bridge path,
without requiring Wine or an MT5 terminal.
"""

from __future__ import annotations

import pytest

from paper_trading.execution.broker_interface import BrokerInterface, Order
from paper_trading.execution.mt5_broker import MT5Broker
from tests.mock_mt5_client import MockMT5Client


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    return MockMT5Client()


@pytest.fixture
def broker(mock_client):
    return MT5Broker(client=mock_client)


# ── Interface compliance ────────────────────────────────────────────────


class TestInterfaceCompliance:
    def test_is_broker_interface(self, broker):
        assert isinstance(broker, BrokerInterface)

    def test_implements_all_abstract_methods(self):
        from paper_trading.execution.broker_interface import BrokerInterface

        abstract = set(BrokerInterface.__abstractmethods__)  # type: ignore[attr-defined]
        concrete = set(
            name for name in dir(MT5Broker) if not name.startswith("_")
        )
        assert abstract.issubset(concrete), f"Missing: {abstract - concrete}"


# ── Connection lifecycle ─────────────────────────────────────────────────


class TestConnection:
    def test_connect_success(self, broker, mock_client):
        assert broker.connect()
        assert mock_client.calls["connect"] == [()]
        assert broker._connected

    def test_connect_failure(self, mock_client):
        mock_client._connect_fails = True
        broker = MT5Broker(client=mock_client)
        assert not broker.connect()
        assert not broker._connected

    def test_disconnect(self, broker, mock_client):
        broker.connect()
        broker.disconnect()
        assert mock_client.calls["disconnect"] == [()]
        assert not broker._connected

    def test_ensure_connected_when_disconnected(self, broker, mock_client):
        assert broker.ensure_connected()
        assert "ensure_connected" in mock_client.calls or "connect" in mock_client.calls

    def test_ensure_connected_when_connected(self, broker, mock_client):
        broker.connect()
        mock_client.calls.clear()
        assert broker.ensure_connected()
        assert "ensure_connected" in mock_client.calls or "connect" in mock_client.calls


# ── Account ─────────────────────────────────────────────────────────────


class TestAccount:
    def test_get_account_summary(self, broker, mock_client):
        broker.connect()
        summary = broker.get_account_summary()
        assert summary.total_cash == 10000.0
        assert summary.buying_power == 10000.0 * 100  # equity * leverage
        assert summary.portfolio_value == 10000.0
        assert "get_account" in mock_client.calls

    def test_get_account_summary_no_info(self, mock_client):
        mock_client._account_info = None
        broker = MT5Broker(client=mock_client)
        broker.connect()
        with pytest.raises(ConnectionError, match="Cannot fetch account info"):
            broker.get_account_summary()


# ── Orders ──────────────────────────────────────────────────────────────


class TestPlaceOrder:
    def test_place_market_order_success(self, broker, mock_client):
        broker.connect()
        order = Order(
            asset="EURUSD",
            side="buy",
            quantity=10000,
            order_type="market",
        )
        order_id = broker.place_order(order)
        assert order_id == "98765"
        assert mock_client.calls["place_order"][0][0] == "EURUSD"
        assert mock_client.calls["place_order"][0][1] == "buy"

    def test_place_order_rejected(self, mock_client):
        mock_client._order_result = {"retcode": 10013, "ticket": 0}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        order = Order(asset="EURUSD", side="buy", quantity=10000, order_type="market")
        order_id = broker.place_order(order)
        assert order_id == ""

    def test_place_non_market_order(self, broker, mock_client):
        broker.connect()
        order = Order(asset="EURUSD", side="buy", quantity=10000, order_type="limit")
        order_id = broker.place_order(order)
        assert order_id == ""

    def test_place_order_exception_returns_empty(self, mock_client):
        def fail(*args, **kwargs):
            raise RuntimeError("Bridge unavailable")

        mock_client.place_order = fail
        broker = MT5Broker(client=mock_client)
        broker.connect()
        order = Order(asset="EURUSD", side="buy", quantity=10000, order_type="market")
        order_id = broker.place_order(order)
        assert order_id == ""


# ── Positions ───────────────────────────────────────────────────────────


class TestPositions:
    def test_get_positions_empty(self, broker, mock_client):
        broker.connect()
        positions = broker.get_positions()
        assert positions == []

    def test_get_positions_with_data(self, mock_client):
        mock_client._positions = [
            {
                "type": "buy",
                "symbol": "EURUSD",
                "volume": 0.1,
                "price_open": 1.0500,
                "price_current": 1.0550,
                "profit": 50.0,
                "commission": -1.0,
            }
        ]
        broker = MT5Broker(client=mock_client)
        broker.connect()
        positions = broker.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p.asset == "EURUSD"
        assert p.quantity == 0.1 * 100000  # lots_to_quantity
        assert p.avg_entry_price == 1.0500
        assert p.current_price == 1.0550
        assert p.unrealized_pnl == 50.0

    def test_position_cache_used(self, mock_client):
        mock_client._positions = [
            {"type": "sell", "symbol": "EURUSD", "volume": 0.1, "price_open": 1.0500, "price_current": 1.0450, "profit": 50.0, "commission": 0.0}
        ]
        broker = MT5Broker(client=mock_client)
        broker.connect()
        mock_client.calls.clear()

        broker.get_positions()
        broker.get_positions()
        # Should only call client.get_positions() once; second call hits cache
        assert len(mock_client.calls.get("get_positions", [])) == 1

    def test_close_position_success(self, broker, mock_client):
        broker.connect()
        assert broker.close_position("EURUSD", "98765")
        assert mock_client.calls["close_position"] == [(98765,)]

    def test_close_position_failure(self, mock_client):
        mock_client._close_result = {"result": {"retcode": -1}}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        assert not broker.close_position("EURUSD", "98765")

    def test_modify_position_success(self, broker, mock_client):
        broker.connect()
        assert broker.modify_position("EURUSD", "98765", sl=1.0400, tp=1.0700)
        assert mock_client.calls["modify_position"] == [(98765, 1.0400, 1.0700)]

    def test_modify_position_failure(self, mock_client):
        mock_client._modify_result = {"result": {"retcode": -1}}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        assert not broker.modify_position("EURUSD", "98765", sl=1.0400)


# ── Price ───────────────────────────────────────────────────────────────


class TestPrice:
    def test_get_current_price(self, mock_client):
        mock_client._realtime_prices = {"EURUSD": 1.0500}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        price = broker.get_current_price("EURUSD")
        assert price == 1.0500
        assert "realtime_mid_price" in mock_client.calls

    def test_get_current_price_none_returns_zero(self, mock_client):
        mock_client._realtime_prices = {"EURUSD": None}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        price = broker.get_current_price("EURUSD")
        assert price == 0.0


# ── Lot conversion ──────────────────────────────────────────────────────


class TestLotConversion:
    def test_quantity_to_lots(self, mock_client):
        broker = MT5Broker(client=mock_client)
        broker.connect()
        lots = broker._quantity_to_lots("EURUSD", 100000)
        assert lots == 1.0

    def test_quantity_to_lots_with_custom_size(self, mock_client):
        mock_client._symbol_infos["EURUSD"] = {
            "contract_size": 1000.0,
            "volume_step": 0.1,
            "min_volume": 0.1,
            "max_volume": 1000.0,
        }
        broker = MT5Broker(client=mock_client)
        broker.connect()
        lots = broker._quantity_to_lots("EURUSD", 5000)
        assert lots == 5.0

    def test_lots_to_quantity(self, mock_client):
        broker = MT5Broker(client=mock_client)
        broker.connect()
        qty = broker._lots_to_quantity("EURUSD", 1.0)
        assert qty == 100000.0

    def test_cancel_order_not_implemented(self, broker):
        assert not broker.cancel_order("12345")

    def test_get_order_status_always_filled(self, broker):
        assert broker.get_order_status("12345") == "filled"


class TestBatchPrices:
    def test_get_current_prices_returns_all(self, mock_client):
        mock_client._realtime_prices = {"EURUSD": 1.05, "GBPUSD": 1.25}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        prices = broker.get_current_prices(["EURUSD", "GBPUSD"])
        assert prices["EURUSD"] == pytest.approx(1.05)
        assert prices["GBPUSD"] == pytest.approx(1.25)
        assert "batch_realtime_price" in mock_client.calls

    def test_get_current_prices_fallback_zero(self, mock_client):
        mock_client._realtime_prices = {"EURUSD": None}
        broker = MT5Broker(client=mock_client)
        broker.connect()
        prices = broker.get_current_prices(["EURUSD"])
        assert prices["EURUSD"] == 0.0
