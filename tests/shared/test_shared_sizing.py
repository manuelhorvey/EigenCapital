import numpy as np
import pandas as pd
import pytest

from shared.portfolio_weights import (
    WeightVector,
    compute_weights,
    list_methods,
    risk_contribution as pf_risk_contribution,
    rolling_weight_matrix,
)
from shared.sizing import (
    risk_contribution,
    VolTargetSizing,
)


# ── risk_contribution ────────────────────────────────────────────────────────


def test_risk_contribution_sums_to_portfolio_vol():
    n = 4
    np.random.seed(42)
    cov = np.random.randn(n, n)
    cov = cov @ cov.T + np.eye(n) * 0.1
    w = np.ones(n) / n
    rc = risk_contribution(w, cov)
    assert abs(rc.sum() - np.sqrt(w @ cov @ w)) < 1e-6


# ── risk_parity_weights ──────────────────────────────────────────────────────


def test_risk_parity_weights_sum_to_one():
    np.random.seed(42)
    returns = pd.DataFrame(np.random.randn(252, 5) * 0.01, columns=list("ABCDE"))
    wv = compute_weights("risk_parity_v1", returns)
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6


def test_risk_parity_weights_all_positive():
    np.random.seed(42)
    returns = pd.DataFrame(np.random.randn(252, 3) * 0.01, columns=["X", "Y", "Z"])
    wv = compute_weights("risk_parity_v1", returns)
    assert all(v > 0 for v in wv.weights.values())


def test_risk_parity_higher_vol_gets_lower_weight():
    np.random.seed(42)
    n = 252
    returns = pd.DataFrame(
        {
            "LOW_VOL": np.random.randn(n) * 0.005,
            "HIGH_VOL": np.random.randn(n) * 0.03,
        }
    )
    wv = compute_weights("risk_parity_v1", returns)
    assert wv.weights["LOW_VOL"] > wv.weights["HIGH_VOL"]


# ── compute_equal_risk_weights ───────────────────────────────────────────────


def test_equal_risk_weights_sum_to_one():
    np.random.seed(42)
    returns = pd.DataFrame(np.random.randn(252, 4) * 0.01, columns=list("ABCD"))
    wv = compute_weights("risk_parity_v1", returns)
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6


def test_equal_risk_weights_all_assets_in_output():
    returns = pd.DataFrame(np.random.randn(100, 3), columns=["A", "B", "C"])
    wv = compute_weights("risk_parity_v1", returns)
    assert set(wv.weights.keys()) == {"A", "B", "C"}


# ── VolTargetSizing ──────────────────────────────────────────────────────────


def test_vol_target_sizing_no_scalar():
    sizer = VolTargetSizing()
    close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
    result = sizer.compute(close, {"vol_scalar": False})
    assert result == 1.0


def test_vol_target_sizing_with_scalar():
    sizer = VolTargetSizing(window=30, target_vol=0.30)
    close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
    result = sizer.compute(close, {"vol_scalar": True})
    assert 0 < result <= 1.0


def test_vol_target_sizing_short_history():
    sizer = VolTargetSizing(window=100)
    close = pd.Series([100.0, 101.0, 102.0])
    result = sizer.compute(close, {"vol_scalar": True})
    assert result == 1.0


def test_vol_target_sizing_regime_aware():
    sizer = VolTargetSizing(window=30, target_vol=0.30, regime_aware=True)
    np.random.seed(42)
    close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
    result_calm = sizer.compute(close, {"vol_scalar": True}, regime="calm")
    result_crisis = sizer.compute(close, {"vol_scalar": True}, regime="crisis")
    assert result_calm >= result_crisis


def test_vol_target_sizing_with_vol_baseline():
    sizer = VolTargetSizing(window=30, target_vol=0.30)
    close = pd.Series(np.full(100, 100.0))
    result = sizer.compute(close, {"vol_scalar": True, "vol_baseline": 0.2})
    assert result == 1.0


def test_vol_target_sizing_edge_decay():
    sizer = VolTargetSizing()
    assert sizer.edge_decay(3.0) == 1.0
    assert sizer.edge_decay(10.0) == 0.5


def test_vol_target_sizing_nan_rv():
    sizer = VolTargetSizing(window=30)
    close = pd.Series([np.nan] * 50)
    result = sizer.compute(close, {"vol_scalar": True})
    assert result == 1.0


# ── portfolio_weights ──────────────────────────────────────────────────────


