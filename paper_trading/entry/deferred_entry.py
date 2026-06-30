import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from paper_trading.entry.decision import TradeDecision

logger = logging.getLogger("quorrin.paper_trading.deferred_entry")


class DeferredEntryStatus(Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass
class DeferredEntry:
    """
    First-class state machine for deferred trade entries.
    """

    decision: TradeDecision
    entry_id: str
    status: DeferredEntryStatus = DeferredEntryStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    bars_elapsed: int = 0
    max_bars: int = 5
    trigger_price: float | None = None

    @classmethod
    def from_decision(cls, decision: TradeDecision, max_bars: int = 5) -> "DeferredEntry":
        """
        Creates a new deferred entry with an idempotent ID.
        """
        # ID is hashed from asset, signal, timestamp to prevent duplicates
        id_str = f"{decision.asset}_{decision.signal}_{decision.timestamp}"
        entry_id = hashlib.md5(id_str.encode()).hexdigest()[:12]

        return cls(decision=decision, entry_id=entry_id, max_bars=max_bars)

    def update(self) -> None:
        """Increments time tracking."""
        self.bars_elapsed += 1
        if self.status == DeferredEntryStatus.PENDING and self.bars_elapsed > self.max_bars:
            self.status = DeferredEntryStatus.EXPIRED
            logger.info(f"Entry {self.entry_id} EXPIRED after {self.max_bars} bars.")

    def trigger(self, fill_price: float) -> None:
        """Transitions to TRIGGERED state."""
        if self.status == DeferredEntryStatus.PENDING:
            self.status = DeferredEntryStatus.TRIGGERED
            self.trigger_price = fill_price
            logger.info(f"Entry {self.entry_id} TRIGGERED at {fill_price}")

    def cancel(self, reason: str = "Manual") -> None:
        """Transitions to CANCELLED state."""
        if self.status in [DeferredEntryStatus.PENDING, DeferredEntryStatus.TRIGGERED]:
            self.status = DeferredEntryStatus.CANCELLED
            logger.info(f"Entry {self.entry_id} CANCELLED. Reason: {reason}")

    def close(self) -> None:
        """Transitions to CLOSED state."""
        self.status = DeferredEntryStatus.CLOSED

    @property
    def is_active(self) -> bool:
        return self.status == DeferredEntryStatus.PENDING
