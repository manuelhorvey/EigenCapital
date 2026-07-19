"""Tests for eigencapital.platform.detector.

All tests mock sys.platform, os.environ, subprocess, and import machinery
to ensure deterministic results regardless of the actual host OS.
"""

from __future__ import annotations

import builtins
import os
import sys
from contextlib import contextmanager
from unittest import mock

import pytest

from eigencapital.platform.detector import (
    DeploymentMode,
    PlatformDetector,
    PlatformType,
    detect,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mt5_blocker():
    """Create a selective ``__import__`` side-effect that blocks MetaTrader5.

    Returns a callable that can be used as ``side_effect`` for
    ``mock.patch.object(builtins, "__import__", side_effect=...)``.
    Captures the real ``__import__`` at definition time to prevent
    infinite recursion when the mock dispatches to the side-effect.
    """
    _real_import = builtins.__import__

    def _side_effect(name: str, *args: object, **kwargs: object) -> object:
        if name == "MetaTrader5":
            raise ImportError(f"No module named '{name}'")
        return _real_import(name, *args, **kwargs)

    return _side_effect


@contextmanager
def without_mt5_module():
    """Context manager that makes MetaTrader5 temporarily unimportable.

    Patching ``builtins.__import__`` with a blanket ``ImportError``
    side-effect breaks internal Python imports.  This helper selectively
    only blocks ``MetaTrader5`` while passing everything else through.
    """
    with mock.patch.object(
        builtins,
        "__import__",
        side_effect=_make_mt5_blocker(),
    ):
        yield


def reset_singleton() -> None:
    """Reset the PlatformDetector singleton between tests."""
    PlatformDetector._instance = None


# We clear the cached ``detect()`` result by resetting the singleton
# *before* the cached decorator re-evaluates.  The ``lru_cache`` on
# ``detect()`` calls ``PlatformDetector.detect()`` which reads
# ``_instance``, so resetting the instance each test is sufficient.
@pytest.fixture(autouse=True)
def _reset_detector():
    reset_singleton()
    yield
    reset_singleton()


# ── Platform type detection ──────────────────────────────────────────────────


class TestPlatformDetection:
    @mock.patch.object(sys, "platform", "linux")
    def test_linux(self):
        plat = PlatformDetector.detect()
        assert plat.platform == PlatformType.LINUX
        assert plat.is_linux is True
        assert plat.is_windows is False
        assert plat.is_macos is False

    @mock.patch.object(sys, "platform", "linux2")
    def test_linux_legacy(self):
        plat = PlatformDetector.detect()
        assert plat.platform == PlatformType.LINUX

    @mock.patch.object(sys, "platform", "win32")
    def test_windows(self):
        plat = PlatformDetector.detect()
        assert plat.platform == PlatformType.WINDOWS
        assert plat.is_windows is True
        assert plat.is_linux is False

    @mock.patch.object(sys, "platform", "darwin")
    def test_macos(self):
        plat = PlatformDetector.detect()
        assert plat.platform == PlatformType.MACOS
        assert plat.is_macos is True

    @mock.patch.object(sys, "platform", "sunos5")
    def test_unknown(self):
        plat = PlatformDetector.detect()
        assert plat.platform == PlatformType.UNKNOWN
        assert plat.is_linux is False
        assert plat.is_windows is False
        assert plat.is_macos is False


# ── Singleton / caching ──────────────────────────────────────────────────────


class TestSingleton:
    def test_detect_returns_same_instance(self):
        a = PlatformDetector.detect()
        b = PlatformDetector.detect()
        assert a is b

    @mock.patch.object(sys, "platform", "win32")
    def test_properties_cached(self):
        """Calling properties multiple times should not raise."""
        plat = PlatformDetector.detect()
        # First call
        _ = plat.platform
        _ = plat.is_wine
        _ = plat.deployment_mode
        # Second call (cached)
        assert plat.platform == PlatformType.WINDOWS
        assert plat.is_wine is False

    def test_detect_function_returns_singleton(self):
        reset_singleton()
        a = detect()
        b = detect()
        assert a is b


# ── Wine detection ───────────────────────────────────────────────────────────


class TestWineDetection:
    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("subprocess.run", side_effect=FileNotFoundError("no wine"))
    def test_linux_no_wine(self, mock_run):
        plat = PlatformDetector.detect()
        assert plat.is_wine is False

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/home/user/.wine"}, clear=True)
    @mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="wine-7.0\n"))
    def test_linux_with_wine_env_var(self, mock_run):
        plat = PlatformDetector.detect()
        assert plat.is_wine is True

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/home/user/.wine"}, clear=True)
    @mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="wine-7.0\n"))
    def test_linux_with_wine_env_var_and_command(self, mock_run):
        """Wine detected when WINEPREFIX is set and wine --version works."""
        plat = PlatformDetector.detect()
        assert plat.is_wine is True

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("subprocess.run", side_effect=FileNotFoundError("no wine"))
    def test_linux_no_wine_no_mt5(self, mock_run):
        with without_mt5_module():
            plat = PlatformDetector.detect()
            assert plat.is_wine is False

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("subprocess.run", side_effect=FileNotFoundError("no wine"))
    def test_linux_wine_detected_via_mt5_import(self, mock_run):
        """If MetaTrader5 is importable on Linux, assume Wine Python."""
        with mock.patch.dict("sys.modules", {"MetaTrader5": mock.Mock(__name__="MetaTrader5")}):
            plat = PlatformDetector.detect()
            assert plat.is_wine is True

    @mock.patch.object(sys, "platform", "win32")
    def test_windows_is_never_wine(self):
        """Wine detection should return False on Windows."""
        plat = PlatformDetector.detect()
        assert plat.is_wine is False

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {"WINE_PREFIX": "/custom/wine"}, clear=True)
    @mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="wine-8.0\n"))
    def test_wine_prefix_env_var(self, mock_run):
        plat = PlatformDetector.detect()
        assert plat.is_wine is True

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/home/user/.wine"}, clear=True)
    @mock.patch("subprocess.run", side_effect=OSError("wine crashed"))
    def test_wine_env_var_set_but_wine_crashed_and_no_mt5(self, mock_run):
        """If wine --version crashes and MT5 is not importable, is_wine is False."""
        with without_mt5_module():
            plat = PlatformDetector.detect()
            assert plat.is_wine is False

    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.dict(os.environ, {"WINEPREFIX": "/home/user/.wine"}, clear=True)
    def test_wine_timeout(self):
        """subprocess.TimeoutExpired is caught gracefully."""
        import subprocess as _subprocess
        with mock.patch("subprocess.run", side_effect=_subprocess.TimeoutExpired("wine", 5)):
            plat = PlatformDetector.detect()
            assert plat.is_wine is False


