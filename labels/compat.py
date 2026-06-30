"""Legacy labeling functions kept for backward compatibility.

This module contains the loop-based ``triple_barrier_labels`` and
``PurgedWalkForwardFolds`` cross-validator.  New code should prefer
the vectorized ``apply_triple_barrier`` from ``labels.triple_barrier``.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator

logger = logging.getLogger("quorrin.labels.compat")


def triple_barrier_labels(
    prices: pd.DataFrame,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    vertical_barrier: int = 10,
    vol_lookback: int = 21,
    min_samples: int = 200,
) -> pd.Series:
    """Triple-barrier labeling using vol-scaled barriers (legacy loop-based).

    .. deprecated::
        Use ``labels.triple_barrier.apply_triple_barrier`` instead,
        which is vectorised and supports ATR volatility primitives.

    Barrier width = vol_lookback-day realised vol * pt_sl multiplier.
    Labels: 1 = TP hit first, -1 = SL hit first, 0 = time-out (neither hit).
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


class PurgedWalkForwardFolds(BaseCrossValidator):
    """Time-series cross-validator with purging and embargo.

    - Training set ends ``gap`` bars before test set starts (embargo)
      to prevent leakage from the test period's leading edge.
    - Each training fold excludes the ``gap`` bars after the previous
      test fold (purging) so no observation appears in both train and test.
    - Supports both expanding (all history) and rolling (fixed lookback)
      training windows via ``window_type`` and ``rolling_window_bars``.

    Parameters
    ----------
    n_folds : int
        Number of test windows (default 5).
    gap : int
        Embargo gap between train and test (default 20).
    min_train : int
        Minimum training samples required (default 200).
    window_type : str
        ``"expanding"`` (all history) or ``"rolling"`` (fixed lookback).
        Default ``"expanding"``.
    rolling_window_bars : int, optional
        Lookback in bars for ``"rolling"`` window.  If not set, defaults
        to ``fold_size * n_folds`` (approximate number of bars for a
        ``n_folds``-fold lookback).
    """

    def __init__(
        self,
        n_folds: int = 5,
        gap: int = 20,
        min_train: int = 200,
        window_type: str = "expanding",
        rolling_window_bars: int | None = None,
    ):
        self.n_folds = n_folds
        self.gap = gap
        self.min_train = min_train
        self.window_type = window_type
        self.rolling_window_bars = rolling_window_bars

    def get_n_splits(self, x=None, y=None, groups=None):
        return self.n_folds

    def split(self, x, y=None, groups=None):
        n = len(x)
        fold_size = n // (self.n_folds + 1)

        for i in range(1, self.n_folds + 1):
            test_start = i * fold_size
            test_end = min(test_start + fold_size, n)

            train_end = test_start - self.gap
            idx = list(range(n))

            train_idx = idx[:train_end]  # expanding (all history)

            # Purge previous folds' test data (with gap) from training set
            for j in range(1, i):
                prev_test_start = j * fold_size
                prev_test_end = min(prev_test_start + fold_size, n)
                purge_start = prev_test_start
                purge_end = min(prev_test_end + self.gap, n)
                train_idx = [t for t in train_idx if t < purge_start or t >= purge_end]

            # Rolling window: truncate to last N bars
            if self.window_type == "rolling":
                max_bars = self.rolling_window_bars or (fold_size * self.n_folds)
                train_idx = train_idx[-max_bars:]

            test_idx = idx[test_start:test_end]

            if len(train_idx) < self.min_train:
                continue

            yield np.array(train_idx, dtype=int), np.array(test_idx, dtype=int)
