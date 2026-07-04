"""Tests for ExecutionBridge — fill simulation, market snapshot, order submission.

Uses mock PaperBroker to avoid requiring MT5 or real market data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from paper_trading.execution.bridge import ExecutionBridge


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_vol_zscore.return_value = 0.5
    broker._get_config.return_value = MagicMock(
        avg_daily_volume=1_000_000,
        spread_bps=5.0,
        cost_bps=2.0,
        impact_decay=0.5,
    )
    broker.set_price = MagicMock()
    broker._update_vol_tracking = MagicMock()
    return broker


class TestInit:
    def test_creates_with_paper_broker(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        assert bridge._is_real_broker is False
        assert bridge.simulator is None

    def test_creates_with_real_broker_flag(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        assert bridge._is_real_broker is True

    def test_creates_with_execution_simulator(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, use_execution_simulator=True, seed=42)
        assert bridge.simulator is not None


class TestBuildMarketSnapshot:
    @pytest.fixture
    def bridge(self, mock_broker):
        return ExecutionBridge(mock_broker)

    def test_builds_from_mid_price_only(self, bridge):
        snap = bridge._build_market_snapshot("EURUSD", mid_price=1.05)
        assert snap.current_price == 1.05
        assert snap.open_price == 1.05
        assert snap.high_price == 1.05
        assert snap.low_price == 1.05

    def test_builds_from_ohlcv(self, bridge):
        ohlcv = pd.DataFrame({
            "open": [1.04, 1.06],
            "high": [1.05, 1.08],
            "low": [1.03, 1.04],
            "close": [1.045, 1.07],
        })
        snap = bridge._build_market_snapshot("EURUSD", mid_price=1.07, ohlcv=ohlcv)
        assert snap.open_price == 1.06
        assert snap.high_price == 1.08
        assert snap.low_price == 1.04

    def test_clamps_high_low(self, bridge):
        ohlcv = pd.DataFrame({
            "open": [100],
            "high": [99],
            "low": [101],
            "close": [100],
        })
        snap = bridge._build_market_snapshot("TEST", mid_price=100, ohlcv=ohlcv)
        assert snap.high_price >= snap.open_price
        assert snap.low_price <= snap.open_price

    def test_empty_ohlcv_falls_back_to_mid(self, bridge):
        ohlcv = pd.DataFrame()
        snap = bridge._build_market_snapshot("EURUSD", mid_price=1.05, ohlcv=ohlcv)
        assert snap.high_price == 1.05
        assert snap.low_price == 1.05


class TestFillPrice:
    def test_real_broker_returns_nominal_spread(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        fill, slip_bps, impact = bridge.fill_price("EURUSD", "buy", 10000, 1.05)
        assert fill > 1.05  # buy pays spread
        assert slip_bps == 2.0

    def test_real_broker_short_side(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        fill, slip_bps, impact = bridge.fill_price("EURUSD", "sell", 10000, 1.05)
        assert fill < 1.05  # sell receives less
        assert slip_bps == 2.0

    def test_zero_mid_price_returns_mid(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        fill, slip_bps, impact = bridge.fill_price("EURUSD", "buy", 0, 0)
        assert fill == 0.0
        assert slip_bps == 0.0

    def test_zero_quantity_returns_mid(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        fill, slip_bps, impact = bridge.fill_price("EURUSD", "buy", 0, 1.05)
        assert fill == 1.05
        assert slip_bps == 0.0

    def test_paper_broker_calls_slippage_computation(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        with patch("paper_trading.execution.bridge.compute_slippage_cost", return_value=np.array([0.0001])):
            with patch("paper_trading.execution.bridge.compute_market_impact", return_value=0.00005):
                fill, slip_bps, impact = bridge.fill_price("EURUSD", "buy", 10000, 1.05)
        assert fill != 1.05
        assert slip_bps > 0

    def test_paper_broker_sell_side(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        with patch("paper_trading.execution.bridge.compute_slippage_cost", return_value=np.array([0.0002])):
            with patch("paper_trading.execution.bridge.compute_market_impact", return_value=0.0001):
                fill, slip_bps, impact = bridge.fill_price("EURUSD", "sell", 10000, 1.05)
        assert fill < 1.05

    def test_uses_simulator_when_configured(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, use_execution_simulator=True)
        bridge.simulator = MagicMock()
        bridge.simulator.simulate.return_value = MagicMock(fill_price=1.051, slippage_bps=3.0, impact_bps=0.0)
        ohlcv = pd.DataFrame({"open": [1.04], "high": [1.06], "low": [1.03], "close": [1.05]})
        fill, slip_bps, impact = bridge.fill_price("EURUSD", "buy", 10000, 1.05, ohlcv)
        assert fill == 1.051
        bridge.simulator.simulate.assert_called_once()


def _make_pos(side="long", **kw):
    from eigencapital.domain.entities.position import PositionIntent, PositionSide

    s = PositionSide.LONG if side == "long" else PositionSide.SHORT
    defaults = dict(
        side=s, entry_price=1.05, entry_date="2026-01-01",
        stop_loss=1.04, take_profit=1.08, vol=0.02,
    )
    defaults.update(kw)
    return PositionIntent(**defaults)


class TestEstimateImpactBps:
    def test_real_broker_returns_zero(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        assert bridge.estimate_impact_bps("EURUSD", 10000) == 0.0

    def test_zero_notional_returns_zero(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        assert bridge.estimate_impact_bps("EURUSD", 0) == 0.0

    def test_paper_broker_computes_impact(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        with patch("paper_trading.execution.bridge.compute_market_impact", return_value=0.0005):
            bps = bridge.estimate_impact_bps("EURUSD", 100000)
        assert bps == pytest.approx(5.0)


class TestFillStopLoss:
    def test_real_broker_long(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        pos = _make_pos()
        result = bridge.fill_stop_loss("EURUSD", pos, 1.04)
        assert result.fill_price > 1.04  # adds slippage

    def test_real_broker_short(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        pos = _make_pos(side="short", stop_loss=1.06, take_profit=1.02)
        result = bridge.fill_stop_loss("EURUSD", pos, 1.06)
        assert result.fill_price < 1.06

    def test_paper_broker_fills_at_stop_loss(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        pos = _make_pos()
        result = bridge.fill_stop_loss("EURUSD", pos, 1.04)
        assert result.fill_price == 1.04

    def test_simulator_path(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, use_execution_simulator=True)
        bridge.simulator = MagicMock()
        bridge.simulator.simulate_stop_loss.return_value = MagicMock(fill_price=1.039, slippage_bps=5.0)
        pos = _make_pos()
        result = bridge.fill_stop_loss("EURUSD", pos, 1.04)
        assert result.fill_price == 1.039


class TestFillTakeProfit:
    def test_real_broker_long(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        pos = _make_pos()
        result = bridge.fill_take_profit("EURUSD", pos, 1.08)
        assert result.fill_price < 1.08  # long take profit, minus spread

    def test_real_broker_short(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        pos = _make_pos(side="short", stop_loss=1.06, take_profit=1.02)
        result = bridge.fill_take_profit("EURUSD", pos, 1.02)
        assert result.fill_price > 1.02

    def test_paper_broker_fills_at_take_profit(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        pos = _make_pos()
        result = bridge.fill_take_profit("EURUSD", pos, 1.08)
        assert result.fill_price == 1.08

    def test_simulator_path(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, use_execution_simulator=True)
        bridge.simulator = MagicMock()
        bridge.simulator.simulate_take_profit.return_value = MagicMock(fill_price=1.079, slippage_bps=3.0)
        pos = _make_pos()
        result = bridge.fill_take_profit("EURUSD", pos, 1.08)
        assert result.fill_price == 1.079


class TestSubmitMarketOrder:
    def test_real_broker_returns_mid_price(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        bridge.orders = MagicMock()
        bridge.orders.submit_market_order.return_value = "order-123"
        fill, order_id = bridge.submit_market_order("EURUSD", "buy", 10000, 1.05)
        assert fill == 1.05
        assert order_id == "order-123"

    def test_paper_broker_computes_fill(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        bridge.orders = MagicMock()
        bridge.orders.submit_market_order.return_value = "order-456"
        with patch.object(bridge, "fill_price", return_value=(1.051, 3.0, 0.0)):
            fill, order_id = bridge.submit_market_order("EURUSD", "sell", 10000, 1.05)
        assert fill == 1.051
        assert order_id == "order-456"

    def test_submit_with_sl_tp(self, mock_broker):
        bridge = ExecutionBridge(mock_broker, is_real_broker=True)
        bridge.orders = MagicMock()
        bridge.submit_market_order("EURUSD", "buy", 10000, 1.05, sl=1.04, tp=1.08)
        bridge.orders.submit_market_order.assert_called_with(
            "EURUSD", "buy", 10000, fill_price=None, sl=1.04, tp=1.08
        )


class TestAllowShort:
    def test_sets_allow_short_on_broker(self, mock_broker):
        bridge = ExecutionBridge(mock_broker)
        assert bridge.broker.allow_short is True
