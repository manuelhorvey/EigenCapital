"""Unit tests for BacktestClock — timing and information boundary."""

import pytest
from eigencapital.core.models.bar import Bar
from eigencapital.backtest.clock import BacktestClock, LookAheadViolationError


def _make_bar(ts_min: int, instrument_id="ES"):
    """Helper to create a bar at minute ts_min."""
    return Bar(
        instrument_id=instrument_id,
        timestamp_utc=f"2024-03-15T09:{ts_min:02d}:00Z",
        bar_start_utc=f"2024-03-15T09:{ts_min - 5:02d}:00Z",
        bar_end_utc=f"2024-03-15T09:{ts_min:02d}:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )


class TestBacktestClock:
    def test_creation(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        assert clock.total_bars == 5
        assert clock.current_index == 0

    def test_available_bars_at_start(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        available = clock.available_bars()
        assert len(available) == 1  # Only first bar at index 0

    def test_available_bars_after_advance(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        clock.advance()
        available = clock.available_bars()
        assert len(available) == 2  # First two bars

    def test_look_ahead_violation(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        with pytest.raises(
            LookAheadViolationError, match="Cannot access bar at index 3"
        ):
            clock.bar_at(3)  # Future bar

    def test_bar_at_current_index(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        bar = clock.bar_at(0)  # Current bar
        assert bar.timestamp_utc == "2024-03-15T09:30:00Z"

    def test_advance_and_reset(self):
        bars = [_make_bar(i) for i in range(30, 35)]
        clock = BacktestClock(bars)
        clock.advance()
        clock.advance()
        assert clock.current_index == 2
        clock.reset()
        assert clock.current_index == 0

    def test_is_at_end(self):
        bars = [_make_bar(i) for i in range(30, 32)]
        clock = BacktestClock(bars)
        assert not clock.is_at_end
        clock.advance()
        clock.advance()
        assert clock.is_at_end

    def test_iteration(self):
        bars = [_make_bar(i) for i in range(30, 33)]
        clock = BacktestClock(bars)
        timestamps = []
        for bar, available in clock:
            timestamps.append(bar.timestamp_utc)
            # At each step, available bars should be <= current
            assert len(available) <= clock.current_index + 1
        assert len(timestamps) == 3

    def test_unsorted_bars_rejected(self):
        bars = [_make_bar(32), _make_bar(30)]  # Out of order
        with pytest.raises(ValueError, match="chronologically"):
            BacktestClock(bars)
