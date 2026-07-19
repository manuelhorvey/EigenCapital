"""Platform-agnostic MT5 Bridge Manager.

Combines platform detection (detector) with platform-specific launch
strategies (mt5_strategies) to provide a unified interface for the
MT5 bridge lifecycle:

- Terminal discovery and launch
- Bridge server launch
- Health monitoring (heartbeat + TCP ping)
- Automatic restart on failure
- Graceful shutdown

Usage::

    from eigencapital.platform.mt5_bridge_manager import MT5BridgeManager

    mgr = MT5BridgeManager()
    mgr.start()
    # ... wait ...
    mgr.stop()
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from eigencapital.platform.detector import detect as _detect
from eigencapital.platform.mt5_strategies import MT5LaunchStrategy, get_strategy
from eigencapital.platform.signals import ShutdownManager

logger = logging.getLogger("eigencapital.platform.mt5_bridge_manager")


@dataclass
class BridgeManagerConfig:
    """Configuration for the MT5 Bridge Manager."""

    bridge_host: str = "127.0.0.1"
    bridge_port: int = 9879
    health_port: int = 9880
    heartbeat_interval: float = 15.0
    watchdog_interval: float = 30.0
    max_restarts: int = 10
    terminal_timeout: float = 30.0
    bridge_timeout: float = 30.0
    auto_start_terminal: bool = True
    auto_start_bridge: bool = True


class MT5BridgeManager:
    """Manages the MT5 terminal and bridge lifecycle.

    Uses the Strategy pattern to handle platform-specific launch and
    monitoring, while providing a unified interface for the rest of
    the system.
    """

    def __init__(
        self,
        config: BridgeManagerConfig | None = None,
        strategy: MT5LaunchStrategy | None = None,
        shutdown: ShutdownManager | None = None,
    ) -> None:
        self.config = config or BridgeManagerConfig()
        self.strategy = strategy or get_strategy()
        self.shutdown = shutdown or ShutdownManager()

        self._terminal_proc: subprocess.Popen | None = None  # type: ignore[name-defined]
        self._bridge_proc: subprocess.Popen | None = None  # type: ignore[name-defined]
        self._watchdog_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._restart_count = 0
        self._started = False

        # Bridge script path
        self._bridge_script = self._resolve_bridge_script()

    # ── Public API ─────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the MT5 terminal and bridge.

        Returns True if both started successfully (or were already running).
        """
        if self._started:
            return True

        env = self.strategy.environment()
        logger.info(
            "Starting MT5 Bridge Manager (strategy=%s, terminal=%s)",
            self.strategy.display_name,
            env.terminal_exe,
        )

        # 1. Start terminal
        if self.config.auto_start_terminal:
            terminal_path = self.strategy.detect_terminal()
            if terminal_path is None:
                logger.warning("MT5 terminal not found — bridge will still attempt to connect")
            elif self.strategy.is_terminal_running():
                logger.info("MT5 terminal already running")
            else:
                self._terminal_proc = self.strategy.launch_terminal(terminal_path)
                if self._terminal_proc is not None:
                    # Wait for terminal to initialise
                    time.sleep(min(self.config.terminal_timeout, 5.0))

        # 2. Start bridge
        if self.config.auto_start_bridge:
            if self._bridge_script.exists():
                self._bridge_proc = self.strategy.launch_bridge(self._bridge_script)

                # Wait for bridge to accept connections
                from eigencapital.platform.process import wait_for_port

                if wait_for_port(self.config.bridge_port, self.config.bridge_host, self.config.bridge_timeout):
                    logger.info("MT5 bridge ready on %s:%d", self.config.bridge_host, self.config.bridge_port)
                else:
                    logger.warning("MT5 bridge did not become ready within %.0fs", self.config.bridge_timeout)
            else:
                logger.error("Bridge script not found: %s", self._bridge_script)

        self._started = True
        return True

    def stop(self) -> None:
        """Gracefully stop the MT5 terminal and bridge."""
        logger.info("Stopping MT5 Bridge Manager")

        # Stop bridge first, then terminal (order matters)
        self._stop_bridge()
        self._stop_terminal()
        self._started = False

    def ensure_running(self) -> bool:
        """Check if the bridge is healthy; attempt restart if not.

        Returns True if the bridge is (now) healthy.
        """
        if not self._started:
            return self.start()

        try:
            alive = self._check_bridge_heartbeat()
        except Exception:  # noqa: BLE001
            alive = False

        if alive:
            self._restart_count = 0
            return True

        logger.warning("MT5 bridge is down — attempting restart")
        with self._lock:
            self._restart_count += 1
            if self._restart_count > self.config.max_restarts:
                logger.error("MT5 bridge exceeded max restarts (%d) — giving up", self.config.max_restarts)
                return False

            self._stop_bridge()
            if self.config.auto_start_bridge and self._bridge_script.exists():
                self._bridge_proc = self.strategy.launch_bridge(self._bridge_script)

            from eigencapital.platform.process import wait_for_port

            if wait_for_port(self.config.bridge_port, self.config.bridge_host, timeout=15.0):
                logger.info("MT5 bridge restarted successfully")
                self._restart_count = 0
                return True

            logger.error("MT5 bridge failed to restart (attempt %d/%d)", self._restart_count, self.config.max_restarts)
            return False

    def is_healthy(self) -> bool:
        """Return True if the bridge is responding to heartbeats."""
        try:
            return self._check_bridge_heartbeat()
        except Exception:  # noqa: BLE001
            return False

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _resolve_bridge_script() -> Path:
        """Find the mt5_bridge.py script relative to the project root."""
        from eigencapital.platform.paths import resolve_project_root

        return resolve_project_root() / "paper_trading" / "ops" / "mt5_bridge.py"

    def _check_bridge_heartbeat(self) -> bool:
        """Send a heartbeat JSON-RPC request to the bridge."""
        import json
        import socket
        import struct

        try:
            with socket.create_connection((self.config.bridge_host, self.config.bridge_port), timeout=2.0) as sock:
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
        except (OSError, ConnectionRefusedError, TimeoutError, json.JSONDecodeError):
            return False

    def _tcp_ping(self) -> bool:
        """Quick TCP-level connectivity check."""
        import socket

        try:
            with socket.create_connection((self.config.bridge_host, self.config.bridge_port), timeout=1.0):
                return True
        except (OSError, ConnectionRefusedError, TimeoutError):
            return False

    def _stop_bridge(self) -> None:
        if self._bridge_proc is not None:
            try:
                self._bridge_proc.terminate()
                self._bridge_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._bridge_proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._bridge_proc = None

    def _stop_terminal(self) -> None:
        if self._terminal_proc is not None:
            try:
                self._terminal_proc.terminate()
                self._terminal_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._terminal_proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._terminal_proc = None

    # ── Watchdog ────────────────────────────────────────────────────────

    def start_watchdog(self) -> None:
        """Start a background watchdog thread that monitors bridge health.

        The watchdog runs until shutdown is requested.
        """
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="qf-mt5-watchdog",
        )
        self._watchdog_thread.start()
        logger.info(
            "MT5 watchdog started (interval=%.0fs, max_restarts=%d)",
            self.config.watchdog_interval,
            self.config.max_restarts,
        )

    def _watchdog_loop(self) -> None:
        """Watchdog main loop — check health, restart if needed."""
        consecutive_fails = 0
        while not self.shutdown.is_set():
            alive = self._check_bridge_heartbeat()
            if alive:
                consecutive_fails = 0
            else:
                consecutive_fails += 1

                if consecutive_fails >= 2:
                    logger.warning("MT5 bridge unhealthy (fail #%d) — restarting", consecutive_fails)
                    self.ensure_running()

            self.shutdown.wait(timeout=self.config.watchdog_interval)

    # ── Context manager ─────────────────────────────────────────────────

    def __enter__(self) -> MT5BridgeManager:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        self.stop()