def test_compute_weights_equal_v1():
    returns = pd.DataFrame(np.random.randn(100, 4), columns=["A", "B", "C", "D"])
    wv = compute_weights("equal_v1", returns)
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
    assert all(abs(v - 0.25) < 1e-6 for v in wv.weights.values())


def test_compute_weights_risk_parity_v1_sums_to_one():
    np.random.seed(42)
    returns = pd.DataFrame(np.random.randn(252, 4) * 0.01, columns=["A", "B", "C", "D"])
    wv = compute_weights("risk_parity_v1", returns)
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6


def test_risk_parity_v1_higher_vol_lower_weight():
    np.random.seed(42)
    n = 252
    cols = ["LOW_VOL", "HIGH_VOL"]
    returns = pd.DataFrame(
        {
            "LOW_VOL": np.random.randn(n) * 0.005,
            "HIGH_VOL": np.random.randn(n) * 0.03,
        }
    )
    wv = compute_weights("risk_parity_v1", returns)
    assert wv.weights["LOW_VOL"] > wv.weights["HIGH_VOL"] + 1e-6


def test_weight_vector_normalizes_on_construction():
    wv = WeightVector(date="2026-01-01", method="equal_v1", weights={"A": 0.5, "B": 0.5})
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
    assert abs(wv.weights["A"] - 0.5) < 1e-6


def test_weight_vector_normalizes_when_not_sum_one():
    wv = WeightVector(date="2026-01-01", method="equal_v1", weights={"A": 2.0, "B": 2.0})
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
    assert abs(wv.weights["A"] - 0.5) < 1e-6


def test_weight_vector_to_series():
    wv = WeightVector(date="2026-01-01", method="equal_v1", weights={"A": 0.6, "B": 0.4})
    s = wv.to_series()
    assert isinstance(s, pd.Series)
    assert abs(s["A"] - 0.6) < 1e-6
    assert abs(s["B"] - 0.4) < 1e-6
    assert s.name == "2026-01-01"


def test_weight_vector_apply():
    wv = WeightVector(date="2026-01-01", method="equal_v1", weights={"A": 0.5, "B": 0.5})
    daily_r = pd.Series({"A": 0.02, "B": -0.01})
    result = wv.apply(daily_r)
    assert abs(result - 0.005) < 1e-6


def test_rolling_weight_matrix_shape_and_sums():
    np.random.seed(42)
    n = 300
    returns = pd.DataFrame(
        np.random.randn(n, 3) * 0.01,
        columns=["A", "B", "C"],
    )
    window = 60
    wm = rolling_weight_matrix(returns, "equal_v1", window=window, min_periods=window)
    expected_rows = n - window
    assert wm.shape == (expected_rows, 3)
    row_sums = wm.sum(axis=1)
    assert (abs(row_sums - 1.0) < 1e-6).all()


def test_compute_weights_raises_unknown_method():
    returns = pd.DataFrame({"A": [0.01, -0.02]})
    with pytest.raises(ValueError, match="Unknown method"):
        compute_weights("nonexistent_v9", returns)  # type: ignore[arg-type]


def test_pf_risk_contribution_shape():
    n = 4
    cov = np.eye(n)
    weights = np.ones(n) / n
    rc = pf_risk_contribution(weights, cov)
    assert rc.shape == (n,)


def test_pf_risk_contribution_sums_to_portfolio_vol():
    np.random.seed(42)
    n = 4
    cov = np.random.randn(n, n)
    cov = cov @ cov.T + np.eye(n) * 0.1
    w = np.ones(n) / n
    rc = pf_risk_contribution(w, cov)
    assert abs(rc.sum() - np.sqrt(w @ cov @ w)) < 1e-6


def test_compute_weights_single_asset():
    returns = pd.DataFrame({"A": [0.01, -0.02, 0.03]})
    wv = compute_weights("equal_v1", returns)
    assert wv.weights == {"A": 1.0}
    wv2 = compute_weights("risk_parity_v1", returns)
    assert wv2.weights == {"A": 1.0}


def test_compute_weights_empty_returns():
    returns = pd.DataFrame()
    wv = compute_weights("equal_v1", returns)
    assert wv.weights == {}


def test_list_methods_returns_frozenset():
    methods = list_methods()
    assert isinstance(methods, frozenset)
    assert "equal_v1" in methods
    assert "risk_parity_v1" in methods
    assert "hrp_v1" in methods


def test_compute_weights_hrp_v1():
    np.random.seed(42)
    returns = pd.DataFrame(np.random.randn(252, 4) * 0.01, columns=["A", "B", "C", "D"])
    wv = compute_weights("hrp_v1", returns)
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
