"""Tests for Probability of Backtest Overfitting."""

import pytest
from eigencapital.analytics.validation.pbo import compute_pbo


class TestPBO:
    """Tests for PBO computation."""

    def test_insufficient_experiments(self):
        """Test PBO with insufficient candidates."""
        result = compute_pbo([
            {"in_sample_sharpe": 2.0, "out_of_sample_sharpe": 0.3},
            {"in_sample_sharpe": 1.5, "out_of_sample_sharpe": 1.2},
        ])
        assert not result.sufficient_experiments
        assert "INSUFFICIENT" in result.message

    def test_sufficient_experiments(self):
        """Test PBO with sufficient candidates."""
        candidates = [
            {"in_sample_sharpe": 2.0 + i * 0.1, "out_of_sample_sharpe": 1.5 - i * 0.2}
            for i in range(15)
        ]
        result = compute_pbo(candidates)
        assert result.sufficient_experiments
        assert 0 <= result.pbo <= 1

    def test_serialization(self):
        """Test deterministic serialization."""
        candidates = [
            {"in_sample_sharpe": float(i), "out_of_sample_sharpe": float(10 - i)}
            for i in range(12)
        ]
        result = compute_pbo(candidates)
        d = result.to_dict()
        assert "pbo" in d
        assert "sufficient_experiments" in d
