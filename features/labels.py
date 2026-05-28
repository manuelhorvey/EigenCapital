import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator

logger = logging.getLogger("quantforge.labels")


def triple_barrier_labels(
    prices: pd.DataFrame,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    vertical_barrier: int = 10,
    vol_lookback: int = 21,
    min_samples: int = 200,
) -> pd.Series:
    """
    Triple-barrier labeling using vol-scaled barriers.

    Barrier width = vol_lookback-day realised vol * pt_sl multiplier.
    Labels: 1 = TP hit first, -1 = SL hit first, 0 = time-out (neither hit).

    Parameters
    ----------
    prices : pd.DataFrame
        Must contain a 'close' column.
    pt_sl : (float, float)
        Multipliers on vol for take-profit and stop-loss barriers.
    vertical_barrier : int
        Max holding period in bars.
    vol_lookback : int
        Rolling window for realised vol estimate.
    min_samples : int
        Minimum rows required; returns all-0 Series if too short.

    Returns
    -------
    pd.Series of int in {-1, 0, 1} aligned to prices.index.
    """
    if len(prices) < min_samples:
        logger.warning("prices length %d < min_samples %d — returning flat labels", len(prices), min_samples)
        return pd.Series(0, index=prices.index, dtype=int)

    close = prices["close"].astype(float)
    log_returns = np.log(close / close.shift(1))
    vol = log_returns.rolling(vol_lookback).std()

    labels = pd.Series(0, index=prices.index, dtype=int)
    n = len(prices)

    for i in range(n - vertical_barrier):
        current = float(close.iloc[i])
        v = float(vol.iloc[i])
        if np.isnan(v) or v <= 0:
            continue

        tp_price = current * (1.0 + v * pt_sl[0])
        sl_price = current * (1.0 - v * pt_sl[1])

        future = close.iloc[i + 1 : i + vertical_barrier + 1]
        hit_tp = future[future >= tp_price]
        hit_sl = future[future <= sl_price]

        if not hit_tp.empty and (hit_sl.empty or hit_tp.index[0] < hit_sl.index[0]):
            labels.iloc[i] = 1
        elif not hit_sl.empty and (hit_tp.empty or hit_sl.index[0] < hit_tp.index[0]):
            labels.iloc[i] = -1

    return labels


def vol_adjusted_label(
    prices: pd.DataFrame,
    vol_lookback: int = 21,
    threshold: float = 0.5,
    forward_horizon: int = 1,
) -> pd.Series:
    """
    Label based on forward returns scaled by realised vol.

    1 if forward return > threshold * vol
    0 if |forward return| <= threshold * vol
   -1 if forward return < -threshold * vol

    Parameters
    ----------
    prices : pd.DataFrame with 'close' column.
    vol_lookback : int  — window for vol estimate.
    threshold : float  — vol multiplier for direction threshold.
    forward_horizon : int  — number of bars forward to measure return.

    Returns
    -------
    pd.Series of int in {-1, 0, 1}.
    """
    close = prices["close"].astype(float)
    log_returns = np.log(close / close.shift(1))
    vol = log_returns.rolling(vol_lookback).std()

    fwd_ret = close.pct_change(forward_horizon).shift(-forward_horizon)

    labels = pd.Series(0, index=prices.index, dtype=int)
    labels[fwd_ret > threshold * vol] = 1
    labels[fwd_ret < -threshold * vol] = -1
    return labels


class PurgedWalkForwardFolds(BaseCrossValidator):
    """
    Time-series cross-validator with purging and embargo.

    - Training set ends `gap` bars before test set starts (embargo)
      to prevent leakage from the test period's leading edge.
    - Each training fold excludes the `gap` bars after the previous
      test fold (purging) so no observation appears in both train
      and test.

    Parameters
    ----------
    n_folds : int (default=5)
    gap : int (default=5)
        Number of embargo bars between train and test.
    min_train : int (default=200)
        Minimum observations required per training fold.
    """

    def __init__(
        self,
        n_folds: int = 5,
        gap: int = 5,
        min_train: int = 200,
    ):
        self.n_folds = n_folds
        self.gap = gap
        self.min_train = min_train

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_folds

    def split(self, X, y=None, groups=None):
        n = len(X)
        fold_size = n // (self.n_folds + 1)

        for i in range(1, self.n_folds + 1):
            test_start = i * fold_size
            test_end = min(test_start + fold_size, n)

            train_end = test_start - self.gap
            idx = list(range(n))

            train_idx = idx[:train_end]
            test_idx = idx[test_start:test_end]

            if len(train_idx) < self.min_train:
                continue

            yield np.array(train_idx, dtype=int), np.array(test_idx, dtype=int)

