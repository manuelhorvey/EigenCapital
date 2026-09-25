"""Vectorized research estimators must match the canonical Bar-based
primitives exactly (same statistic, same window, same annualization)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from eigencapital.core.models.bar import Bar
from eigencapital.features.base.ranges import compute_true_range
from eigencapital.features.base.volatility import compute_realized_volatility
from research.volatility import features as F


def _bars_from_closes(closes: list[float]) -> list[Bar]:
    bars = []
    base = pd.Timestamp("2024-01-01")
    for i, c in enumerate(closes):
        h = c * 1.001
        lo = c * 0.999
        end = (base + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = (base + pd.Timedelta(days=i + 1) - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        bars.append(
            Bar(
                instrument_id="TEST",
                timestamp_utc=end,
                bar_start_utc=start,
                bar_end_utc=end,
                open=c,
                high=h,
                low=lo,
                close=c,
                volume=1,
                bar_interval="1d",
            )
        )
    return bars


def test_realized_vol_matches_canonical_primitive():
    rng = np.random.default_rng(42)
    closes = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60))),
        index=pd.date_range("2024-01-01", periods=60, freq="D"),
    )
    bars = _bars_from_closes(list(closes))
    vec = F.realized_vol(closes, 20)
    lookback = 20
    # vec is built on log_returns (drops first row), so vec.iloc[i-1]
    # is the window ending at closes index i — same window the canonical
    # primitive sees via bars[: i + 1] (last lookback+1 closes).
    for i in range(lookback, len(closes)):
        canon = compute_realized_volatility(bars[: i + 1], lookback)
        assert canon is not None
        assert vec.iloc[i - 1] == pytest.approx(canon, rel=1e-12)


def test_realized_vol_is_annualized_sqrt252():
    rng = np.random.default_rng(7)
    closes = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, 80))),
        index=pd.date_range("2024-01-01", periods=80, freq="D"),
    )
    vec = F.realized_vol(closes, 20)
    r = np.log(closes / closes.shift(1))
    # first return is NaN; vec starts at index 1 (first valid return)
    daily = r.iloc[1:].rolling(20).std(ddof=1)
    pd.testing.assert_series_equal(vec, daily * math.sqrt(252), check_names=False)


def test_true_range_matches_canonical():
    rng = np.random.default_rng(3)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 30))))
    bars = _bars_from_closes(closes)
    prev = None
    for i, b in enumerate(bars):
        if i == 0:
            continue
        prev = bars[i - 1].close
        canon = compute_true_range(b, prev)
        # research panel TR definition (features.atr_pct) on the same numbers
        h, lo = b.high, b.low
        tr = max(h - lo, abs(h - prev), abs(lo - prev))
        assert tr == pytest.approx(canon, rel=1e-15)


def test_log_returns_drops_first_row():
    s = pd.Series([100.0, 101.0, 99.0, 102.0])
    lr = F.log_returns(s)
    assert len(lr) == 3
    assert lr.iloc[0] == pytest.approx(math.log(101 / 100))
