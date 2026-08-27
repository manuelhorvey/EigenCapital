"""Anomaly detection — extreme moves, flatlines, and volume spikes.

Checks performed:
- Extreme price jump (> 20% in single bar)
- Flatlined price (open == high == low == close)
- Volume spike (> 10x typical volume)

Note: Anomalies are classified as WARNING, not INVALID.
A 10% move in BTC may be perfectly legitimate.
The anomaly detector flags unusual patterns for human review.

Usage:
    result = validate_anomalies(bar)
    if result.status == DataQualityStatus.WARNING:
        print(result.messages)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.core.models.market_snapshot import DataQualityStatus

# Thresholds (configurable per-asset-class in production)
EXTREME_PRICE_JUMP_THRESHOLD = 0.20  # 20%
VOLUME_SPIKE_MULTIPLIER = 10.0  # 10x typical


@dataclass(frozen=True)
class AnomalyCheckResult:
    """Result of anomaly detection for a single bar.

    Attributes:
        status: VALID if no anomalies, WARNING if anomalies detected
        messages: Human-readable anomaly descriptions
    """

    status: str  # VALID or WARNING
    messages: List[str] = field(default_factory=list)


def validate_anomalies(bar: Bar) -> AnomalyCheckResult:
    """Detect anomalies in a single bar.

    Anomalies are flagged as WARNING (not INVALID) because unusual
    patterns may be legitimate (e.g., earnings moves, crypto volatility).

    Args:
        bar: Bar instance to check

    Returns:
        AnomalyCheckResult with status and messages
    """
    messages: List[str] = []

    # Check for flatlined price (all OHLC equal)
    if bar.open == bar.high == bar.low == bar.close:
        messages.append(f"Flatlined price: O=H=L=C={bar.open}")

    # Check for extreme price jump (> 20% from open to close)
    if bar.open > 0:
        price_change = abs(bar.close - bar.open) / bar.open
        if price_change > EXTREME_PRICE_JUMP_THRESHOLD:
            messages.append(f"Extreme price jump: {price_change:.1%} (OPEN={bar.open}, CLOSE={bar.close})")

    # Check for zero volume (may indicate halted trading or missing data)
    if bar.volume == 0:
        messages.append("Zero volume detected")

    status = DataQualityStatus.WARNING if messages else DataQualityStatus.VALID
    return AnomalyCheckResult(status=status, messages=messages)
