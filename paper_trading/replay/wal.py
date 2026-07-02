"""Write-Ahead Log — durable decision-chain capture for deterministic replay.

The WAL records every step in the trading decision chain as an ordered event
stream. Each event captures both the input context and the output decision,
enabling full causal reconstruction of engine state.

Causal boundary events (P0 — required for deterministic replay):
    features_snapshot  — exact model input vector + feature hash + model hash
    inference_output   — model probabilities BEFORE governance gating
    decision_output    — final action AFTER governance gating + model hash

Observability events (supporting — not required for causal replay):
    price_update        — OHLC bar data received
    signal_generated    — model signal (entry/flat/exit + confidence)
    entry_executed      — fill result for position entry
    sl_executed         — fill result for stop-loss
    tp_executed         — fill result for take-profit
    position_closed     — position closed (any reason)
    state_committed     — full state snapshot checkpoint
    actor_health        — actor health state change
    stack_added         — pyramid layer added to an existing position
    mt5_order_placed    — MT5 market order submitted to bridge (pre-fill)
    mt5_order_filled    — MT5 order confirmed filled (retcode 10009)
    mt5_order_rejected  — MT5 order rejected (unsupported type, invalid vol, bridge error, retcode != 10009)
    mt5_order_modified  — MT5 SL/TP modification submitted
    mt5_position_closed — MT5 position closed (or already closed / close failed)

Invariants:
    I1: Events from a single source are strictly ordered by sequence.
    I2: All events are deterministic — same inputs → identical payload.
    I3: WAL writer is append-only; past events are never mutated.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("eigencapital.replay.wal")

WAL_DIR = "data/live/wal"


@dataclass
class WalEvent:
    """Single event in the write-ahead log."""

    sequence: int
    source: str
    event_type: str
    timestamp: str = ""
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "source": self.source,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WalEvent:
        return cls(
            sequence=d["sequence"],
            source=d["source"],
            event_type=d["event_type"],
            timestamp=d.get("timestamp", ""),
            payload=d.get("payload", {}),
        )


# ── WAL Writer ──────────────────────────────────────────────────────────────


class WalWriter:
    """Thread-safe, append-only WAL writer.

    Writes one JSON object per line (JSONL format).
    Events are buffered in memory and flushed to disk in batches,
    reducing fsync calls from O(events) to O(flushes).

    Set ``batch_size=1`` (default) to preserve flush-per-event semantics
    equivalent to crash-safe mode. Higher values (e.g. 32) batch writes
    for lower I/O overhead, with a small risk of losing the last batch
    on a hard crash.

    Past events are never mutated (invariant I3).
    """

    def __init__(self, base_dir: str, source: str = "engine", batch_size: int = 64):
        self._base_dir = base_dir
        self._source = source
        self._batch_size = max(batch_size, 1)
        self._seq = 0
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._path = os.path.join(base_dir, WAL_DIR, f"{source}.jsonl")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

    def write(self, event_type: str, payload: dict) -> WalEvent:
        """Append a single event to the WAL buffer. Returns the created event.

        Buffer is flushed to disk when ``batch_size`` events have accumulated.
        Call ``flush()`` explicitly at cycle boundaries to guarantee durability
        without waiting for the batch threshold.

        Lock scope is minimized to sequence increment + event construction
        only. File I/O (``flush()``) runs outside the lock so a hung fsync on
        one thread cannot block other actors from writing.
        """
        with self._lock:
            self._seq += 1
            seq = self._seq
            event = WalEvent(
                sequence=seq,
                source=self._source,
                event_type=event_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
                payload=payload,
            )
            line = json.dumps(event.to_dict(), default=str) + "\n"
            self._buffer.append(line)
            buf_size = len(self._buffer)

        if buf_size >= self._batch_size:
            self.flush()
        return event

    def flush(self) -> None:
        """Flush buffered events to disk (write + fsync).

        Safe to call multiple times — no-op when buffer is empty.
        On write failure (disk full, permissions), events are re-buffered
        for a retry on the next flush cycle.
        """
        with self._lock:
            lines = self._buffer
            self._buffer = []
            if not lines:
                return

        seq_low = self._seq - len(lines) + 1  # approximate for logging
        try:
            with open(self._path, "a") as f:
                f.writelines(lines)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    logger.exception("WAL batch fsync failed for %s seq=%d", self._source, seq_low)
        except OSError:
            logger.exception(
                "WAL batch write failed for %s seq=%d — re-buffering %d events",
                self._source,
                seq_low,
                len(lines),
            )
            with self._lock:
                self._buffer = lines + self._buffer

    @property
    def current_sequence(self) -> int:
        return self._seq

    @property
    def path(self) -> str:
        return self._path


# ── WAL Reader ──────────────────────────────────────────────────────────────


class WalReader:
    """Read and iterate over WAL events. Supports replay from sequence offsets."""

    def __init__(self, base_dir: str, source: str = "engine"):
        self._path = os.path.join(base_dir, WAL_DIR, f"{source}.jsonl")

    def read_all(self) -> list[WalEvent]:
        """Read all events from the WAL."""
        return list(self._iter_events())

    def read_from(self, seq: int) -> list[WalEvent]:
        """Read all events with sequence >= seq."""
        return [e for e in self._iter_events() if e.sequence >= seq]

    def read_last(self, n: int = 10) -> list[WalEvent]:
        """Read the last N events."""
        events = self.read_all()
        return events[-n:]

    def count(self) -> int:
        """Return total event count (fast — reads line count only)."""
        if not os.path.exists(self._path):
            return 0
        with open(self._path) as f:
            return sum(1 for _ in f)

    def _iter_events(self):
        if not os.path.exists(self._path):
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield WalEvent.from_dict(json.loads(line))
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("WAL parse error: %s", e)
