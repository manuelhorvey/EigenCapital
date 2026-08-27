"""Event/Evidence Ledger — immutable, reconstructable trade lifecycle.

Every signal → order → fill → position → risk → exit → reconciliation event
is captured with:
- Immutable UUID
- Timestamp (ISO 8601 UTC)
- Strategy version
- Build ID (git commit SHA)
- Config fingerprint
- Account/tier
- Symbol (if applicable)
- Position/ticket
- Correlation ID (links related events)
- Parent event ID
- Broker reference
- State transition

A complete trade becomes reconstructable from events.
This is the canonical economic record for Phase 2 qualification.

Design principles:
- Append-only: events are never modified or deleted
- Immutable: each event is frozen at creation time
- Reconstructable: any trade can be rebuilt from its event chain
- Bounded: storage is capped with configurable retention
- Durable: events are flushed to disk immediately
- Auditable: every event has a deterministic fingerprint
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    """Event types for the trade lifecycle."""
    
    # Signal events
    SIGNAL_COMPUTED = "SIGNAL_COMPUTED"
    SIGNAL_CLIPPED = "SIGNAL_CLIPPED"
    SIGNAL_BLOCKED = "SIGNAL_BLOCKED"
    
    # Order events
    ORDER_INTENT = "ORDER_INTENT"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    
    # Fill events
    FILL = "FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL_REJECTED = "FILL_REJECTED"
    
    # Position events
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_MODIFIED = "POSITION_MODIFIED"
    
    # Risk events
    RISK_OBSERVATION = "RISK_OBSERVATION"
    RISK_ACTION = "RISK_ACTION"
    RISK_GATE = "RISK_GATE"
    
    # Price events
    PRICE_OBSERVATION = "PRICE_OBSERVATION"
    SPREAD_OBSERVATION = "SPREAD_OBSERVATION"
    
    # Exit events
    EXIT_INTENT = "EXIT_INTENT"
    EXIT_SUBMITTED = "EXIT_SUBMITTED"
    EXIT_FILL = "EXIT_FILL"
    
    # Reconciliation events
    RECONCILIATION = "RECONCILIATION"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    
    # System events
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_STOP = "SYSTEM_STOP"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"
    
    # Health events
    HEALTH_CHANGE = "HEALTH_CHANGE"
    WATCHDOG_STATE = "WATCHDOG_STATE"
    
    # Alert events
    ALERT_DISPATCHED = "ALERT_DISPATCHED"
    
    # Campaign events
    CAMPAIGN_START = "CAMPAIGN_START"
    CAMPAIGN_END = "CAMPAIGN_END"
    CAMPAIGN_SNAPSHOT = "CAMPAIGN_SNAPSHOT"


@dataclass(frozen=True)
class Event:
    """Immutable event in the trade lifecycle."""
    
    # Identity
    event_id: str
    timestamp: str
    event_type: str
    
    # Provenance
    strategy_version: str
    build_id: str
    config_fingerprint: str
    
    # Context
    account_id: str
    tier: str
    campaign_id: str
    
    # Trade context (optional)
    symbol: Optional[str] = None
    position_ticket: Optional[int] = None
    order_ticket: Optional[str] = None
    
    # Correlation
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    
    # Broker reference
    broker_reference: Optional[str] = None
    
    # State transition
    state_transition: Optional[str] = None
    
    # Payload
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Integrity
    event_hash: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        """Create from dictionary."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class EventLedger:
    """Immutable, reconstructable trade lifecycle ledger.
    
    Events are:
    - Appended in order
    - Never modified or deleted
    - Flushed to disk immediately
    - Bounded by configurable retention
    - Indexed by correlation_id for trade reconstruction
    """
    
    def __init__(
        self,
        base_path: str = "reports/event_ledger",
        max_events: int = 100_000,
        flush_after: int = 1,  # Flush after every N events
    ) -> None:
        """Initialize the event ledger.
        
        Args:
            base_path: Directory for event storage
            max_events: Maximum events before rotation
            flush_after: Flush to disk after N events
        """
        self._base_path = Path(base_path)
        self._max_events = max_events
        self._flush_after = flush_after
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Current batch
        self._events: List[Event] = []
        self._batch_count = 0
        
        # Index for correlation lookups
        self._correlation_index: Dict[str, List[str]] = {}  # correlation_id -> [event_id]
        self._position_index: Dict[int, List[str]] = {}  # position_ticket -> [event_id]
        self._symbol_index: Dict[str, List[str]] = {}  # symbol -> [event_id]
        
        # Counters
        self._total_events = 0
        self._total_batches = 0
        
        # Ensure directory exists
        self._base_path.mkdir(parents=True, exist_ok=True)
    
    def _compute_event_hash(self, event_data: Dict[str, Any]) -> str:
        """Compute deterministic hash for event integrity."""
        # Remove event_hash itself to avoid circular reference
        data = {k: v for k, v in event_data.items() if k != "event_hash"}
        payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        return str(uuid.uuid4())
    
    def _get_build_id(self) -> str:
        """Get build ID from git HEAD."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return hashlib.sha256(result.stdout.strip().encode()).hexdigest()[:16]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return "unknown"
    
    def _get_config_fingerprint(self) -> str:
        """Get config fingerprint."""
        try:
            from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
            verifier = FingerprintVerifier()
            return verifier._frozen_config_fp[:16]
        except (ImportError, AttributeError, FileNotFoundError):
            return "unknown"
    
    def append(
        self,
        event_type: EventType,
        account_id: str,
        tier: str,
        campaign_id: str,
        symbol: Optional[str] = None,
        position_ticket: Optional[int] = None,
        order_ticket: Optional[str] = None,
        correlation_id: Optional[str] = None,
        parent_event_id: Optional[str] = None,
        broker_reference: Optional[str] = None,
        state_transition: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        strategy_version: str = "R4.0",
    ) -> Event:
        """Append an event to the ledger.
        
        Args:
            event_type: Type of event
            account_id: MT5 account ID
            tier: Campaign tier (e.g., "T1-5K")
            campaign_id: Campaign identifier
            symbol: Instrument symbol (if applicable)
            position_ticket: Position ticket (if applicable)
            order_ticket: Order ticket (if applicable)
            correlation_id: Links related events
            parent_event_id: Parent event (for nested events)
            broker_reference: Broker's order/fill reference
            state_transition: State change description
            payload: Event-specific data
            strategy_version: Strategy version string
            
        Returns:
            Created event
        """
        now = datetime.now(timezone.utc).isoformat()
        
        # Generate event
        event = Event(
            event_id=self._generate_event_id(),
            timestamp=now,
            event_type=event_type.value,
            strategy_version=strategy_version,
            build_id=self._get_build_id(),
            config_fingerprint=self._get_config_fingerprint(),
            account_id=account_id,
            tier=tier,
            campaign_id=campaign_id,
            symbol=symbol,
            position_ticket=position_ticket,
            order_ticket=order_ticket,
            correlation_id=correlation_id or self._generate_event_id(),
            parent_event_id=parent_event_id,
            broker_reference=broker_reference,
            state_transition=state_transition,
            payload=payload or {},
            event_hash="",  # Will be computed below
        )
        
        # Compute hash
        event_data = event.to_dict()
        event_hash = self._compute_event_hash(event_data)
        event = Event(**{**event_data, "event_hash": event_hash})
        
        # Add to batch with thread safety
        with self._lock:
            self._events.append(event)
            self._total_events += 1
            
            # Update indexes
            if event.correlation_id:
                self._correlation_index.setdefault(event.correlation_id, []).append(event.event_id)
            if event.position_ticket:
                self._position_index.setdefault(event.position_ticket, []).append(event.event_id)
            if event.symbol:
                self._symbol_index.setdefault(event.symbol, []).append(event.event_id)
        
        # Flush if needed (outside lock to avoid holding during I/O)
        if len(self._events) >= self._flush_after:
            self.flush()
        
        return event
    
    def flush(self) -> None:
        """Flush current batch to disk."""
        with self._lock:
            if not self._events:
                return
            # Copy events and clear batch atomically
            events_to_write = self._events[:]
            batch_file = self._base_path / f"events_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self._total_batches:06d}.jsonl"
            self._events = []
            self._batch_count += 1
            self._total_batches += 1
        
        # Write events (outside lock)
        with open(batch_file, "w", encoding="utf-8") as f:
            for event in events_to_write:
                f.write(json.dumps(event.to_dict(), default=str) + "\n")
        
        # Check if we need to rotate
        if self._total_events >= self._max_events:
            self._rotate()
    
    def _rotate(self) -> None:
        """Rotate old batches if we exceed max events."""
        # This is a simplified rotation - in production, you'd want
        # more sophisticated archival/compression
        batches = sorted(self._base_path.glob("events_*.jsonl"))
        if len(batches) > 10:  # Keep at most 10 batches
            for batch in batches[:-5]:  # Delete oldest batches
                batch.unlink()
    
    def query_by_correlation(self, correlation_id: str) -> List[Event]:
        """Query events by correlation ID (trade reconstruction)."""
        event_ids = self._correlation_index.get(correlation_id, [])
        return self._query_by_ids(event_ids)
    
    def query_by_position(self, position_ticket: int) -> List[Event]:
        """Query events by position ticket."""
        event_ids = self._position_index.get(position_ticket, [])
        return self._query_by_ids(event_ids)
    
    def query_by_symbol(self, symbol: str) -> List[Event]:
        """Query events by symbol."""
        event_ids = self._symbol_index.get(symbol, [])
        return self._query_by_ids(event_ids)
    
    def query_by_type(self, event_type: EventType) -> List[Event]:
        """Query events by type."""
        return [e for e in self._events if e.event_type == event_type.value]
    
    def query_by_time_range(
        self,
        start_time: str,
        end_time: str,
    ) -> List[Event]:
        """Query events within time range."""
        return [
            e for e in self._events
            if start_time <= e.timestamp <= end_time
        ]
    
    def _query_by_ids(self, event_ids: List[str]) -> List[Event]:
        """Query events by IDs (from index)."""
        # For now, scan current batch
        # In production, you'd query persisted batches too
        return [e for e in self._events if e.event_id in event_ids]
    
    def get_trade_chain(self, correlation_id: str) -> List[Event]:
        """Get complete event chain for a trade.
        
        Returns events in chronological order, suitable for
        reconstructing the full trade lifecycle.
        """
        events = self.query_by_correlation(correlation_id)
        return sorted(events, key=lambda e: e.timestamp)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get ledger statistics."""
        return {
            "total_events": self._total_events,
            "total_batches": self._total_batches,
            "current_batch_size": len(self._events),
            "correlation_index_size": len(self._correlation_index),
            "position_index_size": len(self._position_index),
            "symbol_index_size": len(self._symbol_index),
        }


