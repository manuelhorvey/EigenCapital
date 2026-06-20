"""
Trend-adjusted triple-barrier labels — penalize reversal bets during trends.

Hypothesis:
  During strong trends, making counter-trend labels harder to achieve
  reduces the model's tendency to flip direction at fold boundaries.

Method:
  1. Compute 20-day EMA slope for trend direction + ADX for confirmation.
  2. When ADX > threshold (default 20), adjust pt_sl per timestep:
     - Uptrend: widen lower barrier (harder to get SELL label).
     - Downtrend: widen upper barrier (harder to get BUY label).
  3. When ADX <= threshold: use base pt_sl (symmetric or as-configured).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _trend_slope(close: pd.Series, span: int = 20) -> pd.Series:
    """Normalized EMA slope as fraction of close."""
    ema = close.ewm(span=span, adjust=False).mean()
    slope = ema.diff(span) / close
    return slope.fillna(0.0)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (0-100)."""
    h = high.astype(float)
    lo = low.astype(float)
    c = close.astype(float)

    up = h.diff()
    down = -lo.diff()

    plus_dm = ((up > down) & (up > 0)).astype(float) * up
    minus_dm = ((down > up) & (down > 0)).astype(float) * down

    tr = pd.concat(
        [h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1
    ).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx.fillna(0.0)


def trend_adjusted_pt_sl(
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    base_pt_sl: tuple[float, float] = (2.0, 2.0),
    trend_span: int = 20,
    adx_period: int = 14,
    adx_threshold: float = 20.0,
    widen_factor: float = 1.5,
    narrow_factor: float = 0.75,
) -> np.ndarray:
    """Per-row pt_sl adjustments based on trend.

    Returns shape (n, 2) array of [tp_mult, sl_mult] per row.
    """
    slope = _trend_slope(close, span=trend_span)

    if high is not None and low is not None:
        strength = _adx(high, low, close, period=adx_period)
    else:
        strength = pd.Series(0.0, index=close.index)

    base_tp, base_sl = base_pt_sl
    n = len(close)
    adjusted = np.full((n, 2), [base_tp, base_sl], dtype=float)

    # Uptrend: slope > 0 and ADX > threshold
    mask_up = (slope > 0.0) & (strength > adx_threshold)
    adjusted[mask_up, 0] = base_tp * narrow_factor  # narrow upper barrier
    adjusted[mask_up, 1] = base_sl * widen_factor    # widen lower barrier

    # Downtrend: slope < 0 and ADX > threshold
    mask_down = (slope < 0.0) & (strength > adx_threshold)
    adjusted[mask_down, 0] = base_tp * widen_factor   # widen upper barrier
    adjusted[mask_down, 1] = base_sl * narrow_factor   # narrow lower barrier

    return adjusted


def trend_adjusted_labels(
    df: pd.DataFrame,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    vertical_barrier: int = 20,
    adx_threshold: float = 20.0,
    widen_factor: float = 1.5,
    narrow_factor: float = 0.75,
) -> pd.Series:
    """Apply triple-barrier with per-timestep trend-adjusted pt_sl.

    Returns pd.Series of labels: 1 (upper hit first), -1 (lower hit first), 0 (timeout).
    """
    if df.empty or len(df) < vertical_barrier + 5:
        return pd.Series(0, index=df.index, dtype=int)

    close = df["close"].astype(float).values
    has_hl = "high" in df.columns and "low" in df.columns
    high = df["high"] if has_hl else None
    low = df["low"] if has_hl else None

    pt_sl_arr = trend_adjusted_pt_sl(
        close=df["close"],
        high=high,
        low=low,
        base_pt_sl=pt_sl,
        adx_threshold=adx_threshold,
        widen_factor=widen_factor,
        narrow_factor=narrow_factor,
    )

    n = len(close)
    vb = vertical_barrier
    labels = np.zeros(n, dtype=int)

    if n <= vb:
        return pd.Series(labels, index=df.index)

    # Volatility for barrier width
    returns = np.log(close / np.roll(close, 1))
    returns[0] = 0.0
    vol = pd.Series(returns).ewm(span=100, adjust=False).std().values

    windows = np.lib.stride_tricks.sliding_window_view(close, vb + 1)
    curr = windows[:, 0]
    vol_slice = vol[: n - vb]
    tp_arr = pt_sl_arr[: n - vb, 0]
    sl_arr = pt_sl_arr[: n - vb, 1]

    upper = curr * (1.0 + vol_slice * tp_arr)
    lower = curr * (1.0 - vol_slice * sl_arr)

    future = windows[:, 1:]

    hit_upper = np.argmax(future >= upper[:, None], axis=1)
    hit_lower = np.argmax(future <= lower[:, None], axis=1)

    no_upper = ~np.any(future >= upper[:, None], axis=1)
    no_lower = ~np.any(future <= lower[:, None], axis=1)
    hit_upper[no_upper] = vb
    hit_lower[no_lower] = vb

    labeled = np.full(n - vb, 0, dtype=int)
    upper_first = hit_upper < hit_lower
    lower_first = hit_lower < hit_upper
    labeled[upper_first] = 1
    labeled[lower_first] = -1

    labels[: n - vb] = labeled
    return pd.Series(labels, index=df.index)
