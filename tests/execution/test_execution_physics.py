import pytest

from paper_trading.execution.broker_interface import Order
from paper_trading.execution.paper_broker import PaperBroker
from shared.execution_config import ExecutionConfig


def test_paper_broker_slippage_with_vol():
    # Setup configs
    config = ExecutionConfig(base_spread_bps=10.0, spread_vol_slope=2.0, spread_max_bps=100.0)
    broker = PaperBroker(initial_capital=100000, execution_configs={"EURUSD=X": config})

    # 1. Zero vol case (normal slippage)
    # Vol z-score will be 1.0 initially
    broker.set_price("EURUSD=X", 1.1000)
    order = Order(asset="EURUSD=X", quantity=10000, side="buy", order_type="market")
    broker.place_order(order)

    # Base spread 10bps + latency 0.5bps = 10.5bps = 0.00105. Buy fill = 1.1000 * 1.00105 = 1.101155
    # Check internal order storage
    filled_order = broker._orders["1"]
    assert filled_order.status == "filled"

    # 2. Check position
    pos = broker._positions["EURUSD=X"]
    assert pos.quantity == 10000
    assert pytest.approx(pos.avg_entry_price) == 1.101155


def test_market_impact_linear():
    config = ExecutionConfig(impact_model="linear", impact_coeff=0.1, avg_daily_volume=1e6)
    broker = PaperBroker(initial_capital=1000000, execution_configs={"AAPL": config})
    broker.set_price("AAPL", 100.0)

    # Trade 10% of ADV (100k notional)
    # participation = 100k / 1M = 0.1
    # impact_bps = 0.1 * 0.1 * 10000 = 100 bps = 1.0%
    # + base_spread 0.5 bps + latency 0.5 bps = 101 bps = 0.0101
    order = Order(asset="AAPL", quantity=1000, side="buy", order_type="market")  # 1000 * 100 = 100k
    broker.place_order(order)

    # Buy price 100.0 * (1 + 0.0101) = 101.01
    pos = broker._positions["AAPL"]
    assert pytest.approx(pos.avg_entry_price) == 101.01
