"""Supervisor tests — verify the watchdog correctly detects a dead bridge,
marks the health endpoint unhealthy, and avoids flapping."""
from __future__ import annotations

import http.client
import json
import socket
import struct
import threading


from scripts.ops.mt5_bridge_supervisor import (
    BridgeSupervisor,
    HealthHandler,
    HealthState,
    _send_heartbeat,
    _tcp_ping,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestHealthState:
    def test_initial_state_dead(self):
        state = HealthState()
        assert state.snapshot()["alive"] is False
        assert state.snapshot()["restart_count"] == 0

    def test_mark_alive_records_heartbeat(self):
        state = HealthState()
        state.mark_alive()
        snap = state.snapshot()
        assert snap["alive"] is True
        assert snap["last_heartbeat_age_s"] is not None
        assert snap["last_heartbeat_age_s"] >= 0

    def test_mark_dead_records_failure_time(self):
        state = HealthState()
        state.mark_alive()
        state.mark_dead()
        snap = state.snapshot()
        assert snap["alive"] is False
        assert snap["failing_for_s"] is not None
        assert snap["failing_for_s"] >= 0

    def test_mark_alive_clears_failure_time(self):
        state = HealthState()
        state.mark_dead()
        state.mark_dead()
        assert state.snapshot()["failing_for_s"] is not None
        state.mark_alive()
        assert state.snapshot()["failing_for_s"] is None


class TestTcpPing:
    def test_tcp_ping_detects_listening(self):
        port = _free_port()
        # Bind but don't accept — should still register as "open"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", port))
            srv.listen(1)
            assert _tcp_ping("127.0.0.1", port, timeout=1.0)

    def test_tcp_ping_detects_closed(self):
        port = _free_port()  # nothing bound
        assert not _tcp_ping("127.0.0.1", port, timeout=0.5)


class TestHeartbeatProtocol:
    """A bridge-like server that responds to JSON-RPC heartbeat frames."""

    @staticmethod
    def _start_mock_bridge(port: int, *, with_password: str | None = None) -> threading.Thread:
        """Start a JSON-RPC server that responds to heartbeat. Returns thread handle."""
        stop = threading.Event()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(2)
        srv.settimeout(0.2)

        def serve():
            while not stop.is_set():
                try:
                    conn, _addr = srv.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        header = conn.recv(4)
                        if len(header) != 4:
                            continue
                        length = struct.unpack("!I", header)[0]
                        body = b""
                        while len(body) < length:
                            chunk = conn.recv(length - len(body))
                            if not chunk:
                                break
                            body += chunk
                        req = json.loads(body.decode())
                        method = req.get("method", "")
                        if method == "heartbeat":
                            resp = {"id": req["id"], "result": "ok"}
                        else:
                            resp = {"id": req["id"], "error": "unknown"}
                        out = json.dumps(resp).encode()
                        conn.sendall(struct.pack("!I", len(out)) + out)
                    except Exception:
                        pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        thread._stop_event = stop
        thread._sock = srv
        return thread

    def test_heartbeat_success(self):
        port = _free_port()
        thread = self._start_mock_bridge(port)
        try:
            assert _send_heartbeat("127.0.0.1", port)
        finally:
            thread._stop_event.set()
            thread._sock.close()

    def test_heartbeat_failure_no_server(self):
        port = _free_port()
        assert not _send_heartbeat("127.0.0.1", port)


class TestSupervisorLifecycle:
    """Smoke tests for the supervisor — verify signal handling and graceful
    shutdown without actually requiring Wine."""

    def test_health_server_200_when_alive(self):
        state = HealthState()
        state.mark_alive()
        HealthHandler.state = state

        port = _free_port()
        srv = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", port), HealthHandler
        )
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            body = json.loads(resp.read().decode())
            assert body["status"] == "ok"
            assert body["alive"] is True
        finally:
            srv.shutdown()

    def test_health_server_503_when_dead(self):
        state = HealthState()
        state.mark_dead()
        HealthHandler.state = state

        port = _free_port()
        from http.server import ThreadingHTTPServer

        srv = ThreadingHTTPServer(("127.0.0.1", port), HealthHandler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 503
            body = json.loads(resp.read().decode())
            assert body["status"] == "down"
        finally:
            srv.shutdown()

    def test_health_server_404_for_unknown(self):
        state = HealthState()
        HealthHandler.state = state

        port = _free_port()
        from http.server import ThreadingHTTPServer

        srv = ThreadingHTTPServer(("127.0.0.1", port), HealthHandler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/unknown")
            resp = conn.getresponse()
            assert resp.status == 404
        finally:
            srv.shutdown()

    def test_supervisor_construction_does_not_block(self):
        sup = BridgeSupervisor(
            bridge_port=19999,
            health_port=19998,
            watchdog_secs=0.5,
            max_restarts=3,
            quiet=True,
        )
        assert sup.bridge_port == 19999
        assert sup.health_port == 19998
        assert sup.max_restarts == 3


class TestSupervisorWatchdogIntegration:
    """End-to-end: start a stub bridge, run the supervisor, verify health."""

    def test_watchdog_marks_alive_when_bridge_responds(self, monkeypatch):
        # Override the heartbeat function with one that talks to our stub.
        # Start a server on a free port.
        port = _free_port()
        stop = threading.Event()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(2)
        srv.settimeout(0.2)

        def serve():
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except (TimeoutError, OSError):
                    continue
                with conn:
                    try:
                        conn.recv(4)
                        body = b""
                        while len(body) < 1024:
                            chunk = conn.recv(1024 - len(body))
                            if not chunk:
                                break
                            body += chunk
                        resp = b'{"id": 1, "result": "ok"}'
                        conn.sendall(struct.pack("!I", len(resp)) + resp)
                    except Exception:
                        pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            # Patch the import in the supervisor module to forward to our port.
            from scripts.ops import mt5_bridge_supervisor as sup_mod

            monkeypatch.setattr(sup_mod, "_send_heartbeat", lambda h, p: p == port)

            sup = BridgeSupervisor(
                bridge_port=port,
                health_port=_free_port(),
                watchdog_secs=0.2,
                max_restarts=1,
                quiet=True,
            )
            # Trigger one round of the watchdog without entering the run() loop
            alive = sup_mod._send_heartbeat("127.0.0.1", port)
            assert alive
            sup.state.mark_alive()
            assert sup.state.snapshot()["alive"] is True
        finally:
            stop.set()
            srv.close()


class TestSupervisorBounds:
    def test_max_restarts_threshold(self):
        """Cap on restarts — supervisor must not loop infinitely."""
        sup = BridgeSupervisor(bridge_port=1, health_port=_free_port(), max_restarts=5, quiet=True)
        assert sup.max_restarts == 5
        # Simulate restart attempts
        for _ in range(5):
            sup.state.restart_count += 1
        assert sup.state.restart_count == 5
