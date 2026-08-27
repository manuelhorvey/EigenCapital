"""Backtest Engine — event-driven research simulation.

The engine orchestrates the full backtest loop:
    Bar(t) → Strategy → Signal → Execution → Fill → P&L

Critical: Signal at t CANNOT fill at information unavailable at t.

Usage:
    engine = BacktestEngine(
        strategy=my_strategy,
        bars=historical_bars,
        cost_model=MODERATE_COST,
    )
    results = engine.run()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from eigencapital.backtest.accounting import AccountingEngine
from eigencapital.backtest.clock import BacktestClock
from eigencapital.core.models.bar import Bar
from eigencapital.research.costs.model import ZERO_COST, CostModel
from eigencapital.research.provenance.hashing import compute_provenance_hash
from eigencapital.strategies.base import BaseStrategy, StrategySignal


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for a backtest run.

    Attributes:
        initial_cash: Starting cash balance
        execution_delay: Bars between signal and fill (minimum 1)
        cost_model: Transaction cost model
        contract_multiplier: Contract multiplier per instrument
    """

    initial_cash: float = 100_000.0
    execution_delay: int = 1
    cost_model: CostModel = field(default_factory=lambda: ZERO_COST)
    contract_multiplier: float = 1.0


@dataclass
class BacktestResults:
    """Results of a completed backtest.

    Attributes:
        config: The configuration used
        equity_curve: List of (timestamp, equity) pairs
        fill_events: All fill events
        signal_events: All signal events
        final_equity: Final equity value
        total_return: Total return percentage
        max_drawdown: Maximum drawdown percentage
        trade_count: Number of round-trip trades
        provenance_hash: Deterministic hash of backtest identity
    """

    config: BacktestConfig = field(default_factory=BacktestConfig)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    fill_events: List[Dict[str, Any]] = field(default_factory=list)
    signal_events: List[Dict[str, Any]] = field(default_factory=list)
    final_equity: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    trade_count: int = 0
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "trade_count": self.trade_count,
            "total_fills": len(self.fill_events),
            "total_signals": len(self.signal_events),
            "provenance_hash": self.provenance_hash,
        }


