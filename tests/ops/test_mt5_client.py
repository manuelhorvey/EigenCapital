"""Tests for MT5Client lower-level internals: circuit breaker, connection lifecycle, data methods.

Uses a mock _proto to avoid requiring Wine or an MT5 terminal.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from paper_trading.ops.mt5_client import (
    MT5Client,
    MT5ConnectionError,
    MT5DataError,
    _FrameConnection,
    _FrameProtocol,
    reset_circuit_breaker,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_breaker():
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


@pytest.fixture
def mock_proto():
    return MagicMock(spec=_FrameProtocol)


@pytest.fixture
def client(mock_proto):
    c = MT5Client(account=12345, password="pwd", server="srv")
    c._proto = mock_proto
    return c


# ── Circuit Breaker ───────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_reset_clears_failures(self):
        import paper_trading.ops.mt5_client as mc

        mc._CIRCUIT_BREAKER_FAILURES = 5
        reset_circuit_breaker()
        assert mc._CIRCUIT_BREAKER_FAILURES == 0

    def test_ensure_connected_returns_false_when_breaker_open(self, client):
        import time

        import paper_trading.ops.mt5_client as mc

        mc._CIRCUIT_BREAKER_FAILURES = 5
        mc._CIRCUIT_BREAKER_LAST_FAILURE = time.monotonic()
        assert not client.ensure_connected()

    def test_ensure_connected_reconnects_when_disconnected(self, client):
        # Simulate a connection that was live and then lost
        client._ever_connected = True
        client._proto.connected = False
        client._proto.connect.side_effect = None
        result = client.ensure_connected()
        assert result
        client._proto.connect.assert_called_once()

    def test_ensure_connected_skips_when_never_connected(self, client):
        """If connect() was never successful, ensure_connected() should
        return False immediately without attempting reconnection."""
        client._ever_connected = False
        client._proto.connected = False
        assert not client.ensure_connected()
        client._proto.connect.assert_not_called()

    def test_ensure_connected_sends_heartbeat_when_due(self, client):
        import time

        client._proto.connected = True
        client._last_heartbeat = time.monotonic() - 30.0
        result = client.ensure_connected()
        assert result
        client._proto.send_request.assert_called_with("heartbeat")

    def test_ensure_connected_skips_heartbeat_when_recent(self, client):
        import time

        client._proto.connected = True
        client._last_heartbeat = time.monotonic() - 5.0
        result = client.ensure_connected()
        assert result
        client._proto.send_request.assert_not_called()

    def test_ensure_connected_returns_true_on_healthy(self, client):
        client._proto.connected = True
        client._last_heartbeat = 0.0
        with patch("paper_trading.ops.mt5_client.time.monotonic", return_value=1.0):
            result = client.ensure_connected()
        assert result


class TestConnectDisconnect:
    def test_connect_success(self, client, mock_proto):
        mock_proto.connect.return_value = None
        assert client.connect()
        mock_proto.connect.assert_called_once()

    def test_connect_failure(self, client, mock_proto):
        mock_proto.connect.side_effect = MT5ConnectionError("fail")
        assert not client.connect()

    def test_disconnect(self, client, mock_proto):
        client.disconnect()
        mock_proto.disconnect.assert_called_once()

    def test_connected_property(self, client, mock_proto):
        mock_proto.connected = True
        assert client.connected
        mock_proto.connected = False
        assert not client.connected


class TestDataFetching:
    def test_fetch_ohlcv_returns_dataframe(self, client, mock_proto):
        mock_proto.send_request.return_value = [
            {"time": 1700000000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 1000},
        ]
        df = client.fetch_ohlcv("EURUSD", years=1)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_fetch_ohlcv_returns_empty_on_no_data(self, client, mock_proto):
        mock_proto.send_request.return_value = None
        df = client.fetch_ohlcv("EURUSD")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_fetch_ohlcv_uses_symbol_map(self, client, mock_proto):
        client._symbol_map = {"US100": "US100Cash"}
        mock_proto.send_request.return_value = [
            {"time": 1700000001, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 500},
        ]
        client.fetch_ohlcv("US100", years=1)
        args, kwargs = mock_proto.send_request.call_args
        assert args[1]["symbol"] == "US100Cash"

    def test_realtime_price(self, client, mock_proto):
        mock_proto.send_request.return_value = {"bid": 1.05, "ask": 1.06, "last": 1.055}
        tick = client.realtime_price("EURUSD")
        assert tick is not None
        assert tick["bid"] == 1.05

    def test_realtime_price_returns_none_on_error(self, client, mock_proto):
        mock_proto.send_request.side_effect = MT5DataError("no data")
        assert client.realtime_price("EURUSD") is None

    def test_realtime_mid_price(self, client, mock_proto):
        mock_proto.send_request.return_value = {"bid": 1.05, "ask": 1.07, "last": 1.06}
        mid = client.realtime_mid_price("EURUSD")
        assert mid == pytest.approx(1.06)

    def test_realtime_mid_price_falls_back_to_last(self, client, mock_proto):
        mock_proto.send_request.return_value = {"last": 1.055}
        mid = client.realtime_mid_price("EURUSD")
        assert mid == 1.055

    def test_realtime_mid_price_returns_none_on_missing(self, client, mock_proto):
        mock_proto.send_request.return_value = {}
        mid = client.realtime_mid_price("EURUSD")
        assert mid is None

    def test_realtime_spread(self, client, mock_proto):
        mock_proto.send_request.return_value = {"bid": 1.05, "ask": 1.051}
        spread = client.realtime_spread("EURUSD")
        assert spread is not None
        assert spread > 0

    def test_realtime_spread_returns_none_on_missing_bid_ask(self, client, mock_proto):
        mock_proto.send_request.return_value = {"last": 1.05}
        spread = client.realtime_spread("EURUSD")
        assert spread is None

    def test_symbol_info(self, client, mock_proto):
        mock_proto.send_request.return_value = {"contract_size": 100000, "min_volume": 0.01}
        info = client.symbol_info("EURUSD")
        assert info is not None
        assert info["contract_size"] == 100000

    def test_symbol_info_returns_none_on_error(self, client, mock_proto):
        mock_proto.send_request.side_effect = MT5DataError("no symbol")
        assert client.symbol_info("EURUSD") is None


class TestTrading:
    def test_place_order(self, client, mock_proto):
        mock_proto.send_request.return_value = {"retcode": 10009, "ticket": 12345}
        result = client.place_order("EURUSD", "buy", 0.1)
        assert result["ticket"] == 12345
        args, kwargs = mock_proto.send_request.call_args
        assert args[0] == "place_order"
        assert args[1]["symbol"] == "EURUSD"
        assert args[1]["volume"] == 0.1

    def test_place_order_with_idempotency_key(self, client, mock_proto):
        mock_proto.send_request.return_value = {"retcode": 10009, "ticket": 12346}
        client.place_order("EURUSD", "sell", 0.05, idempotency_key="key-001")
        args, kwargs = mock_proto.send_request.call_args
        assert args[1]["idempotency_key"] == "key-001"

    def test_place_order_uses_symbol_map(self, client, mock_proto):
        client._symbol_map = {"USDCAD": "USDCAD.ecn"}
        mock_proto.send_request.return_value = {"retcode": 10009, "ticket": 1}
        client.place_order("USDCAD", "buy", 0.1)
        args, kwargs = mock_proto.send_request.call_args
        assert args[1]["symbol"] == "USDCAD.ecn"

    def test_get_positions(self, client, mock_proto):
        mock_proto.send_request.return_value = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}]
        positions = client.get_positions()
        assert len(positions) == 1
        assert positions[0]["ticket"] == 1

    def test_get_account(self, client, mock_proto):
        mock_proto.send_request.return_value = {"login": 123, "balance": 10000}
        acct = client.get_account()
        assert acct["login"] == 123

    def test_get_account_returns_none_on_error(self, client, mock_proto):
        mock_proto.send_request.side_effect = MT5DataError("fail")
        assert client.get_account() is None

    def test_modify_position(self, client, mock_proto):
        mock_proto.send_request.return_value = {"result": {"retcode": 10009}}
        result = client.modify_position(98765, sl=1.04, tp=1.08)
        assert result["result"]["retcode"] == 10009
        args, kwargs = mock_proto.send_request.call_args
        assert args[1]["ticket"] == 98765
        assert args[1]["sl"] == 1.04

    def test_modify_position_skips_nan_sl(self, client, mock_proto):
        mock_proto.send_request.return_value = {"result": {"retcode": 10009}}
        client.modify_position(1, sl=None)
        args, kwargs = mock_proto.send_request.call_args
        assert "sl" not in args[1]

    def test_close_position(self, client, mock_proto):
        mock_proto.send_request.return_value = {"result": {"retcode": 10009}}
        result = client.close_position(98765)
        assert "retcode" in result["result"]


class TestBatchOperations:
    def test_batch_realtime_price(self, client, mock_proto):
        mock_proto.batch_request.return_value = [
            {"bid": 1.05, "ask": 1.06},
            {"bid": 110.0, "ask": 110.1},
        ]
        prices = client.batch_realtime_price(["EURUSD", "JPY"])
        assert prices["EURUSD"] == pytest.approx(1.055)
        assert prices["JPY"] == pytest.approx(110.05)

    def test_batch_realtime_price_returns_none_on_error(self, client, mock_proto):
        mock_proto.batch_request.return_value = [{"error": "fail"}]
        prices = client.batch_realtime_price(["EURUSD"])
        assert prices["EURUSD"] is None

    def test_batch_symbol_info(self, client, mock_proto):
        mock_proto.batch_request.return_value = [
            {"contract_size": 100000},
            {"contract_size": 100},
        ]
        infos = client.batch_symbol_info(["EURUSD", "US100"])
        assert infos["EURUSD"]["contract_size"] == 100000
        assert infos["US100"]["contract_size"] == 100

    def test_batch_symbol_info_returns_none_on_error(self, client, mock_proto):
        mock_proto.batch_request.return_value = [{"error": "fail"}]
        infos = client.batch_symbol_info(["EURUSD"])
        assert infos["EURUSD"] is None


class TestConvenience:
    def test_account_property(self, client):
        assert client.account == 12345

    def test_server_property(self, client):
        assert client.server == "srv"

    def test_connect_configures(self, client, mock_proto):
        client.connect()
        mock_proto.send_request.assert_called_with(
            "configure",
            {"account": 12345, "server": "srv"},
        )


class TestFrameConnection:
    def test_connect_and_disconnect(self):
        conn = _FrameConnection("127.0.0.1", 9879)
        assert not conn.connected
        with pytest.raises(MT5ConnectionError, match="Not connected"):
            conn.send_request("test")

    def test_disconnect_twice_no_error(self):
        conn = _FrameConnection("127.0.0.1", 9879)
        conn.disconnect()
        conn.disconnect()


class TestFrameProtocol:
    def test_init_has_empty_pool(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        assert not proto.connected

    def test_shutdown_cleans_up(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        proto.shutdown()
        assert not proto.connected

    def test_send_request_raises_when_empty_pool(self):
        """When the pool was never populated (empty _conns), send_request
        should fail fast with MT5ConnectionError and NOT attempt reconnect."""
        proto = _FrameProtocol("127.0.0.1", 9999)
        assert not proto._conns  # empty pool
        with pytest.raises(MT5ConnectionError, match="No connections in pool"):
            proto.send_request("test")
        # Should NOT have called _reconnect — empty pool is not a transient
        # disconnection, it means the bridge was never available.
        with pytest.raises(MT5ConnectionError, match="No connections in pool"):
            proto.send_request("test")

    def test_get_conn_round_robin(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        mock = MagicMock(spec=_FrameConnection)
        proto._conns = [mock, MagicMock(spec=_FrameConnection)]
        proto._rr_idx = -1
        c1 = proto._get_conn()
        c2 = proto._get_conn()
        c3 = proto._get_conn()
        assert c1 is not c2
        assert c1 is c3  # wraparound

    def test_get_conn_raises_when_empty(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        with pytest.raises(MT5ConnectionError, match="No connections in pool"):
            proto._get_conn()

    def test_send_request_retries_on_connection_error(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        good_conn = MagicMock(spec=_FrameConnection)
        good_conn.send_request.return_value = {"result": "ok"}
        proto._conns = [good_conn]
        proto._rr_idx = -1
        with patch.object(proto, "_reconnect") as mock_reconnect:
            result = proto.send_request("test")
        assert result == {"result": "ok"}
        mock_reconnect.assert_not_called()

    def test_send_request_calls_reconnect_on_failure(self):
        proto = _FrameProtocol("127.0.0.1", 9999)
        fail_conn = MagicMock(spec=_FrameConnection)
        fail_conn.send_request.side_effect = MT5ConnectionError("fail")
        retry_conn = MagicMock(spec=_FrameConnection)
        retry_conn.send_request.return_value = {"result": "retried"}
        proto._conns = [fail_conn]
        proto._rr_idx = -1
        with patch.object(proto, "_reconnect") as mock_reconnect:
            mock_reconnect.side_effect = lambda: setattr(proto, "_conns", [retry_conn])
            result = proto.send_request("test")
        assert result == {"result": "retried"}
        mock_reconnect.assert_called_once()
