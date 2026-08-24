"""Tests for temporal stability analysis."""

import pytest
from eigencapital.analytics.validation.temporal import (
    TemporalStabilityResult, temporal_stability,
)


class TestTemporalStability:
    """Tests for temporal stability analysis."""

    def test_insufficient_data(self):
        """Test with insufficient data."""
        result = temporal_stability([100, 101, 102], window_size=252)
        assert result.window_count == 0

    def test_basic(self):
        """Test basic temporal stability."""
        equity = [100 * (1 + 0.001 * ((i * 7) % 10 - 5) * 0.01) for i in range(500)]
        result = temporal_stability(equity, window_size=100, step_size=50)
        assert result.window_count > 0
        assert result.min_sharpe <= result.max_sharpe

    def test_constant_equity(self):
        """Test with constant equity (no returns)."""
        equity = [100.0] * 300
        result = temporal_stability(equity, window_size=100)
        # All returns are 0, so Sharpe should be 0
        if result.window_count > 0:
            for m in result.rolling_metrics:
                assert m.sharpe == 0.0

    def test_serialization(self):
        """Test deterministic serialization."""
        equity = [100 * (1 + 0.001 * ((i * 3) % 5 - 2) * 0.01) for i in range(500)]
        result = temporal_stability(equity, window_size=100, step_size=50)
        d = result.to_dict()
        assert "window_count" in d
        assert "performance_decay" in d