class BacktestEngine:
    """Event-driven backtest engine.

    Orchestrates: Bar → Strategy → Signal → Execution → Fill → P&L

    The engine enforces:
    - No look-ahead bias (BacktestClock)
    - Realistic execution (spread, slippage, delays)
    - Cost accounting (mandatory cost model)
    - Provenance tracking (deterministic hash)
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        bars: List[Bar],
        config: BacktestConfig | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.clock = BacktestClock(bars, minimum_delay=self.config.execution_delay)
        self.accounting = AccountingEngine(initial_cash=self.config.initial_cash)
        self._pending_signals: List[Dict[str, Any]] = []

    def run(self) -> BacktestResults:
        """Execute the backtest.

        Returns:
            BacktestResults with equity curve, fills, and metrics
        """
        results = BacktestResults(config=self.config)

        # Initialize strategy
        self.strategy.on_start(self.config.initial_cash)

        # Main event loop
        for bar, available_bars in self.clock:
            # 1. Process any pending fills from previous signals
            self._process_pending_fills(bar, results)

            # 2. Strategy generates signal (with ONLY available bars)
            signal = self.strategy.on_bar(
                timestamp=bar.timestamp_utc,
                bars=available_bars,
                position_quantity=self.accounting.position.quantity,
                cash=self.accounting.accounting.current_cash
                if hasattr(self.accounting, "accounting")
                else self.accounting.current_cash,
            )

            # 3. Record signal
            if signal is not None:
                results.signal_events.append(
                    {
                        "timestamp": bar.timestamp_utc,
                        "direction": signal.direction,
                        "target_risk": signal.target_risk,
                    }
                )

                # 4. Queue fill for next bar (execution delay)
                self._queue_fill(bar, signal, results)

            # 5. Record equity
            equity = self.accounting.compute_equity(bar.close)
            results.equity_curve.append(
                {
                    "timestamp": bar.timestamp_utc,
                    "equity": equity,
                    "cash": self.accounting.current_cash,
                    "position": self.accounting.position.quantity,
                }
            )

        # Process any remaining pending fills
        self._process_pending_fills(None, results)

        # Finalize results
        results.final_equity = results.equity_curve[-1]["equity"] if results.equity_curve else self.config.initial_cash
        results.total_return = (results.final_equity / self.config.initial_cash - 1) * 100
        results.max_drawdown = self._compute_max_drawdown(results.equity_curve)
        results.trade_count = len(results.fill_events) // 2  # Approximate round-trips

        # Compute provenance hash
        hash_input = {
            "strategy_id": self.strategy.strategy_id,
            "strategy_version": self.strategy.strategy_version,
            "initial_cash": self.config.initial_cash,
            "execution_delay": self.config.execution_delay,
            "cost_model": self.config.cost_model.to_dict(),
            "bar_count": self.clock.total_bars,
            "final_equity": results.final_equity,
        }
        results.provenance_hash = compute_provenance_hash(hash_input)

        # Cleanup
        self.strategy.on_end()

        return results

    def _queue_fill(self, bar: Bar, signal: StrategySignal, results: BacktestResults) -> None:
        """Queue a fill for execution after the configured delay."""
        self._pending_signals.append(
            {
                "signal_bar_index": self.clock.current_index,
                "fill_bar_index": self.clock.current_index + self.config.execution_delay,
                "direction": signal.direction,
                "timestamp": bar.timestamp_utc,
            }
        )

    def _process_pending_fills(self, current_bar: Bar | None, results: BacktestResults) -> None:
        """Process any fills that should execute at the current bar."""
        remaining = []
        for pending in self._pending_signals:
            fill_index = pending["fill_bar_index"]
            if current_bar is None or self.clock.current_index >= fill_index:
                # Execute the fill
                self._execute_fill(pending, current_bar, results)
            else:
                remaining.append(pending)
        self._pending_signals = remaining

    def _execute_fill(self, pending: Dict[str, Any], bar: Bar | None, results: BacktestResults) -> None:
        """Execute a fill at the current bar's close price."""
        if bar is None:
            return

        direction = pending["direction"]
        if direction == 0:
            return  # FLAT signal, no fill

        # Compute fill price with costs
        fill_price = bar.close
        multiplier = self.config.contract_multiplier

        # Apply spread (buy pays more, sell receives less)
        spread_ticks = self.config.cost_model.spread_ticks
        # Assuming tick_size = 0.25 for simplicity; production would use Instrument
        tick_size = 0.25
        spread_cost = spread_ticks * tick_size * 0.5
        if direction == 1:  # BUY
            fill_price += spread_cost
        else:  # SELL
            fill_price -= spread_cost

        # Apply slippage
        slippage_ticks = self.config.cost_model.slippage_ticks
        slippage_cost = slippage_ticks * tick_size
        if direction == 1:
            fill_price += slippage_cost
        else:
            fill_price -= slippage_cost

        # Determine quantity (use 1 contract for simplicity)
        quantity = 1.0
        side = "BUY" if direction == 1 else "SELL"

        # Apply commission and fees
        commission = self.config.cost_model.commission_per_contract
        fees = self.config.cost_model.exchange_fee_per_contract

        # Apply fill to accounting
        self.accounting.apply_fill(
            fill_price=fill_price,
            quantity=quantity,
            side=side,
            multiplier=multiplier,
            commission=commission,
            fees=fees,
            timestamp=bar.timestamp_utc,
        )

        results.fill_events.append(
            {
                "timestamp": bar.timestamp_utc,
                "side": side,
                "quantity": quantity,
                "fill_price": fill_price,
                "commission": commission,
                "fees": fees,
            }
        )

    def _compute_max_drawdown(self, equity_curve: List[Dict[str, Any]]) -> float:
        """Compute maximum drawdown from equity curve."""
        if not equity_curve:
            return 0.0

        peak = equity_curve[0]["equity"]
        max_dd = 0.0

        for point in equity_curve:
            equity = point["equity"]
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak if peak > 0 else 0.0
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd * 100  # Return as percentage
