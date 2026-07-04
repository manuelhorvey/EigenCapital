
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution.bridge import ExecutionBridge
from shared.execution_config import ExecutionConfig


def test_fill_price_buy_worse_than_mid():
    config = ExecutionConfig(base_spread_bps=10.0, spread_vol_slope=2.0, impact_model="none")
    broker = PaperBroker(execution_configs={"EURUSD=X": config})
    bridge = ExecutionBridge(broker)
    fill, slip_bps, impact_bps = bridge.fill_price("EURUSD=X", "buy", 10000, 1.10)
    assert fill > 1.10
    assert slip_bps >= 0
    assert impact_bps == 0.0


def test_estimate_impact_bps_square_root():
    config = ExecutionConfig(
        impact_model="square_root",
        impact_coeff=0.1,
        avg_daily_volume=1_000_000,
        base_spread_bps=0.0,
        spread_vol_slope=0.0,
    )
    broker = PaperBroker(execution_configs={"AAPL": config})
    bridge = ExecutionBridge(broker)
    bps = bridge.estimate_impact_bps("AAPL", 100_000)
    assert bps > 0


def test_submit_market_order_uses_single_precomputed_fill():
    config = ExecutionConfig(base_spread_bps=100.0, spread_vol_slope=0.0, spread_max_bps=200.0, impact_model="none")
    broker = PaperBroker(execution_configs={"EURUSD=X": config})
    bridge = ExecutionBridge(broker)

    fill, order_id = bridge.submit_market_order("EURUSD=X", "buy", 10, 100.0)

    assert order_id
    assert fill == 101.005
    assert broker.get_positions()[0].avg_entry_price == 101.005


def test_execution_bridge_can_open_short():
    config = ExecutionConfig(base_spread_bps=0.0, spread_vol_slope=0.0, impact_model="none")
    broker = PaperBroker(execution_configs={"TEST": config})
    bridge = ExecutionBridge(broker)

    fill, order_id = bridge.submit_market_order("TEST", "sell", 5, 100.0)

    assert order_id
    assert fill == 99.995
    position = broker.get_positions()[0]
    assert position.quantity == -5
    assert position.avg_entry_price == 99.995
