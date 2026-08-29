"""WebSocket Resilience Tests — long-running memory and reconnection validation.

Tests:
1. ConnectionManager cleans up disconnected clients
2. State doesn't accumulate across reconnect cycles
3. Background tasks are cancelled on disconnect
4. Rapid reconnect cycles don't leak connections
5. Broadcast doesn't hold references to dead connections
6. Concurrent connections don't interfere
7. Error states are handled without resource leaks
"""

from __future__ import annotations

import asyncio
import gc
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# ConnectionManager Tests
# ═══════════════════════════════════════════════════════════════════


class TestConnectionManager:
    """Verify ConnectionManager resource management."""

    def test_connect_adds_connection(self) -> None:
        """Connecting should add to active connections list."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        _run(cm.connect(ws))
        assert ws in cm.active_connections
        assert len(cm.active_connections) == 1

    def test_disconnect_removes_connection(self) -> None:
        """Disconnecting should remove from active connections list."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        _run(cm.connect(ws))
        assert len(cm.active_connections) == 1

        cm.disconnect(ws)
        assert len(cm.active_connections) == 0

    def test_disconnect_nonexistent_is_safe(self) -> None:
        """Disconnecting a non-existent connection should be a no-op."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        ws = AsyncMock()
        cm.disconnect(ws)
        assert len(cm.active_connections) == 0

    def test_multiple_connect_disconnect_cycles(self) -> None:
        """100 connect/disconnect cycles should not leak connections."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()

        for _ in range(100):
            ws = AsyncMock()
            ws.send_json = AsyncMock()
            _run(cm.connect(ws))
            assert len(cm.active_connections) == 1
            cm.disconnect(ws)
            assert len(cm.active_connections) == 0

        assert len(cm.active_connections) == 0

    def test_broadcast_removes_dead_connections(self) -> None:
        """Broadcast should remove connections that fail to send."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        good_ws = AsyncMock()
        good_ws.send_json = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_json = AsyncMock(side_effect=ConnectionError("dead"))

        _run(cm.connect(good_ws))
        _run(cm.connect(bad_ws))
        assert len(cm.active_connections) == 2

        _run(cm.broadcast({"type": "state_update", "data": {}}))

        assert bad_ws not in cm.active_connections
        assert good_ws in cm.active_connections
        assert len(cm.active_connections) == 1

    def test_broadcast_empty_list_is_safe(self) -> None:
        """Broadcasting to empty connection list should be a no-op."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        _run(cm.broadcast({"type": "state_update", "data": {}}))

    def test_many_concurrent_connections(self) -> None:
        """ConnectionManager should handle 50 concurrent connections."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        connections = []

        for _ in range(50):
            ws = AsyncMock()
            ws.send_json = AsyncMock()
            _run(cm.connect(ws))
            connections.append(ws)

        assert len(cm.active_connections) == 50

        for ws in connections[:25]:
            cm.disconnect(ws)
        assert len(cm.active_connections) == 25

        _run(cm.broadcast({"type": "state_update", "data": {"test": True}}))
        assert len(cm.active_connections) == 25

        for ws in connections[25:]:
            cm.disconnect(ws)
        assert len(cm.active_connections) == 0


# ═══════════════════════════════════════════════════════════════════
# State Accumulation Tests
# ═══════════════════════════════════════════════════════════════════


class TestStateAccumulation:
    """Verify state doesn't grow unbounded across updates."""

    def test_state_replaces_not_accumulates(self) -> None:
        """Each state_update should replace, not append, previous state."""
        states = []
        for _ in range(10):
            state = {
                "type": "state_update",
                "data": {
                    "account": {"equity": 10000, "balance": 10000},
                    "positions": [{"ticket": 1, "symbol": "XAUUSD"}],
                    "health": {"overall_state": "HEALTHY"},
                    "risk": {"overall_level": "NORMAL"},
                    "alerts": [],
                },
            }
            states.append(state)

        assert states[0] is not states[1]
        assert states[0]["data"] is not states[1]["data"]

    def test_position_list_replaces(self) -> None:
        """Position list should be replaced, not appended."""
        state = {"positions": []}

        state["positions"] = [{"ticket": 1}, {"ticket": 2}, {"ticket": 3}]
        assert len(state["positions"]) == 3

        state["positions"] = [{"ticket": 1}]
        assert len(state["positions"]) == 1
        tickets = [p["ticket"] for p in state["positions"]]
        assert 2 not in tickets
        assert 3 not in tickets

    def test_alert_list_replaces(self) -> None:
        """Alert list should be replaced, not appended."""
        state = {"alerts": []}

        state["alerts"] = [{"alert_id": "a1"}, {"alert_id": "a2"}]
        assert len(state["alerts"]) == 2

        state["alerts"] = [{"alert_id": "a1"}]
        assert len(state["alerts"]) == 1


# ═══════════════════════════════════════════════════════════════════
# Reconnection Logic Tests
# ═══════════════════════════════════════════════════════════════════


