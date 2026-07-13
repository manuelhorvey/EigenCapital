"""Group 4 — Event & calendar features.

Deterministic features derived from the date index — no external data
source or economic calendar dependency.

All features are identical for every inference cycle within the same
daily bar, ensuring training-inference consistency.

Features
--------
- ``{ASSET}_dow_0`` .. ``{ASSET}_dow_4``
    One-hot day-of-week (Monday=0 .. Friday=4).  Complements the existing
    ``{ASSET}_dow_signal`` (rolling forward return) by allowing the model
    to learn non-linear day-specific effects.

- ``{ASSET}_month_1`` .. ``{ASSET}_month_12``
    One-hot month-of-year (January=1 .. December=12).  Captures known
    seasonal patterns (January effect, September weakness, etc.).

- ``{ASSET}_fortnight``
    Which half of the month: 0 = first 15 days, 1 = day 16 onward.
    Captures month-two-week effects (e.g., post-NFP, option expiry week).

- ``{ASSET}_month_end``
    Binary: 1 if within 3 trading calendar days of month end.
    Captures portfolio rebalancing / window-dressing effects.

- ``{ASSET}_quarter_end``
    Binary: 1 if within 3 trading calendar days of quarter end.
    Institutional rebalancing flows.

- ``{ASSET}_week_of_month``
    Integer 1-5: which week (Mon-Sun) of the month the date falls in.
    Captures intra-month seasonality.

Coverage
--------
ALL 22 assets — these are purely date-derived.

Notes
-----
- No leakage: all features reflect known information at the time of the
  bar (the date of the bar itself).  No forward-looking reference.
- No external data required: the date index of the OHLCV DataFrame is
  sufficient.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("eigencapital.event_features")

# Trading days before month/quarter end to flag
_BOUNDARY_DAYS = 3


def _month_end_flag(index: pd.DatetimeIndex) -> pd.Series:
    """Return 1 for rows within the last 3 TRADING days of each month."""
    rank = index.to_series().groupby([index.year, index.month]).rank(ascending=False, method="min").astype(int)
    return (rank <= _BOUNDARY_DAYS).astype(int)


def _quarter_end_flag(index: pd.DatetimeIndex) -> pd.Series:
    """Return 1 for rows within the last 3 TRADING days of each quarter."""
    rank = index.to_series().groupby([index.year, index.quarter]).rank(ascending=False, method="min").astype(int)
    return (rank <= _BOUNDARY_DAYS).astype(int)


def _week_of_month(index: pd.DatetimeIndex) -> pd.Series:
    """Return week-of-month (1-5) for each date.

    Week 1 = days 1-7 of month, week 2 = days 8-14, etc.
    """
    day = index.day
    return ((day - 1) // 7 + 1).astype(int)


def compute_event_features(index: pd.Index) -> pd.DataFrame:
    """Compute all Group 4 event/calendar features from a date index.

    Parameters
    ----------
    index : pd.Index
        DatetimeIndex of the feature DataFrame (typically daily frequency).

    Returns
    -------
    pd.DataFrame
        Columns:
        - ``dow_0`` .. ``dow_4``: one-hot day-of-week
        - ``month_1`` .. ``month_12``: one-hot month-of-year
        - ``fortnight``: 0 (first half) / 1 (second half)
        - ``month_end``: binary boundary flag
        - ``quarter_end``: binary boundary flag
        - ``week_of_month``: int 1-5
    """
    if index is None or len(index) == 0:
        return pd.DataFrame()

    idx = pd.DatetimeIndex(index)
    parts: dict[str, pd.Series] = {}

    # Day-of-week one-hot (Mon=0 .. Fri=4)
    dow = idx.dayofweek
    for d in range(5):
        parts[f"dow_{d}"] = (dow == d).astype(int)

    # Month-of-year one-hot (Jan=1 .. Dec=12)
    month = idx.month
    for m in range(1, 13):
        parts[f"month_{m}"] = (month == m).astype(int)

    # Fortnight
    parts["fortnight"] = (idx.day > 15).astype(int)

    # Month / quarter end boundary
    parts["month_end"] = _month_end_flag(idx)
    parts["quarter_end"] = _quarter_end_flag(idx)

    # Week of month
    parts["week_of_month"] = _week_of_month(idx)

    return pd.DataFrame(parts, index=index)
