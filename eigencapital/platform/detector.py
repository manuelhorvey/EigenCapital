"""Platform detection — operating system, Wine, deployment mode.

Centralises all ``sys.platform`` / ``os.name`` checks behind a single
``PlatformDetector`` interface so the rest of the codebase never needs
to import these modules directly.

Usage::

    from eigencapital.platform import detect, PlatformType

    plat = detect()
    if plat.is_windows:
        # Native Windows — use native MT5, no Wine
    elif plat.is_linux:
        if plat.is_wine:
            # Linux + Wine for MT5
        else:
            # Pure Linux (paper mode or no MT5)
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from enum import Enum, auto
from functools import lru_cache


class PlatformType(Enum):
    """Enumeration of recognised operating system platforms."""

    LINUX = auto()
    WINDOWS = auto()
    MACOS = auto()
    UNKNOWN = auto()


class DeploymentMode(Enum):
    """Deployment mode inferred from environment + platform."""

    DEVELOPMENT = auto()
    PRODUCTION = auto()
    CONTAINER = auto()


class PlatformDetector:
    """Detects and caches platform information.

    All properties are lazily evaluated and cached so repeated checks
    are effectively free.

    Usage::

        plat = PlatformDetector.detect()
        if plat.is_windows:
            # Windows-specific path
    """

    _instance: PlatformDetector | None = None

    def __init__(self) -> None:
        self._platform: PlatformType | None = None
        self._is_wine: bool | None = None
        self._deployment_mode: DeploymentMode | None = None

    # ── Factory / singleton ─────────────────────────────────────────────

    @classmethod
    def detect(cls) -> PlatformDetector:
        """Return a singleton PlatformDetector.

        The same instance is reused across the entire process lifetime,
        so all platform checks are computed at most once.
        """
        if cls._instance is None:
            cls._instance = cls()
            # Eagerly cache all checks
            _ = cls._instance.platform
            _ = cls._instance.is_wine
            _ = cls._instance.deployment_mode
        return cls._instance

    # ── Platform type ──────────────────────────────────────────────────

    @property
    def platform(self) -> PlatformType:
        if self._platform is None:
            raw = sys.platform.lower()
            if raw.startswith("win"):
                self._platform = PlatformType.WINDOWS
            elif raw.startswith("linux"):
                self._platform = PlatformType.LINUX
            elif raw.startswith("darwin"):
                self._platform = PlatformType.MACOS
            else:
                self._platform = PlatformType.UNKNOWN
        return self._platform

    @property
    def is_linux(self) -> bool:
        return self.platform == PlatformType.LINUX

    @property
    def is_windows(self) -> bool:
        return self.platform == PlatformType.WINDOWS

    @property
    def is_macos(self) -> bool:
        return self.platform == PlatformType.MACOS

    # ── Wine detection ─────────────────────────────────────────────────

    @property
    def is_wine(self) -> bool:
        """Return True if running under Wine (Linux with Wine)."""
        if self._is_wine is None:
            self._is_wine = self._detect_wine()
        return self._is_wine

    @staticmethod
    def _detect_wine() -> bool:
        """Detect Wine by checking for the wine executable and WINEPREFIX.

        Works by:
        1. Checking if the ``wine`` command exists on PATH.
        2. Checking if ``WINEPREFIX`` or ``WINE_PREFIX`` env vars are set.
        3. Checking if MetaTrader5 is importable under Linux (indicates Wine Python).

        Returns True only if Wine is installed AND configured.
        """
        if sys.platform != "linux":
            return False

        # Check env vars first (fast path)
        if os.environ.get("WINEPREFIX") or os.environ.get("WINE_PREFIX"):
            # Verify wine command exists
            try:
                subprocess.run(
                    ["wine", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                return True
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

        # Check if MetaTrader5 is importable (works under Wine Python on Linux)
        try:
            import MetaTrader5  # noqa: F401

            return True
        except ImportError:
            pass

        return False

    # ── Deployment mode ────────────────────────────────────────────────

    @property
    def deployment_mode(self) -> DeploymentMode:
        if self._deployment_mode is None:
            self._deployment_mode = self._detect_deployment_mode()
        return self._deployment_mode

    @staticmethod
    def _detect_deployment_mode() -> DeploymentMode:
        """Infer deployment mode from environment variables.

        Order:
        1. ``EIGENCAPITAL_DEPLOYMENT`` env var (explicit override).
        2. ``KUBERNETES_SERVICE_HOST`` or ``DOCKER`` env var → CONTAINER.
        3. Production heuristics: no ``.git`` directory, no ``.venv``.
        4. Default: DEVELOPMENT.
        """
        explicit = os.environ.get("EIGENCAPITAL_DEPLOYMENT", "").lower()
        if explicit == "production":
            return DeploymentMode.PRODUCTION
        if explicit == "container":
            return DeploymentMode.CONTAINER
        if explicit == "development":
            return DeploymentMode.DEVELOPMENT

        if os.environ.get("KUBERNETES_SERVICE_HOST") or os.environ.get("DOCKER"):
            return DeploymentMode.CONTAINER

        # Check for .git directory as a heuristic for development
        # Use the project root to avoid CWD-relative false positives
        from eigencapital.platform.paths import resolve_project_root

        project_root = resolve_project_root()
        if (project_root / ".git").is_dir():
            return DeploymentMode.DEVELOPMENT

        return DeploymentMode.PRODUCTION

    @property
    def is_production(self) -> bool:
        return self.deployment_mode == DeploymentMode.PRODUCTION

    @property
    def is_container(self) -> bool:
        return self.deployment_mode == DeploymentMode.CONTAINER

    # ── Python runtime ─────────────────────────────────────────────────

    @property
    def python_executable(self) -> str:
        """Return the path to the Python interpreter.

        On Linux/Wine, this may point to the Wine Python executable.
        On Windows, this is the native Python executable.
        """
        return sys.executable

    @property
    def platform_tag(self) -> str:
        """Short human-readable platform tag for logging/metrics."""
        parts = [self.platform.name.lower()]
        if self.is_wine:
            parts.append("wine")
        if self.is_container:
            parts.append("container")
        return "-".join(parts)

    @property
    def architecture(self) -> str:
        """Return machine architecture (e.g. 'x86_64', 'AMD64')."""
        return platform.machine()

    @property
    def python_version(self) -> str:
        return platform.python_version()

    # ── MT5 detection ──────────────────────────────────────────────────

    @property
    def mt5_available(self) -> bool:
        """Return True if the MetaTrader5 Python package is importable."""
        try:
            import MetaTrader5  # noqa: F401

            return True
        except ImportError:
            return False

    # ── Convenience ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"PlatformDetector("
            f"platform={self.platform.name}, "
            f"wine={self.is_wine}, "
            f"mode={self.deployment_mode.name}, "
            f"arch={self.architecture})"
        )


# ── Shortcut ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def detect() -> PlatformDetector:
    """Shortcut: detect and return the singleton PlatformDetector.

    Usage::

        from eigencapital.platform import detect
        if detect().is_windows:
            ...
    """
    return PlatformDetector.detect()
