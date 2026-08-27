"""Return features — the most fundamental market signal.

Computes:
- Simple returns over various horizons
- Log returns
- Cumulative returns
- Multi-horizon return ratios

All features use only bars available at the decision timestamp.
"""

from __future__ import annotations

import math
from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.features.contracts import FeatureFamily, Normalization
from eigencapital.features.feature import Feature


def compute_simple_return(bars: List[Bar], lookback: int) -> float | None:
    """Compute simple return over lookback period.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars to look back

    Returns:
        Simple return as decimal, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    start_price = bars[-(lookback + 1)].close
    end_price = bars[-1].close

    if start_price <= 0:
        return None

    return (end_price / start_price) - 1.0


def compute_log_return(bars: List[Bar], lookback: int) -> float | None:
    """Compute log return over lookback period.

    Log returns are additive across time, which makes them
    useful for volatility estimation and multi-period analysis.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars to look back

    Returns:
        Log return, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    start_price = bars[-(lookback + 1)].close
    end_price = bars[-1].close

    if start_price <= 0 or end_price <= 0:
        return None

    return math.log(end_price / start_price)


def compute_cumulative_return(bars: List[Bar], lookback: int) -> float | None:
    """Compute cumulative return over lookback period.

    Identical to simple_return but named for clarity in feature context.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars to look back

    Returns:
        Cumulative return as decimal, or None if insufficient data
    """
    return compute_simple_return(bars, lookback)


def compute_return_ratio(bars: List[Bar], short_lookback: int, long_lookback: int) -> float | None:
    """Compute ratio of short-horizon to long-horizon return.

    Useful for detecting momentum acceleration/deceleration.

    Args:
        bars: Available bars (sorted chronologically)
        short_lookback: Short-horizon bars
        long_lookback: Long-horizon bars

    Returns:
        Return ratio, or None if insufficient data
    """
    short_ret = compute_simple_return(bars, short_lookback)
    long_ret = compute_simple_return(bars, long_lookback)

    if short_ret is None or long_ret is None:
        return None

    if abs(long_ret) < 1e-15:
        return None

    return short_ret / long_ret


def make_return_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: str | None = None,
    normalization: str = Normalization.NONE,
) -> Feature | None:
    """Create a Feature from simple return computation.

    Args:
        bars: Available bars
        lookback: Return horizon
        instrument_id: Instrument identifier
        feature_id: Optional custom feature ID
        normalization: Normalization method

    Returns:
        Feature if computation succeeds, None otherwise
    """
    value = compute_simple_return(bars, lookback)
    if value is None:
        return None

    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"return_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.RETURNS,
        lookback=lookback,
        source_features=["close"],
        normalization=normalization,
        availability_timestamp=timestamp,
    )


def make_log_return_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: str | None = None,
    normalization: str = Normalization.NONE,
) -> Feature | None:
    """Create a Feature from log return computation."""
    value = compute_log_return(bars, lookback)
    if value is None:
        return None

    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"log_return_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.RETURNS,
        lookback=lookback,
        source_features=["close"],
        normalization=normalization,
        availability_timestamp=timestamp,
    )