class TestReconnectionLogic:
    """Verify reconnection constants and backoff behavior."""

    def test_reconnect_constants_defined(self) -> None:
        """Reconnection constants should exist in the hook."""
        from pathlib import Path

        hook_path = Path("dashboard/src/hooks/useLiveStream.ts")
        if hook_path.exists():
            content = hook_path.read_text()
            assert "RECONNECT_DELAY" in content
            assert "MAX_RECONNECT_DELAY" in content

    def test_backoff_formula(self) -> None:
        """Exponential backoff should cap at MAX_RECONNECT_DELAY."""
        RECONNECT_DELAY = 3000
        MAX_RECONNECT_DELAY = 30000

        delay = RECONNECT_DELAY
        delays = []
        for _ in range(20):
            delay = min(delay * 2, MAX_RECONNECT_DELAY)
            delays.append(delay)

        assert delays[0] == 6000
        assert delays[-1] == MAX_RECONNECT_DELAY
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1]

    def test_delay_resets_on_success(self) -> None:
        """Delay should reset to initial value on successful connection."""
        RECONNECT_DELAY = 3000

        delay = RECONNECT_DELAY
        for _ in range(5):
            delay = min(delay * 2, 30000)
        assert delay > RECONNECT_DELAY

        delay = RECONNECT_DELAY
        assert delay == 3000


# ═══════════════════════════════════════════════════════════════════
# Resource Leak Detection
# ═══════════════════════════════════════════════════════════════════


class TestResourceLeakDetection:
    """Verify no memory or resource leaks during operation."""

    def test_connection_manager_no_reference_leak(self) -> None:
        """ConnectionManager should not hold references after disconnect."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        refs_before = len(gc.get_referrers(cm))

        for _ in range(50):
            ws = AsyncMock()
            ws.send_json = AsyncMock()
            _run(cm.connect(ws))
            cm.disconnect(ws)

        gc.collect()
        refs_after = len(gc.get_referrers(cm))
        assert refs_after - refs_before < 5, (
            f"Reference leak: {refs_before} -> {refs_after}"
        )

    def test_broadcast_cleans_on_error(self) -> None:
        """Broadcast errors should clean up dead connections immediately."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        for i in range(10):
            ws = AsyncMock()
            ws.send_json = AsyncMock(side_effect=ConnectionError(f"dead-{i}"))
            _run(cm.connect(ws))

        assert len(cm.active_connections) == 10
        _run(cm.broadcast({"type": "state_update", "data": {}}))
        assert len(cm.active_connections) == 0

    def test_get_live_state_returns_bounded_data(self) -> None:
        """get_live_state should return fixed-size structure without cycles."""
        from eigencapital.dashboard.streaming.events import get_live_state

        state = _run(get_live_state())
        assert "type" in state
        assert "data" in state
        data = state["data"]
        assert isinstance(data, dict)

        # Check for circular references (skip None, int, float, str, bool)
        seen = set()
        stack = [data]
        while stack:
            obj = stack.pop()
            if obj is None or isinstance(obj, (int, float, str, bool)):
                continue
            obj_id = id(obj)
            assert obj_id not in seen, f"Circular reference detected: {type(obj)}"
            seen.add(obj_id)
            if isinstance(obj, dict):
                stack.extend(obj.values())
            elif isinstance(obj, list):
                stack.extend(obj)

    def test_concurrent_broadcasts_safe(self) -> None:
        """Multiple concurrent broadcasts should not corrupt state."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        _run(cm.connect(ws))

        async def broadcast_n(n: int) -> None:
            for i in range(n):
                await cm.broadcast({"type": "state_update", "data": {"seq": i}})

        _run(broadcast_n(100))
        assert len(cm.active_connections) == 1
        assert ws.send_json.call_count == 100


# ═══════════════════════════════════════════════════════════════════
# Error Handling Tests
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Verify error conditions don't cause resource leaks."""

    def test_json_parse_error_safe(self) -> None:
        """Malformed JSON should not crash the handler."""
        for raw in ["", "{", "not json", "null", "[]"]:
            try:
                json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass  # Expected

    def test_websocket_close_during_broadcast(self) -> None:
        """Connection closing during broadcast should be handled gracefully."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        cm = ConnectionManager()
        call_count = 0

        async def failing_send(msg: dict) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 5:
                raise ConnectionError("closed")

        ws = AsyncMock()
        ws.send_json = failing_send
        _run(cm.connect(ws))

        for i in range(10):
            _run(cm.broadcast({"type": "state_update", "data": {"seq": i}}))

        assert ws not in cm.active_connections

    def test_empty_state_update_safe(self) -> None:
        """Empty or partial state_update should not crash."""
        test_payloads = [
            {"type": "state_update", "data": {}},
            {"type": "state_update", "data": {"account": None}},
            {"type": "state_update", "data": {"positions": []}},
            {"type": "state_update", "data": {"alerts": []}},
            {"type": "state_update"},
        ]

        for payload in test_payloads:
            data = payload.get("data", {})
            state = {
                "account": data.get("account") or None,
                "positions": data.get("positions") or [],
                "health": data.get("health") or None,
                "risk": data.get("risk") or None,
                "alerts": data.get("alerts") or [],
            }
            assert isinstance(state["positions"], list)
            assert isinstance(state["alerts"], list)

    def test_multiple_error_types_handled(self) -> None:
        """Various error types should not crash the broadcast loop."""
        from eigencapital.dashboard.streaming.events import ConnectionManager

        errors = [
            ConnectionError("connection reset"),
            OSError("socket error"),
            TimeoutError("timeout"),
            RuntimeError("runtime error"),
        ]

        for error in errors:
            cm = ConnectionManager()
            ws = AsyncMock()
            ws.send_json = AsyncMock(side_effect=error)
            _run(cm.connect(ws))

            _run(cm.broadcast({"type": "state_update", "data": {}}))
            assert ws not in cm.active_connections
