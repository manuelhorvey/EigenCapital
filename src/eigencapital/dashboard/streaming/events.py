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
- WebSocket for live state/events
- Reconnect handling on client
- Freshness indicators
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["streaming"])


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


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    """WebSocket endpoint for live state updates.

    Client receives:
    - state_update: Full state snapshot
    - health_change: Health state transition
    - alert: New alert
    - heartbeat: Keepalive
    """
    await manager.connect(websocket)

    try:
        # Send initial state
        initial_state = await get_live_state()
        await websocket.send_json(initial_state)

        # Start background tasks
        async def state_broadcaster() -> None:
            """Broadcast state updates every 5 seconds."""
            while True:
                try:
                    state = await get_live_state()
                    await manager.broadcast(state)
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(1)

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

        # Run broadcasters — track tasks for clean cancellation
        broadcaster_task = asyncio.create_task(state_broadcaster())
        heartbeat_task = asyncio.create_task(heartbeat_sender())

        try:
            # Listen for client messages
            while True:
                try:
                    data = await websocket.receive_text()
                    msg = json.loads(data)

                    if msg.get("type") == "request_state":
                        state = await get_live_state()
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
        finally:
            # Cancel background tasks on disconnect
            broadcaster_task.cancel()
            heartbeat_task.cancel()
            # Suppress CancelledError from task cancellation
            try:
                await broadcaster_task
            except asyncio.CancelledError:
                pass
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)


@router.get("/api/v1/events/stream")
async def sse_events() -> AsyncGenerator[str, None]:
    """SSE endpoint for event streaming.

    Server-Sent Events format:
    event: state_update
    data: {...}

    event: heartbeat
    data: {"timestamp": "..."}
    """
    while True:
        try:
            state = await get_live_state()
            yield f"event: state_update\ndata: {json.dumps(state)}\n\n"
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception:
            yield f"event: error\ndata: {json.dumps({'error': 'Stream error'})}\n\n"
            await asyncio.sleep(1)
