import numpy as np
import pandas as pd
import pytest

from portfolio.correlation_clusters import (
    cluster_assets,
    compute_correlation_matrix,
    correlation_to_distance,
    get_cluster_summary,
)
from portfolio.hrp_allocator import (
    _get_cluster_variance,
    _get_quasi_diag,
)
from shared.portfolio_weights import compute_weights

# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def asset_returns():
    np.random.seed(42)
    n = 252
    returns = pd.DataFrame(
        {
            "ASSET_A": np.random.randn(n) * 0.01,
            "ASSET_B": np.random.randn(n) * 0.015,
            "ASSET_C": np.random.randn(n) * 0.02,
            "ASSET_D": np.random.randn(n) * 0.008,
        },
        index=pd.RangeIndex(n),
    )
    returns["ASSET_E"] = returns["ASSET_A"] * 0.9 + np.random.randn(n) * 0.001
    return returns


@pytest.fixture
def correlated_returns():
    np.random.seed(99)
    n = 252
    base = np.random.randn(n) * 0.01
    return pd.DataFrame(
        {
            "A": base + np.random.randn(n) * 0.002,
            "B": base + np.random.randn(n) * 0.002,
            "C": base + np.random.randn(n) * 0.002,
            "D": np.random.randn(n) * 0.015,
            "E": np.random.randn(n) * 0.02,
        },
        index=pd.RangeIndex(n),
    )


# ── risk_parity ──────────────────────────────────────────────────────────────


class TestRiskParity:
    def test_compute_risk_parity_returns_weight_vector(self, asset_returns):
        result = compute_weights("risk_parity_v1", asset_returns)
        assert result.weights.keys() == set(asset_returns.columns)

    def test_weights_sum_to_one(self, asset_returns):
        result = compute_weights("risk_parity_v1", asset_returns)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_weights_are_positive(self, asset_returns):
        result = compute_weights("risk_parity_v1", asset_returns)
        assert all(v >= 0 for v in result.weights.values())


# ── correlation_clusters ─────────────────────────────────────────────────────


class TestCorrelationClusters:
    def test_compute_correlation_matrix(self, asset_returns):
        corr = compute_correlation_matrix(asset_returns)
        assert corr.shape == (len(asset_returns.columns), len(asset_returns.columns))
        assert corr.values.min() >= -1
        assert corr.values.max() <= 1

    def test_compute_correlation_matrix_spearman(self, asset_returns):
        corr = compute_correlation_matrix(asset_returns, method="spearman")
        assert corr.shape == (len(asset_returns.columns), len(asset_returns.columns))

    def test_correlation_to_distance(self, asset_returns):
        corr = compute_correlation_matrix(asset_returns)
        dist = correlation_to_distance(corr)
        assert dist.shape == corr.shape
        assert dist.values.min() >= 0

    def test_cluster_assets_with_n_clusters(self, asset_returns):
        labels = cluster_assets(asset_returns, n_clusters=3)
        assert isinstance(labels, dict)
        assert set(labels.keys()) == set(asset_returns.columns)
        assert len(set(labels.values())) <= 3

    def test_cluster_assets_with_threshold(self, asset_returns):
        labels = cluster_assets(asset_returns, threshold=0.5)
        assert isinstance(labels, dict)

    def test_cluster_assets_default(self, asset_returns):
        labels = cluster_assets(asset_returns)
        assert isinstance(labels, dict)

    def test_get_cluster_summary(self, asset_returns):
        labels = cluster_assets(asset_returns, n_clusters=2)
        summary = get_cluster_summary(asset_returns, labels)
        assert isinstance(summary, pd.DataFrame)
        assert "cluster" in summary.columns
        assert "n_assets" in summary.columns
        assert "members" in summary.columns

    def test_cluster_correlated_assets(self, correlated_returns):
        labels = cluster_assets(correlated_returns, n_clusters=2)
        label_a = labels["A"]
        label_b = labels["B"]
        label_c = labels["C"]
        assert label_a == label_b == label_c


# ── hrp_allocator ────────────────────────────────────────────────────────────
# The _get_quasi_diag bug (partial-linkage dendrogram instability) is fixed:
# _hrp_weights now uses standard HRP recursive bisection on the full
# quasi-diagonal order, eliminating the partial-linkage slice approach.
# optimal_leaf_ordering is applied in hrp_allocation() for deterministic
# leaf ordering even with non-metric distance matrices.


class TestHRPHelpers:
    def test_get_quasi_diag_basic(self):
        """_get_quasi_diag processes linkage matrix correctly."""
        import numpy as np

        link = np.array([[0, 2, 1.0, 2], [4, 5, 1.0, 3], [1, 6, 1.0, 4], [3, 7, 1.0, 5]])
        result = _get_quasi_diag(link)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_get_quasi_diag_optimal_leaf_ordering(self):
        """_get_quasi_diag with dist produces a consistent leaf order
        regardless of the metric properties of the distance matrix."""
        import numpy as np
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import squareform

        np.random.seed(42)
        corr = np.array(
            [
                [1.0, 0.9, 0.3, 0.2],
                [0.9, 1.0, 0.25, 0.15],
                [0.3, 0.25, 1.0, 0.85],
                [0.2, 0.15, 0.85, 1.0],
            ]
        )
        dist = np.sqrt(2 * (1 - corr))
        condensed = squareform(dist, force="tovector", checks=False)
        link = linkage(condensed, method="single")
        result_a = _get_quasi_diag(link, condensed)
        result_b = _get_quasi_diag(link, condensed)
        assert result_a == result_b, "optimal_leaf_ordering must be deterministic"

    def test_hrp_allocation_deterministic(self, asset_returns):
        """hrp_allocation produces deterministic weights."""
        from portfolio.hrp_allocator import hrp_allocation

        w1 = hrp_allocation(asset_returns)
        w2 = hrp_allocation(asset_returns)
        assert w1 == w2

    def test_hrp_allocation_weights_sum_to_one(self, asset_returns):
        """hrp_allocation weights sum to 1."""
        from portfolio.hrp_allocator import hrp_allocation

        w = hrp_allocation(asset_returns)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_get_cluster_variance(self, asset_returns):
        """_get_cluster_variance returns a positive float."""
        cov = asset_returns.cov()
        v = _get_cluster_variance(cov, [0, 1, 2])
        assert isinstance(v, float)
        assert v > 0
