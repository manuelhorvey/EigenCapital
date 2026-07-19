"""Tests for eigencapital.platform.mt5_strategies.

All tests mock subprocess.Popen, shutil.which, subprocess.run, os.environ,
Path.exists, and the detector to ensure deterministic results.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from eigencapital.platform.mt5_strategies import (
    MT5Environment,
    MT5LaunchStrategy,
    NativeWindowsMT5Strategy,
    NoopMT5Strategy,
    WineMT5Strategy,
    get_strategy,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_detector():
    """Reset the PlatformDetector singleton so each test starts fresh."""
    from eigencapital.platform.detector import PlatformDetector

    PlatformDetector._instance = None
    from eigencapital.platform.detector import detect as _detect_fn

    _detect_fn.cache_clear()
    yield
    PlatformDetector._instance = None
    _detect_fn.cache_clear()


@pytest.fixture
def fake_terminal_path() -> Path:
    return Path("/fake/terminal64.exe")


@pytest.fixture
def fake_bridge_script() -> Path:
    return Path("/fake/mt5_bridge.py")


# ── MT5Environment dataclass ─────────────────────────────────────────────────


class TestMT5Environment:
    def test_minimal_creation(self):
        env = MT5Environment(
            terminal_exe=Path("C:/mt5/terminal64.exe"),
            bridge_script=Path("mt5_bridge.py"),
            python_exe="python",
        )
        assert env.terminal_exe == Path("C:/mt5/terminal64.exe")
        assert env.bridge_script == Path("mt5_bridge.py")
        assert env.python_exe == "python"
        assert env.wine_prefix is None
        assert env.use_xvfb is False
        assert env.env_overrides is None

    def test_full_creation(self):
        env = MT5Environment(
            terminal_exe=Path("term.exe"),
            bridge_script=Path("bridge.py"),
            python_exe="python3",
            wine_prefix="/home/user/.wine",
            use_xvfb=True,
            env_overrides={"FOO": "bar"},
        )
        assert env.wine_prefix == "/home/user/.wine"
        assert env.use_xvfb is True
        assert env.env_overrides == {"FOO": "bar"}

    def test_to_env_dict_sets_bridge_port(self):
        env = MT5Environment(
            terminal_exe=Path("term.exe"),
            bridge_script=Path("bridge.py"),
            python_exe="python",
        )
        result = env.to_env_dict()
        assert result["MT5_BRIDGE_PORT"] == "9879"

    def test_to_env_dict_applies_overrides(self):
        env = MT5Environment(
            terminal_exe=Path("term.exe"),
            bridge_script=Path("bridge.py"),
            python_exe="python",
            env_overrides={"MY_VAR": "my_value"},
        )
        result = env.to_env_dict()
        assert result["MY_VAR"] == "my_value"

    def test_to_env_dict_sets_wine_prefix(self):
        env = MT5Environment(
            terminal_exe=Path("term.exe"),
            bridge_script=Path("bridge.py"),
            python_exe="python",
            wine_prefix="/custom/wine",
        )
        result = env.to_env_dict()
        assert result["WINEPREFIX"] == "/custom/wine"
        assert result["WINE_PREFIX"] == "/custom/wine"

    def test_to_env_dict_no_mutation_of_original(self):
        """to_env_dict should copy os.environ, not mutate it."""
        env = MT5Environment(
            terminal_exe=Path("term.exe"),
            bridge_script=Path("bridge.py"),
            python_exe="python",
        )
        original = os.environ.copy()
        _ = env.to_env_dict()
        assert os.environ == original  # no mutation


# ── NoopMT5Strategy ──────────────────────────────────────────────────────────


class TestNoopMT5Strategy:
    def setup_method(self):
        self.strategy = NoopMT5Strategy()

    def test_is_available_false(self):
        assert self.strategy.is_available is False

    def test_detect_terminal_returns_none(self):
        assert self.strategy.detect_terminal() is None

    def test_launch_terminal_returns_none(self):
        result = self.strategy.launch_terminal(Path("/dev/null"))
        assert result is None

    def test_launch_bridge_returns_none(self):
        result = self.strategy.launch_bridge(Path("bridge.py"))
        assert result is None

    def test_is_terminal_running_false(self):
        assert self.strategy.is_terminal_running() is False

    def test_environment_returns_dev_null(self):
        env = self.strategy.environment()
        assert env.terminal_exe == Path("/dev/null")

    def test_display_name(self):
        assert self.strategy.display_name == "Noop"


# ── WineMT5Strategy — _resolve_wine_prefix ───────────────────────────────────


class TestWineResolvePrefix:
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/env/wine"}, clear=True)
    def test_uses_wineprefix_env_var(self):
        prefix = WineMT5Strategy._resolve_wine_prefix()
        assert prefix == "/env/wine"

    @mock.patch.dict(os.environ, {"WINE_PREFIX": "/env/wine2"}, clear=True)
    def test_uses_wine_prefix_env_var(self):
        prefix = WineMT5Strategy._resolve_wine_prefix()
        assert prefix == "/env/wine2"

    @mock.patch.dict(os.environ, {"WINEPREFIX": "/env/wine", "WINE_PREFIX": "/env/wine2"}, clear=True)
    def test_wineprefix_takes_precedence(self):
        prefix = WineMT5Strategy._resolve_wine_prefix()
        assert prefix == "/env/wine"

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_defaults_to_home_wine_mt5(self):
        prefix = WineMT5Strategy._resolve_wine_prefix()
        assert prefix == str(Path.home() / ".wine_mt5")


# ── WineMT5Strategy — detect_terminal ────────────────────────────────────────


class TestWineDetectTerminal:
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/fake/wine"}, clear=True)
    def test_finds_existing_terminal(self):
        expected = Path("/fake/wine/drive_c/Program Files/MetaTrader 5/terminal64.exe")
        with mock.patch.object(Path, "exists", return_value=True):
            strategy = WineMT5Strategy()
            result = strategy.detect_terminal()
        assert result == expected

    @mock.patch.dict(os.environ, {"WINEPREFIX": "/fake/wine"}, clear=True)
    def test_returns_none_when_missing(self):
        with mock.patch.object(Path, "exists", return_value=False):
            strategy = WineMT5Strategy()
            result = strategy.detect_terminal()
        assert result is None


# ── WineMT5Strategy — launch_terminal ────────────────────────────────────────


class TestWineLaunchTerminal:
    def test_launches_with_wine_and_xvfb(self, fake_terminal_path):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine", "xvfb-run": "/usr/bin/xvfb-run"}.get(x)):
            with mock.patch("subprocess.Popen", return_value=mock.Mock(pid=12345)) as mock_popen:
                strategy = WineMT5Strategy()
                result = strategy.launch_terminal(fake_terminal_path)
        assert result is not None
        assert result.pid == 12345
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "/usr/bin/xvfb-run" in args
        assert "/usr/bin/wine" in args
        assert str(fake_terminal_path) in args

    def test_launches_without_xvfb(self, fake_terminal_path):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine", "xvfb-run": None}.get(x)):
            with mock.patch("subprocess.Popen", return_value=mock.Mock(pid=12346)) as mock_popen:
                strategy = WineMT5Strategy()
                result = strategy.launch_terminal(fake_terminal_path)
        assert result is not None
        assert result.pid == 12346
        args = mock_popen.call_args[0][0]
        assert "/usr/bin/xvfb-run" not in args
        assert "/usr/bin/wine" in args

    def test_returns_none_when_wine_missing(self, fake_terminal_path):
        with mock.patch("shutil.which", return_value=None):
            strategy = WineMT5Strategy()
            result = strategy.launch_terminal(fake_terminal_path)
        assert result is None

    def test_returns_none_on_popen_error(self, fake_terminal_path):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine"}.get(x)):
            with mock.patch("subprocess.Popen", side_effect=OSError("exec format error")):
                strategy = WineMT5Strategy()
                result = strategy.launch_terminal(fake_terminal_path)
        assert result is None

    def test_passes_env_with_wineprefix(self, fake_terminal_path):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine"}.get(x)):
            with mock.patch("subprocess.Popen") as mock_popen:
                strategy = WineMT5Strategy()
                strategy.launch_terminal(fake_terminal_path)
        _, kwargs = mock_popen.call_args
        assert "WINEPREFIX" in kwargs["env"]
        assert "WINE_PREFIX" in kwargs["env"]


# ── WineMT5Strategy — launch_bridge ──────────────────────────────────────────


class TestWineLaunchBridge:
    def test_launches_bridge_with_wine_and_xvfb(self, fake_bridge_script):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine", "xvfb-run": "/usr/bin/xvfb-run"}.get(x)):
            with mock.patch("subprocess.Popen", return_value=mock.Mock(pid=23456)) as mock_popen:
                strategy = WineMT5Strategy()
                result = strategy.launch_bridge(fake_bridge_script)
        assert result is not None
        assert result.pid == 23456
        args = mock_popen.call_args[0][0]
        assert any("python" in a for a in args)
        assert str(fake_bridge_script) in " ".join(args)

    def test_returns_none_when_wine_missing(self, fake_bridge_script):
        with mock.patch("shutil.which", return_value=None):
            strategy = WineMT5Strategy()
            result = strategy.launch_bridge(fake_bridge_script)
        assert result is None

    def test_returns_none_on_popen_error(self, fake_bridge_script):
        with mock.patch("shutil.which", side_effect=lambda x: {"wine": "/usr/bin/wine"}.get(x)):
            with mock.patch("subprocess.Popen", side_effect=OSError("spawn failed")):
                strategy = WineMT5Strategy()
                result = strategy.launch_bridge(fake_bridge_script)
        assert result is None


# ── WineMT5Strategy — is_terminal_running ────────────────────────────────────


class TestWineIsTerminalRunning:
    def test_returns_true_when_tasklist_finds_terminal(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="terminal64.exe", returncode=0)):
            strategy = WineMT5Strategy()
            assert strategy.is_terminal_running() is True

    def test_returns_false_when_tasklist_not_found(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="nothing.exe", returncode=0)):
            strategy = WineMT5Strategy()
            assert strategy.is_terminal_running() is False

    def test_falls_back_to_pgrep_on_timeout(self):
        """When wine tasklist times out, falls back to pgrep."""
        with mock.patch("subprocess.run", side_effect=[
            subprocess.TimeoutExpired("wine tasklist", 10),
            mock.Mock(returncode=0),
        ]):
            strategy = WineMT5Strategy()
            assert strategy.is_terminal_running() is True

    def test_falls_back_to_pgrep_and_fails(self):
        """When both wine tasklist and pgrep fail, returns False."""
        with mock.patch("subprocess.run", side_effect=[
            subprocess.TimeoutExpired("wine tasklist", 10),
            mock.Mock(returncode=1),
        ]):
            strategy = WineMT5Strategy()
            assert strategy.is_terminal_running() is False

    def test_returns_false_on_pgrep_error(self):
        with mock.patch("subprocess.run", side_effect=[
            FileNotFoundError("wine not found"),
            FileNotFoundError("pgrep not found"),
        ]):
            strategy = WineMT5Strategy()
            assert strategy.is_terminal_running() is False


# ── WineMT5Strategy — environment and display_name ──────────────────────────


class TestWineEnvironment:
    def test_environment_has_wine_python(self):
        with mock.patch.dict(os.environ, {"WINEPREFIX": "/fake/wine"}, clear=True):
            with mock.patch.object(Path, "exists", return_value=True):
                strategy = WineMT5Strategy()
                env = strategy.environment()
        assert env.python_exe == "wine python"
        assert env.wine_prefix == "/fake/wine"
        assert env.use_xvfb is True

    def test_display_name(self):
        strategy = WineMT5Strategy()
        assert strategy.display_name == "Linux+Wine"


# ── NativeWindowsMT5Strategy — detect_terminal ───────────────────────────────


class TestNativeDetectTerminal:
    def test_finds_terminal_at_mt5_path_env(self):
        with mock.patch.dict(os.environ, {"MT5_PATH": "D:/mt5/terminal64.exe"}, clear=True):
            with mock.patch.object(Path, "exists", return_value=True):
                strategy = NativeWindowsMT5Strategy()
                result = strategy.detect_terminal()
        assert result == Path("D:/mt5/terminal64.exe")

    def test_checks_default_candidates(self):
        """When MT5_PATH is not set, should check default candidates."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(Path, "exists", side_effect=lambda: False):
                strategy = NativeWindowsMT5Strategy()
                result = strategy.detect_terminal()
        assert result is None

    def test_returns_none_when_not_found(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(Path, "exists", return_value=False):
                strategy = NativeWindowsMT5Strategy()
                result = strategy.detect_terminal()
        assert result is None

    def test_uses_programfiles_env(self):
        with mock.patch.dict(os.environ, {"PROGRAMFILES": "D:/Program Files"}, clear=True):
            with mock.patch.object(Path, "exists", side_effect=lambda: False):
                strategy = NativeWindowsMT5Strategy()
                strategy.detect_terminal()
        # Should have tried D:/Program Files/MetaTrader 5/terminal64.exe
        assert strategy._terminal_exe is None

    def test_first_candidate_wins(self):
        candidates = iter(["C:/first/exists.exe", "C:/second/exists.exe"])

        def exists_side_effect():
            return next(candidates) == "C:/first/exists.exe"

        with mock.patch.dict(os.environ, {"MT5_PATH": "C:/first/exists.exe"}, clear=True):
            with mock.patch.object(Path, "exists", return_value=True):
                strategy = NativeWindowsMT5Strategy()
                result = strategy.detect_terminal()
        assert result == Path("C:/first/exists.exe")


# ── NativeWindowsMT5Strategy — launch_terminal ───────────────────────────────


class TestNativeLaunchTerminal:
    def test_launches_terminal(self, fake_terminal_path):
        with mock.patch("subprocess.Popen", return_value=mock.Mock(pid=34567)) as mock_popen:
            strategy = NativeWindowsMT5Strategy()
            result = strategy.launch_terminal(fake_terminal_path)
        assert result is not None
        assert result.pid == 34567
        args = mock_popen.call_args[0][0]
        assert str(fake_terminal_path) in args

    def test_returns_none_on_error(self, fake_terminal_path):
        with mock.patch("subprocess.Popen", side_effect=OSError("access denied")):
            strategy = NativeWindowsMT5Strategy()
            result = strategy.launch_terminal(fake_terminal_path)
        assert result is None


# ── NativeWindowsMT5Strategy — launch_bridge ─────────────────────────────────


class TestNativeLaunchBridge:
    def test_launches_bridge(self, fake_bridge_script):
        with mock.patch("subprocess.Popen", return_value=mock.Mock(pid=45678)) as mock_popen:
            strategy = NativeWindowsMT5Strategy()
            result = strategy.launch_bridge(fake_bridge_script)
        assert result is not None
        assert result.pid == 45678
        args = mock_popen.call_args[0][0]
        assert sys.executable in args
        assert str(fake_bridge_script) in args

    def test_returns_none_on_error(self, fake_bridge_script):
        with mock.patch("subprocess.Popen", side_effect=OSError("access denied")):
            strategy = NativeWindowsMT5Strategy()
            result = strategy.launch_bridge(fake_bridge_script)
        assert result is None


# ── NativeWindowsMT5Strategy — is_terminal_running ──────────────────────────


class TestNativeIsTerminalRunning:
    def test_returns_true_when_tasklist_finds(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="terminal64.exe", returncode=0)):
            strategy = NativeWindowsMT5Strategy()
            assert strategy.is_terminal_running() is True

    def test_returns_false_when_not_found(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="nothing.exe", returncode=0)):
            strategy = NativeWindowsMT5Strategy()
            assert strategy.is_terminal_running() is False

    def test_returns_false_on_error(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("tasklist not found")):
            strategy = NativeWindowsMT5Strategy()
            assert strategy.is_terminal_running() is False


