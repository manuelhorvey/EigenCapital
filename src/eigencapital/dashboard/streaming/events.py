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
Clients pass the API key as `?token=` (or `Authorization: Bearer`) — browsers
cannot set custom headers on the WebSocket handshake.
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


def _api_key() -> str:
    """Read the configured API key (env override each request)."""
    return os.environ.get("DASHBOARD_API_KEY", "dev-key-change-in-production")


def _is_authorized(websocket: WebSocket) -> bool:
    """Authenticate a WebSocket handshake against the dashboard API key.

    Mirrors the /api/v1 HTTP middleware (S7): DASHBOARD_DISABLE_AUTH=1 bypasses
    auth for local development only; otherwise the token query parameter or the
    Authorization header must carry the configured key.
    """
    if os.environ.get("DASHBOARD_DISABLE_AUTH") == "1":
        return True
    token = websocket.query_params.get("token", "")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :]
    # Constant-time comparison, mirroring the HTTP middleware.
    return bool(token) and secrets.compare_digest(token.encode("utf-8"), _api_key().encode("utf-8"))


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
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

    Authentication: `?token=<DASHBOARD_API_KEY>` (or Authorization: Bearer).
    Unauthorized handshakes are closed with policy violation code 1008.
    """
    if not _is_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await manager.connect(websocket)
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
