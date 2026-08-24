"""OHLC validation — structural price invariant checks.

Checks performed:
- high >= max(open, close)
- low <= min(open, close)
- All prices positive
- Volume non-negative

Usage:
    result = validate_ohlc(bar)
    if result.status != DataQualityStatus.VALID:
        print(result.messages)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.core.models.market_snapshot import DataQualityStatus


@dataclass(frozen=True)
class OHLCCheckResult:
    """Result of OHLC validation for a single bar.

    Attributes:
        status: VALID if all checks pass, INVALID if structural violation
        messages: Human-readable issue descriptions
    """

    status: str  # VALID or INVALID
    messages: List[str] = field(default_factory=list)


def validate_ohlc(bar: Bar) -> OHLCCheckResult:
    """Validate OHLC structural invariants for a single bar.

    Note: The Bar model already enforces these invariants in __post_init__.
    This function re-checks them explicitly for the validation report,
    and handles edge cases that might arise from deserialization.

    Args:
        bar: Bar instance to validate

    Returns:
        OHLCCheckResult with status and messages
    """
    messages: List[str] = []

    # Check high >= max(open, close)
    max_oc = max(bar.open, bar.close)
    if bar.high < max_oc:
        messages.append(f"HIGH ({bar.high}) < max(OPEN, CLOSE) ({max_oc})")

    # Check low <= min(open, close)
    min_oc = min(bar.open, bar.close)
    if bar.low > min_oc:
        messages.append(f"LOW ({bar.low}) > min(OPEN, CLOSE) ({min_oc})")

    # Check prices positive
    for field_name, price in [
        ("OPEN", bar.open),
        ("HIGH", bar.high),
        ("LOW", bar.low),
        ("CLOSE", bar.close),
    ]:
        if price <= 0:
            messages.append(f"{field_name} ({price}) must be > 0")

    # Check volume non-negative
    if bar.volume < 0:
        messages.append(f"VOLUME ({bar.volume}) must be >= 0")

    status = DataQualityStatus.INVALID if messages else DataQualityStatus.VALID
    return OHLCCheckResult(status=status, messages=messages)
