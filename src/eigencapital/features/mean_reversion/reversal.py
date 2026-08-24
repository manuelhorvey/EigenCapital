"""Short-term reversal and RSI features.

Computes:
- Short-term reversal (1-period return reversal)
- RSI (Relative Strength Index)
- RSI divergence from price

These are feature PRIMITIVES — they output numeric values, not trading signals.
"""

from __future__ import annotations

from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureFamily, Normalization


def compute_short_term_reversal(bars: List[Bar], lookback: int = 1) -> Optional[float]:
    """Compute short-term reversal signal.

    The reversal is the NEGATIVE of the recent return.
    If price went up, reversal signal is negative (expecting reversion).

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for reversal calculation

    Returns:
        Reversal signal (negative of return), or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    start_price = bars[-(lookback + 1)].close
    end_price = bars[-1].close

    if start_price <= 0:
        return None

    ret = (end_price / start_price) - 1.0
    return -ret  # Reversal is negative of return


def compute_rsi(bars: List[Bar], lookback: int = 14) -> Optional[float]:
    """Compute Relative Strength Index (RSI).

    RSI ranges from 0 to 100:
    - RSI > 70: Overbought
    - RSI < 30: Oversold
    - RSI ≈ 50: Neutral

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for RSI calculation

    Returns:
        RSI value (0-100), or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    # Compute price changes
    changes = []
    for i in range(-lookback, 0):
        change = bars[i].close - bars[i - 1].close
        changes.append(change)

    if not changes:
        return None

    # Separate gains and losses
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]

    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)

    if avg_loss < 1e-15:
        return 100.0  # All gains

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_rsi_zscore(bars: List[Bar], lookback: int = 14) -> Optional[float]:
    """Compute RSI as z-score (centered at 50, scaled by typical RSI range).

    This makes RSI comparable across instruments.

    RSI z-score > 0: Overbought relative to typical range
    RSI z-score < 0: Oversold relative to typical range

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for RSI calculation

    Returns:
        RSI z-score, or None if insufficient data
    """
    rsi = compute_rsi(bars, lookback)
    if rsi is None:
        return None

    # Center at 50, scale by typical RSI range (0-100)
    return (rsi - 50) / 50


def make_rsi_feature(
    bars: List[Bar],
    lookback: int = 14,
    instrument_id: str = "",
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from RSI computation."""
    value = compute_rsi(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"rsi_{lookback}_{instrument_id}"

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


def make_reversal_feature(
    bars: List[Bar],
    lookback: int = 1,
    instrument_id: str = "",
    feature_id: Optional[str] = None,
) -> Optional[Feature]:
    """Create a Feature from short-term reversal computation."""
    value = compute_short_term_reversal(bars, lookback)
    if value is None:
        return None
    if not bars:
        return None

    timestamp = bars[-1].timestamp_utc
    fid = feature_id or f"reversal_{lookback}_{instrument_id}"

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
