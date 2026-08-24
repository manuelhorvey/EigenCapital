"""Volume features — volume-based signals.

Computes:
- Volume moving average
- Volume ratio (current / MA)
- Volume z-score
- On-balance volume (OBV) direction

All features use only bars available at the decision timestamp.
"""

from __future__ import annotations

import math
from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_volume_ma(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute volume moving average.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for MA calculation

    Returns:
        Average volume, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    volumes = [b.volume for b in recent]

    return sum(volumes) / len(volumes)


def compute_volume_ratio(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute volume ratio (current volume / MA volume).

    Volume ratio > 1 indicates above-average volume.
    Volume ratio < 1 indicates below-average volume.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for MA calculation

    Returns:
        Volume ratio, or None if insufficient data or zero MA
    """
    if len(bars) < lookback + 1:
        return None

    current_volume = bars[-1].volume
    ma_volume = compute_volume_ma(bars[:-1], lookback)

    if ma_volume is None or ma_volume <= 0:
        return None

    return current_volume / ma_volume


def compute_volume_zscore(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute volume z-score.

    Z-score > 2 indicates unusually high volume.
    Z-score < -2 indicates unusually low volume.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for z-score calculation

    Returns:
        Volume z-score, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    volumes = [b.volume for b in recent]

    if len(volumes) < 2:
        return None

    mean = sum(volumes) / len(volumes)
    variance = sum((v - mean) ** 2 for v in volumes) / (len(volumes) - 1)
    std = math.sqrt(variance)

    if std < 1e-15:
        return 0.0

    current = bars[-1].volume
    return (current - mean) / std


def compute_obv_direction(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute On-Balance Volume direction over lookback period.

    Returns +1 if OBV is trending up, -1 if trending down, 0 if flat.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for OBV calculation

    Returns:
        OBV direction (-1, 0, +1), or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    recent = bars[-(lookback + 1):]
    obv = 0.0

    for i in range(1, len(recent)):
        if recent[i].close > recent[i - 1].close:
            obv += recent[i].volume
        elif recent[i].close < recent[i - 1].close:
            obv -= recent[i].volume

    if obv > 0:
        return 1.0
    elif obv < 0:
        return -1.0
    else:
        return 0.0


def make_volume_ratio_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
    normalization: str = Normalization.NONE,
) -> Optional[Feature]:
    """Create a Feature from volume ratio computation."""
    value = compute_volume_ratio(bars, lookback)
    if value is None:
        return None

    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"volume_ratio_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.VOLUME,
        lookback=lookback,
        source_features=["volume"],
        normalization=normalization,
        availability_timestamp=timestamp,
    )
