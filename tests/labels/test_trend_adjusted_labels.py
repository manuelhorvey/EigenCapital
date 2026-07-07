"""Tests for labels/trend_adjusted_labels — trend-adjusted triple-barrier labels."""

import numpy as np
import pandas as pd
import pytest

from labels.trend_adjusted_labels import (
    _trend_slope,
    _adx,
    trend_adjusted_pt_sl,
    trend_adjusted_labels,
)


class TestTrendSlope:
    def test_positive_slope_for_upward_trend(self):
        close = pd.Series(np.linspace(100, 200, 100))
        slope = _trend_slope(close, span=20)
        last_vals = slope.tail(10)
        assert (last_vals > 0).all()

    def test_negative_slope_for_downward_trend(self):
        close = pd.Series(np.linspace(200, 100, 100))
        slope = _trend_slope(close, span=20)
        last_vals = slope.tail(10)
        assert (last_vals < 0).all()

    def test_near_zero_for_flat(self):
        close = pd.Series(np.ones(100) * 100)
        slope = _trend_slope(close, span=20)
        assert slope.abs().max() < 1e-6

    def test_fills_na_with_zero(self):
        close = pd.Series([100.0] * 100)
        slope = _trend_slope(close, span=20)
        assert not slope.isna().any()


class TestADX:
    def test_high_adx_in_trending_market(self):
        rng = np.random.RandomState(42)
        n = 200
        close = pd.Series(100 + np.cumsum(rng.randn(n) * 0.5))
        high = close * 1.01
        low = close * 0.99
        adx = _adx(high, low, close, period=14)
        assert adx.max() <= 100
        assert adx.min() >= 0

    def test_low_adx_in_random_market(self):
        rng = np.random.RandomState(42)
        n = 300
        close = pd.Series(100 + np.cumsum(rng.randn(n) * 0.1))
        high = close * 1.005
        low = close * 0.995
        adx = _adx(high, low, close, period=14)
        assert adx.max() <= 100

    def test_returns_series(self):
        close = pd.Series(np.linspace(100, 110, 100))
        high = close * 1.01
        low = close * 0.99
        adx = _adx(high, low, close)
        assert isinstance(adx, pd.Series)
        assert len(adx) == 100


class TestTrendAdjustedPtSl:
    def test_returns_correct_shape(self):
        close = pd.Series(np.linspace(100, 110, 200))
        high = close * 1.01
        low = close * 0.99
        result = trend_adjusted_pt_sl(close, high, low, base_pt_sl=(2.0, 2.0))
        assert result.shape == (200, 2)

    def test_uptrend_narrows_tp_widens_sl(self):
        """In an uptrend, TP barrier should narrow and SL barrier widen."""
        close = pd.Series(np.linspace(100, 200, 300))
        high = close * 1.01
        low = close * 0.99
        adjusted = trend_adjusted_pt_sl(close, high, low, base_pt_sl=(2.0, 2.0),
                                         adx_threshold=15.0, widen_factor=1.5, narrow_factor=0.75)
        # After trend is established, tp_mult should be < base and sl_mult > base
        later = adjusted[-50:]
        assert later[:, 0].mean() < 2.0  # TP narrowed
        assert later[:, 1].mean() > 2.0  # SL widened

    def test_base_returns_when_no_high_low(self):
        close = pd.Series(np.linspace(100, 110, 200))
        result = trend_adjusted_pt_sl(close, high=None, low=None, base_pt_sl=(2.0, 2.0))
        assert result.shape == (200, 2)
        # Without high/low, ADX is always 0, so no adjustment
        assert np.allclose(result, [2.0, 2.0])


class TestTrendAdjustedLabels:
    def test_returns_series_with_valid_labels(self):
        rng = np.random.RandomState(42)
        n = 300
        df = pd.DataFrame({
            "close": 100 + np.cumsum(rng.randn(n) * 0.5),
            "high": 100 + np.cumsum(rng.randn(n) * 0.5) * 1.01,
            "low": 100 + np.cumsum(rng.randn(n) * 0.5) * 0.99,
        })
        labels = trend_adjusted_labels(df, pt_sl=(2.0, 2.0), vertical_barrier=20)
        assert isinstance(labels, pd.Series)
        assert labels.isin([-1, 0, 1]).all()
        assert len(labels) == n

    def test_returns_flat_with_insufficient_data(self):
        df = pd.DataFrame({"close": [100, 101, 102]})
        labels = trend_adjusted_labels(df, pt_sl=(2.0, 2.0), vertical_barrier=20)
        assert (labels == 0).all()

    def test_custom_parameters(self):
        rng = np.random.RandomState(42)
        n = 300
        df = pd.DataFrame({
            "close": 100 + np.cumsum(rng.randn(n) * 0.5),
            "high": 100 + np.cumsum(rng.randn(n) * 0.5) * 1.01,
            "low": 100 + np.cumsum(rng.randn(n) * 0.5) * 0.99,
        })
        labels = trend_adjusted_labels(df, pt_sl=(1.0, 1.0), vertical_barrier=10,
                                        adx_threshold=25.0, widen_factor=2.0, narrow_factor=0.5)
        assert len(labels) == n

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        labels = trend_adjusted_labels(df, pt_sl=(2.0, 2.0), vertical_barrier=20)
        assert labels.empty
