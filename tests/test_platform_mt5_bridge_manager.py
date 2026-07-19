"""Tests for eigencapital.platform.mt5_bridge_manager.

All tests mock the strategy, TCP sockets, and process management to ensure
deterministic results without requiring a real MT5 terminal or bridge.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from eigencapital.platform.mt5_bridge_manager import (
    BridgeManagerConfig,
    MT5BridgeManager,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_strategy():
    """Create a mocked MT5LaunchStrategy with canned responses."""
    strategy = mock.MagicMock()
    strategy.display_name = "MockStrategy"
    strategy.detect_terminal.return_value = Path("/fake/terminal64.exe")
    strategy.is_terminal_running.return_value = False
    strategy.launch_terminal.return_value = mock.Mock(pid=11111)
    strategy.launch_bridge.return_value = mock.Mock(pid=22222)
    strategy.environment.return_value = mock.Mock(terminal_exe=Path("/fake/terminal64.exe"))
    return strategy


@pytest.fixture
def mgr(mock_strategy):
    """Create a MT5BridgeManager with a mocked strategy and zero delays."""
    cfg = BridgeManagerConfig(
        terminal_timeout=0.01,
        bridge_timeout=0.01,
        watchdog_interval=0.05,
        heartbeat_interval=0.05,
        max_restarts=3,
    )
    return MT5BridgeManager(config=cfg, strategy=mock_strategy)


@pytest.fixture(autouse=True)
def _no_delays():
    """Prevent actual time.sleep calls in all tests."""
    with mock.patch("time.sleep"):
        yield


# ── BridgeManagerConfig ──────────────────────────────────────────────────────


class TestBridgeManagerConfig:
    def test_default_values(self):
        cfg = BridgeManagerConfig()
        assert cfg.bridge_host == "127.0.0.1"
        assert cfg.bridge_port == 9879
        assert cfg.health_port == 9880
        assert cfg.heartbeat_interval == 15.0
        assert cfg.watchdog_interval == 30.0
        assert cfg.max_restarts == 10
        assert cfg.auto_start_terminal is True
        assert cfg.auto_start_bridge is True

    def test_custom_values(self):
        cfg = BridgeManagerConfig(
            bridge_host="0.0.0.0",
            bridge_port=5555,
            max_restarts=5,
            auto_start_bridge=False,
        )
        assert cfg.bridge_host == "0.0.0.0"
        assert cfg.bridge_port == 5555
        assert cfg.max_restarts == 5
        assert cfg.auto_start_bridge is False


# ── Constructor ──────────────────────────────────────────────────────────────


class TestConstructor:
    def test_default_config_and_strategy(self):
        """Using no args creates default config and real strategy (via get_strategy)."""
        mgr = MT5BridgeManager(config=BridgeManagerConfig(terminal_timeout=0.01, bridge_timeout=0.01))
        assert mgr.config.bridge_port == 9879
        assert mgr.strategy is not None
        assert mgr.shutdown is not None

    def test_custom_strategy_and_shutdown(self, mock_strategy):
        shutdown = mock.Mock()
        shutdown.is_set.return_value = False
        mgr = MT5BridgeManager(
            config=BridgeManagerConfig(),
            strategy=mock_strategy,
            shutdown=shutdown,
        )
        assert mgr.strategy is mock_strategy
        assert mgr.shutdown is shutdown

    def test_not_started_after_init(self, mgr):
        assert mgr._started is False
        assert mgr._terminal_proc is None
        assert mgr._bridge_proc is None
        assert mgr._restart_count == 0


# ── start() ──────────────────────────────────────────────────────────────────


class TestStart:
    def test_launches_terminal_and_bridge(self, mgr, mock_strategy):
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                result = mgr.start()
        assert result is True
        assert mgr._started is True
        mock_strategy.launch_terminal.assert_called_once()
        mock_strategy.launch_bridge.assert_called_once()

    def test_skips_terminal_when_already_running(self, mgr, mock_strategy):
        mock_strategy.is_terminal_running.return_value = True
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                result = mgr.start()
        assert result is True
        mock_strategy.launch_terminal.assert_not_called()
        mock_strategy.launch_bridge.assert_called_once()

    def test_skips_terminal_when_not_found(self, mgr, mock_strategy):
        mock_strategy.detect_terminal.return_value = None
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                result = mgr.start()
        assert result is True
        mock_strategy.launch_terminal.assert_not_called()

    def test_logs_warning_on_bridge_timeout(self, mgr, mock_strategy):
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=False):
            with mock.patch.object(Path, "exists", return_value=True):
                result = mgr.start()
        assert result is True  # start() returns True even if bridge doesn't become ready

    def test_auto_start_terminal_false(self, mgr, mock_strategy):
        mgr.config.auto_start_terminal = False
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                result = mgr.start()
        assert result is True
        mock_strategy.detect_terminal.assert_not_called()
        mock_strategy.launch_terminal.assert_not_called()
        mock_strategy.launch_bridge.assert_called_once()

    def test_auto_start_bridge_false(self, mgr, mock_strategy):
        mgr.config.auto_start_bridge = False
        result = mgr.start()
        assert result is True
        mock_strategy.launch_bridge.assert_not_called()

    def test_bridge_script_not_found(self, mgr, mock_strategy):
        with mock.patch.object(Path, "exists", return_value=False):
            result = mgr.start()
        assert result is True
        mock_strategy.launch_bridge.assert_not_called()

    def test_idempotent(self, mgr):
        """Calling start() twice should be a no-op on the second call."""
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                mgr.start()
                mgr.start()  # second call
        # internal started flag ensures we don't re-launch
        assert mgr._started is True


# ── stop() ──────────────────────────────────────────────────────────────────


class TestStop:
    def test_stops_bridge_then_terminal(self, mgr):
        bridge_proc = mock.Mock()
        terminal_proc = mock.Mock()
        mgr._bridge_proc = bridge_proc
        mgr._terminal_proc = terminal_proc
        mgr._started = True

        mgr.stop()
        assert mgr._started is False
        bridge_proc.terminate.assert_called_once()
        terminal_proc.terminate.assert_called_once()

    def test_handles_no_processes(self, mgr):
        """Stopping with no bridge or terminal processes should not raise."""
        mgr._started = True
        mgr.stop()  # should not raise
        assert mgr._started is False

    def test_kill_on_terminate_failure(self, mgr):
        """If terminate() fails, should fall back to kill()."""
        bridge_proc = mock.Mock()
        bridge_proc.terminate.side_effect = Exception("terminate failed")
        bridge_proc.kill.return_value = None
        mgr._bridge_proc = bridge_proc
        mgr._started = True

        mgr.stop()
        bridge_proc.kill.assert_called_once()
        bridge_proc.terminate.assert_called_once()


# ── ensure_running() ─────────────────────────────────────────────────────────


class TestEnsureRunning:
    def test_calls_start_if_not_started(self, mgr):
        with mock.patch.object(mgr, "start", return_value=True) as mock_start:
            result = mgr.ensure_running()
        assert result is True
        mock_start.assert_called_once()

    def test_healthy_heartbeat_resets_restart_count(self, mgr):
        mgr._started = True
        mgr._restart_count = 5
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=True):
            result = mgr.ensure_running()
        assert result is True
        assert mgr._restart_count == 0

    def test_restarts_on_unhealthy_heartbeat(self, mgr, mock_strategy):
        mgr._started = True
        mgr._bridge_proc = mock.Mock()
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
                with mock.patch.object(Path, "exists", return_value=True):
                    result = mgr.ensure_running()
        assert result is True
        mock_strategy.launch_bridge.assert_called_once()
        assert mgr._restart_count == 0  # reset after successful restart

    def test_hits_max_restarts(self, mgr):
        mgr._started = True
        mgr._restart_count = 99  # above max_restarts (3)
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            result = mgr.ensure_running()
        assert result is False

    def test_skips_bridge_launch_when_script_missing(self, mgr, mock_strategy):
        mgr._started = True
        mgr._bridge_proc = mock.Mock()
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            with mock.patch("eigencapital.platform.process.wait_for_port", return_value=False):
                with mock.patch.object(Path, "exists", return_value=False):
                    result = mgr.ensure_running()
        assert result is False
        mock_strategy.launch_bridge.assert_not_called()

    def test_consecutive_restart_calls(self, mgr, mock_strategy):
        """Ensure sequential calls to ensure_running with an unhealthy state
        each attempt to restart (bounded by max_restarts)."""
        mgr._started = True
        mgr._bridge_proc = mock.Mock()

        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            with mock.patch("eigencapital.platform.process.wait_for_port", return_value=False):
                with mock.patch.object(Path, "exists", return_value=False):
                    r1 = mgr.ensure_running()
                    r2 = mgr.ensure_running()
        assert r1 is False
        assert r2 is False


# ── is_healthy() ────────────────────────────────────────────────────────────


class TestIsHealthy:
    def test_returns_true_when_heartbeat_ok(self, mgr):
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=True):
            assert mgr.is_healthy() is True

    def test_returns_false_when_heartbeat_fails(self, mgr):
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            assert mgr.is_healthy() is False

    def test_handles_exception_gracefully(self, mgr):
        with mock.patch.object(mgr, "_check_bridge_heartbeat", side_effect=RuntimeError("oops")):
            assert mgr.is_healthy() is False


# ── _check_bridge_heartbeat ──────────────────────────────────────────────────


class TestCheckBridgeHeartbeat:
    @staticmethod
    def _make_mock_socket(resp_data: dict) -> mock.Mock:
        """Create a mock socket that returns a proper JSON-RPC response.

        CRITICAL: Must set ``__enter__.return_value = self`` so that
        ``with create_connection() as sock:`` in the source binds *the
        same* mock (not a child mock created by MagicMock's default
        ``__enter__``).
        """
        payload = json.dumps(resp_data).encode()
        header = struct.pack("!I", len(payload))

        sock = mock.MagicMock()
        sock.__enter__.return_value = sock  # <-- critical for with-statement
        sock.recv.side_effect = [header, payload]
        return sock

    def test_heartbeat_success(self, mgr):
        sock = self._make_mock_socket({"id": 1, "result": "pong"})
        with mock.patch("socket.create_connection", return_value=sock):
            result = mgr._check_bridge_heartbeat()
        assert result is True

    def test_heartbeat_missing_result(self, mgr):
        sock = self._make_mock_socket({"id": 1, "error": "not found"})
        with mock.patch("socket.create_connection", return_value=sock):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_heartbeat_connection_refused(self, mgr):
        with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError()):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_heartbeat_timeout(self, mgr):
        with mock.patch("socket.create_connection", side_effect=TimeoutError("timed out")):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_heartbeat_json_decode_error(self, mgr):
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        bad_payload = b"not valid json"
        header = struct.pack("!I", len(bad_payload))
        sock.recv.side_effect = [header, bad_payload]
        with mock.patch("socket.create_connection", return_value=sock):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_heartbeat_short_header(self, mgr):
        """When header recv returns less than 4 bytes, should return False."""
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.side_effect = [b"\x00\x00"]  # only 2 bytes
        with mock.patch("socket.create_connection", return_value=sock):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_heartbeat_empty_chunk(self, mgr):
        """When payload recv returns empty bytes, should return False."""
        payload = json.dumps({"id": 1, "result": "pong"}).encode()
        header = struct.pack("!I", len(payload))
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.side_effect = [header, b""]  # empty chunk while reading payload
        with mock.patch("socket.create_connection", return_value=sock):
            result = mgr._check_bridge_heartbeat()
        assert result is False

    def test_sends_correct_payload(self, mgr):
        sock = self._make_mock_socket({"id": 1, "result": "pong"})
        with mock.patch("socket.create_connection", return_value=sock):
            mgr._check_bridge_heartbeat()

        # Verify the heartbeat request was sent
        sent_data = sock.sendall.call_args[0][0]
        assert b"heartbeat" in sent_data, "heartbeat method in payload"
        assert b"method" in sent_data, "JSON-RPC structure"


# ── _tcp_ping ────────────────────────────────────────────────────────────────


class TestTcpPing:
    def test_ping_success(self, mgr):
        with mock.patch("socket.create_connection") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock.Mock()
            result = mgr._tcp_ping()
        assert result is True

    def test_ping_failure(self, mgr):
        with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError()):
            result = mgr._tcp_ping()
        assert result is False


# ── Watchdog ─────────────────────────────────────────────────────────────────


class TestWatchdog:
    def test_start_watchdog_creates_thread(self, mgr):
        mgr.start_watchdog()
        assert mgr._watchdog_thread is not None
        assert mgr._watchdog_thread.is_alive()
        # Clean up
        mgr.shutdown.trigger()
        mgr._watchdog_thread.join(timeout=1)

    def test_start_watchdog_idempotent(self, mgr):
        mgr.start_watchdog()
        t1 = mgr._watchdog_thread
        mgr.start_watchdog()  # second call
        assert mgr._watchdog_thread is t1  # same thread, not replaced
        mgr.shutdown.trigger()
        mgr._watchdog_thread.join(timeout=1)

    def test_watchdog_restarts_on_consecutive_failures(self, mgr):
        """After 2 consecutive heartbeat failures, watchdog should call ensure_running."""
        with mock.patch.object(mgr, "_check_bridge_heartbeat", return_value=False):
            with mock.patch.object(mgr, "ensure_running", return_value=True) as mock_ensure:
                with mock.patch.object(mgr.shutdown, "wait", return_value=None):
                    with mock.patch.object(mgr.shutdown, "is_set", side_effect=[False, False, True]):
                        mgr._watchdog_loop()
        # ensure_running should be called when consecutive_fails >= 2
        assert mock_ensure.call_count >= 1

    def test_watchdog_resets_on_success(self, mgr):
        """After a successful heartbeat, consecutive_fails should reset and ensure_running not called."""
        with mock.patch.object(mgr, "_check_bridge_heartbeat", side_effect=[True, False, False]):
            with mock.patch.object(mgr, "ensure_running", return_value=True) as mock_ensure:
                with mock.patch.object(mgr.shutdown, "wait", return_value=None):
                    with mock.patch.object(mgr.shutdown, "is_set", side_effect=[False, False, False, True]):
                        mgr._watchdog_loop()
        # First call was True → reset. Two Falses → call ensure_running once (when fails >= 2)
        assert mock_ensure.call_count == 1

    def test_watchdog_exits_on_shutdown(self, mgr):
        """Watchdog loop should exit when shutdown is set."""
        mgr.shutdown.trigger()
        import time
        with mock.patch.object(time, "sleep"):
            mgr._watchdog_loop()
        # No crash — just exits cleanly


# ── _stop_bridge / _stop_terminal ──────────────────────────────────────────


class TestStopProcesses:
    def test_stop_bridge_terminates_and_clears(self, mgr):
        proc = mock.Mock()
        mgr._bridge_proc = proc
        mgr._stop_bridge()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)
        assert mgr._bridge_proc is None

    def test_stop_bridge_kills_on_terminate_failure(self, mgr):
        proc = mock.Mock()
        proc.terminate.side_effect = Exception("fail")
        mgr._bridge_proc = proc
        mgr._stop_bridge()
        proc.kill.assert_called_once()
        assert mgr._bridge_proc is None

    def test_stop_bridge_noop_when_none(self, mgr):
        """Stopping when _bridge_proc is None should not raise."""
        mgr._stop_bridge()  # should not raise
        assert mgr._bridge_proc is None

    def test_stop_terminal_noop_when_none(self, mgr):
        mgr._stop_terminal()  # should not raise

    def test_stop_terminal_terminates_and_clears(self, mgr):
        proc = mock.Mock()
        mgr._terminal_proc = proc
        mgr._stop_terminal()
        proc.terminate.assert_called_once()
        assert mgr._terminal_proc is None


# ── Context manager ──────────────────────────────────────────────────────────


class TestContextManager:
    def test_enter_starts(self, mgr):
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                with mgr as manager:
                    assert manager._started is True

    def test_exit_stops(self, mgr, mock_strategy):
        # Do NOT set _bridge_proc / _terminal_proc here — start() will
        # overwrite them via mock_strategy.launch_bridge / launch_terminal.
        # Instead, capture the process mocks that start() creates.
        with mock.patch("eigencapital.platform.process.wait_for_port", return_value=True):
            with mock.patch.object(Path, "exists", return_value=True):
                with mgr:
                    pass
        assert mgr._started is False
        # start() called launch_bridge which returned a mock; that mock
        # should have been terminated during __exit__ → stop().
        mock_strategy.launch_bridge.return_value.terminate.assert_called_once()
        mock_strategy.launch_terminal.return_value.terminate.assert_called_once()


# ── _resolve_bridge_script ──────────────────────────────────────────────────


class TestResolveBridgeScript:
    def test_returns_path_under_project_root(self):
        path = MT5BridgeManager._resolve_bridge_script()
        assert isinstance(path, Path)
        assert path.name == "mt5_bridge.py"
        assert "paper_trading" in path.parts
        assert "ops" in path.parts