# ── Deployment mode ──────────────────────────────────────────────────────────


class TestDeploymentMode:
    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": "production"}, clear=True)
    def test_explicit_production(self):
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.PRODUCTION
        assert plat.is_production is True
        assert plat.is_container is False

    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": "container"}, clear=True)
    def test_explicit_container(self):
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.CONTAINER
        assert plat.is_container is True

    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": "development"}, clear=True)
    def test_explicit_development(self):
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.DEVELOPMENT

    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": "Production"}, clear=True)
    def test_explicit_case_insensitive(self):
        """Env var value should be lowercased before comparison."""
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.PRODUCTION

    @mock.patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, clear=True)
    def test_container_via_kubernetes(self):
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.CONTAINER

    @mock.patch.dict(os.environ, {"DOCKER": "true"}, clear=True)
    def test_container_via_docker_env(self):
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.CONTAINER

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_development_via_git_dir(self):
        """When a .git directory exists in the project root, assume development."""
        plat = PlatformDetector.detect()
        # The project root should have a .git directory since this is a real project
        assert plat.deployment_mode == DeploymentMode.DEVELOPMENT

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("eigencapital.platform.paths.resolve_project_root")
    def test_production_no_git_dir(self, mock_resolve_root):
        """When no .git directory exists, assume production."""
        import pathlib
        mock_root = pathlib.Path("/tmp/fake_project")
        mock_resolve_root.return_value = mock_root
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.PRODUCTION

    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": ""}, clear=True)
    def test_empty_env_var_not_explicit(self):
        """Empty string should not match any explicit mode."""
        plat = PlatformDetector.detect()
        assert plat.deployment_mode == DeploymentMode.DEVELOPMENT  # because .git exists

    @mock.patch.dict(os.environ, {"EIGENCAPITAL_DEPLOYMENT": "staging"}, clear=True)
    @mock.patch("eigencapital.platform.paths.resolve_project_root")
    def test_unknown_deployment_mode_falls_through_to_git_heuristic(self, mock_resolve_root):
        """An unknown EIGENCAPITAL_DEPLOYMENT value (e.g. 'staging') should fall
        through to the .git heuristic instead of silently defaulting to PRODUCTION.
        """
        import pathlib
        mock_root = pathlib.Path("/tmp/fake_project")
        mock_resolve_root.return_value = mock_root

        plat = PlatformDetector.detect()
        # No .git at /tmp/fake_project → falls through to PRODUCTION
        # (This verifies the unknown value doesn't cause a crash and doesn't
        #  return CONTAINER or DEVELOPMENT incorrectly.)
        assert plat.deployment_mode == DeploymentMode.PRODUCTION


