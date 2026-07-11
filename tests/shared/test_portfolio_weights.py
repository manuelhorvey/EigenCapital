"""Tests for ``shared/portfolio_weights.py`` — weight computation."""

import numpy as np
import pandas as pd
import pytest

from shared.portfolio_weights import (
    IncrementalEWMACov,
    WeightVector,
    _ewma_cov,
    _shrinkage_cov,
    compute_weights,
    list_methods,
    risk_contribution,
    rolling_weight_matrix,
)


@pytest.fixture
def simple_returns():
    """3 assets × 100 days of correlated returns."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    data = {
        "EURUSD": rng.normal(0.0003, 0.005, 100),
        "GBPUSD": rng.normal(0.0002, 0.006, 100),
        "USDJPY": rng.normal(0.0001, 0.007, 100),
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def single_asset_returns():
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    return pd.DataFrame({"EURUSD": np.random.default_rng(42).normal(0.0003, 0.005, 50)}, index=dates)


# ═══════════════════════════════════════════════════════════════════
# WeightVector
# ═══════════════════════════════════════════════════════════════════


class TestWeightVector:
    def test_normalizes_to_one(self):
        wv = WeightVector(date="2025-01-01", method="equal_v1", weights={"A": 0.5, "B": 0.5})
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_handles_zero_total(self):
        wv = WeightVector(date="2025-01-01", method="equal_v1", weights={"A": 0.0, "B": 0.0})
        # No division by zero when total is 0
        assert abs(sum(wv.weights.values())) < 1e-6

    def test_to_series(self):
        wv = WeightVector(date="2025-01-01", method="equal_v1", weights={"A": 0.6, "B": 0.4})
        s = wv.to_series()
        assert s["A"] == 0.6
        assert s["B"] == 0.4
        assert s.name == "2025-01-01"

    def test_apply(self):
        wv = WeightVector(date="2025-01-01", method="equal_v1", weights={"A": 0.6, "B": 0.4})
        daily_r = pd.Series({"A": 0.01, "B": -0.005})
        result = wv.apply(daily_r)
        assert abs(result - (0.6 * 0.01 + 0.4 * -0.005)) < 1e-10

    def test_apply_skips_missing_assets(self):
        wv = WeightVector(date="2025-01-01", method="equal_v1", weights={"A": 1.0})
        daily_r = pd.Series({"B": 0.01})  # A not in index
        result = wv.apply(daily_r)
        assert result == 0.0

    def test_to_dict(self):
        wv = WeightVector(date="2025-01-01", method="risk_parity_v1", weights={"A": 1.0}, n_iter=10, converged=True)
        d = wv.to_dict()
        assert d["method"] == "risk_parity_v1"
        assert d["n_iter"] == 10
        assert d["converged"] is True


# ═══════════════════════════════════════════════════════════════════
# risk_contribution
# ═══════════════════════════════════════════════════════════════════


class TestRiskContribution:
    def test_returns_valid_values(self):
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        weights = np.array([0.5, 0.5])
        rc = risk_contribution(weights, cov)
        assert len(rc) == 2
        assert all(rc >= 0)

    def test_handles_zero_variance(self):
        cov = np.array([[0.0, 0.0], [0.0, 0.0]])
        weights = np.array([0.5, 0.5])
        rc = risk_contribution(weights, cov)
        assert all(rc == 0.5)

    def test_single_asset(self):
        cov = np.array([[0.04]])
        weights = np.array([1.0])
        rc = risk_contribution(weights, cov)
        # rc = w * cov * w / sqrt(w*cov*w) = sqrt(cov) = sqrt(0.04) = 0.2
        assert abs(rc[0] - 0.2) < 1e-6


# ═══════════════════════════════════════════════════════════════════
# Covariance estimators
# ═══════════════════════════════════════════════════════════════════


class TestShrinkageCov:
    def test_returns_dataframe(self, simple_returns):
        cov = _shrinkage_cov(simple_returns)
        assert isinstance(cov, pd.DataFrame)
        assert list(cov.columns) == list(simple_returns.columns)


class TestEwmaCov:
    def test_returns_dataframe(self, simple_returns):
        cov = _ewma_cov(simple_returns)
        assert isinstance(cov, pd.DataFrame)
        assert list(cov.columns) == list(simple_returns.columns)

    def test_handles_insufficient_data(self):
        returns = pd.DataFrame({"A": [0.01]}, index=pd.date_range("2025-01-01", periods=1))
        cov = _ewma_cov(returns)
        assert isinstance(cov, pd.DataFrame)
        assert cov.iloc[0, 0] == 0.0


# ═══════════════════════════════════════════════════════════════════
# compute_weights
# ═══════════════════════════════════════════════════════════════════


class TestComputeWeights:
    def test_equal_v1(self, simple_returns):
        wv = compute_weights("equal_v1", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
        n = len(simple_returns.columns)
        assert all(abs(w - 1.0 / n) < 1e-6 for w in wv.weights.values())

    def test_risk_parity_v1(self, simple_returns):
        wv = compute_weights("risk_parity_v1", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
        assert wv.method == "risk_parity_v1"

    def test_risk_parity_v2(self, simple_returns):
        wv = compute_weights("risk_parity_v2", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_risk_parity_v3(self, simple_returns):
        wv = compute_weights("risk_parity_v3", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_single_asset(self, single_asset_returns):
        wv = compute_weights("risk_parity_v1", single_asset_returns)
        assert abs(wv.weights["EURUSD"] - 1.0) < 1e-6

    def test_hrp_v1(self, simple_returns):
        wv = compute_weights("hrp_v1", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_factor_constrained_v2(self, simple_returns):
        wv = compute_weights("factor_constrained_v2", simple_returns)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_conviction_weighted_v1(self, simple_returns):
        wv = compute_weights(
            "conviction_weighted_v1",
            simple_returns,
            conviction={"EURUSD": 0.8, "GBPUSD": 0.6, "USDJPY": 0.4},
        )
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6

    def test_unknown_method_raises(self, simple_returns):
        with pytest.raises(ValueError, match="Unknown method"):
            compute_weights("nonexistent_v42", simple_returns)

    def test_accepts_date(self, simple_returns):
        wv = compute_weights("equal_v1", simple_returns, date="2025-06-15")
        assert wv.date == "2025-06-15"

    def test_empty_returns(self):
        df = pd.DataFrame()
        wv = compute_weights("equal_v1", df)
        assert wv.weights == {}


# ═══════════════════════════════════════════════════════════════════
# IncrementalEWMACov
# ═══════════════════════════════════════════════════════════════════


class TestIncrementalEWMACov:
    def test_initial_state(self):
        cov = IncrementalEWMACov(span=60)
        assert cov.cov is None
        assert cov._n == 0
        assert not cov._initialized

    def test_updates_single_asset(self):
        cov = IncrementalEWMACov(span=60)
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        for i in range(5):
            row = pd.Series({"A": np.random.randn()}, name=dates[i])
            cov.update(row)
        assert cov._initialized
        assert cov.cov is not None
        assert "A" in cov.cov.columns

    def test_converges_to_finite_values(self):
        """Incremental EWMA covariance should produce finite, reasonable
        values after many observations.  The incremental version does NOT
        annualize (the annualization factor is incompatible with incremental
        updates), so values are at daily frequency scale (~1e-5 to 1e-4).

        Use ``batch_annualize()`` to get annualized values comparable to
        ``_ewma_cov()``.
        """
        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-01", periods=200, freq="D")
        returns = pd.DataFrame({
            "A": rng.normal(0.0003, 0.005, 200),
            "B": rng.normal(0.0002, 0.006, 200),
        }, index=dates)

        inc = IncrementalEWMACov(span=60)
        for idx in range(len(returns)):
            inc.update(returns.iloc[idx])

        # After 200 observations, cov should be finite and non-NaN
        assert inc.cov is not None
        assert not np.any(np.isnan(inc.cov.values))
        assert not np.any(np.isinf(inc.cov.values))
        # Values are daily-scale (not annualized), so should be small
        assert -0.01 < inc.cov.values.min() < 0.01
        assert -0.01 < inc.cov.values.max() < 0.01
        # batch_annualize should return annualized values
        ann = inc.batch_annualize()
        assert ann is not None
        assert ann.shape == inc.cov.shape

    def test_raises_on_name_mismatch(self):
        cov = IncrementalEWMACov(span=60)
        cov.update(pd.Series({"A": 0.01}))
        with pytest.raises(ValueError, match="Asset names changed"):
            cov.update(pd.Series({"B": 0.01}))

    def test_reset(self):
        cov = IncrementalEWMACov(span=60)
        cov.update(pd.Series({"A": 0.01}))
        assert cov._initialized
        cov.reset()
        assert not cov._initialized
        assert cov.cov is None


# ═══════════════════════════════════════════════════════════════════
# list_methods
# ═══════════════════════════════════════════════════════════════════


class TestListMethods:
    def test_returns_registered_methods(self):
        methods = list_methods()
        assert "equal_v1" in methods
        assert "risk_parity_v1" in methods
        assert len(methods) >= 7  # at least the basic methods


# ═══════════════════════════════════════════════════════════════════
# rolling_weight_matrix
# ═══════════════════════════════════════════════════════════════════


class TestRollingWeightMatrix:
    def test_returns_dataframe(self, simple_returns):
        result = rolling_weight_matrix(simple_returns, "equal_v1", window=10, min_periods=5)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == list(simple_returns.columns)

    def test_each_row_sums_to_one(self, simple_returns):
        result = rolling_weight_matrix(simple_returns, "equal_v1", window=10, min_periods=5)
        for _, row in result.iterrows():
            assert abs(row.sum() - 1.0) < 1e-6

    def test_returns_empty_with_insufficient_data(self):
        df = pd.DataFrame({"A": [0.01, 0.02]}, index=pd.date_range("2025-01-01", periods=2))
        result = rolling_weight_matrix(df, "equal_v1", window=10, min_periods=5)
        assert result.empty
