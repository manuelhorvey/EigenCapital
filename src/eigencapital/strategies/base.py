"""Strategy Base Class — interface for all trading strategies.

Every strategy must implement on_bar(), receiving only bars
available up to the current time (enforced by BacktestClock).

Usage:
    class MyStrategy(BaseStrategy):
        def on_bar(self, timestamp, bars, position, cash):
            # bars contains ONLY historical data (no look-ahead)
            # Return: (direction, target_risk) or None
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eigencapital.core.models.bar import Bar


@dataclass(frozen=True)
class StrategySignal:
    """A trading signal from a strategy.

    Attributes:
        direction: 1=LONG, -1=SHORT, 0=FLAT
        target_risk: Portfolio-relative risk >= 0
        confidence: Optional confidence score (0-1)
        metadata: Free-form signal metadata
    """

    direction: int  # 1, -1, or 0
    target_risk: float = 0.0
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in (1, -1, 0):
            raise ValueError(f"direction must be 1, -1, or 0, got {self.direction}")
        if self.target_risk < 0:
            raise ValueError(f"target_risk must be >= 0, got {self.target_risk}")


class BaseStrategy(ABC):
    """Abstract base class for trading strategies.

    Subclasses must implement:
    - on_bar(): Process a new bar and optionally generate a signal
    - strategy_id: Unique strategy identifier
    - strategy_version: Strategy version string
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique strategy identifier."""
        ...

    @property
    @abstractmethod
    def strategy_version(self) -> str:
        """Strategy version string."""
        ...

    @abstractmethod
    def on_bar(
        self,
        timestamp: str,
        bars: List[Bar],
        position_quantity: float,
        cash: float,
    ) -> Optional[StrategySignal]:
        """Process a new bar and optionally generate a signal.

        Args:
            timestamp: Current bar timestamp (ISO-8601 UTC)
            bars: All bars available up to and including the current bar
                  (NO future bars — enforced by BacktestClock)
            position_quantity: Current position (signed: positive=LONG, negative=SHORT)
            cash: Current cash balance

        Returns:
            StrategySignal if the strategy wants to trade, None otherwise
        """
        ...

    def on_start(self, initial_cash: float) -> None:
        """Called once at the start of a backtest. Override for initialization."""
        pass

    def on_end(self) -> None:
        """Called once at the end of a backtest. Override for cleanup."""
        pass
