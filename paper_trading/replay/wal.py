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
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from eigencapital.domain.time import utc_now

logger = logging.getLogger("eigencapital.replay.wal")


DEFAULT_WAL_SUBDIR = "data/live/wal"
DEFAULT_WAL_DIR = "data/live/wal"


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

    def __init__(
        self,
        base_dir: str | Path,
        source: str = "engine",
        batch_size: int = 64,
        wal_dir: str | Path | None = None,
    ):
        self._base_dir = Path(base_dir).resolve()
        if wal_dir is not None:
            self._wal_dir = Path(wal_dir).resolve()
        else:
            self._wal_dir = self._base_dir / DEFAULT_WAL_SUBDIR
        self._source = source
        self._batch_size = max(batch_size, 1)
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._path = self._wal_dir / f"{source}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._first_write = not self._path.exists()
        self._seq = self._read_last_sequence()

    def _read_last_sequence(self) -> int:
        """Read the last sequence number from existing WAL file."""
        if not self._path.exists():
            return 0
        try:
            with open(self._path, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size == 0:
                    return 0

                # Read backwards in chunks to find the last valid line
                chunk_size = 8192
                remaining = file_size
                last_line = b""
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    remaining -= read_size
                    f.seek(remaining)
                    chunk = f.read(read_size)
                    lines = (chunk + last_line).split(b"\n")
                    last_line = lines[0]
                    for line in reversed(lines[1:]):
                        if line.strip():
                            try:
                                data = json.loads(line)
                                return data.get("sequence", 0)
                            except (json.JSONDecodeError, KeyError):
                                continue
                # Check the very first line if we haven't found one yet
                if last_line.strip():
                    try:
                        data = json.loads(last_line)
                        return data.get("sequence", 0)
                    except (json.JSONDecodeError, KeyError):
                        pass
        except OSError:
            logger.exception("Failed to read last sequence from %s", self._path)
        return 0

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
                timestamp=utc_now().isoformat(),
                payload=payload,
            )
            line = json.dumps(event.to_dict(), cls=EigenCapitalJSONEncoder) + "\n"
            self._buffer.append(line)
            buf_size = len(self._buffer)

            if buf_size >= self._batch_size:
                # Flush while still holding lock to avoid re-buffer race
                lines = self._buffer
                self._buffer = []
            else:
                lines = None

        if lines is not None:
            self._flush_lines(lines)
        return event

    def _flush_lines(self, lines: list[str]) -> None:
        """Append lines to WAL file with fsync for durability."""
        if not lines:
            return

        # Ensure directory exists (may have been created after writer init)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Open in append mode for WAL semantics
            with open(self._path, "a") as f:
                f.writelines(lines)
                f.flush()
                os.fsync(f.fileno())

            # Fsync directory to persist file creation metadata on first write
            if self._first_write:
                try:
                    dir_fd = os.open(self._path.parent, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError:
                    logger.exception("WAL directory fsync failed for %s", self._source)
                self._first_write = False

        except OSError:
            logger.exception(
                "WAL batch write failed for %s — re-buffering %d events",
                self._source,
                len(lines),
            )
            # Clean up - no temp file to clean since we write directly
            with self._lock:
                self._buffer = lines + self._buffer

    def flush(self) -> None:
        """Flush buffered events to disk (write + fsync).

        Safe to call multiple times — no-op when buffer is empty.
        On write failure (disk full, permissions), events are re-buffered
        for a retry on the next flush cycle.
        """
        with self._lock:
            lines = self._buffer
            self._buffer = []

        if lines:
            self._flush_lines(lines)

    @property
    def current_sequence(self) -> int:
        return self._seq

    @property
    def path(self) -> str:
        return str(self._path)


# ── WAL Reader ──────────────────────────────────────────────────────────────


class WalReader:
    """Read and iterate over WAL events. Supports replay from sequence offsets."""

    def __init__(self, base_dir: str | Path, source: str = "engine", wal_dir: str | Path | None = None):
        self._base_dir = Path(base_dir).resolve()
        if wal_dir is not None:
            self._wal_dir = Path(wal_dir).resolve()
        else:
            self._wal_dir = self._base_dir / DEFAULT_WAL_SUBDIR
        self._source = source
        self._path = self._wal_dir / f"{source}.jsonl"
        self._corrupt_lines = 0
        self._expected_seq = 1

    @property
    def corrupt_lines(self) -> int:
        """Number of corrupt lines encountered during reads."""
        return self._corrupt_lines

    def read_all(self) -> list[WalEvent]:
        """Read all events from the WAL."""
        return list(self._iter_events())

    def read_from(self, seq: int) -> Iterator[WalEvent]:
        """Iterate over events with sequence >= seq (lazy, memory-efficient)."""
        for event in self._iter_events():
            if event.sequence >= seq:
                yield event

    def read_last(self, n: int = 10) -> list[WalEvent]:
        """Read the last N events."""
        events = self.read_all()
        return events[-n:]

    def count(self) -> int:
        """Return total event count (fast — reads line count only)."""
        if not self._path.exists():
            return 0
        with open(self._path) as f:
            return sum(1 for _ in f)

    def _iter_events(self) -> Iterator[WalEvent]:
        if not self._path.exists():
            return
        self._expected_seq = 1
        first_gap_logged = False
        with open(self._path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = WalEvent.from_dict(data)
                    # Sequence validation
                    if event.sequence != self._expected_seq and not first_gap_logged:
                        logger.warning(
                            "WAL sequence gap/duplicate for %s at line %d: expected %d, got %d",
                            self._source,
                            line_num,
                            self._expected_seq,
                            event.sequence,
                        )
                        first_gap_logged = True
                    self._expected_seq = event.sequence + 1
                    yield event
                except (json.JSONDecodeError, KeyError) as e:
                    self._corrupt_lines += 1
                    logger.error(
                        "WAL corrupt line %d in %s: %s",
                        line_num,
                        self._path,
                        e,
                    )
