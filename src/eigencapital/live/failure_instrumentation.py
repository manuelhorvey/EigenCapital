"""Failure/Edge-Case Instrumentation — comprehensive failure tracking.

Tracks:
- Partial fills
- Rejected orders
- Disconnects
- Stale prices
- Restarts
- Duplicate processes
- Broker/internal mismatches
- Weekend/session transitions
- Persistence corruption/unavailability

Each failure is:
- Classified by severity
- Recorded to event ledger
- Tracked for patterns
- Alerted via structured alerts
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List


class FailureType(str, Enum):
    """Types of failures to track."""

    PARTIAL_FILL = "PARTIAL_FILL"
    ORDER_REJECTED = "ORDER_REJECTED"
    BROKER_DISCONNECT = "BROKER_DISCONNECT"
    STALE_PRICE = "STALE_PRICE"
    PROCESS_RESTART = "PROCESS_RESTART"
    DUPLICATE_PROCESS = "DUPLICATE_PROCESS"
    MISMATCH = "MISMATCH"
    WEEKEND_SESSION = "WEEKEND_SESSION"
    PERSISTENCE_CORRUPT = "PERSISTENCE_CORRUPT"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class FailureSeverity(str, Enum):
    """Failure severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    HALT = "HALT"


@dataclass(frozen=True)
class FailureEvent:
    """Recorded failure event."""

    failure_id: str
    timestamp: str
    failure_type: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None  # Link to event ledger
    correlation_id: str | None = None
    recovered: bool = False
    recovery_time_seconds: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "timestamp": self.timestamp,
            "failure_type": self.failure_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "recovered": self.recovered,
            "recovery_time_seconds": self.recovery_time_seconds,
        }


