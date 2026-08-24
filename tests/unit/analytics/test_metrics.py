"""Adversarial tests for canonical performance metrics.

Test edge cases: constant returns, zero returns, empty series,
large drawdowns, single-trade, etc.
"""

import pytest
import math
from eigencapital.analytics.metrics import (
    PerformanceMetrics, compute_metrics, compute_returns,
)


class TestComputeReturns:
    """Tests for return computation."""

    def test_basic(self):
        """Test basic return computation."""
        returns = compute_returns([100, 110, 105])
        assert len(returns) == 2
        assert abs(returns[0] - 0.10) < 0.001
        assert abs(returns[1] - (-5/110)) < 0.001

    def test_single_value(self):
        """Test with single equity value."""
        returns = compute_returns([100])
        assert len(returns) == 0

    def test_empty(self):
        """Test with empty equity curve."""
        returns = compute_returns([])
        assert len(returns) == 0


class TestComputeMetrics:
    """Adversarial tests for performance metrics."""

    def test_constant_positive_returns(self):
        """Test with constant positive returns."""
        equity = [100 * (1.001 ** i) for i in range(252)]
        metrics = compute_metrics(equity)
        assert metrics.total_return > 0
        assert metrics.sharpe_ratio > 0
        assert metrics.max_drawdown == 0.0

    def test_constant_negative_returns(self):
        """Test with constant negative returns."""
        equity = [100 * (0.999 ** i) for i in range(252)]
        metrics = compute_metrics(equity)
        assert metrics.total_return < 0
        assert metrics.max_drawdown > 0

    def test_all_positive_returns(self):
        """Test with all positive returns."""
        equity = [100 + i * 0.5 for i in range(100)]
        metrics = compute_metrics(equity)
        assert metrics.total_return > 0
        assert metrics.max_drawdown == 0.0

    def test_single_trade(self):
        """Test with single trade P&L."""
        equity = [100, 110, 110]
        trades = [10.0]
        metrics = compute_metrics(equity, trades=trades)
        assert metrics.trade_count == 1
        assert metrics.hit_rate == 1.0
        assert metrics.avg_win == 10.0

    def test_empty_equity_raises(self):
        """Test that empty equity curve raises ValueError."""
        with pytest.raises(ValueError, match="at least 2 values"):
            compute_metrics([])

    def test_single_equity_raises(self):
        """Test that single equity value raises ValueError."""
        with pytest.raises(ValueError, match="at least 2 values"):
            compute_metrics([100])

    def test_negative_equity_raises(self):
        """Test that negative equity raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            compute_metrics([100, -50, 80])

    def test_zero_equity_raises(self):
        """Test that zero equity raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            compute_metrics([100, 0, 80])

    def test_large_drawdown(self):
        """Test with large drawdown scenario."""
        equity = [100, 110, 50, 60]  # 54% drawdown
        metrics = compute_metrics(equity)
        assert metrics.max_drawdown > 0.5

    def test_immediate_recovery(self):
        """Test with immediate drawdown recovery."""
        equity = [100, 90, 100, 105]
        metrics = compute_metrics(equity)
        assert metrics.max_drawdown > 0
        assert metrics.total_return > 0

    def test_extreme_outlier(self):
        """Test with extreme single-period outlier."""
        equity = [100, 200, 100, 100, 100]  # +100%, -50%
        metrics = compute_metrics(equity)
        assert metrics.trade_count == 0  # No explicit trades
        assert metrics.total_return == 0  # Flat overall

    def test_with_trades_mixed(self):
        """Test with mixed winning and losing trades."""
        trades = [10, -5, 8, -3, 12, -7, 5, -2, 15, -4]
        equity = [100]
        cum = 100
        for t in trades:
            cum += t
            equity.append(cum)
        metrics = compute_metrics(equity, trades=trades)
        assert metrics.trade_count == 10
        assert metrics.hit_rate == 0.5
        assert metrics.consecutive_wins >= 1
        assert metrics.consecutive_losses >= 1

    def test_deterministic_serialization(self):
        """Test that serialization is deterministic."""
        equity = [100 + i * 0.1 for i in range(100)]
        m1 = compute_metrics(equity)
        m2 = compute_metrics(equity)
        assert m1.to_dict() == m2.to_dict()

    def test_skew_computation(self):
        """Test skew is computed for sufficient data."""
        equity = [100 * (1 + 0.01 * (i % 3 - 1) * 0.1) for i in range(100)]
        metrics = compute_metrics(equity)
        assert isinstance(metrics.skew, float)

    def test_var_computation(self):
        """Test VaR is computed for sufficient data."""
        equity = [100 * (1 + 0.01 * ((i * 7) % 10 - 5) * 0.1) for i in range(100)]
        metrics = compute_metrics(equity)
        assert metrics.var_95 <= 0  # VaR should be negative or zero
