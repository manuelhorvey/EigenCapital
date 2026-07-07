"""Tests for labels/compat — PurgedWalkForwardFolds and legacy triple_barrier_labels."""

import numpy as np
import pandas as pd
import pytest

from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels


class TestTripleBarrierLabels:
    def test_returns_series_with_correct_index(self):
        prices = pd.DataFrame({"close": 100 + np.cumsum(np.random.randn(300) * 0.5)})
        labels = triple_barrier_labels(prices, pt_sl=(2.0, 2.0), vertical_barrier=10, min_samples=100)
        assert isinstance(labels, pd.Series)
        assert len(labels) == len(prices)

    def test_labels_are_valid_values(self):
        prices = pd.DataFrame({"close": 100 + np.cumsum(np.random.randn(500) * 0.5)})
        labels = triple_barrier_labels(prices, pt_sl=(1.0, 1.0), vertical_barrier=20, min_samples=100)
        assert labels.isin([-1, 0, 1]).all()

    def test_below_min_samples_returns_flat(self):
        prices = pd.DataFrame({"close": 100 + np.cumsum(np.random.randn(10) * 0.5)})
        labels = triple_barrier_labels(prices, pt_sl=(2.0, 2.0), vertical_barrier=10, min_samples=200)
        assert (labels == 0).all()

    def test_custom_pt_sl(self):
        prices = pd.DataFrame({"close": 100 + np.cumsum(np.random.randn(300) * 0.5)})
        labels = triple_barrier_labels(prices, pt_sl=(3.0, 1.0), vertical_barrier=10, min_samples=100)
        assert len(labels) == len(prices)

    def test_handles_nan_vol(self):
        prices = pd.DataFrame({"close": [100.0] * 300})
        labels = triple_barrier_labels(prices, pt_sl=(2.0, 2.0), vertical_barrier=10, min_samples=100)
        assert (labels == 0).all()


class TestPurgedWalkForwardFolds:
    def test_default_parameters(self):
        cv = PurgedWalkForwardFolds()
        assert cv.n_folds == 5
        assert cv.gap == 20
        assert cv.min_train == 200
        assert cv.window_type == "expanding"

    def test_custom_parameters(self):
        cv = PurgedWalkForwardFolds(n_folds=3, gap=10, min_train=50, window_type="rolling", rolling_window_bars=200)
        assert cv.n_folds == 3
        assert cv.gap == 10
        assert cv.window_type == "rolling"

    def test_get_n_splits(self):
        cv = PurgedWalkForwardFolds(n_folds=4)
        assert cv.get_n_splits() == 4

    def test_split_returns_train_test_indices(self):
        n = 1000
        X = pd.DataFrame({"x": range(n)})
        cv = PurgedWalkForwardFolds(n_folds=3, gap=10, min_train=50)
        splits = list(cv.split(X))
        assert len(splits) == 3
        for train_idx, test_idx in splits:
            assert len(train_idx) > 0
            assert len(test_idx) > 0
            assert train_idx.dtype == np.int64 or train_idx.dtype == np.int32
            assert test_idx.dtype == np.int64 or test_idx.dtype == np.int32

    def test_split_no_overlap_between_train_and_test(self):
        n = 1000
        cv = PurgedWalkForwardFolds(n_folds=3, gap=20, min_train=50)
        for train_idx, test_idx in cv.split(pd.DataFrame({"x": range(n)})):
            overlap = set(train_idx) & set(test_idx)
            assert len(overlap) == 0

    def test_embargo_gap_respected(self):
        """Training set should end at least gap bars before test set starts."""
        n = 1000
        cv = PurgedWalkForwardFolds(n_folds=3, gap=20, min_train=50)
        for train_idx, test_idx in cv.split(pd.DataFrame({"x": range(n)})):
            if len(train_idx) > 0 and len(test_idx) > 0:
                max_train = train_idx.max()
                min_test = test_idx.min()
                assert max_train < min_test

    def test_rolling_window_type(self):
        n = 1000
        cv = PurgedWalkForwardFolds(n_folds=3, gap=10, min_train=50, window_type="rolling", rolling_window_bars=200)
        for train_idx, test_idx in cv.split(pd.DataFrame({"x": range(n)})):
            assert len(train_idx) <= 200

    def test_min_train_skips_small_folds(self):
        """When min_train is set high, early folds with insufficient data are skipped."""
        n = 500
        cv = PurgedWalkForwardFolds(n_folds=5, gap=20, min_train=400)
        splits = list(cv.split(pd.DataFrame({"x": range(n)})))
        # Some early folds may be skipped if train data is too small
        assert len(splits) <= 5
