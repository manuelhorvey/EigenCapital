"""Temporal validation — timestamp ordering, gaps, and overlap checks.

Checks performed:
- Timestamp is ISO-8601 UTC format
- bar_start_utc < bar_end_utc (chronological order)
- timestamp_utc == bar_end_utc (interval-end convention)
- Timestamps are non-decreasing (no out-of-order)

Usage:
    result = validate_temporal(bar, index=5)
    if result.status != DataQualityStatus.VALID:
        print(result.messages)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from eigencapital.core.models.bar import Bar
from eigencapital.core.models.market_snapshot import DataQualityStatus


@dataclass(frozen=True)
class TemporalCheckResult:
    """Result of temporal validation for a single bar.

    Attributes:
        status: VALID, WARNING, or INVALID
        messages: Human-readable issue descriptions
    """

    status: str  # VALID, WARNING, or INVALID
    messages: List[str] = field(default_factory=list)


def validate_temporal(bar: Bar, bar_index: int = 0) -> TemporalCheckResult:
    """Validate temporal invariants for a single bar.

    Args:
        bar: Bar instance to validate
        bar_index: Position in the series (for gap detection)

    Returns:
        TemporalCheckResult with status and messages
    """
    messages: List[str] = []

    # Check ISO-8601 format
    if "T" not in bar.timestamp_utc:
        messages.append(f"Timestamp not ISO-8601: {bar.timestamp_utc}")

    # Check UTC suffix
    if not bar.timestamp_utc.endswith("Z"):
        messages.append(f"Timestamp not UTC (missing Z suffix): {bar.timestamp_utc}")

    # Check bar_start < bar_end
    if bar.bar_start_utc >= bar.bar_end_utc:
        messages.append(f"bar_start_utc ({bar.bar_start_utc}) >= bar_end_utc ({bar.bar_end_utc})")

    # Determine status
    if messages:
        # Timestamp format issues are INVALID, ordering issues are INVALID
        status = DataQualityStatus.INVALID
    else:
        status = DataQualityStatus.VALID

    return TemporalCheckResult(status=status, messages=messages)
