"""Z-score and Bollinger band position features.

Computes:
- Rolling z-score
- Bollinger band position
- Bollinger bandwidth

These are feature PRIMITIVES — they output numeric values, not trading signals.
"""

from __future__ import annotations

import math
from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_rolling_zscore(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute rolling z-score of close prices.

    Z-score = (current - mean) / std

    Values > 2 indicate the price is unusually high.
    Values < -2 indicate the price is unusually low.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for z-score calculation

    Returns:
        Z-score, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    closes = [b.close for b in bars[-lookback:]]

    if len(closes) < 2:
        return None

    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance)

    if std < 1e-15:
        return 0.0

    current = bars[-1].close
    return (current - mean) / std


def compute_bollinger_bandwidth(
    bars: List[Bar], lookback: int, num_std: float = 2.0
) -> Optional[float]:
    """Compute Bollinger Bandwidth (upper - lower) / middle.

    Bandwidth indicates volatility relative to price level.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for calculation
        num_std: Number of standard deviations for bands

    Returns:
        Bollinger bandwidth, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    closes = [b.close for b in bars[-lookback:]]
    sma = sum(closes) / len(closes)

    if sma <= 0:
        return None

    variance = sum((c - sma) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance)

    upper = sma + num_std * std
    lower = sma - num_std * std

    return (upper - lower) / sma


def make_zscore_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from rolling z-score computation."""
    value = compute_rolling_zscore(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"zscore_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.MEAN_REVERSION,
        lookback=lookback,
        source_features=["close"],
        normalization=Normalization.ZSCORE,
        availability_timestamp=timestamp,
    )
