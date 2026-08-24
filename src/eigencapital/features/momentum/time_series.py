"""Time-series momentum features.

Computes:
- Rate of Change (ROC)
- Moving average crossover signal
- Dual momentum (absolute + relative)
- Momentum z-score

These are feature PRIMITIVES — they output numeric values, not trading signals.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_roc(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute Rate of Change (ROC).

    ROC = (current_price / price_n_bars_ago) - 1

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars to look back

    Returns:
        ROC as decimal, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    current = bars[-1].close
    past = bars[-(lookback + 1)].close

    if past <= 0:
        return None

    return (current / past) - 1.0


def compute_ma_crossover(
    bars: List[Bar], short_window: int, long_window: int
) -> Optional[float]:
    """Compute moving average crossover signal.

    Returns:
    - +1.0 when short MA > long MA (bullish)
    - -1.0 when short MA < long MA (bearish)
    - 0.0 when MAs are equal

    The magnitude indicates the spread between MAs (normalized).

    Args:
        bars: Available bars (sorted chronologically)
        short_window: Short MA window
        long_window: Long MA window

    Returns:
        Crossover signal (-1 to +1), or None if insufficient data
    """
    if len(bars) < long_window:
        return None

    # Compute short MA
    short_prices = [b.close for b in bars[-short_window:]]
    short_ma = sum(short_prices) / len(short_prices)

    # Compute long MA
    long_prices = [b.close for b in bars[-long_window:]]
    long_ma = sum(long_prices) / len(long_prices)

    if long_ma <= 0:
        return None

    # Normalize by long MA
    spread = (short_ma - long_ma) / long_ma

    # Clip to [-1, 1] range
    return max(-1.0, min(1.0, spread * 10))  # Scale factor


def compute_dual_momentum(
    bars: List[Bar], absolute_lookback: int, relative_lookback: int
) -> Optional[float]:
    """Compute dual momentum (absolute + relative).

    Dual momentum combines:
    - Absolute momentum: Is the asset trending up?
    - Relative momentum: Is it outperforming?

    Returns:
    - +1.0: Both absolute and relative momentum positive
    - -1.0: Both negative
    - 0.0: Mixed signals

    Args:
        bars: Available bars (sorted chronologically)
        absolute_lookback: Lookback for absolute momentum
        relative_lookback: Lookback for relative momentum (typically longer)

    Returns:
        Dual momentum signal, or None if insufficient data
    """
    if len(bars) < max(absolute_lookback, relative_lookback) + 1:
        return None

    # Absolute momentum
    abs_return = (bars[-1].close / bars[-(absolute_lookback + 1)].close) - 1.0

    # Relative momentum (longer horizon)
    rel_return = (bars[-1].close / bars[-(relative_lookback + 1)].close) - 1.0

    if abs_return > 0 and rel_return > 0:
        return 1.0
    elif abs_return < 0 and rel_return < 0:
        return -1.0
    else:
        return 0.0


def compute_momentum_zscore(
    bars: List[Bar], lookback: int, vol_lookback: int
) -> Optional[float]:
    """Compute momentum z-score (return / volatility).

    This normalizes momentum by recent volatility, producing
    a signal comparable across instruments.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Lookback for return calculation
        vol_lookback: Lookback for volatility calculation

    Returns:
        Momentum z-score, or None if insufficient data
    """
    if len(bars) < max(lookback, vol_lookback) + 1:
        return None

    # Compute return
    ret = (bars[-1].close / bars[-(lookback + 1)].close) - 1.0

    # Compute volatility
    closes = [b.close for b in bars[-(vol_lookback + 1):]]
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 2:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    vol = math.sqrt(variance)

    if vol < 1e-15:
        return None

    return ret / vol


def make_roc_feature(
    bars: List[Bar],
    lookback: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from ROC computation."""
    value = compute_roc(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"roc_{lookback}_{instrument_id}"

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
    )


def make_ma_crossover_feature(
    bars: List[Bar],
    short_window: int,
    long_window: int,
    instrument_id: str,
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from MA crossover computation."""
    value = compute_ma_crossover(bars, short_window, long_window)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"ma_cross_{short_window}_{long_window}_{instrument_id}"

    return Feature(
        feature_id=fid,
        feature_version="v1",
        instrument_id=instrument_id,
        timestamp_utc=timestamp,
        value=value,
        feature_family=FeatureFamily.MOMENTUM,
        lookback=long_window,
        source_features=["close"],
        normalization=Normalization.NONE,
        availability_timestamp=timestamp,
        metadata={"short_window": short_window, "long_window": long_window},
    )
