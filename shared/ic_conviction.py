"""
Rolling Information-Coefficient-based conviction scoring.

Computes per-asset conviction scores from rolling IC (Spearman rank
correlation of ``p_long`` vs ``label``) over a lookback window.  The
conviction score drives portfolio weight tilts in
``conviction_weighted_v2`` — assets with persistently strong IC
get a larger weight; assets with weak or negative IC get down-weighted.

Usage
-----
    from shared.ic_conviction import compute_rolling_ic_conviction

    scores = compute_rolling_ic_conviction(
        asset_signal_dfs,
        cutoff_date="2025-06-01",
        ic_window=60,
    )
    # scores == {"EURUSD": 1.24, "GBPUSD": 0.87, ...}
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_rolling_ic(
    df: pd.DataFrame,
    cutoff: pd.Timestamp,
    window: int = 60,
    min_periods: int = 20,
) -> float:
    """Compute rolling Information Coefficient for a single asset up to *cutoff*.

    IC is the Spearman rank correlation of ``p_long`` vs ``label`` over the
    trailing *window* rows (strictly before *cutoff* — no lookahead).

    Parameters
    ----------
    df : pd.DataFrame
        Signal DataFrame with columns ``p_long`` and ``label`` and a
        DatetimeIndex (may be timezone-aware).
    cutoff : pd.Timestamp
        Compute IC using data strictly before this timestamp.
    window : int
        Trailing rows to include in the IC computation (default 60).
    min_periods : int
        Minimum number of rows required to compute a non-nan IC (default 20).

    Returns
    -------
    float
        Spearman IC in [-1, 1], or 0.0 if insufficient data.
    """
    from scipy.stats import spearmanr

    # Filter data strictly before cutoff
    hist = df[df.index < cutoff].copy()
    if len(hist) < min_periods:
        return 0.0

    # Use the trailing window rows
    lookback = hist.tail(window)

    p_long = lookback["p_long"].astype(float).values
    label = lookback["label"].astype(float).values

    # Filter out NaN
    valid = ~(np.isnan(p_long) | np.isnan(label))
    if valid.sum() < min_periods:
        return 0.0

    ic_val, p_val = spearmanr(p_long[valid], label[valid])
    if np.isnan(ic_val):
        return 0.0

    return float(ic_val)


def ic_to_conviction(
    ic_values: dict[str, float] | pd.Series,
    scale_factor: float = 0.05,
    min_score: float = 0.25,
    max_score: float = 2.0,
) -> dict[str, float]:
    """Map raw IC values to conviction scores in [*min_score*, *max_score*].

    The mapping is::

        score = clamp(ic / scale_factor, min_score, max_score)

    where the default *scale_factor* (0.05) maps an IC of +0.05 (the
    portfolio average from our analysis) to a neutral score of 1.0.
    An IC of +0.448 (GC) maps to 2.0 (capped), and an IC of -0.12
    (NZDJPY) maps to 0.0 → clamped to *min_score* (0.25).

    Parameters
    ----------
    ic_values : dict[str, float] or pd.Series
        Asset → IC in [-1, 1].
    scale_factor : float
        IC value that maps to a score of 1.0 (neutral).
        Default 0.05 = portfolio-average IC from historical analysis.
    min_score : float
        Floor for output scores (default 0.25).
    max_score : float
        Ceiling for output scores (default 2.0).

    Returns
    -------
    dict[str, float]
        Asset → conviction score in [*min_score*, *max_score*].
    """
    if isinstance(ic_values, pd.Series):
        ic_values = ic_values.to_dict()

    scores: dict[str, float] = {}
    for asset, ic in ic_values.items():
        if np.isnan(ic) or ic == 0.0:
            # NaN or zero IC means insufficient data or truly no correlation.
            # Treat both as neutral (score = 1.0).
            scores[asset] = 1.0
        else:
            raw = ic / scale_factor if scale_factor > 0 else 1.0
            scores[asset] = round(float(np.clip(raw, min_score, max_score)), 4)

    return scores


def compute_rolling_ic_conviction(
    asset_signal_dfs: dict[str, pd.DataFrame],
    cutoff_date: str | pd.Timestamp,
    ic_window: int = 60,
    ic_min_periods: int = 20,
    scale_factor: float = 0.05,
    min_score: float = 0.25,
    max_score: float = 2.0,
    negative_ic_floor: float = 0.25,
) -> dict[str, float]:
    """Compute per-asset conviction scores from rolling IC up to *cutoff_date*.

    This is the main entry point for the rolling IC conviction pipeline.
    For each asset:
      1. Compute rolling IC (Spearman of ``p_long`` vs ``label``) over the
         trailing *ic_window* rows before *cutoff_date*.
      2. Map IC → conviction score using ``ic_to_conviction()``.

    Parameters
    ----------
    asset_signal_dfs : dict[str, pd.DataFrame]
        Per-asset signal DataFrames with columns ``p_long``, ``label``,
        ``signal`` and a DatetimeIndex (may be timezone-aware).
    cutoff_date : str or pd.Timestamp
        Only data strictly before this date is used (no lookahead).
        If a string, parsed as ISO date (timezone-naive).
    ic_window : int
        Trailing rows for IC computation (default 60).
    ic_min_periods : int
        Minimum rows for a valid IC (default 20).
    scale_factor : float
        IC value mapping to neutral score 1.0 (default 0.05).
    min_score : float
        Floor for output scores (default 0.25).
    max_score : float
        Ceiling for output scores (default 2.0).
    negative_ic_floor : float
        Assets with negative IC get this score (default 0.25), because
        a negative IC means the model's predictions are inverted — the
        portfolio should not trust those signals.

    Returns
    -------
    dict[str, float]
        Asset → conviction score in [*min_score*, *max_score*].
    """
    if isinstance(cutoff_date, str):
        # Infer timezone from signal DataFrames
        sample_df = next(iter(asset_signal_dfs.values()), pd.DataFrame())
        index_tz = sample_df.index.tz if not sample_df.empty else None
        cutoff = pd.Timestamp(cutoff_date, tz=index_tz) if index_tz else pd.Timestamp(cutoff_date)
    else:
        cutoff = cutoff_date

    ic_values: dict[str, float] = {}
    for asset, df in asset_signal_dfs.items():
        ic = compute_rolling_ic(df, cutoff, window=ic_window, min_periods=ic_min_periods)
        ic_values[asset] = ic

    scores = ic_to_conviction(ic_values, scale_factor=scale_factor, min_score=min_score, max_score=max_score)

    # Override negative-IC assets to the floor — the portfolio should
    # underweight assets whose predictions are systematically inverted.
    for asset, ic in ic_values.items():
        if ic < 0:
            scores[asset] = negative_ic_floor

    n_with_data = sum(1 for v in ic_values.values() if abs(v) > 0.01)
    n_negative = sum(1 for v in ic_values.values() if v < -0.01)
    n_positive = sum(1 for v in ic_values.values() if v > 0.01)

    if n_with_data > 0:
        mean_ic = float(np.mean([v for v in ic_values.values() if abs(v) > 0.01]))
    else:
        mean_ic = 0.0

    logger.debug(
        "Rolling IC conviction: %d/%d assets with signal, mean IC=%.4f, "
        "%d positive, %d negative → score range [%.2f, %.2f]",
        n_with_data,
        len(asset_signal_dfs),
        mean_ic,
        n_positive,
        n_negative,
        min(scores.values()),
        max(scores.values()),
    )

    return scores


def compute_rolling_ic_time_series(
    asset_signal_dfs: dict[str, pd.DataFrame],
    dates: list[pd.Timestamp],
    ic_window: int = 60,
    min_periods: int = 20,
) -> pd.DataFrame:
    """Compute IC values at each date for all assets.

    Produces a DataFrame where rows are dates and columns are assets,
    with IC values computed at each date using data strictly before it.
    Useful for generating conviction weight time series in backtesting.

    Parameters
    ----------
    asset_signal_dfs : dict[str, pd.DataFrame]
        Per-asset signal DataFrames.
    dates : list[pd.Timestamp]
        Dates at which to compute IC.  Only data strictly before each
        date is used.
    ic_window : int
        Trailing rows for IC computation (default 60).
    min_periods : int
        Minimum rows for a valid IC (default 20).

    Returns
    -------
    pd.DataFrame
        Index = dates, columns = assets, values = IC in [-1, 1].
        Assets with insufficient data at any date get NaN.
    """
    records: list[dict[str, float]] = []
    for dt in dates:
        ic_vals: dict[str, float] = {}
        for asset, df in asset_signal_dfs.items():
            ic = compute_rolling_ic(df, dt, window=ic_window, min_periods=min_periods)
            ic_vals[asset] = ic if abs(ic) > 0 else 0.0
        records.append(ic_vals)

    df_ic = pd.DataFrame(records, index=pd.DatetimeIndex(dates))
    return df_ic


def conviction_from_ic_time_series(
    ic_df: pd.DataFrame,
    scale_factor: float = 0.05,
    min_score: float = 0.25,
    max_score: float = 2.0,
    negative_ic_floor: float = 0.25,
) -> pd.DataFrame:
    """Convert a rolling IC time series DataFrame into conviction scores.

    Parameters
    ----------
    ic_df : pd.DataFrame
        IC values from ``compute_rolling_ic_time_series()``.
    scale_factor : float
        IC value mapping to score 1.0 (default 0.05).
    min_score : float
        Floor for output scores (default 0.25).
    max_score : float
        Ceiling for output scores (default 2.0).
    negative_ic_floor : float
        Score given to assets with negative IC (default 0.25).

    Returns
    -------
    pd.DataFrame
        Same shape as *ic_df* with IC values converted to conviction scores.
    """
    raw = ic_df.copy()

    # Convert IC → score: raw / scale_factor, clamped
    scores = raw / scale_factor
    scores = scores.clip(lower=min_score, upper=max_score)

    # Negative IC assets get the floor
    scores[raw < 0] = negative_ic_floor

    # Zero IC (no data) gets neutral
    scores[raw == 0] = 1.0

    # Fill NaN (no data) with neutral
    scores = scores.fillna(1.0)

    return scores


def rolling_conviction_matrix(
    asset_signal_dfs: dict[str, pd.DataFrame],
    dates: list[pd.Timestamp] | pd.DatetimeIndex,
    ic_window: int = 60,
    min_periods: int = 20,
    scale_factor: float = 0.05,
    min_score: float = 0.25,
    max_score: float = 2.0,
    negative_ic_floor: float = 0.25,
    rebalance_freq: str = "monthly",
) -> pd.DataFrame:
    """Pre-compute a conviction score matrix for the full backtest period.

    Unlike ``compute_rolling_ic_conviction()`` which computes scores at a
    single date, this produces a DataFrame with conviction scores at each
    rebalance date.  Between rebalances, the conviction score is held
    constant (step-function).

    Parameters
    ----------
    asset_signal_dfs : dict[str, pd.DataFrame]
        Per-asset signal DataFrames.
    dates : list[pd.Timestamp] or pd.DatetimeIndex
        All trading dates in the backtest period.
    ic_window : int
        Trailing rows for IC computation (default 60).
    min_periods : int
        Minimum rows for a valid IC (default 20).
    scale_factor : float
        IC value mapping to score 1.0 (default 0.05).
    min_score : float
        Floor for output scores (default 0.25).
    max_score : float
        Ceiling for output scores (default 2.0).
    negative_ic_floor : float
        Score for negative-IC assets (default 0.25).
    rebalance_freq : str
        Frequency for re-computing conviction: ``"monthly"`` (default),
        ``"weekly"``, ``"daily"``.

    Returns
    -------
    pd.DataFrame
        Index = dates, columns = assets, values = conviction scores.
        Constant between rebalance dates.
    """
    if not isinstance(dates, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(sorted(dates))

    if len(dates) == 0:
        return pd.DataFrame()

    # Determine rebalance dates
    if rebalance_freq == "daily":
        reb_dates = dates
    elif rebalance_freq == "weekly":
        reb_dates = dates[dates.dayofweek == 0]  # Mondays
        if len(reb_dates) == 0:
            reb_dates = dates[[0]]
    elif rebalance_freq == "monthly":
        # First trading day of each month
        seen_months: set[str] = set()
        reb_idx: list[int] = []
        for i, dt in enumerate(dates):
            month_key = str(dt.date())[:7]
            if month_key not in seen_months:
                seen_months.add(month_key)
                reb_idx.append(i)
        reb_dates = dates[reb_idx]
    else:
        raise ValueError(f"Unknown rebalance_freq: {rebalance_freq}")

    # Compute IC at each rebalance date
    ic_df = compute_rolling_ic_time_series(
        asset_signal_dfs,
        list(reb_dates),
        ic_window=ic_window,
        min_periods=min_periods,
    )

    # Convert to conviction scores
    conv_df = conviction_from_ic_time_series(
        ic_df,
        scale_factor=scale_factor,
        min_score=min_score,
        max_score=max_score,
        negative_ic_floor=negative_ic_floor,
    )

    # Forward-fill from rebalance dates to all dates
    # Create a DataFrame indexed by all dates, forward-fill from the nearest
    # rebalance date
    full = pd.DataFrame(index=dates, columns=conv_df.columns, dtype=float)
    for col in conv_df.columns:
        full[col] = conv_df[col].reindex(dates, method="ffill").fillna(1.0)

    return full


def compute_conviction_at_date(
    asset_signal_dfs: dict[str, pd.DataFrame],
    cutoff_date: str | pd.Timestamp,
    **kwargs: Any,
) -> dict[str, float]:
    """Alias for ``compute_rolling_ic_conviction()`` with same signature.

    Convenience wrapper that forward-fills the rolling IC score to the
    given date.  Typically called at each rebalance date in a live engine
    or backtest.

    Parameters
    ----------
    asset_signal_dfs : dict[str, pd.DataFrame]
        Per-asset signal DataFrames.
    cutoff_date : str or pd.Timestamp
        Compute IC using data up to this date.
    **kwargs
        Passed to ``compute_rolling_ic_conviction()``.

    Returns
    -------
    dict[str, float]
        Asset → conviction score.
    """
    return compute_rolling_ic_conviction(asset_signal_dfs, cutoff_date, **kwargs)
