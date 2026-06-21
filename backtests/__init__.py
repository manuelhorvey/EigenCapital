"""Backtesting utilities — per-fold label computation to prevent year-boundary leakage."""

import numpy as np
import pandas as pd

from labels.triple_barrier import apply_triple_barrier


def compute_per_fold_labels(
    close: pd.Series,
    train_mask: pd.Series | np.ndarray,
    test_mask: pd.Series | np.ndarray,
    contract,
) -> tuple[pd.Series, pd.Series]:
    """Compute triple-barrier labels per fold to prevent year-boundary lookahead leakage.

    Labels are computed separately for train and test sets, each extended
    by *vertical_barrier* rows beyond their respective boundaries so that
    near-boundary rows have a complete lookahead window.

    Returns (train_labels, test_labels) as int64 Series with values in {0, 1, 2}.
    """
    label_params = contract.label_params
    pt_sl = label_params.get("pt_sl", [2.0, 2.0])
    vb = label_params.get("vertical_barrier", 20)

    train_indices = np.where(
        train_mask.values if hasattr(train_mask, "values") else np.asarray(train_mask)
    )[0]
    test_indices = np.where(
        test_mask.values if hasattr(test_mask, "values") else np.asarray(test_mask)
    )[0]

    if len(train_indices) == 0 or len(test_indices) == 0:
        return pd.Series(dtype=int), pd.Series(dtype=int)

    all_close = close.values

    def _fold_labels(indices: np.ndarray, close_arr: np.ndarray) -> pd.Series:
        start = indices[0]
        end = min(len(close_arr), indices[-1] + vb + 1)
        fold_close = close_arr[start:end]
        fold_df = pd.DataFrame({"close": fold_close}, index=close.index[start:end])
        labeled = apply_triple_barrier(fold_df, pt_sl=pt_sl, vertical_barrier=vb)
        fold_labels = (labeled["label"] + 1).reindex(close.index[indices]).dropna().astype(int)
        return fold_labels

    train_labels = _fold_labels(train_indices, all_close)
    test_labels = _fold_labels(test_indices, all_close)

    return train_labels, test_labels
