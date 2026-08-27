"""Distance from moving average features.

Computes:
- Distance from SMA (percentage)
- Distance from EMA (percentage)
- VWAP deviation

These are feature PRIMITIVES — they output numeric values, not trading signals.
"""

from __future__ import annotations

from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.features.contracts import FeatureFamily, Normalization
from eigencapital.features.feature import Feature


def compute_distance_from_sma(bars: List[Bar], lookback: int) -> float | None:
    """Compute distance from Simple Moving Average (as percentage).

    Positive = above SMA, negative = below SMA.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for SMA calculation

    Returns:
        Distance from SMA as decimal, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    closes = [b.close for b in bars[-lookback:]]
    sma = sum(closes) / len(closes)

    if sma <= 0:
        return None

    current = bars[-1].close
    return (current - sma) / sma


def compute_distance_from_ema(bars: List[Bar], lookback: int, span: int | None = None) -> float | None:
    """Compute distance from Exponential Moving Average (as percentage).

    EMA gives more weight to recent prices.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for EMA calculation
        span: EMA span (defaults to lookback)

    Returns:
        Distance from EMA as decimal, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    span = span or lookback
    alpha = 2.0 / (span + 1)

    # Compute EMA
    ema = bars[0].close
    for i in range(1, len(bars)):
        ema = alpha * bars[i].close + (1 - alpha) * ema

    if ema <= 0:
        return None

    current = bars[-1].close
    return (current - ema) / ema


def compute_vwap_deviation(bars: List[Bar], lookback: int) -> float | None:
    """Compute deviation from VWAP (Volume-Weighted Average Price).

    Positive = above VWAP, negative = below VWAP.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for VWAP calculation

    Returns:
        VWAP deviation as decimal, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    total_volume = 0
    total_pv = 0  # price * volume

    for bar in recent:
        typical_price = (bar.high + bar.low + bar.close) / 3
        total_pv += typical_price * bar.volume
        total_volume += bar.volume

    if total_volume <= 0:
        return None

    vwap = total_pv / total_volume
    if vwap <= 0:
        return None

    current = bars[-1].close
    return (current - vwap) / vwap


def make_distance_from_sma_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: str | None = None,
) -> Feature | None:
    """Create a Feature from distance-from-SMA computation."""
    value = compute_distance_from_sma(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"dist_sma_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.MEAN_REVERSION,
        lookback=lookback,
        source_features=["close"],
        normalization=Normalization.NONE,
        availability_timestamp=timestamp,
    )
