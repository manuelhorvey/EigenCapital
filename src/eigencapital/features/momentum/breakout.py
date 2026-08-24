"""Breakout features — price breakout signals.

Computes:
- Donchian breakout (price relative to N-period high/low)
- Bollinger breakout (price relative to Bollinger bands)
- Distance from breakout boundary

These are feature PRIMITIVES — they output numeric values, not trading signals.
"""

from __future__ import annotations

import math
from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_donchian_position(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute position within Donchian channel.

    Returns a value between 0 and 1:
    - 0 = at lower band (N-period low)
    - 1 = at upper band (N-period high)
    - 0.5 = mid-channel

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for channel calculation

    Returns:
        Donchian position (0-1), or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    high = max(b.high for b in recent)
    low = min(b.low for b in recent)
    close = bars[-1].close

    channel_range = high - low
    if channel_range <= 0:
        return 0.5  # Flat market

    return (close - low) / channel_range


def compute_donchian_breakout(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute Donchian breakout signal.

    Returns:
    - +1.0 if price breaks above N-period high
    - -1.0 if price breaks below N-period low
    - 0.0 if within channel

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for channel calculation

    Returns:
        Breakout signal (-1, 0, +1), or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    # Channel from bars BEFORE current bar
    channel_bars = bars[-(lookback + 1) : -1]
    high = max(b.high for b in channel_bars)
    low = min(b.low for b in channel_bars)

    current_close = bars[-1].close

    if current_close > high:
        return 1.0
    elif current_close < low:
        return -1.0
    else:
        return 0.0


def compute_bollinger_position(
    bars: List[Bar], lookback: int, num_std: float = 2.0
) -> Optional[float]:
    """Compute position within Bollinger Bands.

    Returns a value between 0 and 1:
    - 0 = at lower band
    - 1 = at upper band
    - 0.5 = at middle band (SMA)

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for SMA and std calculation
        num_std: Number of standard deviations for bands

    Returns:
        Bollinger position (0-1), or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    closes = [b.close for b in bars[-lookback:]]
    sma = sum(closes) / len(closes)

    variance = sum((c - sma) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance)

    upper = sma + num_std * std
    lower = sma - num_std * std

    band_range = upper - lower
    if band_range <= 0:
        return 0.5

    current = bars[-1].close
    return (current - lower) / band_range


def compute_distance_from_high(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute distance from N-period high (as percentage).

    Negative = below high, positive = at/above high.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for high calculation

    Returns:
        Distance from high as decimal, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    high = max(b.high for b in recent)
    current = bars[-1].close

    if high <= 0:
        return None

    return (current - high) / high


def make_donchian_position_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from Donchian position computation."""
    value = compute_donchian_position(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"donchian_pos_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.MOMENTUM,
        lookback=lookback,
        source_features=["high", "low", "close"],
        normalization=Normalization.NONE,
        availability_timestamp=timestamp,
    )


def make_bollinger_position_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    num_std: float = 2.0,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from Bollinger position computation."""
    value = compute_bollinger_position(bars, lookback, num_std)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"bollinger_pos_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.MOMENTUM,
        lookback=lookback,
        source_features=["close"],
        normalization=Normalization.NONE,
        availability_timestamp=timestamp,
        metadata={"num_std": num_std},
    )
