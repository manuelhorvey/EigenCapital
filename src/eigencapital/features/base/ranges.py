"""Range features — price range and ATR signals.

Computes:
- Average True Range (ATR)
- High-low range (absolute and normalized)
- Close-to-close range

All features use only bars available at the decision timestamp.
"""

from __future__ import annotations

from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.features.contracts import FeatureFamily, Normalization
from eigencapital.features.feature import Feature


def compute_true_range(bar: Bar, prev_close: float | None = None) -> float:
    """Compute true range for a single bar.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)

    Args:
        bar: Current bar
        prev_close: Previous bar's close price

    Returns:
        True range value
    """
    if prev_close is None:
        return bar.high - bar.low

    return max(
        bar.high - bar.low,
        abs(bar.high - prev_close),
        abs(bar.low - prev_close),
    )


def compute_atr(bars: List[Bar], lookback: int) -> float | None:
    """Compute Average True Range.

    ATR is a measure of volatility that accounts for gaps.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for ATR calculation

    Returns:
        ATR value, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    # Need one extra bar for prev_close of the first ATR bar
    relevant = bars[-(lookback + 1) :]
    true_ranges = []

    for i in range(1, len(relevant)):
        prev_close = relevant[i - 1].close
        tr = compute_true_range(relevant[i], prev_close)
        true_ranges.append(tr)

    if not true_ranges:
        return None

    return sum(true_ranges) / len(true_ranges)


def compute_high_low_range(bars: List[Bar], lookback: int) -> float | None:
    """Compute absolute high-low range over lookback period.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for range calculation

    Returns:
        High-low range (highest high - lowest low), or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    highs = [b.high for b in recent]
    lows = [b.low for b in recent]

    return max(highs) - min(lows)


def compute_normalized_range(bars: List[Bar], lookback: int) -> float | None:
    """Compute normalized high-low range (range / close).

    Normalized range is useful for comparing volatility across
    instruments with different price levels.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for range calculation

    Returns:
        Normalized range (0-1 scale), or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    highs = [b.high for b in recent]
    lows = [b.low for b in recent]
    close = recent[-1].close

    if close <= 0:
        return None

    range_val = max(highs) - min(lows)
    return range_val / close


def make_atr_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: str | None = None,
    normalization: str = Normalization.NONE,
) -> Feature | None:
    """Create a Feature from ATR computation."""
    value = compute_atr(bars, lookback)
    if value is None:
        return None

    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"atr_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.RANGES,
        lookback=lookback,
        source_features=["high", "low", "close"],
        normalization=normalization,
        availability_timestamp=timestamp,
    )
