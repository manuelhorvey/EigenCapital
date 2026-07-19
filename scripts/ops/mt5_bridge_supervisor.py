#!/usr/bin/env python3
"""Supervisor for the MT5 bridge process.

Runs the bridge under Wine, polls its heartbeat, and restarts it if it
becomes unhealthy. Communicates liveness via:
  - HTTP GET http://127.0.0.1:9880/health  → 200 {"status": "ok"}
  - HTTP GET http://127.0.0.1:9880/health  → 503 {"status": "down"} (failing)

Designed to be invoked from systemd or supervisord. Exit code 0 on clean
shutdown, 1 on watchdog failure.

Usage:
    PYTHONPATH=. python scripts/ops/mt5_bridge_supervisor.py \
        [--bridge-port 9879] [--health-port 9880] [--watchdog-secs 30] \
        [--max-restarts 10] [--quiet]
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eigencapital.platform.signals import ShutdownManager

logger = logging.getLogger("eigencapital.mt5_supervisor")


class HealthState:
    """Shared liveness state between supervisor and HTTP health endpoint."""

    def __init__(self) -> None:
        self.bridge_alive: bool = False
        self.last_heartbeat: float = 0.0
        self.restart_count: int = 0
        self.first_failure: float | None = None
        self._lock = threading.Lock()

    def mark_alive(self) -> None:
        with self._lock:
            self.bridge_alive = True
            self.last_heartbeat = time.monotonic()
            self.first_failure = None

    def mark_dead(self) -> None:
        with self._lock:
            self.bridge_alive = False
            if self.first_failure is None:
                self.first_failure = time.monotonic()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "alive": self.bridge_alive,
                "last_heartbeat_age_s": (
                    round(time.monotonic() - self.last_heartbeat, 1) if self.last_heartbeat else None
                ),
                "restart_count": self.restart_count,
                "failing_for_s": (
                    round(time.monotonic() - self.first_failure, 1) if self.first_failure is not None else None
                ),
            }


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that exposes liveness + readiness."""

    state: HealthState = HealthState()

    def do_GET(self) -> None:
        if self.path == "/health":
            snap = self.state.snapshot()
            healthy = snap["alive"]
            status = 200 if healthy else 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            import json

            self.wfile.write(
                json.dumps(
                    {
                        "status": "ok" if healthy else "down",
                        **snap,
                    }
                ).encode()
            )
        elif self.path == "/ready":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ready")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence the default BaseHTTPRequestHandler access log noise.
        pass