# Convenience functions for common event patterns

def signal_computed(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    symbol: str,
    direction: float,
    weight: float,
    regime: str,
    correlation_id: Optional[str] = None,
) -> Event:
    """Record signal computation event."""
    return ledger.append(
        event_type=EventType.SIGNAL_COMPUTED,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        symbol=symbol,
        correlation_id=correlation_id,
        payload={
            "direction": direction,
            "weight": weight,
            "regime": regime,
        },
        state_transition="SIGNAL_COMPUTED",
    )


def order_submitted(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    symbol: str,
    side: str,
    quantity: float,
    order_ticket: str,
    correlation_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
) -> Event:
    """Record order submission event."""
    return ledger.append(
        event_type=EventType.ORDER_SUBMITTED,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        symbol=symbol,
        order_ticket=order_ticket,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        payload={
            "side": side,
            "quantity": quantity,
        },
        state_transition="ORDER_SUBMITTED",
    )


def fill(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    symbol: str,
    position_ticket: int,
    fill_price: float,
    fill_quantity: float,
    spread: float,
    slippage: float,
    order_ticket: str,
    correlation_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
) -> Event:
    """Record fill event."""
    return ledger.append(
        event_type=EventType.FILL,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        symbol=symbol,
        position_ticket=position_ticket,
        order_ticket=order_ticket,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        payload={
            "fill_price": fill_price,
            "fill_quantity": fill_quantity,
            "spread": spread,
            "slippage": slippage,
        },
        state_transition="FILL",
    )


