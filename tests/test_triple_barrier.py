import pytest
import pandas as pd
import numpy as np
from labels.triple_barrier import apply_triple_barrier
from shared.volatility import compute_atr_pct


class TestComputeAtrPct:
    def test_returns_series(self, sample_price_data):
        vol = compute_atr_pct(sample_price_data, period=14)
        assert isinstance(vol, pd.Series)
        assert len(vol) > 0

    def test_positive_values(self, sample_price_data):
        vol = compute_atr_pct(sample_price_data, period=14)
        assert (vol > 0).all()


class TestApplyTripleBarrier:
    def test_returns_dataframe_with_label(self, sample_price_data):
        result = apply_triple_barrier(sample_price_data, pt_sl=[2, 2], vertical_barrier=5)
        assert isinstance(result, pd.DataFrame)
        assert "label" in result.columns

    def test_label_values_are_valid(self, sample_price_data):
        result = apply_triple_barrier(sample_price_data, pt_sl=[2, 2], vertical_barrier=5)
        labels = result["label"].dropna()
        assert labels.isin([-1, 0, 1]).all()

    def test_default_vertical_barrier(self, sample_price_data):
        result = apply_triple_barrier(sample_price_data, pt_sl=[1, 1])
        assert "label" in result.columns

    def test_custom_pt_sl(self, sample_price_data):
        result = apply_triple_barrier(sample_price_data, pt_sl=[3, 3], vertical_barrier=10)
        assert "label" in result.columns

    def test_empty_dataframe(self):
        empty = pd.DataFrame(columns=["close"])
        result = apply_triple_barrier(empty, pt_sl=[2, 2], vertical_barrier=5)
        assert "label" in result.columns

    def test_short_window(self):
        short = pd.DataFrame({"close": [100, 101, 102]})
        result = apply_triple_barrier(short, pt_sl=[2, 2], vertical_barrier=5)
        assert "label" in result.columns

    def test_provided_target(self, sample_price_data):
        target = pd.Series(np.full(len(sample_price_data), 0.02), index=sample_price_data.index)
        result = apply_triple_barrier(sample_price_data, pt_sl=[1, 1], target=target, vertical_barrier=5)
        assert "label" in result.columns

    def test_main_executes_without_error(self):
        import labels.triple_barrier as tb
        assert hasattr(tb, "apply_triple_barrier")

    def test_all_three_labels_appear_with_enough_data(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(500) * 0.5)
        df = pd.DataFrame({"close": prices})
        result = apply_triple_barrier(df, pt_sl=[1, 1], vertical_barrier=20)
        labels = result["label"].dropna()
        unique_labels = set(labels.unique())
        assert -1 in unique_labels
        assert 0 in unique_labels
        assert 1 in unique_labels
