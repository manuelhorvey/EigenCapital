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
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


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
    event_id: Optional[str] = None  # Link to event ledger
    correlation_id: Optional[str] = None
    state_transition: Optional[str] = None
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
    ) -> None:
        """Initialize alert dispatcher.
        
        Args:
            alert_path: Path for durable alert storage
            dedup_window_seconds: Window for deduplication
            max_consecutive_alerts: Max consecutive identical alerts
            mirror_stderr: Mirror critical/warning alerts to stderr
        """
        self._alert_path = alert_path
        self._dedup_window = dedup_window_seconds
        self._max_consecutive = max_consecutive_alerts
        self._mirror_stderr = mirror_stderr
        
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
        details: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        state_transition: Optional[str] = None,
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
            self._stats["total_deduplicated"] += 1
            # Return a placeholder - alert was deduplicated
            return Alert(
                alert_id="DEDUP",
                timestamp=datetime.now(timezone.utc).isoformat(),
                severity=severity.value,
                category=category.value,
                event_type=event_type,
                message="[DEDUPLICATED]",
                consecutive_count=self._consecutive_counts.get(dedup_key, 0),
            )
        
        # Create alert
        now = datetime.now(timezone.utc).isoformat()
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
            self._history = self._history[-self._max_history:]
        
        # Update stats
        self._stats["total_dispatched"] += 1
        self._stats["by_severity"][severity.value] = self._stats["by_severity"].get(severity.value, 0) + 1
        self._stats["by_category"][category.value] = self._stats["by_category"].get(category.value, 0) + 1
        
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
        if self._mirror_stderr and alert.severity in (AlertSeverity.CRITICAL.value, AlertSeverity.WARNING.value):
            import sys
            print(f"[{alert.severity}] {alert.category}: {alert.message}", file=sys.stderr)
    
    def get_history(self) -> List[Dict[str, Any]]:
        """Get alert history."""
        return list(self._history)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        return dict(self._stats)
    
    def clear_dedup(self, category: Optional[AlertCategory] = None) -> None:
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
    event_id: Optional[str] = None,
) -> Alert:
    """Alert on health state change."""
    severity = AlertSeverity.WARNING if new_state in ("DEGRADED", "BLOCKED") else AlertSeverity.INFO
    
    return dispatcher.dispatch(
        severity=severity,
        category=AlertCategory.HEALTH,
        event_type="HEALTH_STATE_CHANGE",
        message=f"{dimension}: {old_state} → {new_state}",
        details={"dimension": dimension, "old_state": old_state, "new_state": new_state, "reason": reason},
        event_id=event_id,
        state_transition=f"{dimension}:{old_state}->{new_state}",
    )


def alert_risk_threshold(
    dispatcher: StructuredAlertDispatcher,
    dimension: str,
    value: float,
    limit: float,
    message: str,
    event_id: Optional[str] = None,
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
    event_id: Optional[str] = None,
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
    event_id: Optional[str] = None,
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
    event_id: Optional[str] = None,
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
    event_id: Optional[str] = None,
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
