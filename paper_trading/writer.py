"""Background persistence writer — single-threaded drain of WAL + DB queues.

All actors enqueue write commands to a shared queue. A dedicated background
thread drains the queue and serializes writes to the WAL and SQLite store.
This ensures:

- Deterministic ordering of events across all actors
- No lock contention on WAL file handles
- Single SQLite writer avoids serialisation conflicts

Thread safety:
    ``enqueue`` is safe to call from any thread.
    The background thread owns all persistence resources.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

logger = logging.getLogger("quantforge.writer")


class WriteOp(Enum):
    WAL_EVENT = auto()
    DB_TRADE = auto()
    DB_ATTRIBUTION = auto()
    DB_SHADOW_TRADE = auto()
    DB_CONFIDENCE_BUCKET = auto()
    DB_EQUITY_HISTORY = auto()


@dataclass
class WriteCommand:
    op: WriteOp
    payload: dict[str, Any]
    source: str = ""
    callback: Callable[[], None] | None = None


class BackgroundWriter:
    """Single-threaded persistence writer.

    Usage::

        writer = BackgroundWriter(wal, db)
        writer.enqueue(WriteCommand(WriteOp.WAL_EVENT, {"kind": "signal", ...}))
        writer.flush()  # block until all queued writes complete
        writer.shutdown()  # stop the background thread
    """

    def __init__(
        self,
        wal_writer,
        db_store,
        max_queue_size: int = 10_000,
    ):
        self._wal = wal_writer
        self._db = db_store
        self._queue: queue.Queue[WriteCommand | None] = queue.Queue(maxsize=max_queue_size)
        self._flush_event = threading.Event()
        self._flush_done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="qf-writer", daemon=True)
        self._shutdown_flag = False
        self._thread.start()

    def enqueue(self, cmd: WriteCommand) -> None:
        """Enqueue a write command (thread-safe)."""
        self._queue.put_nowait(cmd)

    def flush(self, timeout: float = 10.0) -> bool:
        """Block until all previously enqueued writes are persisted."""
        self._flush_event.set()
        return self._flush_done.wait(timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait for the background thread to finish."""
        self._shutdown_flag = True
        self._queue.put_nowait(None)
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        """Background thread main loop."""
        while not self._shutdown_flag:
            try:
                cmd = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if cmd is None:
                break
            try:
                self._execute(cmd)
            except Exception:
                logger.exception("Background writer failed to execute %s", cmd.op)
            self._queue.task_done()
            if cmd.callback:
                try:
                    cmd.callback()
                except Exception:
                    logger.exception("Background writer callback failed")
            if self._flush_event.is_set():
                self._flush_event.clear()
                self._flush_done.set()
                self._flush_done.clear()

    def _execute(self, cmd: WriteCommand) -> None:
        if cmd.op == WriteOp.WAL_EVENT:
            event_type = cmd.payload.pop("event_type", "unknown")
            self._wal.write(event_type, cmd.payload)
        elif cmd.op == WriteOp.DB_TRADE:
            self._db.append_trade(cmd.payload)
        elif cmd.op == WriteOp.DB_ATTRIBUTION:
            self._db.append_attribution(cmd.payload)
        elif cmd.op == WriteOp.DB_SHADOW_TRADE:
            self._db.append_shadow_trade(cmd.payload)
        elif cmd.op == WriteOp.DB_CONFIDENCE_BUCKET:
            self._db.append_confidence_bucket(cmd.payload)
        elif cmd.op == WriteOp.DB_EQUITY_HISTORY:
            self._db.append_equity_history(cmd.payload)