# ── NativeWindowsMT5Strategy — environment and display_name ─────────────────


class TestNativeEnvironment:
    def test_environment_uses_sys_executable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            strategy = NativeWindowsMT5Strategy()
            env = strategy.environment()
        assert env.python_exe == sys.executable
        assert env.wine_prefix is None
        assert env.use_xvfb is False

    def test_display_name(self):
        strategy = NativeWindowsMT5Strategy()
        assert strategy.display_name == "WindowsNative"


# ── Abstract base class ──────────────────────────────────────────────────────


class TestMT5LaunchStrategy:
    def test_is_available_true_on_concrete(self):
        """Concrete subclasses inherit is_available=True unless overridden."""
        assert NativeWindowsMT5Strategy().is_available is True
        assert NoopMT5Strategy().is_available is False  # Noop overrides to False

    def test_cannot_instantiate_abstract(self):
        """Should not be able to instantiate the ABC directly."""
        with pytest.raises(TypeError):
            MT5LaunchStrategy()


# ── get_strategy factory ─────────────────────────────────────────────────────


class TestGetStrategy:
    @mock.patch.object(sys, "platform", "win32")
    def test_windows_returns_native_strategy(self):
        strategy = get_strategy()
        assert isinstance(strategy, NativeWindowsMT5Strategy)

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch("eigencapital.platform.detector.PlatformDetector._detect_wine", return_value=True)
    def test_linux_with_wine_returns_wine_strategy(self, mock_wine):
        strategy = get_strategy()
        assert isinstance(strategy, WineMT5Strategy)

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch("eigencapital.platform.detector.PlatformDetector._detect_wine", return_value=False)
    def test_linux_without_wine_returns_noop(self, mock_wine):
        strategy = get_strategy()
        assert isinstance(strategy, NoopMT5Strategy)

    @mock.patch.object(sys, "platform", "darwin")
    def test_macos_returns_noop(self):
        strategy = get_strategy()
        assert isinstance(strategy, NoopMT5Strategy)

    @mock.patch.object(sys, "platform", "sunos5")
    def test_unknown_returns_noop(self):
        strategy = get_strategy()
        assert isinstance(strategy, NoopMT5Strategy)
