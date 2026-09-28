"""Audit Event Log — immutable record of all state transitions.

Every important state transition produces an immutable audit event.
Every event contains enough provenance to reconstruct what happened.

Every emitted event is also persisted append-only (durable_audit: inter-process
lock, fsync, hash-chained JSONL plus an atomic mirror), so a crash cannot lose
the trail. The in-memory view callers read is rebuilt from that store on
construction: persistence is transparent, and a failed write is logged and
re-raised — never swallowed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

from eigencapital.live.durable_audit import DurableAudit

logger = logging.getLogger(__name__)

_STORE_ENV_VAR = "EIGENCAPITAL_EXECUTION_AUDIT_STORE"
_DEFAULT_STORE = "reports/execution_audit.jsonl"


def _resolve_store_path(store_path: Path | str | None) -> Path:
    """Resolve the event store location.

    Injectable for callers/tests; the default follows the repo evidence
    convention (``reports/*.jsonl`` — same directory family as the campaign
    and alert stores) with an ``EIGENCAPITAL_*`` env override, mirroring how
    ``EIGENCAPITAL_CAMPAIGN_STORE`` resolves the campaign store.
    """
    if store_path is not None:
        return Path(store_path)
    return Path(os.environ.get(_STORE_ENV_VAR, _DEFAULT_STORE))


def _mirror_path(path: Path) -> Path:
    """Mirror location, following durable_audit's ``*.mirror.*`` naming."""
    return path.with_name(f"{path.stem}.mirror{path.suffix}")


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

    Each append is fsync'd to an append-only JSONL store (with an atomically
    published mirror copy) *before* the event becomes visible in memory, and
    the store is replayed on construction — so a crash or restart loses
    neither the trail nor its ordering, and the live view can never run
    ahead of the durable history.
    """

    def __init__(self, store_path: Path | str | None = None) -> None:
        path = _resolve_store_path(store_path)
        self._mirror = _mirror_path(path)
        self._store = DurableAudit(path, self._mirror)
        self._events: List[AuditEvent] = []
        self._event_counter = 0
        self._load()

    # ── durable store ───────────────────────────────────────────────
    @property
    def path(self) -> Path:
        """Location of the append-only event store."""
        return self._store.path

    def _restore_primary_from_mirror(self) -> None:
        """Recreate a lost or zeroed primary from the mirror (stage+fsync+replace).

        The mirror is rewritten write-then-replace after every successful
        append, so it holds every record the primary had. Staging is done on
        a temp file, so a crash mid-restore can never truncate either copy.
        """
        primary = self._store.path
        if primary.exists() and primary.stat().st_size > 0:
            return
        if not self._mirror.exists() or self._mirror.stat().st_size == 0:
            return
        primary.parent.mkdir(parents=True, exist_ok=True)
        staged = primary.with_name(primary.name + ".tmp")
        with open(staged, "wb") as handle:
            handle.write(self._mirror.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, primary)

    def _repair_torn_tail(self) -> None:
        """Terminate a torn tail line so the next append gets its own line.

        A crash mid-append leaves a partial record with no trailing newline;
        without this, durable_audit's next append would concatenate onto the
        garbage line and become unreadable. Append-only repair: exactly one
        delimiter byte is added — no existing byte is ever touched. The check
        and the write share the inter-process lock durable_audit holds while
        appending, so a concurrent writer can never land between them.
        """
        path = self._store.path
        if not path.exists():
            return
        with open(path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    return
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) == b"\n":
                    return
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _event_from_record(raw: Dict[str, Any]) -> AuditEvent | None:
        """Rebuild an event from its persisted dict; None if it is unreadable."""
        event_type = raw.get("event_type")
        if not isinstance(event_type, str):
            return None
        try:
            parsed_type = EventType(event_type)
        except ValueError:
            return None
        details = raw.get("details")
        return AuditEvent(
            event_id=str(raw.get("event_id", "")),
            timestamp_utc=str(raw.get("timestamp_utc", "")),
            event_type=parsed_type,
            instrument_id=str(raw.get("instrument_id", "")),
            order_id=str(raw.get("order_id", "")),
            fill_id=str(raw.get("fill_id", "")),
            strategy_id=str(raw.get("strategy_id", "")),
            experiment_id=str(raw.get("experiment_id", "")),
            details=dict(details) if isinstance(details, dict) else {},
            previous_state_hash=str(raw.get("previous_state_hash", "")),
            resulting_state_hash=str(raw.get("resulting_state_hash", "")),
            event_hash=str(raw.get("event_hash", "")),
        )

    def _absorb_event_id(self, event_id: str) -> None:
        """Keep the event counter ahead of every id already on disk."""
        suffix = event_id[4:] if event_id.startswith("EVT-") else ""
        if suffix.isascii() and suffix.isdigit():
            self._event_counter = max(self._event_counter, int(suffix))

    def _load(self) -> None:
        """Rebuild the in-memory view by replaying the durable store.

        Replaying the persisted records on every construction is what makes
        the trail survive a crash: a new process sees exactly the events the
        previous one durably wrote. Unparseable lines are torn tail records
        from a crash mid-append and are skipped exactly as durable_audit
        skips them when chaining — one bad tail line never zeroes the
        history behind it. Records that parse but cannot be reconstructed
        are logged as errors rather than dropped silently.
        """
        self._restore_primary_from_mirror()
        self._repair_torn_tail()
        path = self._store.path
        if not path.exists():
            return
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn tail line from a crash mid-append: no record there
                payload = record.get("payload") if isinstance(record, dict) else None
                raw = payload.get("event") if isinstance(payload, dict) else None
                if not isinstance(raw, dict):
                    logger.error("audit store %s: record carries no event payload: %.120s", path, line)
                    continue
                event = self._event_from_record(raw)
                if event is None:
                    logger.error("audit store %s: unreadable audit event: %.120s", path, line)
                    continue
                self._events.append(event)
                self._absorb_event_id(event.event_id)

    # ── write path ──────────────────────────────────────────────────
    def append(self, event: AuditEvent) -> None:
        """Append an event to the log, durably before it reaches memory.

        A write failure is logged at error level and re-raised: a lost audit
        trail must be loud, and the live view must never run ahead of the
        durable history.
        """
        try:
            # Torn-tail check first so a partial line left by a crashed
            # concurrent writer cannot swallow this record into an
            # unreadable line.
            self._repair_torn_tail()
            self._store.append("AUDIT_EVENT", {"event": event.to_dict()})
        except Exception as exc:
            logger.error(
                "audit event %s failed to persist to %s: %s",
                event.event_id,
                self._store.path,
                exc,
            )
            raise
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
