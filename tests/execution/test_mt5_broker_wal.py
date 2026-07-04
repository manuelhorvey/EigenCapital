"""Tests for MT5Broker WAL event emission during order lifecycle."""

from __future__ import annotations

import pytest

from paper_trading.execution.broker_interface import Order
from paper_trading.execution.mt5_broker import MT5Broker
from tests.mock_mt5_client import MockMT5Client


class _WalRecorder:
    """Captures WAL events in memory for test assertions."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def write(self, event_type: str, payload: dict):
        self.events.append((event_type, payload))


@pytest.fixture
def wal_recorder():
    return _WalRecorder()


@pytest.fixture
def mock_client():
    return MockMT5Client()


@pytest.fixture
def broker(mock_client, wal_recorder):
    b = MT5Broker(client=mock_client)
    b.set_wal_writer(wal_recorder)
    return b


class TestMT5BrokerWAL:
    def test_place_order_emits_placed_and_filled(self, broker, wal_recorder):
        order = Order(asset="EURUSD", side="buy", quantity=1000, order_type="market")
        broker.place_order(order)

        events = {t for t, _ in wal_recorder.events}
        assert "mt5_order_placed" in events
        assert "mt5_order_filled" in events
        assert "mt5_order_rejected" not in events

    def test_place_order_rejected_emits_rejected(self, mock_client, wal_recorder):
        mock_client._order_result = {"retcode": 10010, "ticket": 0}
        broker = MT5Broker(client=mock_client)
        broker.set_wal_writer(wal_recorder)

        order = Order(asset="EURUSD", side="buy", quantity=1000, order_type="market")
        broker.place_order(order)

        event_types = {t for t, _ in wal_recorder.events}
        assert "mt5_order_placed" in event_types
        assert "mt5_order_rejected" in event_types
        assert "mt5_order_filled" not in event_types

    def test_place_order_rejected_includes_retcode(self, mock_client, wal_recorder):
        mock_client._order_result = {"retcode": 10010, "ticket": 0}
        broker = MT5Broker(client=mock_client)
        broker.set_wal_writer(wal_recorder)

        order = Order(asset="EURUSD", side="buy", quantity=1000, order_type="market")
        broker.place_order(order)

        rejected_events = [(t, p) for t, p in wal_recorder.events if t == "mt5_order_rejected"]
        assert len(rejected_events) == 1
        assert rejected_events[0][1]["retcode"] == 10010
        assert rejected_events[0][1]["asset"] == "EURUSD"

    def test_place_order_rejects_non_market(self, broker, wal_recorder):
        order = Order(asset="EURUSD", side="buy", quantity=1000, order_type="limit")
        broker.place_order(order)

        event_types = {t for t, _ in wal_recorder.events}
        assert "mt5_order_rejected" in event_types
        assert "mt5_order_filled" not in event_types

    def test_close_position_emits_closed_event(self, broker, wal_recorder):
        broker.close_position("EURUSD", "98765")

        event_types = {t for t, _ in wal_recorder.events}
        assert "mt5_position_closed" in event_types

    def test_close_position_rejected(self, mock_client, wal_recorder):
        mock_client._close_result = {"result": {"retcode": 10010}}
        broker = MT5Broker(client=mock_client)
        broker.set_wal_writer(wal_recorder)

        broker.close_position("EURUSD", "98765")

        closed_events = [(t, p) for t, p in wal_recorder.events if t == "mt5_position_closed"]
        assert len(closed_events) == 1
        assert closed_events[0][1]["reason"] == "close_failed"
        assert closed_events[0][1]["retcode"] == 10010

    def test_close_position_already_closed(self, mock_client, wal_recorder):
        mock_client._close_result = {"error": "not found"}
        broker = MT5Broker(client=mock_client)
        broker.set_wal_writer(wal_recorder)

        broker.close_position("EURUSD", "98765")

        closed_events = [(t, p) for t, p in wal_recorder.events if t == "mt5_position_closed"]
        assert len(closed_events) == 1
        assert closed_events[0][1]["reason"] == "already_closed"

    def test_modify_position_emits_modified(self, broker, wal_recorder):
        broker.modify_position("EURUSD", "98765", sl=1.05, tp=1.15)

        event_types = {t for t, _ in wal_recorder.events}
        assert "mt5_order_modified" in event_types

    def test_modify_position_includes_sl_tp(self, broker, wal_recorder):
        broker.modify_position("EURUSD", "98765", sl=1.05, tp=1.15)

        modified_events = [(t, p) for t, p in wal_recorder.events if t == "mt5_order_modified"]
        assert len(modified_events) == 1
        assert modified_events[0][1]["sl"] == 1.05
        assert modified_events[0][1]["tp"] == 1.15
        assert modified_events[0][1]["ticket"] == "98765"

    def test_no_wal_writer_does_not_crash(self, mock_client):
        """Broker without WAL writer should not raise."""
        broker = MT5Broker(client=mock_client)
        order = Order(asset="EURUSD", side="buy", quantity=1000, order_type="market")
        broker.place_order(order)
        assert broker.close_position("EURUSD", "98765") is True
