import numpy as np
import pandas as pd
import pytest

from features.regime_features import (
    compute_hurst,
    compute_kaufman_er,
    generate_regime_features,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    n = 250
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "close": close,
        "high": close * (1 + np.random.uniform(0.001, 0.005, n)),
        "low": close * (1 - np.random.uniform(0.001, 0.005, n)),
        "volume": np.random.randint(1000, 100000, n).astype(float),
    }, index=pd.date_range("2020-01-01", periods=n, freq="D"))


# ── compute_hurst ────────────────────────────────────────────────────────────

def test_compute_hurst_returns_series(sample_ohlcv):
    h = compute_hurst(sample_ohlcv["close"], window=63)
    assert isinstance(h, pd.Series)
    assert len(h) == len(sample_ohlcv)


def test_compute_hurst_values_in_range(sample_ohlcv):
    h = compute_hurst(sample_ohlcv["close"], window=63).dropna()
    assert all(0 <= v <= 1 for v in h)


def test_compute_hurst_constant_series():
    series = pd.Series([100.0] * 200)
    h = compute_hurst(series, window=63).dropna()
    assert all(0 <= v <= 1 for v in h)


def test_compute_hurst_short_series():
    series = pd.Series([1, 2, 3, 4])
    h = compute_hurst(series, window=63)
    assert len(h.dropna()) == 0


# ── compute_kaufman_er ───────────────────────────────────────────────────────

def test_compute_kaufman_er_returns_series(sample_ohlcv):
    er = compute_kaufman_er(sample_ohlcv["close"], window=10)
    assert isinstance(er, pd.Series)
    assert len(er) == len(sample_ohlcv)


def test_compute_kaufman_er_bounds(sample_ohlcv):
    er = compute_kaufman_er(sample_ohlcv["close"], window=10).dropna()
    assert all(0 <= v <= 1 for v in er)


def test_compute_kaufman_er_perfect_trend():
    close = pd.Series(np.arange(100.0, 400.0))
    er = compute_kaufman_er(close, window=10).dropna()
    assert er.mean() > 0.8


def test_compute_kaufman_er_constant():
    close = pd.Series([100.0] * 100)
    er = compute_kaufman_er(close, window=10).dropna()
    assert all(v == 0.0 for v in er)


# ── generate_regime_features ─────────────────────────────────────────────────

def test_generate_regime_features_returns_expected_columns(sample_ohlcv):
    result = generate_regime_features(sample_ohlcv)
    expected = ["hurst", "kaufman_er", "adx", "vol_zscore", "compression", "utc_hour", "session_vol_profile"]
    for col in expected:
        assert col in result.columns, f"Missing column: {col}"


def test_generate_regime_features_no_nan_after_dropna(sample_ohlcv):
    result = generate_regime_features(sample_ohlcv)
    assert not result.isna().any().any()


def test_generate_regime_features_short_data():
    """Sufficient data for ADX but not for all rolling windows."""
    np.random.seed(42)
    n = 100
    df = pd.DataFrame({
        "close": 100 + np.cumsum(np.random.randn(n) * 0.5),
        "high": [101.5] * n,
        "low": [98.5] * n,
    }, index=pd.RangeIndex(n))
    result = generate_regime_features(df)
    assert len(result) > 0
    assert "adx" in result.columns


def test_generate_regime_features_utc_hour_present(sample_ohlcv):
    result = generate_regime_features(sample_ohlcv)
    assert "utc_hour" in result.columns
    assert result["utc_hour"].iloc[0] in range(24)


def test_generate_regime_features_vol_zscore(sample_ohlcv):
    result = generate_regime_features(sample_ohlcv)
    assert "vol_zscore" in result.columns
    assert result["vol_zscore"].notna().any()
