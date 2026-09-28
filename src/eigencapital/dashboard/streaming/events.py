"""Live Streaming — WebSocket/SSE for real-time dashboard updates.

Provides:
- Account updates
- Position updates
- Risk observations
- Health transitions
- Reconciliation events
- Alerts
- Execution events

Design:
- REST for historical/query data
- WebSocket for live state/events (authenticated — same API key as /api/v1)
- ONE shared broadcaster loop feeds all clients (a per-connection poll loop
  multiplied MT5 load by connection count; audit F-04)
- Reconnect handling on client
- Freshness indicators

Security (DASHBOARD_CONTRACT.md §2 T5): the live transport is authenticated.
Browsers cannot set custom headers on the WebSocket handshake, so the API key
is passed via the `api-key.<key>` subprotocol (`Sec-WebSocket-Protocol`); the
server echoes the selected protocol per RFC 6455. `Authorization: Bearer` is
also accepted (non-browser clients). Legacy `?token=` query authentication
remains accepted only during the transition window — the key must not travel
in the URL (H-11).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["streaming"])

_BROADCAST_INTERVAL_SECONDS = 5.0
_STATE_CACHE_MAX_AGE_SECONDS = 5.0

# Preferred credential transport (H-11): `Sec-WebSocket-Protocol: api-key.<key>`.
# Subprotocol tokens are client-offered and server-echoed, so the key never
# appears in the URL and no custom handshake header is required.
_API_KEY_PROTOCOL_PREFIX = "api-key."


def _api_key() -> str:
    """Read the configured API key (env override each request)."""
    return os.environ.get("DASHBOARD_API_KEY", "dev-key-change-in-production")


def _offered_api_key_protocol(websocket: WebSocket) -> str | None:
    """Return the offered `api-key.<key>` subprotocol token, if any.

    The header may carry a comma-separated list of client-offered protocols;
    the full token (prefix included) is returned so it can be echoed back as
    the server-selected protocol on accept.
    """
    header = websocket.headers.get("sec-websocket-protocol", "")
    for offered in header.split(","):
        protocol = offered.strip()
        if protocol.startswith(_API_KEY_PROTOCOL_PREFIX):
            return protocol
    return None


def _is_authorized(websocket: WebSocket) -> bool:
    """Authenticate a WebSocket handshake against the dashboard API key.

    Mirrors the /api/v1 HTTP middleware (S7): DASHBOARD_DISABLE_AUTH=1 bypasses
    auth for local development only. Credentials are accepted from, in order
    of preference:
    1. the `api-key.<key>` subprotocol (Sec-WebSocket-Protocol header),
    2. `Authorization: Bearer <key>`,
    3. the legacy `?token=` query parameter (transition window, H-11).

    Every non-empty candidate is checked with a constant-time comparison.
    """
    if os.environ.get("DASHBOARD_DISABLE_AUTH") == "1":
        return True
    candidates: list[str] = []
    api_key_protocol = _offered_api_key_protocol(websocket)
    if api_key_protocol is not None:
        candidates.append(api_key_protocol[len(_API_KEY_PROTOCOL_PREFIX) :])
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        candidates.append(auth_header[len("Bearer ") :])
    candidates.append(websocket.query_params.get("token", ""))

    expected = _api_key().encode("utf-8")
    authorized = False
    for candidate in candidates:
        if candidate:
            # Constant-time comparison for each non-empty candidate (bytes —
            # tolerates non-ASCII input that would raise in str compare_digest),
            # mirroring the HTTP middleware. No candidate short-circuits the rest.
            authorized = secrets.compare_digest(candidate.encode("utf-8"), expected) or authorized
    return authorized


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, subprotocol: str | None = None) -> None:
        # Echo the server-selected subprotocol (RFC 6455): browsers reject a
        # response that names a protocol the client did not offer.
        await websocket.accept(subprotocol=subprotocol)
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()

# ── Shared state cache + broadcaster (audit F-04) ────────────────────
# One cached state snapshot refreshed at most every _STATE_CACHE_MAX_AGE_SECONDS,
# and ONE broadcaster task pushing it to all connected clients. Before this,
# every WebSocket connection ran its own MT5-polling loop and every SSE client
# polled independently — O(connections) broker load.

_state_cache: dict[str, Any] | None = None
_state_cache_ts: float = 0.0
_broadcaster_task: asyncio.Task[None] | None = None


async def get_live_state() -> dict[str, Any]:
    """Read current live state for streaming."""
    try:
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        service = DashboardStateService()
        account = service.get_account_state()
        positions = service.get_positions()
        health = service.get_system_health()
        risk = service.get_risk_state()
        alerts = service.get_recent_alerts(limit=5)

        return {
            "type": "state_update",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "account": account,
                "positions": positions,
                "health": health,
                "risk": risk,
                "alerts": alerts,
            },
        }
    except Exception as e:
        return {
            "type": "error",
            "timestamp": datetime.now(UTC).isoformat(),
            "error": str(e),
        }


async def get_live_state_cached() -> dict[str, Any]:
    """Return the cached live state, refreshing it if older than the max age."""
    global _state_cache, _state_cache_ts
    now = time.monotonic()
    if _state_cache is None or (now - _state_cache_ts) >= _STATE_CACHE_MAX_AGE_SECONDS:
        _state_cache = await get_live_state()
        _state_cache_ts = now
    return _state_cache


def _ensure_broadcaster() -> None:
    """Start the shared broadcaster task if it is not already running."""
    global _broadcaster_task
    if _broadcaster_task is None or _broadcaster_task.done():
        _broadcaster_task = asyncio.create_task(_broadcast_loop())


async def _broadcast_loop() -> None:
    """Broadcast cached state to all clients on one shared interval.

    Idles (no MT5 polling) while there are no connected clients, and exits
    when the last connection goes away — it is restarted on the next connect.
    """
    try:
        while manager.active_connections:
            state = await get_live_state_cached()
            await manager.broadcast(state)
            await asyncio.sleep(_BROADCAST_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Broadcaster died unexpectedly; allow the next connect to restart it.
        pass
    finally:
        global _broadcaster_task
        if _broadcaster_task is asyncio.current_task():
            _broadcaster_task = None


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    """Authenticated WebSocket endpoint for live state updates.

    Client receives:
    - state_update: Full state snapshot
    - health_change: Health state transition
    - alert: New alert
    - heartbeat: Keepalive

    Authentication: `Sec-WebSocket-Protocol: api-key.<DASHBOARD_API_KEY>`
    (preferred — the selected protocol is echoed on accept), or
    `Authorization: Bearer <key>`. The legacy `?token=<DASHBOARD_API_KEY>`
    query parameter is still accepted during the transition window but the
    key must no longer be placed in the URL (H-11).
    Unauthorized handshakes are closed with policy violation code 1008.
    """
    if not _is_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    # Echo the offered `api-key.*` protocol (or None when the client offered
    # none / authenticated via bearer or legacy query token).
    await manager.connect(websocket, subprotocol=_offered_api_key_protocol(websocket))
    _ensure_broadcaster()

    heartbeat_task: asyncio.Task[None] | None = None
    try:
        # Send initial state immediately
        initial_state = await get_live_state_cached()
        await websocket.send_json(initial_state)

        async def heartbeat_sender() -> None:
            """Send heartbeat every 30 seconds."""
            while True:
                try:
                    await asyncio.sleep(30)
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
                except asyncio.CancelledError:
                    break
                except Exception:
                    break

        heartbeat_task = asyncio.create_task(heartbeat_sender())

        # Listen for client messages
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data)

                if msg.get("type") == "request_state":
                    state = await get_live_state_cached()
                    await websocket.send_json(state)
                elif msg.get("type") == "ping":
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                continue

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


@router.get("/api/v1/events/stream")
async def sse_events() -> AsyncGenerator[str, None]:
    """SSE endpoint for event streaming (shares the cached state snapshot).

    Server-Sent Events format:
    event: state_update
    data: {...}

    event: heartbeat
    data: {"timestamp": "..."}
    """
    while True:
        try:
            state = await get_live_state_cached()
            yield f"event: state_update\ndata: {json.dumps(state)}\n\n"
            await asyncio.sleep(_BROADCAST_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception:
            yield f"event: error\ndata: {json.dumps({'error': 'Stream error'})}\n\n"
            await asyncio.sleep(1)
