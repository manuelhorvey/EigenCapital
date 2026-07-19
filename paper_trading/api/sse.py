"""Server-Sent Events endpoint — pushes real-time state-bundle updates."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paper_trading.state_store import StateStore

logger = logging.getLogger("eigencapital.api.sse")

POLL_INTERVAL = 1.0  # seconds between state checks


def handle_sse(
    _path: str,
    _query: dict[str, str],
    state_store: StateStore | None = None,
) -> str:
    """Stream state-bundle updates via Server-Sent Events.

    This handler is NOT called through the normal GET_ROUTES dispatch —
    it is invoked directly from ``handler.py`` ``do_GET`` with a raw
    ``self`` reference so it can write to the wire.
    """
    # This function is a placeholder — the actual SSE handler is
    # ``sse_stream()`` below, which is invoked directly from the
    # request handler with access to ``self`` (the HTTP handler).
    raise RuntimeError("handle_sse must be called via sse_stream()")


def sse_stream(handler, state_store: StateStore | None = None) -> None:
    """Stream SSE events to the connected client.

    Called directly from ``handler.do_GET`` with the handler instance
    so we can write to the raw socket.
    """
    # Set SSE headers
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")  # disable nginx buffering
    # Copy auth headers from the handler
    from paper_trading.api.common import auth_headers

    for k, v in auth_headers().items():
        handler.send_header(k, v)
    handler.end_headers()

    wfile = handler.wfile
    last_snapshot_id = None

    try:
        while True:
            snapshot = None
            if state_store is not None:
                raw = state_store.load_snapshot()
                if raw is not None and hasattr(raw, "model_dump"):
                    snapshot = raw.model_dump(mode="json")
                elif raw is not None and isinstance(raw, dict):
                    snapshot = raw
                elif raw is not None:
                    snapshot = raw.__dict__ if hasattr(raw, "__dict__") else None

            if snapshot is not None:
                seq_id = snapshot.get("sequence_id") or snapshot.get("meta", {}).get("snapshot_sequence_id")
                if seq_id is not None and seq_id != last_snapshot_id:
                    last_snapshot_id = seq_id
                    msg = f"data: {json.dumps(snapshot)}\n\n"
                    try:
                        wfile.write(msg.encode("utf-8"))
                        wfile.flush()
                    except OSError:
                        break  # client disconnected

            # Send keepalive comment every poll interval to prevent
            # proxy timeouts when state hasn't changed
            try:
                wfile.write(": keepalive\n\n".encode("utf-8"))
                wfile.flush()
            except OSError:
                break

            time.sleep(POLL_INTERVAL)

    except (BrokenPipeError, ConnectionResetError, OSError):
        logger.debug("SSE client disconnected")
