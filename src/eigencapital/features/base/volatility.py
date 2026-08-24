"""Volatility features — risk and regime signals.

Computes:
- Realized volatility (close-to-close)
- Parkinson volatility (high-low range)
- Garman-Klass volatility (OHLC-based)
- Volatility ratio (short/long)
- Volatility z-score

All features use only bars available at the decision timestamp.
"""

from __future__ import annotations

import math
from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_realized_volatility(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute annualized realized volatility from close-to-close returns.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for volatility calculation

    Returns:
        Annualized volatility as decimal, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    closes = [b.close for b in bars[-(lookback + 1):]]
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 2:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)

    return daily_vol * math.sqrt(252)


def compute_parkinson_volatility(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute Parkinson volatility from high-low range.

    Parkinson (1980) estimator uses the high-low range, which is
    more efficient than close-to-close for estimating volatility.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for calculation

    Returns:
        Annualized Parkinson volatility, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    sum_sq = 0.0
    count = 0

    for bar in recent:
        if bar.high > 0 and bar.low > 0:
            log_hl = math.log(bar.high / bar.low)
            sum_sq += log_hl ** 2
            count += 1

    if count < 2:
        return None

    # Parkinson estimator
    daily_var = sum_sq / (4 * count * math.log(2))
    daily_vol = math.sqrt(daily_var)

    return daily_vol * math.sqrt(252)


def compute_garman_klass_volatility(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute Garman-Klass volatility from OHLC data.

    Garman-Klass (1980) uses open, high, low, close for a more
    efficient volatility estimate.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for calculation

    Returns:
        Annualized Garman-Klass volatility, or None if insufficient data
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]
    sum_gk = 0.0
    count = 0

    for bar in recent:
        if bar.high > 0 and bar.low > 0 and bar.open > 0 and bar.close > 0:
            log_hl = math.log(bar.high / bar.low)
            log_co = math.log(bar.close / bar.open)
            sum_gk += 0.5 * log_hl ** 2 - (2 * math.log(2) - 1) * log_co ** 2
            count += 1

    if count < 2:
        return None

    daily_var = sum_gk / count
    if daily_var < 0:
        daily_var = 0.0

    daily_vol = math.sqrt(daily_var)

    return daily_vol * math.sqrt(252)


def compute_volatility_ratio(
    bars: List[Bar], short_lookback: int, long_lookback: int
) -> Optional[float]:
    """Compute ratio of short-term to long-term volatility.

    Useful for detecting volatility expansion/contraction.

    Args:
        bars: Available bars (sorted chronologically)
        short_lookback: Short-horizon bars
        long_lookback: Long-horizon bars

    Returns:
        Volatility ratio, or None if insufficient data
    """
    short_vol = compute_realized_volatility(bars, short_lookback)
    long_vol = compute_realized_volatility(bars, long_lookback)

    if short_vol is None or long_vol is None:
        return None

    if long_vol < 1e-15:
        return None

    return short_vol / long_vol


def make_volatility_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
    normalization: str = Normalization.NONE,
) -> Optional[Feature]:
    """Create a Feature from realized volatility computation."""
    value = compute_realized_volatility(bars, lookback)
    if value is None:
        return None

    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"volatility_{lookback}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.VOLATILITY,
        lookback=lookback,
        source_features=["close"],
        normalization=normalization,
        availability_timestamp=timestamp,
    )