# ── Python / runtime properties ──────────────────────────────────────────────


class TestRuntimeProperties:
    def test_python_executable_returns_string(self):
        plat = PlatformDetector.detect()
        assert isinstance(plat.python_executable, str)
        assert len(plat.python_executable) > 0

    def test_architecture_returns_string(self):
        plat = PlatformDetector.detect()
        assert isinstance(plat.architecture, str)
        assert len(plat.architecture) > 0

    def test_python_version_returns_string(self):
        plat = PlatformDetector.detect()
        assert isinstance(plat.python_version, str)

    @mock.patch.object(sys, "platform", "linux")
    def test_platform_tag_linux(self):
        plat = PlatformDetector.detect()
        tag = plat.platform_tag
        assert "linux" in tag

    @mock.patch.object(sys, "platform", "win32")
    def test_platform_tag_windows(self):
        plat = PlatformDetector.detect()
        assert plat.platform_tag == "windows"

    @mock.patch.object(sys, "platform", "linux")
    def test_platform_tag_linux_wine(self):
        """If Wine is detected, tag should include 'wine'."""
        with mock.patch.object(PlatformDetector, "_detect_wine", return_value=True):
            plat = PlatformDetector.detect()
            tag = plat.platform_tag
            assert "linux" in tag
            assert "wine" in tag


class TestMT5Available:
    def test_mt5_not_available(self):
        with without_mt5_module():
            plat = PlatformDetector.detect()
            assert plat.mt5_available is False

    def test_mt5_available(self):
        with mock.patch.dict("sys.modules", {"MetaTrader5": mock.Mock(__name__="MetaTrader5")}):
            plat = PlatformDetector.detect()
            assert plat.mt5_available is True


# ── __repr__ ─────────────────────────────────────────────────────────────────


class TestRepr:
    @mock.patch.object(sys, "platform", "linux")
    @mock.patch.object(PlatformDetector, "_detect_wine", return_value=False)
    def test_repr_linux(self, mock_wine):
        plat = PlatformDetector.detect()
        text = repr(plat)
        assert "PlatformDetector" in text
        assert "LINUX" in text
        assert "DEVELOPMENT" in text

    @mock.patch.object(sys, "platform", "win32")
    def test_repr_windows(self):
        plat = PlatformDetector.detect()
        text = repr(plat)
        assert "PlatformDetector" in text
        assert "WINDOWS" in text
