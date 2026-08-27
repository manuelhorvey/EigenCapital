"""Audit Event Log — immutable record of all state transitions.

Every important state transition produces an immutable audit event.
Every event contains enough provenance to reconstruct what happened.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    """Types of audit events."""

    ORDER_CREATED = "order_created"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_CHANGED = "position_changed"
    ACCOUNT_CHANGED = "account_changed"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    RECONCILIATION_PASSED = "reconciliation_passed"
    RECONCILIATION_FAILED = "reconciliation_failed"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event.

    Attributes:
        event_id: Unique identifier
        timestamp_utc: When event occurred
        event_type: Type of event
        instrument_id: Instrument (if applicable)
        order_id: Order (if applicable)
        fill_id: Fill (if applicable)
        strategy_id: Strategy (if applicable)
        experiment_id: Experiment (if applicable)
        details: Event-specific details
        previous_state_hash: Hash of previous state
        resulting_state_hash: Hash of resulting state
        event_hash: Deterministic hash of this event
    """

    event_id: str
    timestamp_utc: str
    event_type: EventType
    instrument_id: str = ""
    order_id: str = ""
    fill_id: str = ""
    strategy_id: str = ""
    experiment_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    previous_state_hash: str = ""
    resulting_state_hash: str = ""
    event_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp_utc": self.timestamp_utc,
            "event_type": self.event_type.value,
            "instrument_id": self.instrument_id,
            "order_id": self.order_id,
            "fill_id": self.fill_id,
            "strategy_id": self.strategy_id,
            "experiment_id": self.experiment_id,
            "details": dict(sorted(self.details.items())),
            "previous_state_hash": self.previous_state_hash,
            "resulting_state_hash": self.resulting_state_hash,
            "event_hash": self.event_hash,
        }

    def compute_hash(self) -> str:
        data = self.to_dict()
        data.pop("event_hash", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AuditLog:
    """Append-only audit log of all events.

    The audit log is permanent. Events cannot be modified or deleted.
    """

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._event_counter = 0

    def append(self, event: AuditEvent) -> None:
        """Append an event to the log."""
        self._events.append(event)

    def create_event(
        self,
        event_type: EventType,
        timestamp_utc: str = "",
        **kwargs: Any,
    ) -> AuditEvent:
        """Create and append a new audit event."""
        self._event_counter += 1
        event = AuditEvent(
            event_id=f"EVT-{self._event_counter:06d}",
            timestamp_utc=timestamp_utc,
            event_type=event_type,
            **kwargs,
        )
        # Compute hash
        event_hash = event.compute_hash()
        event = AuditEvent(**{**event.__dict__, "event_hash": event_hash})
        self.append(event)
        return event

    def get_events(self, event_type: EventType | None = None) -> List[AuditEvent]:
        """Get events, optionally filtered by type."""
        if event_type is None:
            return list(self._events)
        return [e for e in self._events if e.event_type == event_type]

    def get_events_for_instrument(self, instrument_id: str) -> List[AuditEvent]:
        """Get events for a specific instrument."""
        return [e for e in self._events if e.instrument_id == instrument_id]

    def get_events_for_order(self, order_id: str) -> List[AuditEvent]:
        """Get events for a specific order."""
        return [e for e in self._events if e.order_id == order_id]

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)