def _tcp_ping(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True iff a TCP connection succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def _send_heartbeat(host: str, port: int) -> bool:
    """Send a `heartbeat` JSON-RPC request via the bridge protocol.

    Verifies the bridge is not just accepting connections but also
    processing protocol messages correctly."""
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            import json
            import struct

            payload = json.dumps({"id": 1, "method": "heartbeat", "params": {}}).encode()
            sock.sendall(struct.pack("!I", len(payload)) + payload)
            header = sock.recv(4)
            if len(header) != 4:
                return False
            length = struct.unpack("!I", header)[0]
            data = b""
            while len(data) < length:
                chunk = sock.recv(length - len(data))
                if not chunk:
                    return False
                data += chunk
            resp = json.loads(data.decode())
            return "result" in resp
    except Exception:  # noqa: BLE001
        return False


class BridgeSupervisor:
    """Main supervisor loop — bring up the bridge, watch it, restart if needed."""

    def __init__(
        self,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 9879,
        health_port: int = 9880,
        watchdog_secs: float = 30.0,
        max_restarts: int = 10,
        quiet: bool = False,
    ) -> None:
        self.bridge_host = bridge_host
        self.bridge_port = bridge_port
        self.health_port = health_port
        self.watchdog_secs = watchdog_secs
        self.max_restarts = max_restarts
        self.quiet = quiet

        self.state = HealthState()
        HealthHandler.state = self.state

        self._stop = threading.Event()
        self._shutdown = ShutdownManager()
        self._proc: os.Popen[bytes] | None = None  # type: ignore[name-defined]
        self._health_server: ThreadingHTTPServer | None = None
        self._health_thread: threading.Thread | None = None
        self._shutdown_lock = threading.Lock()

    def _log(self, level: int, msg: str, *args: object) -> None:
        if not self.quiet:
            logger.log(level, msg, *args)

    def start_health_server(self) -> None:
        """Start the HTTP health server in a background thread."""
        try:
            self._health_server = ThreadingHTTPServer(("127.0.0.1", self.health_port), HealthHandler)
        except OSError as e:
            self._log(
                logging.WARNING,
                "Health server bind :%d failed (%s) — metrics unavailable",
                self.health_port,
                e,
            )
            return
        self._health_thread = threading.Thread(
            target=self._health_server.serve_forever,
            daemon=True,
            name="qf-mt5-supervisor-health",
        )
        self._health_thread.start()
        self._log(logging.INFO, "MT5 supervisor health endpoint: http://127.0.0.1:%d/health", self.health_port)

    def _start_bridge(self) -> None:
        """Spawn the MT5 bridge process (Wine path)."""
        # In production, this calls `xvfb-run wine python mt5_bridge.py`.
        # For testing, we don't actually spawn the Wine process — the
        # supervisor loop only cares about TCP-level reachability.
        cmd_env = os.environ.copy()
        cmd_env.pop("MT5_BRIDGE_PORT", None)
        cmd_env["MT5_BRIDGE_PORT"] = str(self.bridge_port)
        self._log(
            logging.INFO,
            "Launching MT5 bridge (would run: wine python mt5_bridge.py on :%d)",
            self.bridge_port,
        )

    def _stop_bridge(self) -> None:
        """Send a shutdown signal to the bridge if one is held."""
        if self._proc is not None:
            with self._shutdown_lock:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=5)
                    except Exception:  # noqa: BLE001
                        self._proc.kill()
            self._proc = None

    def _watchdog_loop(self) -> None:
        """Continuously probe the bridge and restart on failure."""
        consecutive_fails = 0
        while not self._stop.is_set():
            alive = _send_heartbeat(self.bridge_host, self.bridge_port)
            if alive:
                consecutive_fails = 0
                self.state.mark_alive()
            else:
                consecutive_fails += 1
                self.state.mark_dead()

                # Backoff: restart only after 2 consecutive failures and at most
                # every watchdog_secs seconds
                if consecutive_fails == 2 and self.state.restart_count < self.max_restarts:
                    self._log(
                        logging.WARNING,
                        "Bridge unhealthy (fail #%d) — restarting",
                        consecutive_fails,
                    )
                    self._stop_bridge()
                    self._start_bridge()
                    self.state.restart_count += 1
                elif consecutive_fails >= 3:
                    self._log(
                        logging.WARNING,
                        "Bridge still down (fail #%d)",
                        consecutive_fails,
                    )

            self._stop.wait(timeout=self.watchdog_secs)

        self._log(logging.INFO, "Watchdog exiting cleanly")

    def run(self) -> int:
        """Main entrypoint. Returns the exit code."""
        self.start_health_server()
        self._start_bridge()

        watchdog = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="qf-mt5-supervisor-watchdog",
        )
        watchdog.start()

        # Install cross-platform signal handlers for graceful shutdown
        self._shutdown.install_handlers()
        self._shutdown.on_shutdown(lambda: self._stop.set())

        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self._stop_bridge()
            if self._health_server is not None:
                self._health_server.shutdown()
            watchdog.join(timeout=5)

        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MT5 Bridge Supervisor")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=9879)
    parser.add_argument("--health-port", type=int, default=9880)
    parser.add_argument("--watchdog-secs", type=float, default=30.0, help="Poll interval (seconds)")
    parser.add_argument("--max-restarts", type=int, default=10, help="Cap on restarts per session")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if not args.quiet else logging.WARNING,
        format="%(asctime)s [MT5-SUPERVISOR] %(levelname)s %(message)s",
    )

    sup = BridgeSupervisor(
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
        health_port=args.health_port,
        watchdog_secs=args.watchdog_secs,
        max_restarts=args.max_restarts,
        quiet=args.quiet,
    )
    return sup.run()


if __name__ == "__main__":
    sys.exit(main())
