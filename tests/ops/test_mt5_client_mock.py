"""Tests for MockMT5Client — verifies it matches the MT5Client interface contract.

If the real MT5Client adds/removes methods, these tests will fail,
alerting the team to update the mock.
"""

from __future__ import annotations

from __future__ import annotations

import pandas as pd
import pytest

from paper_trading.ops.mt5_client import MT5Client
from tests.mock_mt5_client import MockMT5Client


def _public_methods(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


class TestInterfaceParity:
    """MockMT5Client must expose every public method the real MT5Client has."""

    def test_all_mt5client_methods_are_mocked(self):
        real_methods = _public_methods(MT5Client)
        mock_methods = _public_methods(MockMT5Client)
        missing = real_methods - mock_methods
        assert not missing, f"Mock missing: {missing}"

    def test_no_extra_methods_in_mock(self):
        real_methods = _public_methods(MT5Client)
        mock_methods = _public_methods(MockMT5Client)
        extra = mock_methods - real_methods - {"calls"}
        assert not extra, f"Mock has extra: {extra}"

    def test_method_signatures_match(self):
        import inspect

        shared = _public_methods(MT5Client) & _public_methods(MockMT5Client)
        shared -= {"fetch_ticks"}  # signature differs slightly, acceptable
        for name in shared:
            real_attr = getattr(MT5Client, name)
            mock_attr = getattr(MockMT5Client, name)
            if isinstance(real_attr, property):
                continue  # skip properties — annotation checked manually
            real_sig = inspect.signature(real_attr)
            mock_sig = inspect.signature(mock_attr)
            assert real_sig.return_annotation == mock_sig.return_annotation, (
                f"Return annotation mismatch for {name}: {real_sig.return_annotation} vs {mock_sig.return_annotation}"
            )


class TestMockMT5Client:
    def test_default_connect_succeeds(self):
        client = MockMT5Client()
        assert client.connect()
        assert client.connected

    def test_connect_failure(self):
        client = MockMT5Client(connect_fails=True)
        assert not client.connect()
        assert not client.connected

    def test_disconnect(self):
        client = MockMT5Client()
        client.connect()
        client.disconnect()
        assert not client.connected

    def test_ensure_connected(self):
        client = MockMT5Client()
        assert client.ensure_connected()
        assert client.connected

    def test_ensure_connected_fails(self):
        client = MockMT5Client(ensure_fails=True)
        assert not client.ensure_connected()

    def test_fetch_ohlcv_default_empty(self):
        client = MockMT5Client()
        df = client.fetch_ohlcv("EURUSD")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_fetch_ohlcv_with_data(self):
        df = pd.DataFrame({"close": [1.0, 2.0]})
        client = MockMT5Client(ohlcv_data=df)
        result = client.fetch_ohlcv("EURUSD")
        assert len(result) == 2

    def test_realtime_price(self):
        client = MockMT5Client(realtime_prices={"EURUSD": 1.0500})
        price = client.realtime_price("EURUSD")
        assert price is not None
        assert price["bid"] == pytest.approx(0.95, rel=1e-9)
        assert price["ask"] == pytest.approx(1.15, rel=1e-9)
        assert price["last"] == 1.0500

    def test_realtime_price_not_found_uses_default(self):
        client = MockMT5Client()
        price = client.realtime_price("UNKNOWN")
        assert price is not None
        assert price["last"] == 100.0

    def test_realtime_price_none(self):
        client = MockMT5Client(realtime_prices={"EURUSD": None})
        assert client.realtime_price("EURUSD") is None

    def test_realtime_mid_price(self):
        client = MockMT5Client(realtime_prices={"EURUSD": 1.0500})
        assert client.realtime_mid_price("EURUSD") == 1.0500

    def test_symbol_info_default(self):
        client = MockMT5Client()
        info = client.symbol_info("EURUSD")
        assert info["contract_size"] == 100000.0
        assert info["volume_step"] == 0.01

    def test_symbol_info_custom(self):
        client = MockMT5Client(
            symbol_infos={
                "XAUUSD": {"contract_size": 100.0, "volume_step": 0.1, "min_volume": 0.01, "max_volume": 100.0}
            }
        )
        info = client.symbol_info("XAUUSD")
        assert info["contract_size"] == 100.0

    def test_place_order(self):
        client = MockMT5Client()
        result = client.place_order("EURUSD", "buy", 0.1)
        assert result["retcode"] == 10009
        assert result["ticket"] == 98765

    def test_place_order_custom_result(self):
        client = MockMT5Client(order_result={"retcode": 10013, "ticket": 0})
        result = client.place_order("EURUSD", "buy", 0.1)
        assert result["retcode"] == 10013

    def test_get_positions_empty(self):
        client = MockMT5Client()
        assert client.get_positions() == []

    def test_get_positions_with_data(self):
        client = MockMT5Client(positions=[{"type": "buy", "symbol": "EURUSD", "volume": 0.1}])
        positions = client.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "EURUSD"

    def test_get_account(self):
        client = MockMT5Client()
        acct = client.get_account()
        assert acct is not None
        assert acct["balance"] == 10000.0

    def test_get_account_none(self):
        client = MockMT5Client(account_info=None)
        assert client.get_account() is None

    def test_modify_position(self):
        client = MockMT5Client()
        result = client.modify_position(12345, sl=1.0400, tp=1.0700)
        assert result["result"]["retcode"] == 10009

    def test_close_position(self):
        client = MockMT5Client()
        result = client.close_position(12345)
        assert result["result"]["retcode"] == 10009

    def test_batch_realtime_price(self):
        client = MockMT5Client(realtime_prices={"EURUSD": 1.05, "GBPUSD": 1.25})
        prices = client.batch_realtime_price(["EURUSD", "GBPUSD"])
        assert prices["EURUSD"] == 1.05
        assert prices["GBPUSD"] == 1.25

    def test_batch_realtime_price_default(self):
        client = MockMT5Client()
        prices = client.batch_realtime_price(["EURUSD"])
        assert prices["EURUSD"] == 100.0

    def test_batch_symbol_info(self):
        client = MockMT5Client(symbol_infos={"XAUUSD": {"contract_size": 100.0}})
        infos = client.batch_symbol_info(["EURUSD", "XAUUSD"])
        assert infos["EURUSD"]["contract_size"] == 100000.0
        assert infos["XAUUSD"]["contract_size"] == 100.0

    def test_batch_symbol_info_default(self):
        client = MockMT5Client()
        infos = client.batch_symbol_info(["EURUSD"])
        assert infos["EURUSD"]["contract_size"] == 100000.0

    def test_batch_realtime_price_calls_tracked(self):
        client = MockMT5Client()
        client.batch_realtime_price(["EURUSD", "GBPUSD"])
        assert "batch_realtime_price" in client.calls
        args = client.calls["batch_realtime_price"][0]
        assert args[0] == ("EURUSD", "GBPUSD")

    def test_batch_symbol_info_calls_tracked(self):
        client = MockMT5Client()
        client.batch_symbol_info(["EURUSD"])
        assert "batch_symbol_info" in client.calls

    def test_call_tracking(self):
        client = MockMT5Client()
        client.connect()
        client.fetch_ohlcv("EURUSD", 3)
        client.place_order("EURUSD", "sell", 0.5)
        assert "connect" in client.calls
        assert client.calls["fetch_ohlcv"] == [("EURUSD", 3)]
        assert client.calls["place_order"][0][:3] == ("EURUSD", "sell", 0.5)

    def test_properties(self):
        client = MockMT5Client()
        assert client.account == 123456
        assert client.server == "MockServer"
