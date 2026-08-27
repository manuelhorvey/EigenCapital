"""Trading Provider Contract Tests — prove platform abstraction works.

These tests verify that:
1. The TradingProvider ABC is well-defined
2. Platform-specific providers satisfy the contract
3. Data models are correct
4. The factory function works
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.execution.trading_provider import (
    AccountInfo,
    BarData,
    LinuxMT5Provider,
    OrderRequest,
    OrderResult,
    OrderSide,
    PositionInfo,
    SymbolInfo,
    TickInfo,
    TradingProvider,
    WindowsMT5Provider,
    create_trading_provider,
)


class TestDataProviderModels:
    """Test the data models used by TradingProvider."""

    def test_account_info_creation(self):
        info = AccountInfo(login=12345, balance=10000, equity=10500)
        assert info.login == 12345
        assert info.balance == 10000
        assert info.equity == 10500
        assert info.currency == "USD"

    def test_account_info_immutable(self):
        info = AccountInfo(login=12345)
        with pytest.raises(AttributeError):
            info.login = 99999

    def test_position_info_creation(self):
        pos = PositionInfo(ticket=1001, symbol="EURUSD", side="BUY", volume=0.1, price_open=1.1000)
        assert pos.ticket == 1001
        assert pos.symbol == "EURUSD"
        assert pos.side == "BUY"
        assert pos.volume == 0.1

    def test_position_info_immutable(self):
        pos = PositionInfo(ticket=1001)
        with pytest.raises(AttributeError):
            pos.ticket = 9999

    def test_tick_info_creation(self):
        tick = TickInfo(bid=1.1000, ask=1.1002)
        assert tick.bid == 1.1000
        assert tick.ask == 1.1002

    def test_symbol_info_creation(self):
        sym = SymbolInfo(symbol="EURUSD", spread=12, digits=5, trade_contract_size=100000, volume_min=0.01)
        assert sym.symbol == "EURUSD"
        assert sym.spread == 12
        assert sym.volume_min == 0.01

    def test_order_request_creation(self):
        req = OrderRequest(symbol="EURUSD", side="BUY", volume=0.1, price=1.1000)
        assert req.symbol == "EURUSD"
        assert req.side == "BUY"
        assert req.volume == 0.1

    def test_order_result_creation(self):
        res = OrderResult(success=True, deal=5001, price=1.1001)
        assert res.success is True
        assert res.deal == 5001

    def test_bar_data_creation(self):
        bar = BarData(time=1700000000, open=1.1, high=1.11, low=1.09, close=1.105)
        assert bar.open == 1.1
        assert bar.close == 1.105


class TestOrderSideEnum:
    def test_order_sides(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"


class TestLinuxMT5ProviderContract:
    """Verify LinuxMT5Provider satisfies TradingProvider interface."""

    def test_is_subclass(self):
        assert issubclass(LinuxMT5Provider, TradingProvider)

    def test_has_required_methods(self):
        provider = LinuxMT5Provider()
        assert hasattr(provider, "connect")
        assert hasattr(provider, "disconnect")
        assert hasattr(provider, "is_connected")
        assert hasattr(provider, "account_info")
        assert hasattr(provider, "positions_get")
        assert hasattr(provider, "symbol_info")
        assert hasattr(provider, "symbol_info_tick")
        assert hasattr(provider, "symbol_select")
        assert hasattr(provider, "copy_rates_from_pos")
        assert hasattr(provider, "order_send")
        assert hasattr(provider, "last_error")

    def test_not_connected_returns_none(self):
        """Before connecting, all queries should return None/empty."""
        provider = LinuxMT5Provider()
        assert provider.is_connected() is False
        assert provider.account_info() is None
        assert provider.positions_get() == []
        assert provider.symbol_info("EURUSD") is None
        assert provider.symbol_info_tick("EURUSD") is None

    def test_disconnect_is_idempotent(self):
        provider = LinuxMT5Provider()
        provider.disconnect()  # Should not raise
        provider.disconnect()  # Should not raise

    def test_order_send_when_not_connected(self):
        provider = LinuxMT5Provider()
        req = OrderRequest(symbol="EURUSD", side="BUY", volume=0.1)
        result = provider.order_send(req)
        assert result.success is False
        assert "Not connected" in result.comment


class TestWindowsMT5ProviderContract:
    """Verify WindowsMT5Provider satisfies TradingProvider interface."""

    def test_is_subclass(self):
        assert issubclass(WindowsMT5Provider, TradingProvider)

    def test_has_required_methods(self):
        provider = WindowsMT5Provider()
        assert hasattr(provider, "connect")
        assert hasattr(provider, "disconnect")
        assert hasattr(provider, "is_connected")
        assert hasattr(provider, "account_info")
        assert hasattr(provider, "positions_get")
        assert hasattr(provider, "symbol_info")
        assert hasattr(provider, "symbol_info_tick")
        assert hasattr(provider, "symbol_select")
        assert hasattr(provider, "copy_rates_from_pos")
        assert hasattr(provider, "order_send")
        assert hasattr(provider, "last_error")

    def test_not_connected_returns_none(self):
        provider = WindowsMT5Provider()
        assert provider.is_connected() is False
        assert provider.account_info() is None
        assert provider.positions_get() == []

    def test_connect_fails_gracefully_on_linux(self):
        """WindowsMT5Provider.connect() should fail gracefully on Linux."""
        provider = WindowsMT5Provider()
        result = provider.connect()
        # May succeed or fail depending on whether MetaTrader5 is installed
        # But should not raise
        assert isinstance(result, bool)


class TestFactory:
    """Test the create_trading_provider factory."""

    def test_factory_returns_provider(self):
        """Factory should return a TradingProvider instance."""
        try:
            provider = create_trading_provider()
            assert isinstance(provider, TradingProvider)
        except RuntimeError:
            # Acceptable if no MT5 is available in test environment
            pass
