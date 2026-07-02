"""Divergence detection for trend-exhaustion signals.

Detects bullish and bearish divergences between price and oscillators
(RSI, MACD) that precede trend reversals.

Reference:
    Lo, Mamaysky & Wang (2000) — "Foundations of Technical Analysis"
    demonstrate that divergence patterns have predictive power for
    short-term reversals in equity and FX markets.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger("eigencapital.divergence")


def rsi_divergence(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    rsi_window: int = 14,
    lookback: int = 20,
    rsi_threshold: float = 0.35,
) -> pd.Series:
    """Detect RSI divergence — the most reliable reversal signal.

    Bullish divergence (+1): Price makes a lower low (LL) while RSI
    makes a higher low (HL).  Indicates selling momentum is exhausting
    and a reversal higher is likely.  Most reliable when the second RSI
    low is below the oversold threshold (< 0.35 in normalized RSI).

    Bearish divergence (-1): Price makes a higher high (HH) while RSI
    makes a lower high (LH).  Indicates buying momentum is exhausting
    and a reversal lower is likely.

    For each day in *close*, checks the past *lookback* bars for any
    divergence pattern.  Returns -1 (bearish), 0 (none), or +1 (bullish)
    per day.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC data (same index).
    rsi_window : int
        RSI calculation window (default 14).
    lookback : int
        Lookback window for divergence detection (default 20 bars).
    rsi_threshold : float
        Normalized RSI threshold for extreme reading confirmation.
        RSI < threshold = oversold (needed for bullish divergence).
        RSI > 1 - threshold = overbought (needed for bearish divergence).

    Returns
    -------
    pd.Series with values {-1, 0, 1}, same index as *close*.
    """
    rsi_raw = ta.momentum.rsi(close, window=rsi_window)
    rsi = rsi_raw / 100.0  # Normalize to [0, 1]

    result = pd.Series(0, index=close.index, dtype=int)

    if len(close) < lookback * 2:
        logger.debug("RSI divergence: insufficient data (%d rows)", len(close))
        return result

    values = close.values
    rsi_vals = rsi.values

    for i in range(lookback, len(close)):
        left = i - lookback
        right = i + 1

        price_window = values[left:right]
        rsi_window_vals = rsi_vals[left:right]

        # Find local extrema in this window
        min_px = price_window.min()
        max_px = price_window.max()
        min_rsi = rsi_window_vals.min()
        max_rsi = rsi_window_vals.max()

        # Indices of extrema within the window
        min_px_idx = np.where(price_window == min_px)[0]
        max_px_idx = np.where(price_window == max_px)[0]
        min_rsi_idx = np.where(rsi_window_vals == min_rsi)[0]
        max_rsi_idx = np.where(rsi_window_vals == max_rsi)[0]

        # ── Bullish divergence —────────────────────────────────────────
        # Price makes a lower low (the most recent low is lower than the
        # previous low), but RSI makes a higher low.
        # Confirmed if the most recent RSI low is below oversold threshold.
        if len(min_px_idx) >= 2 and len(min_rsi_idx) >= 2:
            # Get the two most recent lows for price and RSI
            recent_px_low = min_px_idx[-1]
            prev_px_low = min_px_idx[-2]
            recent_rsi_low = min_rsi_idx[-1]
            prev_rsi_low = min_rsi_idx[-2]

            if (
                price_window[recent_px_low] < price_window[prev_px_low]  # Lower low in price
                and rsi_window_vals[recent_rsi_low] > rsi_window_vals[prev_rsi_low]  # Higher low in RSI
                and rsi_window_vals[recent_rsi_low] < rsi_threshold  # Oversold confirmation
            ):
                result.iloc[i] = 1  # Bullish divergence
                continue

        # ── Bearish divergence —────────────────────────────────────────
        # Price makes a higher high (the most recent high is higher than
        # the previous high), but RSI makes a lower high.
        if len(max_px_idx) >= 2 and len(max_rsi_idx) >= 2:
            recent_px_high = max_px_idx[-1]
            prev_px_high = max_px_idx[-2]
            recent_rsi_high = max_rsi_idx[-1]
            prev_rsi_high = max_rsi_idx[-2]

            if (
                price_window[recent_px_high] > price_window[prev_px_high]  # Higher high in price
                and rsi_window_vals[recent_rsi_high] < rsi_window_vals[prev_rsi_high]  # Lower high in RSI
                and rsi_window_vals[recent_rsi_high] > 1 - rsi_threshold  # Overbought confirmation
            ):
                result.iloc[i] = -1  # Bearish divergence
                # continue (no need, last assignment)

    return result
