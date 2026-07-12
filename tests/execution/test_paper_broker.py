import numpy as np
import pytest
from unittest.mock import patch

from paper_trading.execution.broker_interface import Order
from paper_trading.execution.paper_broker import PaperBroker
from shared.execution_config import ExecutionConfig, compute_slippage_cost


@pytest.fixture
def zero_spread_config():
    return ExecutionConfig(
        base_spread_bps=0.0,
        spread_vol_slope=0.0,
        spread_max_bps=0.0,
        impact_model="none",
    )


@pytest.fixture
def priced_broker(zero_spread_config):
    b = PaperBroker(
        initial_capital=100000,
        execution_configs={"TEST": zero_spread_config, "ASSET_A": zero_spread_config, "ASSET_B": zero_spread_config},
        fees=0.0,
    )
    b.set_price("TEST", 100.0)
    b.set_price("ASSET_A", 50.0)
    b.set_price("ASSET_B", 100.0)
    return b


class TestPaperBroker:
    @pytest.fixture(autouse=True)
    def _mock_yfinance(self):
        with patch("paper_trading.execution.paper_broker.yf.Ticker", side_effect=ConnectionError("yfinance unavailable")):
            yield

    @pytest.fixture
    def broker(self, zero_spread_config):
        return PaperBroker(
            initial_capital=100000,
            execution_configs={"TEST": zero_spread_config},
            fees=0.0,
        )

    def test_initial_state(self, broker):
        summary = broker.get_account_summary()
        assert summary.total_cash == 100000
        assert summary.buying_power == 200000
        assert summary.portfolio_value == 100000
        assert len(summary.positions) == 0

    def test_connect_disconnect(self, broker):
        assert broker.connect() is True
        assert broker.disconnect() is True

    def test_get_current_price_returns_zero_for_unknown(self, broker):
        price = broker.get_current_price("NONEXISTENT_SYMBOL_12345")
        assert price == 0.0

    def test_place_buy_order_insufficient_cash(self, priced_broker):
        order = Order(asset="TEST", side="buy", quantity=1e9, order_type="market")
        order_id = priced_broker.place_order(order)
        assert order_id != ""
        summary = priced_broker.get_account_summary()
        assert summary.total_cash < 100000

    def test_place_sell_no_position(self, broker):
        order = Order(asset="TEST", side="sell", quantity=100, order_type="market")
        order_id = broker.place_order(order)
        assert order_id == ""

    def test_place_sell_no_position_can_open_short_when_enabled(self, zero_spread_config):
        broker = PaperBroker(
            initial_capital=100000,
            execution_configs={"TEST": zero_spread_config},
            fees=0.0,
            allow_short=True,
        )
        broker.set_price("TEST", 100.0)
        order_id = broker.place_order(Order(asset="TEST", side="sell", quantity=10, order_type="market"))

        assert order_id != ""
        position = broker.get_positions()[0]
        assert position.quantity == -10
        assert broker.get_account_summary().portfolio_value == 100000

    def test_cancel_order(self, broker):
        assert broker.cancel_order("1") is False

    def test_get_order_status_unknown(self, broker):
        assert broker.get_order_status("999") == "unknown"

    def test_get_positions_empty(self, broker):
        assert broker.get_positions() == []

    def test_refresh_prices_empty(self, broker):
        broker.refresh_prices()

    def test_reset(self, priced_broker):
        priced_broker.place_order(Order(asset="TEST", side="buy", quantity=10, order_type="market"))
        priced_broker.reset(capital=50000)
        assert priced_broker.initial_capital == 50000
        assert priced_broker.cash == 50000
        assert len(priced_broker._positions) == 0

    def test_buy_order_fills_and_tracks_position(self, priced_broker):
        order = Order(asset="TEST", side="buy", quantity=10, order_type="market")
        order_id = priced_broker.place_order(order)
        assert order_id != ""
        assert order.status == "filled"
        positions = priced_broker.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 10

    def test_sell_reduces_position(self, priced_broker):
        priced_broker.place_order(Order(asset="TEST", side="buy", quantity=10, order_type="market"))
        cash_after_buy = priced_broker.get_account_summary().total_cash
        priced_broker.place_order(Order(asset="TEST", side="sell", quantity=5, order_type="market"))
        assert priced_broker.get_account_summary().total_cash > cash_after_buy

    def test_dual_positions(self, priced_broker):
        priced_broker.place_order(Order(asset="ASSET_A", side="buy", quantity=10, order_type="market"))
        priced_broker.place_order(Order(asset="ASSET_B", side="buy", quantity=20, order_type="market"))
        summary = priced_broker.get_account_summary()
        assert len(summary.positions) == 2

    def test_spread_widens_with_vol_zscore_capped_at_max(self):
        config = ExecutionConfig(
            base_spread_bps=10.0,
            spread_vol_slope=5.0,
            spread_max_bps=30.0,
            impact_model="none",
            vol_window=5,
        )
        low_slip = compute_slippage_cost(np.array([1.0]), config)[0]
        high_slip = compute_slippage_cost(np.array([3.0]), config)[0]
        capped_slip = compute_slippage_cost(np.array([100.0]), config)[0]

        assert high_slip > low_slip
        assert capped_slip == pytest.approx(config.spread_max_bps / 10000.0)

        broker = PaperBroker(initial_capital=100000, execution_configs={"FX": config}, fees=0.0)
        broker.set_price("FX", 1.0)
        # Calm period then shock window → recent vol >> full-sample vol
        broker._returns_history["FX"] = [0.0001] * 30 + [0.08, -0.07, 0.09, -0.08, 0.10]
        high_z = broker.get_vol_zscore("FX")
        assert high_z > 1.0
        broker_slip = compute_slippage_cost(np.array([high_z]), config)[0]
        assert broker_slip > low_slip
