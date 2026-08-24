"""Feature computation for the cross-asset trend strategy.

Computes:
- Normalized momentum (Z-score of cumulative return)
- Realized volatility (annualized)
- Trend signal (momentum / volatility)

All features are computed from available bars only (no look-ahead).
"""

from __future__ import annotations

import math
from typing import List, Optional

from eigencapital.core.models.bar import Bar


def compute_cumulative_return(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute cumulative return over lookback period.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars to look back

    Returns:
        Cumulative return as a decimal, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    # Use close prices
    start_price = bars[-(lookback + 1)].close
    end_price = bars[-1].close

    if start_price <= 0:
        return None

    return (end_price / start_price) - 1.0


def compute_realized_volatility(bars: List[Bar], lookback: int) -> Optional[float]:
    """Compute annualized realized volatility.

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Number of bars for volatility calculation

    Returns:
        Annualized volatility as a decimal, or None if insufficient data
    """
    if len(bars) < lookback + 1:
        return None

    # Compute log returns
    closes = [b.close for b in bars[-(lookback + 1) :]]
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 2:
        return None

    # Compute standard deviation
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)

    # Annualize (assuming ~252 trading days)
    annual_vol = daily_vol * math.sqrt(252)
    return annual_vol


def compute_trend_signal(
    bars: List[Bar],
    lookback: int,
    vol_lookback: int,
) -> Optional[float]:
    """Compute trend signal as Z-score of momentum.

    Signal = cumulative_return / realized_volatility

    Args:
        bars: Available bars (sorted chronologically)
        lookback: Bars for momentum calculation
        vol_lookback: Bars for volatility calculation

    Returns:
        Z-score signal, or None if insufficient data
    """
    cum_return = compute_cumulative_return(bars, lookback)
    if cum_return is None:
        return None

    vol = compute_realized_volatility(bars, vol_lookback)
    if vol is None or vol <= 0:
        return None

    return cum_return / vol


def compute_position_size(
    signal: float,
    risk_target: float,
    volatility: float,
    max_position: float,
) -> float:
    """Compute volatility-scaled position size.

    Position = risk_target / volatility * sign(signal)

    Capped at max_position.

    Args:
        signal: Trend signal (Z-score)
        risk_target: Target volatility (e.g., 0.10)
        volatility: Realized volatility (annualized)
        max_position: Maximum position size

    Returns:
        Position size (positive=LONG, negative=SHORT)
    """
    if volatility <= 0 or math.isnan(volatility):
        return 0.0

    # Volatility-scaled sizing
    raw_size = risk_target / volatility

    # Apply direction
    if signal > 0:
        size = min(raw_size, max_position)
    elif signal < 0:
        size = max(-raw_size, -max_position)
    else:
        size = 0.0

    return size
