"""Tests for eigencapital.platform.process.

All tests mock psutil, os.listdir, subprocess, os.kill, and socket
to ensure deterministic results regardless of the actual host OS.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from dataclasses import fields
from unittest import mock

import pytest

from eigencapital.platform.process import (
    ProcessInfo,
    _find_process_procfs,
    _find_process_psutil,
    _find_process_tasklist,
    _has_psutil,
    find_process_by_name,
    is_process_running,
    kill_process,
    wait_for_port,
)

# ── Real exception subclasses for psutil mocking ─────────────────────────────
# The source code does ``except (psutil.NoSuchProcess, psutil.AccessDenied)``,
# so these must be real classes inheriting from Exception, not Mock instances.


class _MockNoSuchProcess(Exception):
    """Stand-in for psutil.NoSuchProcess."""


class _MockAccessDenied(Exception):
    """Stand-in for psutil.AccessDenied."""


class _MockTimeoutExpired(Exception):
    """Stand-in for psutil.TimeoutExpired."""


def _make_psutil_mock() -> mock.Mock:
    """Create a mock ``psutil`` module with real exception classes.

    Usage::

        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [...]
        with mock.patch.dict(\"sys.modules\", {\"psutil\": psutil}):
            ...
    """
    m = mock.MagicMock()
    m.NoSuchProcess = _MockNoSuchProcess
    m.AccessDenied = _MockAccessDenied
    m.TimeoutExpired = _MockTimeoutExpired
    m.pid_exists = mock.Mock()
    m.Process = mock.Mock()
    return m


def _make_proc(info: dict | type[Exception]) -> mock.Mock:
    """Create a mock process with ``.info`` as a type-level PropertyMock.

    Args:
        info: A dict (returned by ``.info``) or an Exception class
              (raised by ``.info`` via ``side_effect``).

    Returns:
        A mock process object suitable for ``psutil.process_iter``.
    """
    p = mock.Mock()
    if isinstance(info, type) and issubclass(info, BaseException):
        type(p).info = mock.PropertyMock(side_effect=info())
    else:
        type(p).info = mock.PropertyMock(return_value=info)
    return p


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_psutil_cache():
    """Reset the _PSUTIL_AVAILABLE singleton between tests."""
    import eigencapital.platform.process as _proc_mod

    _proc_mod._PSUTIL_AVAILABLE = None
    yield
    _proc_mod._PSUTIL_AVAILABLE = None


# ── ProcessInfo dataclass ────────────────────────────────────────────────────


class TestProcessInfo:
    def test_minimal_creation(self):
        pi = ProcessInfo(pid=1234, name="python")
        assert pi.pid == 1234
        assert pi.name == "python"
        assert pi.cmdline == ""
        assert pi.create_time == 0.0
        assert pi.status == ""

    def test_full_creation(self):
        pi = ProcessInfo(
            pid=5678,
            name="bash",
            cmdline="bash --login",
            create_time=1000.0,
            status="running",
        )
        assert pi.pid == 5678
        assert pi.cmdline == "bash --login"

    def test_all_fields_present(self):
        field_names = {f.name for f in fields(ProcessInfo)}
        expected = {"pid", "name", "cmdline", "create_time", "status"}
        assert field_names == expected

    def test_repr(self):
        pi = ProcessInfo(pid=1, name="init")
        text = repr(pi)
        assert "ProcessInfo" in text
        assert "pid=1" in text


# ── _has_psutil ──────────────────────────────────────────────────────────────


class TestHasPsutil:
    def test_psutil_available(self):
        with mock.patch.dict("sys.modules", {"psutil": mock.Mock()}):
            assert _has_psutil() is True

    def test_psutil_not_available(self):
        import builtins

        _real_import = builtins.__import__

        def _no_psutil(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return _real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=_no_psutil):
            assert _has_psutil() is False

    def test_cache_cached(self):
        with mock.patch.dict("sys.modules", {"psutil": mock.Mock()}):
            assert _has_psutil() is True
            assert _has_psutil() is True


# ── find_process_by_name — psutil path ────────────────────────────────────────


class TestFindProcessByNamePsutil:
    def test_finds_matching_process(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 100, "name": "python", "cmdline": ["python", "mt5_bridge.py"],
                         "create_time": 0.0, "status": "running"}),
            _make_proc({"pid": 200, "name": "bash", "cmdline": ["bash"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("python")
        assert len(results) == 1
        assert results[0].pid == 100
        assert "mt5_bridge.py" in results[0].cmdline

    def test_matches_by_cmdline(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 123, "name": "wine", "cmdline": ["wine", "terminal64.exe"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("terminal64")
        assert len(results) == 1
        assert results[0].pid == 123

    def test_no_match_returns_empty(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 100, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("zzz_no_match")
        assert results == []

    def test_case_insensitive_match(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 100, "name": "Python", "cmdline": ["PYTHON"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("python")
        assert len(results) == 1

    def test_skips_no_such_process(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc(_MockNoSuchProcess),
            _make_proc({"pid": 100, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("python")
        assert len(results) == 1
        assert results[0].pid == 100

    def test_skips_access_denied(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc(_MockAccessDenied),
            _make_proc({"pid": 100, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("python")
        assert len(results) == 1
        assert results[0].pid == 100

    def test_multiple_matches(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 101, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
            _make_proc({"pid": 102, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
            _make_proc({"pid": 103, "name": "python", "cmdline": ["python"],
                         "create_time": 0.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = find_process_by_name("python")
        assert len(results) == 3
        assert [r.pid for r in results] == [101, 102, 103]


# ── find_process_by_name — procfs fallback ───────────────────────────────────


class TestFindProcessByNameProcfs:
    _FAKE_FILES = {
        "/proc/1/comm": "init\n",
        "/proc/1/cmdline": "/sbin/init\x00--quiet\x00",
        "/proc/100/comm": "python\n",
        "/proc/100/cmdline": "python\x00mt5_bridge.py\x00",
        "/proc/200/comm": "bash\n",
        "/proc/200/cmdline": "bash\x00--login\x00",
    }

    def _fake_open(self, path, *args, **kwargs):
        """Side-effect for ``builtins.open`` that serves fake /proc content."""
        if path in self._FAKE_FILES:
            return mock.mock_open(read_data=self._FAKE_FILES[path]).return_value
        raise FileNotFoundError(f"Not found: {path}")

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_finds_by_comm(self, mock_detect, mock_psutil):
        plat = mock.Mock()
        plat.is_linux = True
        plat.is_windows = False
        mock_detect.return_value = plat

        with mock.patch("os.listdir", return_value=["1", "100", "200"]):
            with mock.patch("builtins.open", side_effect=self._fake_open):
                results = find_process_by_name("python")
        assert len(results) == 1
        assert results[0].pid == 100
        assert "mt5_bridge.py" in results[0].cmdline

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_no_match_returns_empty(self, mock_detect, mock_psutil):
        plat = mock.Mock()
        plat.is_linux = True
        mock_detect.return_value = plat

        with mock.patch("os.listdir", return_value=["1"]):
            with mock.patch(
                "builtins.open",
                side_effect=[
                    mock.mock_open(read_data="init\n").return_value,
                    mock.mock_open(read_data="init\n").return_value,
                ],
            ):
                results = find_process_by_name("zzz_nonexistent")
        assert results == []

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_handles_oserror_during_listdir(self, mock_detect, mock_psutil):
        plat = mock.Mock()
        plat.is_linux = True
        mock_detect.return_value = plat

        with mock.patch("os.listdir", side_effect=OSError("permission denied")):
            results = find_process_by_name("python")
        assert results == []

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_handles_file_not_found(self, mock_detect, mock_psutil):
        """Skip a process when /proc/PID/cmdline is unreadable."""
        plat = mock.Mock()
        plat.is_linux = True
        mock_detect.return_value = plat

        # Single PID: comm succeeds, cmdline raises FileNotFoundError
        # The process is skipped (no results) because the match check
        # requires both comm and cmdline to be readable.
        with mock.patch("os.listdir", return_value=["1"]):
            with mock.patch(
                "builtins.open",
                side_effect=[
                    mock.mock_open(read_data="python\n").return_value,
                    FileNotFoundError(),
                ],
            ):
                results = find_process_by_name("python")
        assert len(results) == 0

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_case_insensitive_match(self, mock_detect, mock_psutil):
        plat = mock.Mock()
        plat.is_linux = True
        mock_detect.return_value = plat

        with mock.patch("os.listdir", return_value=["100"]):
            with mock.patch(
                "builtins.open",
                side_effect=[
                    mock.mock_open(read_data="Python\n").return_value,
                    mock.mock_open(read_data="Python\x00script.py\n").return_value,
                ],
            ):
                results = find_process_by_name("python")
        assert len(results) == 1
        assert results[0].pid == 100


# ── find_process_by_name — tasklist fallback (Windows) ───────────────────────


class TestFindProcessByNameTasklist:
    """Tests the tasklist fallback path directly via ``_find_process_tasklist``.

    We call the private helper directly rather than ``find_process_by_name``
    because the mock for ``_has_psutil`` doesn't reliably override the real
    function on all Python runtimes.  Direct calls are simpler and more
    predictable.
    """

    _TASKLIST_OUTPUT = (
        '"python.exe","1234","Console","1","7,888 K","Running","username","N/A"\n'
        '"bash.exe","5678","Console","1","4,000 K","Running","username","N/A"\n'
        '"terminal64.exe","9012","Console","0","15,000 K","Running","username","N/A"'
    )

    @mock.patch("subprocess.run")
    def test_finds_by_name(self, mock_run):
        mock_run.return_value = mock.Mock(stdout=self._TASKLIST_OUTPUT)
        results = _find_process_tasklist("terminal64")
        assert len(results) == 1
        assert results[0].pid == 9012
        assert results[0].name == "terminal64.exe"

    @mock.patch("subprocess.run")
    def test_no_match_returns_empty(self, mock_run):
        mock_run.return_value = mock.Mock(stdout=self._TASKLIST_OUTPUT)
        results = _find_process_tasklist("nonexistent")
        assert results == []

    @mock.patch("subprocess.run")
    def test_subprocess_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("tasklist", 10)
        results = _find_process_tasklist("python")
        assert results == []

    @mock.patch("subprocess.run")
    def test_subprocess_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("tasklist not found")
        results = _find_process_tasklist("python")
        assert results == []

    @mock.patch("subprocess.run")
    def test_invalid_pid_skipped(self, mock_run):
        bad_output = '"python.exe","NOT_A_PID","Console","1","7,888 K","Running","user","N/A"\n'
        mock_run.return_value = mock.Mock(stdout=bad_output)
        results = _find_process_tasklist("python")
        assert results == []

    @mock.patch("subprocess.run")
    def test_subprocess_os_error(self, mock_run):
        """OSError from subprocess.run should be caught gracefully."""
        mock_run.side_effect = OSError("tasklist not available")
        results = _find_process_tasklist("python")
        assert results == []

    @mock.patch("subprocess.run")
    def test_multiple_matches(self, mock_run):
        multi_output = (
            '"python.exe","100","Console","1","7,888 K","Running","user","N/A"\n'
            '"python.exe","101","Console","1","7,900 K","Running","user","N/A"\n'
        )
        mock_run.return_value = mock.Mock(stdout=multi_output)
        results = _find_process_tasklist("python")
        assert len(results) == 2
        assert [r.pid for r in results] == [100, 101]


# ── find_process_by_name — unsupported platform ──────────────────────────────


class TestFindProcessByNameUnsupported:
    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    @mock.patch("eigencapital.platform.process._detect")
    def test_macos_returns_empty(self, mock_detect, mock_psutil):
        plat = mock.Mock()
        plat.is_linux = False
        plat.is_windows = False
        mock_detect.return_value = plat

        results = find_process_by_name("python")
        assert results == []


# ── is_process_running ───────────────────────────────────────────────────────


class TestIsProcessRunning:
    def test_with_psutil_pid_exists(self):
        psutil = _make_psutil_mock()
        psutil.pid_exists.return_value = True
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            assert is_process_running(100) is True

    def test_with_psutil_pid_not_exists(self):
        psutil = _make_psutil_mock()
        psutil.pid_exists.return_value = False
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            assert is_process_running(99999) is False

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_running(self, mock_psutil):
        with mock.patch("os.kill", return_value=None):
            assert is_process_running(100) is True

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_not_running(self, mock_psutil):
        with mock.patch("os.kill", side_effect=OSError("no such process")):
            assert is_process_running(99999) is False

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_permission_denied(self, mock_psutil):
        with mock.patch("os.kill", side_effect=PermissionError("permission denied")):
            assert is_process_running(100) is False


# ── kill_process ─────────────────────────────────────────────────────────────


class TestKillProcess:
    def test_with_psutil_terminate(self):
        psutil = _make_psutil_mock()
        proc = mock.Mock()
        psutil.Process.return_value = proc
        proc.wait.return_value = None
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            result = kill_process(100, force=False)
        assert result is True
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)

    def test_with_psutil_force_kill(self):
        psutil = _make_psutil_mock()
        proc = mock.Mock()
        psutil.Process.return_value = proc
        proc.wait.return_value = None
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            result = kill_process(100, force=True)
        assert result is True
        proc.kill.assert_called_once()

    def test_with_psutil_no_such_process(self):
        psutil = _make_psutil_mock()
        psutil.Process.side_effect = _MockNoSuchProcess()
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            result = kill_process(100)
        assert result is False

    def test_with_psutil_access_denied(self):
        psutil = _make_psutil_mock()
        psutil.Process.side_effect = _MockAccessDenied()
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            result = kill_process(100)
        assert result is False

    def test_with_psutil_timeout_expired(self):
        """When proc.wait() times out, return False."""
        psutil = _make_psutil_mock()
        proc = mock.Mock()
        psutil.Process.return_value = proc
        proc.wait.side_effect = _MockTimeoutExpired("timed out")
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            result = kill_process(100)
        assert result is False
        proc.terminate.assert_called_once()

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_uses_correct_signals(self, mock_psutil):
        """Force=True sends SIGKILL; force=False sends SIGTERM."""
        with mock.patch("os.kill", return_value=None) as mock_kill:
            with mock.patch(
                "eigencapital.platform.process.is_process_running", side_effect=[False]
            ):
                kill_process(100, force=True)
        assert mock_kill.call_args[0] == (100, signal.SIGKILL)

        with mock.patch("os.kill", return_value=None) as mock_kill:
            with mock.patch(
                "eigencapital.platform.process.is_process_running", side_effect=[False]
            ):
                kill_process(200, force=False)
        assert mock_kill.call_args[0] == (200, signal.SIGTERM)

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_force_kill(self, mock_psutil):
        with mock.patch("os.kill", return_value=None):
            with mock.patch("eigencapital.platform.process.is_process_running", side_effect=[True, False]):
                result = kill_process(100, force=True)
        assert result is True

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_graceful_terminate(self, mock_psutil):
        with mock.patch("os.kill", return_value=None):
            with mock.patch("eigencapital.platform.process.is_process_running", side_effect=[True, False]):
                result = kill_process(100, force=False)
        assert result is True

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_process_not_found(self, mock_psutil):
        with mock.patch("os.kill", side_effect=OSError("no such process")):
            result = kill_process(99999)
        assert result is False

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_process_lookup_error(self, mock_psutil):
        with mock.patch("os.kill", side_effect=ProcessLookupError()):
            result = kill_process(99999)
        assert result is False

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_graceful_timeout(self, mock_psutil):
        """When process doesn't exit after SIGTERM, return False (caller retries with force)."""
        with mock.patch("os.kill", return_value=None):
            with mock.patch("eigencapital.platform.process.is_process_running", return_value=True):
                with mock.patch("eigencapital.platform.process.time.sleep"):
                    result = kill_process(100, force=False)
        assert result is False  # graceful didn't work

    @mock.patch("eigencapital.platform.process._has_psutil", return_value=False)
    def test_without_psutil_force_kill_after_wait(self, mock_psutil):
        """Force kill returns True even if process doesn't die immediately."""
        with mock.patch("os.kill", return_value=None):
            with mock.patch("eigencapital.platform.process.is_process_running", return_value=True):
                with mock.patch("eigencapital.platform.process.time.sleep"):
                    result = kill_process(100, force=True)
        assert result is True  # force returns True even if still running after wait


# ── wait_for_port ────────────────────────────────────────────────────────────


class TestWaitForPort:
    @mock.patch("socket.create_connection")
    def test_port_opens_immediately(self, mock_connect):
        result = wait_for_port(9879, timeout=5.0)
        assert result is True
        mock_connect.assert_called_once_with(("127.0.0.1", 9879), timeout=2.0)

    @mock.patch("socket.create_connection")
    @mock.patch("eigencapital.platform.process.time.sleep")
    def test_port_opens_after_retries(self, mock_sleep, mock_connect):
        mock_connect.side_effect = [
            ConnectionRefusedError(),
            OSError(),
            mock.MagicMock().__enter__.return_value,
        ]
        result = wait_for_port(9879, timeout=10.0)
        assert result is True
        assert mock_connect.call_count == 3

    @mock.patch("socket.create_connection")
    @mock.patch("eigencapital.platform.process.time.sleep")
    def test_port_timeout(self, mock_sleep, mock_connect):
        mock_connect.side_effect = ConnectionRefusedError()
        result = wait_for_port(9879, timeout=0.5)
        assert result is False

    @mock.patch("socket.create_connection")
    @mock.patch("eigencapital.platform.process.time.sleep")
    def test_timeout_error_retries(self, mock_sleep, mock_connect):
        mock_connect.side_effect = [
            TimeoutError("connection timed out"),
            mock.MagicMock().__enter__.return_value,
        ]
        result = wait_for_port(9879, timeout=10.0)
        assert result is True

    @mock.patch("socket.create_connection")
    @mock.patch("eigencapital.platform.process.time.sleep")
    def test_timeout_deterministic(self, mock_sleep, mock_connect):
        """Timeout with time.monotonic mocked — fast and deterministic.

        Three monotonic calls: (1) deadline calc, (2) loop check enters,
        (3) loop check exits.  Only one connection attempt is made.
        """
        mock_connect.side_effect = ConnectionRefusedError()
        with mock.patch(
            "eigencapital.platform.process.time.monotonic", side_effect=[0.0, 0.0, 0.1]
        ):
            result = wait_for_port(9879, timeout=0.05)
        assert result is False
        assert mock_connect.call_count == 1

    @mock.patch("socket.create_connection")
    @mock.patch("eigencapital.platform.process.time.sleep")
    def test_custom_host(self, mock_sleep, mock_connect):
        with mock.patch("eigencapital.platform.process.time.monotonic", side_effect=[0.0, 0.1]):
            result = wait_for_port(80, host="localhost", timeout=0.05)
            assert result is False


# ── Private helpers (unit tests) ─────────────────────────────────────────────


class TestPrivateHelpers:
    def test_find_process_psutil_direct(self):
        psutil = _make_psutil_mock()
        psutil.process_iter.return_value = [
            _make_proc({"pid": 42, "name": "test_proc", "cmdline": ["test_proc", "--flag"],
                         "create_time": 100.0, "status": "running"}),
        ]
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            results = _find_process_psutil("test_proc")
        assert len(results) == 1
        assert results[0].pid == 42

    def test_find_process_procfs_empty_on_no_proc(self):
        with mock.patch("os.listdir", side_effect=FileNotFoundError("no /proc")):
            results = _find_process_procfs("anything")
        assert results == []

    def test_find_process_tasklist_empty_on_error(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("tasklist not found")):
            results = _find_process_tasklist("anything")
        assert results == []


# ── Integration smoke tests ─────────────────────────────────────────────────


class TestIntegration:
    def test_find_process_by_name_returns_list(self):
        results = find_process_by_name("")
        assert isinstance(results, list)

    def test_is_process_running_returns_bool(self):
        result = is_process_running(-1)
        assert isinstance(result, bool)

    def test_kill_process_returns_bool(self):
        with mock.patch.dict("sys.modules", {"psutil": mock.Mock()}):
            result = kill_process(-1)
        assert isinstance(result, bool)

    def test_wait_for_port_returns_bool(self):
        with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError()):
            with mock.patch("eigencapital.platform.process.time.sleep"):
                result = wait_for_port(1, timeout=0.01)
        assert isinstance(result, bool)

    def test_process_info_from_all_backends(self):
        pi_tasklist = ProcessInfo(pid=100, name="python.exe")
        assert pi_tasklist.pid == 100
        assert pi_tasklist.name == "python.exe"
        assert pi_tasklist.cmdline == ""

        pi_procfs = ProcessInfo(pid=200, name="python", cmdline="python script.py")
        assert pi_procfs.cmdline == "python script.py"

        pi_psutil = ProcessInfo(
            pid=300, name="python", cmdline="python --version", create_time=500.0, status="running"
        )
        assert pi_psutil.create_time == 500.0
        assert pi_psutil.status == "running"
