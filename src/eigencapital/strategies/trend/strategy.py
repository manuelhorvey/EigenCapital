"""Cross-asset trend strategy — deliberately simple baseline.

Hypothesis:
    Persistent price trends contain exploitable information at medium-term
    horizons, and a diversified, volatility-scaled implementation may retain
    positive risk-adjusted expectancy after realistic costs.

This is the FIRST strategy for EigenCapital — designed to test the
complete research pipeline, not to be profitable.

Parameters:
    lookback_period: 63 bars (~3 months daily)
    entry_threshold: 1.0 Z-score
    exit_threshold: 0.0 Z-score (mean reversion)
    volatility_lookback: 21 bars (~1 month)
    risk_target: 10% annualized volatility
    max_position_size: 1 contract

Constraints:
- ≤ 5-10 meaningful parameters
- No ML
- No parameter optimization marathon
- No strategy-specific risk exceptions
- Costs included from first experiment
"""

from __future__ import annotations

from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.strategies.base import BaseStrategy, StrategySignal
from eigencapital.strategies.trend.config import TrendConfig
from eigencapital.strategies.trend.features import (
    compute_realized_volatility,
    compute_trend_signal,
)


class CrossAssetTrendStrategy(BaseStrategy):
    """Cross-asset trend/momentum strategy.

    Computes a simple momentum signal (cumulative return / volatility),
    applies volatility-scaled position sizing, and generates LONG/SHORT/FLAT
    signals based on Z-score thresholds.

    This strategy deliberately avoids:
    - Machine learning
    - Complex parameter optimization
    - Asset-specific rules
    - Regime detection
    - Mean reversion overlays

    The purpose is to test the complete research pipeline.
    """

    def __init__(self, config: Optional[TrendConfig] = None) -> None:
        self.config = config or TrendConfig()
        self._strategy_id = "cross_asset_trend_v1"
        self._strategy_version = "v1.0.0"

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def strategy_version(self) -> str:
        return self._strategy_version

    def on_bar(
        self,
        timestamp: str,
        bars: List[Bar],
        position_quantity: float,
        cash: float,
    ) -> Optional[StrategySignal]:
        """Process a new bar and generate a signal.

        Args:
            timestamp: Current bar timestamp (ISO-8601 UTC)
            bars: All bars available up to and including current bar
            position_quantity: Current position (signed)
            cash: Current cash balance

        Returns:
            StrategySignal if strategy wants to trade, None otherwise
        """
        # Need minimum data for signal
        min_bars = max(self.config.lookback_period, self.config.volatility_lookback) + 1
        if len(bars) < min_bars:
            return None

        # Compute trend signal
        signal_zscore = compute_trend_signal(
            bars,
            self.config.lookback_period,
            self.config.volatility_lookback,
        )

        if signal_zscore is None:
            return None

        # Compute volatility for position sizing
        volatility = compute_realized_volatility(bars, self.config.volatility_lookback)
        if volatility is None or volatility <= 0:
            return None

        # Determine direction based on signal and thresholds
        current_direction = (
            1 if position_quantity > 0 else (-1 if position_quantity < 0 else 0)
        )

        if current_direction == 0:
            # No position — check for entry
            if signal_zscore > self.config.entry_threshold:
                direction = 1  # LONG
            elif signal_zscore < -self.config.entry_threshold:
                direction = -1  # SHORT
            else:
                return None  # No signal
        else:
            # Have position — check for exit
            if current_direction == 1 and signal_zscore < self.config.exit_threshold:
                direction = 0  # Exit LONG
            elif (
                current_direction == -1 and signal_zscore > -self.config.exit_threshold
            ):
                direction = 0  # Exit SHORT
            else:
                # Hold — no signal
                return None

        # Compute position size
        target_risk = abs(signal_zscore) * self.config.risk_target

        return StrategySignal(
            direction=direction,
            target_risk=target_risk,
            confidence=min(abs(signal_zscore) / 3.0, 1.0),  # Normalize to [0, 1]
            metadata={
                "signal_zscore": signal_zscore,
                "volatility": volatility,
                "lookback": self.config.lookback_period,
            },
        )

    def on_start(self, initial_cash: float) -> None:
        """Called at backtest start."""
        pass

    def on_end(self) -> None:
        """Called at backtest end."""
        pass