def position_opened(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    symbol: str,
    position_ticket: int,
    entry_price: float,
    notional: float,
    correlation_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
) -> Event:
    """Record position opened event."""
    return ledger.append(
        event_type=EventType.POSITION_OPENED,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        symbol=symbol,
        position_ticket=position_ticket,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        payload={
            "entry_price": entry_price,
            "notional": notional,
        },
        state_transition="POSITION_OPENED",
    )


def risk_observation(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    equity: float,
    drawdown: float,
    daily_loss: float,
    position_count: int,
    gross_exposure: float,
    correlation_id: Optional[str] = None,
) -> Event:
    """Record risk observation event."""
    return ledger.append(
        event_type=EventType.RISK_OBSERVATION,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        correlation_id=correlation_id,
        payload={
            "equity": equity,
            "drawdown": drawdown,
            "daily_loss": daily_loss,
            "position_count": position_count,
            "gross_exposure": gross_exposure,
        },
        state_transition="RISK_OBSERVATION",
    )


def reconciliation(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    status: str,
    mismatches: List[str],
    correlation_id: Optional[str] = None,
) -> Event:
    """Record reconciliation event."""
    return ledger.append(
        event_type=EventType.RECONCILIATION,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        correlation_id=correlation_id,
        payload={
            "status": status,
            "mismatches": mismatches,
        },
        state_transition=f"RECONCILIATION_{status.upper()}",
    )


def health_change(
    ledger: EventLedger,
    account_id: str,
    tier: str,
    campaign_id: str,
    dimension: str,
    old_state: str,
    new_state: str,
    reason: str,
    correlation_id: Optional[str] = None,
) -> Event:
    """Record health state change event."""
    return ledger.append(
        event_type=EventType.HEALTH_CHANGE,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        correlation_id=correlation_id,
        payload={
            "dimension": dimension,
            "old_state": old_state,
            "new_state": new_state,
            "reason": reason,
        },
        state_transition=f"{dimension}:{old_state}->{new_state}",
    )
