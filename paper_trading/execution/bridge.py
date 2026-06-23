"""Connect PaperBroker execution physics to AssetEngine fills.

Phase 4 integration: OHLC-driven MarketSnapshot with real gap-through
detection, asymmetric slippage, partial fill degradation, and seeded
stochastic latency for stop-loss and take-profit fills.

The simulator sits AFTER PolicyDecision freeze and never mutates it.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from paper_trading.entry.decision import PositionIntent
from paper_trading.execution.order_manager import OrderManager
from paper_trading.execution.paper_broker import PaperBroker
from paper_trading.execution.simulator import (
    ExecutionSimulator,
    FillResult,
    MarketSnapshot,
)
from shared.execution_config import compute_market_impact, compute_slippage_cost

logger = logging.getLogger("quantforge.execution_bridge")


class ExecutionBridge:
    """Simulates realistic fill prices via PaperBroker and ExecutionSimulator.

    Phase 4 (real OHLC snapshots) provides gap-through detection using
    actual bar data. When ohlcv is provided, open/high/low come from
    real bars instead of collapsing to mid price.

    When ``is_real_broker`` is True (e.g. MT5 demo account), fill prices
    are returned at mid price with zero slippage — the real fill comes
    from the broker's order execution, not this simulation layer.
    """

    def __init__(
        self,
        broker: PaperBroker,
        use_execution_simulator: bool = False,
        seed: int = 42,
        is_real_broker: bool = False,
    ):
        self.broker = broker
        if hasattr(broker, "allow_short"):
            self.broker.allow_short = True
        self.orders = OrderManager(broker)
        self.simulator = ExecutionSimulator(seed) if use_execution_simulator else None
        self._is_real_broker = is_real_broker

    def _build_market_snapshot(
        self,
        asset: str,
        mid_price: float,
        ohlcv: pd.DataFrame | None = None,
    ) -> MarketSnapshot:
        """Build a MarketSnapshot from broker state and optional OHLC bar data.

        When ohlcv is provided, open/high/low are taken from the last bar.
        When ohlcv is None, all fields fall back to mid_price.
        """
        vol_z = self.broker.get_vol_zscore(asset)
        if ohlcv is not None and not ohlcv.empty:
            last = ohlcv.iloc[-1]
            open_px = float(last.get("open", mid_price))
            high_px = float(last.get("high", mid_price))
            low_px = float(last.get("low", mid_price))
            # Clamp: high >= max(open, close), low <= min(open, close)
            close_px = float(last.get("close", mid_price))
            high_px = max(high_px, open_px, close_px)
            low_px = min(low_px, open_px, close_px)
        else:
            open_px = mid_price
            high_px = mid_price
            low_px = mid_price

        return MarketSnapshot(
            current_price=mid_price,
            open_price=open_px,
            high_price=high_px,
            low_price=low_px,
            vol_zscore=vol_z,
        )

    def estimate_impact_bps(self, asset: str, notional: float) -> float:
        if self._is_real_broker or notional <= 0:
            return 0.0
        config = self.broker._get_config(asset)
        impact = compute_market_impact(notional, config)
        return float(impact * 10000.0)

    def fill_price(
        self,
        asset: str,
        side: str,
        quantity: float,
        mid_price: float,
        ohlcv: pd.DataFrame | None = None,
    ) -> tuple[float, float, float]:
        if mid_price <= 0 or quantity <= 0:
            return mid_price, 0.0, 0.0

        # Real broker: apply nominal spread estimate so paper P&L tracks
        # closer to real MT5 fills instead of showing zero-slippage mid prices.
        if self._is_real_broker:
            slip_bps = 2.0
            fill = mid_price * (1 + slip_bps / 10000) if side == "buy" else mid_price * (1 - slip_bps / 10000)
            logger.debug("%s %s fill: mid=%.4f fill=%.4f slip=%.1fbps (real)", asset, side, mid_price, fill, slip_bps)
            return fill, slip_bps, 0.0

        self.broker.set_price(asset, mid_price)
        self.broker._update_vol_tracking(asset, mid_price)
        vol_z = self.broker.get_vol_zscore(asset)
        config = self.broker._get_config(asset)
        if self.simulator is not None:
            market = self._build_market_snapshot(asset, mid_price, ohlcv)
            result = self.simulator.simulate("entry", side, mid_price, quantity, market, config)
            fill = result.fill_price
            slippage_bps = result.slippage_bps
            impact_bps = 0.0
        else:
            slippage = float(compute_slippage_cost(np.array([vol_z]), config)[0])
            impact = float(compute_market_impact(quantity * mid_price, config))
            total = slippage + impact
            fill = mid_price * (1 + total) if side == "buy" else mid_price * (1 - total)
            slippage_bps = (slippage + impact) * 10000.0
            impact_bps = impact * 10000.0
        logger.debug(
            "%s %s fill: mid=%.4f fill=%.4f slip=%.1fbps vol_z=%.2f",
            asset,
            side,
            mid_price,
            fill,
            slippage_bps,
            vol_z,
        )
        return fill, slippage_bps, impact_bps

    def fill_stop_loss(
        self,
        asset: str,
        position: PositionIntent,
        current_price: float,
        ohlcv: pd.DataFrame | None = None,
    ) -> FillResult:
        if self._is_real_broker:
            slip_bps = 3.0
            slip_px = current_price * slip_bps / 10000
            fill_px = current_price + slip_px if position.side == "long" else current_price - slip_px
            return FillResult(fill_px, max(position.vol * 1000, 1.0), slip_bps, 0, False, False)
        if self.simulator is not None:
            config = self.broker._get_config(asset)
            market = self._build_market_snapshot(asset, current_price, ohlcv)
            return self.simulator.simulate_stop_loss(position, current_price, market, config)
        fill_px = position.stop_loss
        return FillResult(fill_px, max(position.vol * 1000, 1.0), 0.0, 0, False, False)

    def fill_take_profit(
        self,
        asset: str,
        position: PositionIntent,
        current_price: float,
        ohlcv: pd.DataFrame | None = None,
    ) -> FillResult:
        """Simulate a take-profit fill with OHLC context (gap-through never applies).

        When ohlcv is provided, it informs vol-based degradation only.
        When ohlcv is None, falls back to price-based fill.
        """
        if self._is_real_broker:
            slip_bps = 2.0
            slip_px = current_price * slip_bps / 10000
            fill_px = current_price - slip_px if position.side == "long" else current_price + slip_px
            return FillResult(fill_px, max(position.vol * 1000, 1.0), slip_bps, 0, False, False)
        if self.simulator is not None:
            config = self.broker._get_config(asset)
            market = self._build_market_snapshot(asset, current_price, ohlcv)
            return self.simulator.simulate_take_profit(position, current_price, market, config)

        fill_px = position.take_profit
        return FillResult(fill_px, max(position.vol * 1000, 1.0), 0.0, 0, False, False)

    def submit_market_order(
        self,
        asset: str,
        side: str,
        quantity: float,
        mid_price: float,
        ohlcv: pd.DataFrame | None = None,
        sl: float | None = None,
        tp: float | None = None,
    ) -> tuple[float, str]:
        """Place order through OrderManager; returns (fill_price, order_id)."""
        if self._is_real_broker:
            order_id = self.orders.submit_market_order(asset, side, quantity, fill_price=None, sl=sl, tp=tp)
            return mid_price, order_id or ""
        fill, _, _ = self.fill_price(asset, side, quantity, mid_price, ohlcv)
        order_id = self.orders.submit_market_order(asset, side, quantity, fill_price=fill)
        return fill, order_id or ""
