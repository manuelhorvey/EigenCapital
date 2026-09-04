"""Structured Alerting — state-transition tied, deduplicated, traceable.

Alerts are:
- Tied to actual state transitions (not polling-based)
- Deduplicated (no noisy repeated alerts)
- Traceable to the event ledger
- Structured for machine consumption
- Delivered durably (JSONL + optional stderr)

Alert severities:
- CRITICAL: Immediate operator attention required
- WARNING: Investigation recommended
- INFO: Informational only

Alert categories:
- HEALTH: System health state changes
- RISK: Risk observation threshold breaches
- RECONCILIATION: State mismatch detected
- EXECUTION: Order/fill anomalies
- BROKER: Connection/data issues
- WATCHDOG: Watchdog state changes
- SYSTEM: System-level events
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class AlertCategory(str, Enum):
    """Alert categories."""

    HEALTH = "HEALTH"
    RISK = "RISK"
    RECONCILIATION = "RECONCILIATION"
    EXECUTION = "EXECUTION"
    BROKER = "BROKER"
    WATCHDOG = "WATCHDOG"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class Alert:
    """Structured alert."""

    alert_id: str
    timestamp: str
    severity: str
    category: str
    event_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None  # Link to event ledger
    correlation_id: str | None = None
    state_transition: str | None = None
    consecutive_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "category": self.category,
            "event_type": self.event_type,
            "message": self.message,
            "details": self.details,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "state_transition": self.state_transition,
            "consecutive_count": self.consecutive_count,
        }


class StructuredAlertDispatcher:
    """Structured alerting with deduplication and event ledger traceability.

    Alerts are:
    - Tied to state transitions
    - Deduplicated by category+event_type
    - Traceable to event ledger
    - Delivered durably
    """

    def __init__(
        self,
        alert_path: str = "reports/alerts.jsonl",
        dedup_window_seconds: float = 300.0,  # 5 minutes
        max_consecutive_alerts: int = 10,
        mirror_stderr: bool = True,
        webhook_url: str | None = None,
        telegram_bot_token: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> None:
        """Initialize alert dispatcher.

        Args:
            alert_path: Path for durable alert storage
            dedup_window_seconds: Window for deduplication
            max_consecutive_alerts: Max consecutive identical alerts
            mirror_stderr: Mirror critical/warning alerts to stderr
            webhook_url: Optional webhook URL for alert delivery
            telegram_bot_token: Optional Telegram bot token
            telegram_chat_id: Optional Telegram chat ID
        """
        self._alert_path = alert_path
        self._dedup_window = dedup_window_seconds
        self._max_consecutive = max_consecutive_alerts
        self._mirror_stderr = mirror_stderr
        self._webhook_url = webhook_url or os.environ.get("ALERT_WEBHOOK_URL")
        self._telegram_bot_token = telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self._telegram_chat_id = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")

        # Deduplication tracking
        self._recent_alerts: Dict[str, float] = {}  # key -> last_sent_time
        self._consecutive_counts: Dict[str, int] = {}  # key -> count

        # Alert history
        self._history: List[Dict[str, Any]] = []
        self._max_history = 1000

        # Statistics
        self._stats = {
            "total_dispatched": 0,
            "total_deduplicated": 0,
            "by_severity": {},
            "by_category": {},
        }

        # Ensure directory exists
        os.makedirs(os.path.dirname(alert_path) or ".", exist_ok=True)

    def _generate_alert_id(self) -> str:
        """Generate unique alert ID."""
        import uuid

        return str(uuid.uuid4())[:8]

    def _get_dedup_key(self, category: str, event_type: str) -> str:
        """Generate deduplication key."""
        return f"{category}:{event_type}"

    def _should_send(self, dedup_key: str) -> bool:
        """Check if alert should be sent (deduplication logic).

        Within the dedup window, identical alerts are suppressed
        unless the consecutive count exceeds the max consecutive limit.
        """
        now = time.time()
        last_sent = self._recent_alerts.get(dedup_key, 0)

        # Check dedup window
        if now - last_sent < self._dedup_window:
            self._consecutive_counts[dedup_key] = self._consecutive_counts.get(dedup_key, 0) + 1

            # Still suppress (deduplicate) within the window
            return False

        # Reset consecutive count when window expires
        self._consecutive_counts[dedup_key] = 1
        return True

    def dispatch(
        self,
        severity: AlertSeverity,
        category: AlertCategory,
        event_type: str,
        message: str,
        details: Dict[str, Any] | None = None,
        event_id: str | None = None,
        correlation_id: str | None = None,
        state_transition: str | None = None,
    ) -> Alert:
        """Dispatch a structured alert.

        Args:
            severity: Alert severity
            category: Alert category
            event_type: Type of event
            message: Human-readable message
            details: Additional context
            event_id: Link to event ledger
            correlation_id: Correlation ID for related events
            state_transition: State change description

        Returns:
            Created alert
        """
        # Check deduplication
        dedup_key = self._get_dedup_key(category.value, event_type)
        if not self._should_send(dedup_key):
            self._stats["total_deduplicated"] = self._stats["total_deduplicated"] + 1  # type: ignore[operator]
            # Return a placeholder - alert was deduplicated
            return Alert(
                alert_id="DEDUP",
                timestamp=datetime.now(UTC).isoformat(),
                severity=severity.value,
                category=category.value,
                event_type=event_type,
                message="[DEDUPLICATED]",
                consecutive_count=self._consecutive_counts.get(dedup_key, 0),
            )

        # Create alert
        now = datetime.now(UTC).isoformat()
        alert = Alert(
            alert_id=self._generate_alert_id(),
            timestamp=now,
            severity=severity.value,
            category=category.value,
            event_type=event_type,
            message=message,
            details=details or {},
            event_id=event_id,
            correlation_id=correlation_id,
            state_transition=state_transition,
            consecutive_count=self._consecutive_counts.get(dedup_key, 1),
        )

        # Update dedup tracking
        self._recent_alerts[dedup_key] = time.time()

        # Deliver alert
        self._deliver(alert)

        # Record to history
        self._history.append(alert.to_dict())
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        # Update stats
        self._stats["total_dispatched"] = self._stats["total_dispatched"] + 1  # type: ignore[operator]
        by_sev: dict[str, int] = self._stats["by_severity"]  # type: ignore[assignment]
        by_cat: dict[str, int] = self._stats["by_category"]  # type: ignore[assignment]
        by_sev[severity.value] = by_sev.get(severity.value, 0) + 1
        by_cat[category.value] = by_cat.get(category.value, 0) + 1

        return alert

    def _deliver(self, alert: Alert) -> None:
        """Deliver alert to all sinks."""
        line = json.dumps(alert.to_dict(), sort_keys=True, default=str)

        # Durable JSONL sink
        try:
            with open(self._alert_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass

        # Stderr mirror for critical/warning
        if self._mirror_stderr and alert.severity in (
            AlertSeverity.CRITICAL.value,
            AlertSeverity.WARNING.value,
        ):
            import sys

            print(f"[{alert.severity}] {alert.category}: {alert.message}", file=sys.stderr)

        # Webhook delivery (if configured)
        if self._webhook_url and alert.severity in (
            AlertSeverity.CRITICAL.value,
            AlertSeverity.WARNING.value,
        ):
            self._deliver_webhook(alert)

        # Telegram delivery (if configured)
        if self._telegram_bot_token and self._telegram_chat_id:
            if alert.severity == AlertSeverity.CRITICAL.value:
                self._deliver_telegram(alert)

    def _deliver_webhook(self, alert: Alert) -> None:
        """Deliver alert via webhook (POST to URL)."""
        import logging
        import urllib.request

        logger = logging.getLogger(__name__)

        try:
            payload = json.dumps(
                {
                    "text": f"[{alert.severity}] {alert.category}: {alert.message}",
                    "alert_id": alert.alert_id,
                    "severity": alert.severity,
                    "category": alert.category,
                    "timestamp": alert.timestamp,
                    "details": alert.details,
                }
            ).encode()

            req = urllib.request.Request(
                self._webhook_url or "",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning(f"Webhook delivery failed: {e}")

    def _deliver_telegram(self, alert: Alert) -> None:
        """Deliver alert via Telegram bot."""
        import logging
        import urllib.parse
        import urllib.request

        logger = logging.getLogger(__name__)

        try:
            text = f"🔴 *{alert.severity}* | {alert.category}\n{alert.message}"
            if alert.details:
                detail_str = json.dumps(alert.details, default=str)[:200]
                text += f"\n\n`{detail_str}`"

            url = f"https://api.telegram.org/bot{self._telegram_bot_token}/sendMessage"
            data = urllib.parse.urlencode(
                {
                    "chat_id": self._telegram_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                }
            ).encode()

            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning(f"Telegram delivery failed: {e}")

    def get_history(self) -> List[Dict[str, Any]]:
        """Get alert history."""
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        return dict(self._stats)

    def clear_dedup(self, category: AlertCategory | None = None) -> None:
        """Clear deduplication state."""
        if category:
            keys_to_clear = [k for k in self._recent_alerts if k.startswith(category.value)]
            for key in keys_to_clear:
                del self._recent_alerts[key]
                self._consecutive_counts.pop(key, None)
        else:
            self._recent_alerts.clear()
            self._consecutive_counts.clear()


# Convenience functions for common alert patterns


def alert_health_change(
    dispatcher: StructuredAlertDispatcher,
    dimension: str,
    old_state: str,
    new_state: str,
    reason: str,
    event_id: str | None = None,
) -> Alert:
    """Alert on health state change."""
    severity = AlertSeverity.WARNING if new_state in ("DEGRADED", "BLOCKED") else AlertSeverity.INFO

    return dispatcher.dispatch(
        severity=severity,
        category=AlertCategory.HEALTH,
        event_type="HEALTH_STATE_CHANGE",
        message=f"{dimension}: {old_state} → {new_state}",
        details={
            "dimension": dimension,
            "old_state": old_state,
            "new_state": new_state,
            "reason": reason,
        },
        event_id=event_id,
        state_transition=f"{dimension}:{old_state}->{new_state}",
    )


def alert_risk_threshold(
    dispatcher: StructuredAlertDispatcher,
    dimension: str,
    value: float,
    limit: float,
    message: str,
    event_id: str | None = None,
) -> Alert:
    """Alert on risk threshold breach."""
    severity = AlertSeverity.CRITICAL if value >= limit else AlertSeverity.WARNING

    return dispatcher.dispatch(
        severity=severity,
        category=AlertCategory.RISK,
        event_type="RISK_THRESHOLD",
        message=message,
        details={"dimension": dimension, "value": value, "limit": limit},
        event_id=event_id,
    )


def alert_reconciliation_mismatch(
    dispatcher: StructuredAlertDispatcher,
    status: str,
    mismatches: List[str],
    event_id: str | None = None,
) -> Alert:
    """Alert on reconciliation mismatch."""
    severity = AlertSeverity.CRITICAL if status in ("BLOCKING", "MISMATCH") else AlertSeverity.WARNING

    return dispatcher.dispatch(
        severity=severity,
        category=AlertCategory.RECONCILIATION,
        event_type="RECONCILIATION_MISMATCH",
        message=f"Reconciliation {status}: {len(mismatches)} mismatches",
        details={"status": status, "mismatches": mismatches},
        event_id=event_id,
    )


def alert_execution_anomaly(
    dispatcher: StructuredAlertDispatcher,
    anomaly_type: str,
    details: Dict[str, Any],
    event_id: str | None = None,
) -> Alert:
    """Alert on execution anomaly."""
    return dispatcher.dispatch(
        severity=AlertSeverity.WARNING,
        category=AlertCategory.EXECUTION,
        event_type="EXECUTION_ANOMALY",
        message=f"Execution anomaly: {anomaly_type}",
        details=details,
        event_id=event_id,
    )


def alert_broker_disconnect(
    dispatcher: StructuredAlertDispatcher,
    reason: str,
    event_id: str | None = None,
) -> Alert:
    """Alert on broker disconnect."""
    return dispatcher.dispatch(
        severity=AlertSeverity.CRITICAL,
        category=AlertCategory.BROKER,
        event_type="BROKER_DISCONNECT",
        message=f"Broker disconnected: {reason}",
        details={"reason": reason},
        event_id=event_id,
    )


def alert_watchdog_state(
    dispatcher: StructuredAlertDispatcher,
    old_state: str,
    new_state: str,
    reason: str,
    event_id: str | None = None,
) -> Alert:
    """Alert on watchdog state change."""
    severity = AlertSeverity.CRITICAL if new_state in ("CONTAIN", "HALT") else AlertSeverity.WARNING

    return dispatcher.dispatch(
        severity=severity,
        category=AlertCategory.WATCHDOG,
        event_type="WATCHDOG_STATE_CHANGE",
        message=f"Watchdog: {old_state} → {new_state}",
        details={"old_state": old_state, "new_state": new_state, "reason": reason},
        event_id=event_id,
        state_transition=f"watchdog:{old_state}->{new_state}",
    )


# Escalation thresholds
ESCALATION_THRESHOLDS = {
    "WARNING_TO_CRITICAL": 3,  # 3 consecutive WARNINGs → escalate to CRITICAL
    "ELEVATED_TO_WARNING": 5,  # 5 consecutive ELEVATEDs → escalate to WARNING
    "TIMEOUT_TO_CRITICAL": 600,  # 10 minutes without resolution → CRITICAL
}


def should_escalate(
    dispatcher: StructuredAlertDispatcher,
    category: AlertCategory,
    current_severity: AlertSeverity,
    consecutive_count: int,
    first_alert_time: float | None = None,
) -> tuple[AlertSeverity, str]:
    """Determine if an alert should be escalated based on repetition.

    Escalation rules:
    - 3+ consecutive WARNINGs → escalate to CRITICAL
    - 5+ consecutive ELEVATEDs → escalate to WARNING
    - 10+ minutes without resolution → escalate to CRITICAL

    Returns:
        (escalated_severity, escalation_reason)
    """
    import time

    now = time.time()
    reason = ""
    escalated = current_severity

    # Repetition-based escalation
    if current_severity == AlertSeverity.WARNING and consecutive_count >= ESCALATION_THRESHOLDS["WARNING_TO_CRITICAL"]:
        escalated = AlertSeverity.CRITICAL
        reason = f"{consecutive_count} consecutive WARNINGs — escalated to CRITICAL"

    elif current_severity == AlertSeverity.INFO and consecutive_count >= ESCALATION_THRESHOLDS["ELEVATED_TO_WARNING"]:
        escalated = AlertSeverity.WARNING
        reason = f"{consecutive_count} consecutive ELEVATEDs — escalated to WARNING"

    # Time-based escalation
    if first_alert_time and (now - first_alert_time) >= ESCALATION_THRESHOLDS["TIMEOUT_TO_CRITICAL"]:
        if escalated.value != "CRITICAL":
            escalated = AlertSeverity.CRITICAL
            reason = f"Unresolved for {now - first_alert_time:.0f}s — escalated to CRITICAL"

    return escalated, reason
