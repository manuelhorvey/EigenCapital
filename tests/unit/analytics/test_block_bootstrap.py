"""Tests for block bootstrap."""

from eigencapital.analytics.validation.block_bootstrap import block_bootstrap


class TestBlockBootstrap:
    """Tests for block bootstrap analysis."""

    def test_insufficient_data(self):
        """Test with insufficient data."""
        result = block_bootstrap([0.01] * 5, block_size=21)
        assert result.n_bootstrap == 0

    def test_basic(self):
        """Test basic block bootstrap."""
        returns = [0.005 + (i % 3 - 1) * 0.002 for i in range(200)]
        result = block_bootstrap(returns, block_size=21, n_bootstrap=100, seed=42)
        assert result.n_bootstrap == 100
        assert result.sharpe_ci_lower < result.sharpe_ci_upper
        assert result.block_size == 21

    def test_reproducible(self):
        """Test reproducibility with same seed."""
        returns = [0.005 + (i % 5 - 2) * 0.001 for i in range(200)]
        r1 = block_bootstrap(returns, block_size=10, n_bootstrap=100, seed=42)
        r2 = block_bootstrap(returns, block_size=10, n_bootstrap=100, seed=42)
        assert r1.sharpe_mean == r2.sharpe_mean
        assert r1.sharpe_ci_lower == r2.sharpe_ci_lower

    def test_serialization(self):
        """Test deterministic serialization."""
        returns = [0.005 + (i % 3 - 1) * 0.001 for i in range(100)]
        result = block_bootstrap(returns, block_size=10, n_bootstrap=50)
        d = result.to_dict()
        assert "block_size" in d
        assert "method" in d
        assert d["method"] == "block"
