"""Backtest Clock — event timing and information boundary.

The clock ensures that at every decision point, the strategy has access
to exactly the data it should have — no more, no less.

Critical invariant: NO future bar access. EVER.

Usage:
    clock = BacktestClock(bars)
    for t, available_bars in clock:
        signal = strategy.on_bar(t, available_bars)
        # available_bars contains ONLY bars up to time t
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

from eigencapital.core.models.bar import Bar


class LookAheadViolationError(RuntimeError):
    """Raised when future data is accessed — a critical backtest error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass
class BacktestClock:
    """Manages bar iteration and enforces information boundaries.

    Attributes:
        bars: Sorted list of all bars in the dataset
        current_index: Current position in the bar series
        minimum_delay: Minimum bars between signal and fill
    """

    bars: List[Bar] = field(default_factory=list)
    current_index: int = 0
    minimum_delay: int = 1  # Default: next-bar execution

    def __post_init__(self) -> None:
        # Validate bars are sorted chronologically
        for i in range(1, len(self.bars)):
            if self.bars[i].timestamp_utc <= self.bars[i - 1].timestamp_utc:
                raise ValueError(
                    f"Bars must be sorted chronologically. "
                    f"Bar {i} ({self.bars[i].timestamp_utc}) <= "
                    f"Bar {i-1} ({self.bars[i-1].timestamp_utc})"
                )

    @property
    def total_bars(self) -> int:
        """Total number of bars in the dataset."""
        return len(self.bars)

    @property
    def current_bar(self) -> Optional[Bar]:
        """The bar at the current time index."""
        if 0 <= self.current_index < len(self.bars):
            return self.bars[self.current_index]
        return None

    @property
    def current_timestamp(self) -> Optional[str]:
        """Current time as ISO-8601 UTC string."""
        bar = self.current_bar
        return bar.timestamp_utc if bar else None

    @property
    def is_at_end(self) -> bool:
        """Check if we've processed all bars."""
        return self.current_index >= len(self.bars)

    def available_bars(self, up_to_index: Optional[int] = None) -> List[Bar]:
        """Return bars available at the current time index.

        This is the key method that enforces the information boundary.
        The strategy can ONLY see bars up to the given index.

        Args:
            up_to_index: Maximum index (inclusive). Defaults to current_index.

        Returns:
            List of bars available up to the given time
        """
        if up_to_index is None:
            up_to_index = self.current_index
        return self.bars[:up_to_index + 1]

    def bar_at(self, index: int) -> Bar:
        """Access a bar by index.

        Raises:
            LookAheadViolationError: if accessing a future bar
        """
        if index > self.current_index:
            raise LookAheadViolationError(
                f"Cannot access bar at index {index} (future). "
                f"Current index is {self.current_index}. "
                f"This is a look-ahead violation."
            )
        if index < 0 or index >= len(self.bars):
            raise IndexError(f"Bar index {index} out of range")
        return self.bars[index]

    def advance(self) -> bool:
        """Advance the clock by one bar.

        Returns:
            True if advanced successfully, False if at end
        """
        if self.current_index < len(self.bars):
            self.current_index += 1
            return True
        return False

    def reset(self) -> None:
        """Reset the clock to the beginning."""
        self.current_index = 0

    def __iter__(self):
        """Iterate over (bar, available_bars) pairs."""
        self.reset()
        for i, bar in enumerate(self.bars):
            self.current_index = i
            yield bar, self.available_bars(i)
