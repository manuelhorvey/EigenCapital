"""Execution Simulator — market physics emulator.

Sits AFTER PolicyDecision freeze.
Only degrades outcomes, never improves them.
All randomness seeded and deterministic.

Flow:
    PolicyDecision (immutable)
        -> ExecutionSimulator.simulate()
        -> FillResult (frozen)

Architecture:
    - SlippageModel: asymmetric SL worse / TP neutral
    - FillModel: gap-through detection, partial fill degradation
    - LatencyModel: deterministic bar-level delay
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Literal

from paper_trading.entry.decision import PolicyDecision, PositionIntent
from paper_trading.execution.fill import FillModel
from paper_trading.execution.latency import LatencyModel
from paper_trading.execution.slippage import SlippageModel
from shared.execution_config import ExecutionConfig

logger = logging.getLogger("eigencapital.execution_simulator")

OrderType = Literal["entry", "stop_loss", "take_profit"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class MarketSnapshot:
    """Point-in-time market state at execution simulation."""

    current_price: float
    open_price: float
    high_price: float
    low_price: float
    vol_zscore: float


@dataclass(frozen=True)
class FillResult:
    """Frozen outcome of a simulated execution."""

    fill_price: float
    fill_qty: float
    slippage_bps: float
    latency_bars: int
    partial_fill: bool
    gap_fill: bool


class ExecutionSimulator:
    """Market physics emulator.

    Pure function composition with seeded random components.
    Same seed + same inputs -> identical FillResult.
    """

    def __init__(self, seed: int = 42):
        self._seed = seed
        self.slippage = SlippageModel(seed)
        self.fill = FillModel(seed)
        self.latency = LatencyModel(seed)

    def recreate(self, seed: int) -> ExecutionSimulator:
        return ExecutionSimulator(seed)

    def simulate(
        self,
        order_type: OrderType,
        side: Side,
        requested_price: float,
        requested_qty: float,
        market: MarketSnapshot,
        config: ExecutionConfig,
    ) -> FillResult:
        """Simulate a single fill event.

        Parameters
        ----------
        order_type : "entry" | "stop_loss" | "take_profit"
            Determines slippage model applied.
        side : "buy" | "sell"
        requested_price : float
            The trigger price (mid for entry, SL level, TP level).
        requested_qty : float
            Desired fill quantity.
        market : MarketSnapshot
            Current market state (price, vol, OHLC).
        config : ExecutionConfig
            Per-asset execution degradation parameters.

        Returns
        -------
        FillResult
            Frozen simulation outcome.
        """
        if requested_price <= 0 or requested_qty <= 0:
            return FillResult(
                fill_price=requested_price,
                fill_qty=0.0,
                slippage_bps=0.0,
                latency_bars=0,
                partial_fill=False,
                gap_fill=False,
            )

        # 1. Compute latency (before fill — delay is informational here)
        latency_bars = self.latency.execution_delay_bars(market.vol_zscore, config)

        # 2. Check gap-through (for stop-loss fills)
        gap_fill = False
        fill_price = requested_price
        if order_type == "stop_loss" and self.fill.check_gap_through(market.open_price, requested_price, side):
            gap_fill = True
            fill_price = self.fill.gap_fill_price(market.open_price, requested_price, side)

        # 3. Apply order-type-specific slippage.
        # NOTE on sign convention for SL/TP (matches SlippageModel docstring):
        # - SL buy (closing short): adverse = HIGHER fill = pay more.
        # - SL sell (closing long): adverse = LOWER fill = get less.
        # - TP buy (closing short): adverse = HIGHER fill = pay more.
        # - TP sell (closing long): adverse = LOWER fill = get less.
        # Earlier versions of this code applied slippage in the same sign
        # direction for both sides, which produced favorable (better than
        # trigger) fills for closing orders.  The correct sign is side-aware
        # as below.  See tests/test_execution_simulator.py for regression
        # coverage.
        slippage_bps = 0.0
        if order_type == "stop_loss" and not gap_fill:
            price_slip = self.slippage.stop_loss_slippage(fill_price, market.vol_zscore, config, side)
            slippage_bps = (price_slip / fill_price * 10000) if fill_price > 0 else 0.0
            fill_price = fill_price + price_slip if side == "buy" else fill_price - price_slip

        elif order_type == "take_profit":
            price_slip = self.slippage.take_profit_slippage(fill_price, config)
            slippage_bps = (price_slip / fill_price * 10000) if fill_price > 0 else 0.0
            fill_price = fill_price + price_slip if side == "buy" else fill_price - price_slip

        elif order_type == "entry":
            price_slip = self.slippage.entry_slippage(fill_price, market.vol_zscore, config)
            slippage_bps = price_slip * 10000
            fill_price = fill_price * (1.0 + price_slip) if side == "buy" else fill_price * (1.0 - price_slip)

        fill_price = max(fill_price, 0.0)

        # 4. Partial fill degradation
        actual_qty = self.fill.fill_qty_fraction(requested_qty, market.vol_zscore, config)
        partial_fill = actual_qty < requested_qty
        actual_qty = min(actual_qty, requested_qty)

        return FillResult(
            fill_price=round(fill_price, 6),
            fill_qty=round(actual_qty, 6),
            slippage_bps=round(slippage_bps, 4),
            latency_bars=latency_bars,
            partial_fill=partial_fill,
            gap_fill=gap_fill,
        )

    def simulate_entry(
        self,
        decision: PolicyDecision,
        mid_price: float,
        market: MarketSnapshot,
        config: ExecutionConfig,
    ) -> FillResult:
        """Convenience: simulate an entry fill from a PolicyDecision.

        Does NOT mutate the decision. PolicyDecision hash is invariant.
        """
        if decision.entry_plan is None:
            return FillResult(mid_price, 0.0, 0.0, 0, False, False)

        entry = decision.entry_plan
        if isinstance(entry, PositionIntent):
            side = "buy" if entry.side == "long" else "sell"
            qty = entry.vol * 1000
        else:
            side = "buy"
            qty = 1.0

        return self.simulate("entry", side, mid_price, qty, market, config)

    def simulate_stop_loss(
        self,
        position: PositionIntent,
        current_price: float,
        market: MarketSnapshot,
        config: ExecutionConfig,
    ) -> FillResult:
        """Simulate SL fill with adverse slippage and gap-through."""
        if position.stop_loss is None:
            return FillResult(current_price, 0.0, 0.0, 0, False, False)

        side = "sell" if position.side == "long" else "buy"
        return self.simulate("stop_loss", side, position.stop_loss, position.vol * 1000, market, config)

    def simulate_take_profit(
        self,
        position: PositionIntent,
        current_price: float,
        market: MarketSnapshot,
        config: ExecutionConfig,
    ) -> FillResult:
        """Simulate TP fill with neutral slippage."""
        if position.take_profit is None:
            return FillResult(current_price, 0.0, 0.0, 0, False, False)

        side = "sell" if position.side == "long" else "buy"
        return self.simulate("take_profit", side, position.take_profit, position.vol * 1000, market, config)

    def seed_hash(self) -> str:
        raw = f"{self.slippage.seed_hash()}:{self.fill.seed_hash()}:{self.latency.seed_hash()}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]