class FailureInstrumentation:
    """Comprehensive failure tracking and instrumentation.

    Tracks all failure types and patterns for Phase 2 qualification.
    """

    def __init__(
        self,
        max_history: int = 10000,
        alert_threshold: int = 5,  # Alert after N failures of same type
    ) -> None:
        """Initialize failure instrumentation.

        Args:
            max_history: Maximum failure events to retain
            alert_threshold: Threshold for pattern-based alerts
        """
        self._max_history = max_history
        self._alert_threshold = alert_threshold

        # Failure history
        self._failures: List[FailureEvent] = []

        # Pattern tracking
        self._failure_counts: Dict[str, int] = {}  # type -> count
        self._recent_failures: Dict[str, List[float]] = {}  # type -> [timestamps]

        # Recovery tracking
        self._active_failures: Dict[str, FailureEvent] = {}  # type -> active failure
        self._recovery_times: Dict[str, List[float]] = {}  # type -> [recovery_times]

        # Statistics
        self._stats: dict[str, Any] = {
            "total_failures": 0,
            "by_type": {},
            "by_severity": {},
            "recovered": 0,
            "unrecovered": 0,
        }

        # Failure ID counter
        self._failure_counter = 0

    def _generate_failure_id(self) -> str:
        """Generate unique failure ID."""
        self._failure_counter += 1
        return f"FAIL-{self._failure_counter:06d}"

    def record_failure(
        self,
        failure_type: FailureType,
        severity: FailureSeverity,
        message: str,
        details: Dict[str, Any] | None = None,
        event_id: str | None = None,
        correlation_id: str | None = None,
    ) -> FailureEvent:
        """Record a failure event.

        Args:
            failure_type: Type of failure
            severity: Severity level
            message: Human-readable message
            details: Additional context
            event_id: Link to event ledger
            correlation_id: Correlation ID

        Returns:
            Created failure event
        """
        now = datetime.now(UTC).isoformat()

        failure = FailureEvent(
            failure_id=self._generate_failure_id(),
            timestamp=now,
            failure_type=failure_type.value,
            severity=severity.value,
            message=message,
            details=details or {},
            event_id=event_id,
            correlation_id=correlation_id,
        )

        # Add to history
        self._failures.append(failure)
        if len(self._failures) > self._max_history:
            self._failures = self._failures[-self._max_history :]

        # Update counts
        self._failure_counts[failure_type.value] = self._failure_counts.get(failure_type.value, 0) + 1

        # Update recent failures for pattern detection
        if failure_type.value not in self._recent_failures:
            self._recent_failures[failure_type.value] = []
        self._recent_failures[failure_type.value].append(time.time())

        # Clean old recent failures (keep last hour)
        cutoff = time.time() - 3600
        self._recent_failures[failure_type.value] = [t for t in self._recent_failures[failure_type.value] if t > cutoff]

        # Track active failure
        self._active_failures[failure_type.value] = failure

        # Update stats
        self._stats["total_failures"] += 1
        by_type: dict[str, int] = self._stats["by_type"]  # type: ignore[assignment]
        by_sev: dict[str, int] = self._stats["by_severity"]  # type: ignore[assignment]
        by_type[failure_type.value] = by_type.get(failure_type.value, 0) + 1
        by_sev[severity.value] = by_sev.get(severity.value, 0) + 1

        return failure

    def record_recovery(
        self,
        failure_type: FailureType,
        recovery_details: Dict[str, Any] | None = None,
    ) -> FailureEvent | None:
        """Record recovery from a failure.

        Args:
            failure_type: Type of failure being recovered from
            recovery_details: Recovery context

        Returns:
            Updated failure event if found
        """
        active = self._active_failures.get(failure_type.value)
        if not active:
            return None

        datetime.now(UTC).isoformat()
        recovery_time = time.time() - datetime.fromisoformat(active.timestamp).timestamp()

        # Create updated failure event
        updated = FailureEvent(
            failure_id=active.failure_id,
            timestamp=active.timestamp,
            failure_type=active.failure_type,
            severity=active.severity,
            message=active.message,
            details={**active.details, "recovery_details": recovery_details or {}},
            event_id=active.event_id,
            correlation_id=active.correlation_id,
            recovered=True,
            recovery_time_seconds=recovery_time,
        )

        # Update in history
        for i, f in enumerate(self._failures):
            if f.failure_id == active.failure_id:
                self._failures[i] = updated
                break

        # Remove from active
        del self._active_failures[failure_type.value]

        # Track recovery time
        if failure_type.value not in self._recovery_times:
            self._recovery_times[failure_type.value] = []
        self._recovery_times[failure_type.value].append(recovery_time)

        # Update stats
        self._stats["recovered"] = int(self._stats["recovered"]) + 1

        return updated

    def get_active_failures(self) -> List[FailureEvent]:
        """Get all currently active (unrecovered) failures."""
        return list(self._active_failures.values())

    def get_failure_history(
        self,
        failure_type: FailureType | None = None,
        severity: FailureSeverity | None = None,
        limit: int = 100,
    ) -> List[FailureEvent]:
        """Get failure history with optional filtering."""
        results = self._failures

        if failure_type:
            results = [f for f in results if f.failure_type == failure_type.value]

        if severity:
            results = [f for f in results if f.severity == severity.value]

        return results[-limit:]

    def get_pattern_alerts(self) -> List[Dict[str, Any]]:
        """Check for failure patterns that require alerts."""
        alerts = []

        now = time.time()
        cutoff = now - 3600  # Last hour

        for failure_type, timestamps in self._recent_failures.items():
            recent_count = sum(1 for t in timestamps if t > cutoff)

            if recent_count >= self._alert_threshold:
                alerts.append(
                    {
                        "failure_type": failure_type,
                        "count": recent_count,
                        "window": "1 hour",
                        "threshold": self._alert_threshold,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

        return alerts

    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery time statistics."""
        stats = {}

        for failure_type, times in self._recovery_times.items():
            if times:
                stats[failure_type] = {
                    "count": len(times),
                    "avg_seconds": sum(times) / len(times),
                    "min_seconds": min(times),
                    "max_seconds": max(times),
                }

        return stats

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive failure statistics."""
        return {
            **self._stats,
            "active_failures": len(self._active_failures),
            "failure_counts": dict(self._failure_counts),
        }

    def clear_active_failures(self) -> None:
        """Clear all active failures (use with caution)."""
        self._active_failures.clear()

    def export_for_ledger(self) -> List[Dict[str, Any]]:
        """Export failures for event ledger integration."""
        return [f.to_dict() for f in self._failures[-100:]]  # Last 100 failures


# Convenience functions for common failure patterns


def record_partial_fill(
    instrumentation: FailureInstrumentation,
    order_ticket: str,
    symbol: str,
    requested_qty: float,
    filled_qty: float,
    event_id: str | None = None,
) -> FailureEvent:
    """Record a partial fill failure."""
    return instrumentation.record_failure(
        failure_type=FailureType.PARTIAL_FILL,
        severity=FailureSeverity.WARNING,
        message=f"Partial fill on {symbol}: requested={requested_qty}, filled={filled_qty}",
        details={
            "order_ticket": order_ticket,
            "symbol": symbol,
            "requested_qty": requested_qty,
            "filled_qty": filled_qty,
            "fill_pct": filled_qty / requested_qty if requested_qty > 0 else 0,
        },
        event_id=event_id,
    )


def record_order_rejected(
    instrumentation: FailureInstrumentation,
    order_ticket: str,
    symbol: str,
    reason: str,
    event_id: str | None = None,
) -> FailureEvent:
    """Record an order rejection."""
    return instrumentation.record_failure(
        failure_type=FailureType.ORDER_REJECTED,
        severity=FailureSeverity.WARNING,
        message=f"Order rejected on {symbol}: {reason}",
        details={
            "order_ticket": order_ticket,
            "symbol": symbol,
            "reason": reason,
        },
        event_id=event_id,
    )


def record_broker_disconnect(
    instrumentation: FailureInstrumentation,
    reason: str,
    event_id: str | None = None,
) -> FailureEvent:
    """Record a broker disconnect."""
    return instrumentation.record_failure(
        failure_type=FailureType.BROKER_DISCONNECT,
        severity=FailureSeverity.CRITICAL,
        message=f"Broker disconnected: {reason}",
        details={"reason": reason},
        event_id=event_id,
    )


def record_stale_price(
    instrumentation: FailureInstrumentation,
    symbol: str,
    age_seconds: float,
    threshold_seconds: float,
    event_id: str | None = None,
) -> FailureEvent:
    """Record stale price data."""
    return instrumentation.record_failure(
        failure_type=FailureType.STALE_PRICE,
        severity=FailureSeverity.WARNING,
        message=f"Stale price on {symbol}: {age_seconds:.0f}s old (threshold: {threshold_seconds:.0f}s)",
        details={
            "symbol": symbol,
            "age_seconds": age_seconds,
            "threshold_seconds": threshold_seconds,
        },
        event_id=event_id,
    )


def record_mismatch(
    instrumentation: FailureInstrumentation,
    mismatch_type: str,
    broker_value: Any,
    internal_value: Any,
    event_id: str | None = None,
) -> FailureEvent:
    """Record a broker/internal mismatch."""
    return instrumentation.record_failure(
        failure_type=FailureType.MISMATCH,
        severity=FailureSeverity.CRITICAL,
        message=f"Mismatch ({mismatch_type}): broker={broker_value}, internal={internal_value}",
        details={
            "mismatch_type": mismatch_type,
            "broker_value": broker_value,
            "internal_value": internal_value,
        },
        event_id=event_id,
    )


def record_weekend_session(
    instrumentation: FailureInstrumentation,
    session_start: str,
    event_id: str | None = None,
) -> FailureEvent:
    """Record weekend/session transition."""
    return instrumentation.record_failure(
        failure_type=FailureType.WEEKEND_SESSION,
        severity=FailureSeverity.INFO,
        message=f"Weekend/session transition: {session_start}",
        details={"session_start": session_start},
        event_id=event_id,
    )


def record_persistence_corrupt(
    instrumentation: FailureInstrumentation,
    file_path: str,
    error: str,
    event_id: str | None = None,
) -> FailureEvent:
    """Record persistence corruption."""
    return instrumentation.record_failure(
        failure_type=FailureType.PERSISTENCE_CORRUPT,
        severity=FailureSeverity.CRITICAL,
        message=f"Persistence corrupt: {file_path} - {error}",
        details={"file_path": file_path, "error": error},
        event_id=event_id,
    )
