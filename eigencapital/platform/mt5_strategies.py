"""MT5 platform strategies — Wine vs Native Windows vs unsupported.

Strategy pattern for MT5 terminal launch, bridge startup, and API
initialisation.  Each platform-specific behaviour is encapsulated
behind the ``MT5LaunchStrategy`` interface.

The ``MT5BridgeManager`` (in eigencapital.platform.mt5_bridge_manager)
selects the appropriate strategy based on the current platform.

Usage::

    from eigencapital.platform.mt5_strategies import get_strategy

    strategy = get_strategy()
    if strategy.is_available:
        strategy.launch_terminal()
        strategy.launch_bridge()
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from eigencapital.platform.detector import detect as _detect

logger = logging.getLogger("eigencapital.platform.mt5")

# Default paths for MT5 terminal
_WINE_MT5_RELATIVE = Path("drive_c") / "Program Files" / "MetaTrader 5" / "terminal64.exe"
_WINDOWS_MT5 = Path("C:/Program Files/MetaTrader 5/terminal64.exe")
_DEFAULT_BRIDGE_PORT = 9879


@dataclass
class MT5Environment:
    """Describes the MT5 environment for the current platform."""

    terminal_exe: Path
    bridge_script: Path
    python_exe: str
    wine_prefix: str | None = None
    use_xvfb: bool = False
    env_overrides: dict[str, str] | None = None

    def to_env_dict(self) -> dict[str, str]:
        """Build environment variables dict for subprocess."""
        env = os.environ.copy()
        env["MT5_BRIDGE_PORT"] = str(_DEFAULT_BRIDGE_PORT)
        if self.env_overrides:
            env.update(self.env_overrides)
        if self.wine_prefix:
            env["WINEPREFIX"] = self.wine_prefix
            env["WINE_PREFIX"] = self.wine_prefix
        return env


class MT5LaunchStrategy(ABC):
    """Abstract strategy for MT5 terminal and bridge lifecycle.

    Each platform (Linux+Wine, Native Windows) implements this
    interface.
    """

    @abstractmethod
    def detect_terminal(self) -> Path | None:
        """Locate the MT5 terminal executable.

        Returns:
            Path to terminal64.exe or None if not found.
        """
        ...

    @abstractmethod
    def launch_terminal(self, terminal_path: Path) -> subprocess.Popen | None:
        """Launch the MT5 terminal.

        Args:
            terminal_path: Path to terminal64.exe.

        Returns:
            Popen object for the terminal process, or None on failure.
        """
        ...

    @abstractmethod
    def launch_bridge(self, bridge_script: Path) -> subprocess.Popen | None:
        """Launch the MT5 bridge server.

        Args:
            bridge_script: Path to mt5_bridge.py.

        Returns:
            Popen object for the bridge process, or None on failure.
        """
        ...

    @abstractmethod
    def is_terminal_running(self) -> bool:
        """Check if the MT5 terminal process is currently running."""
        ...

    @abstractmethod
    def environment(self) -> MT5Environment:
        """Return the MT5 environment description for this platform."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable platform name for logging."""
        ...

    @property
    def is_available(self) -> bool:
        """Return True if MT5 is available on this platform."""
        return True


class NoopMT5Strategy(MT5LaunchStrategy):
    """No-op strategy for platforms where MT5 is unavailable.

    All methods return None / False and log a warning.  Use this
    on pure Linux without Wine or on unsupported platforms.
    """

    @property
    def is_available(self) -> bool:
        return False

    def detect_terminal(self) -> Path | None:
        return None

    def launch_terminal(self, terminal_path: Path) -> subprocess.Popen | None:
        logger.warning("MT5 terminal cannot be launched on this platform (no Wine/Windows)")
        return None

    def launch_bridge(self, bridge_script: Path) -> subprocess.Popen | None:
        logger.warning("MT5 bridge cannot be launched on this platform (no Wine/Windows)")
        return None

    def is_terminal_running(self) -> bool:
        return False

    def environment(self) -> MT5Environment:
        return MT5Environment(
            terminal_exe=Path("/dev/null"),
            bridge_script=Path("paper_trading/ops/mt5_bridge.py"),
            python_exe=sys.executable,
        )

    @property
    def display_name(self) -> str:
        return "Noop"


class WineMT5Strategy(MT5LaunchStrategy):
    """MT5 strategy for Linux + Wine.

    MT5 runs as a Windows binary under Wine, with the bridge running
    under Wine Python.  Uses ``xvfb-run`` for headless operation.
    """

    def __init__(self) -> None:
        self._wine_prefix = self._resolve_wine_prefix()
        self._terminal_exe: Path | None = None

    @staticmethod
    def _resolve_wine_prefix() -> str:
        return os.environ.get("WINEPREFIX") or os.environ.get("WINE_PREFIX") or str(Path.home() / ".wine_mt5")

    def detect_terminal(self) -> Path | None:
        candidate = Path(self._wine_prefix) / _WINE_MT5_RELATIVE
        if candidate.exists():
            self._terminal_exe = candidate
            return candidate
        logger.warning("MT5 terminal not found at %s (Wine prefix: %s)", candidate, self._wine_prefix)
        return None

    def launch_terminal(self, terminal_path: Path) -> subprocess.Popen | None:
        wine = shutil.which("wine")
        if not wine:
            logger.error("wine command not found on PATH")
            return None

        xvfb = shutil.which("xvfb-run")
        cmd: list[str] = []
        if xvfb:
            cmd.extend([xvfb, wine, str(terminal_path)])
        else:
            cmd.extend([wine, str(terminal_path)])

        env = os.environ.copy()
        env["WINEPREFIX"] = self._wine_prefix
        env["WINE_PREFIX"] = self._wine_prefix

        logger.info("Launching MT5 terminal: %s", " ".join(shlex.quote(c) for c in cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("MT5 terminal started (PID %d)", proc.pid)
            return proc
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Failed to launch MT5 terminal: %s", e)
            return None

    def launch_bridge(self, bridge_script: Path) -> subprocess.Popen | None:
        wine = shutil.which("wine")
        if not wine:
            logger.error("wine command not found on PATH")
            return None

        xvfb = shutil.which("xvfb-run")
        # Build the PYTHONPATH for Wine Python
        project_root = bridge_script.resolve().parent.parent.parent
        wine_pythonpath = f"Z:{project_root}"

        cmd: list[str] = []
        if xvfb:
            cmd.append(xvfb)

        cmd.extend([
            "env",
            f"PYTHONPATH={wine_pythonpath}",
            wine,
            "python",
            str(bridge_script),
        ])

        env = os.environ.copy()
        env["WINEPREFIX"] = self._wine_prefix
        env["WINE_PREFIX"] = self._wine_prefix

        logger.info("Launching MT5 bridge: wine python %s", bridge_script)
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("MT5 bridge started (PID %d)", proc.pid)
            return proc
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Failed to launch MT5 bridge: %s", e)
            return None

    def is_terminal_running(self) -> bool:
        try:
            # Check via tasklist under Wine
            result = subprocess.run(
                ["wine", "tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "terminal64.exe" in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return self._check_terminal_pgrep()

    @staticmethod
    def _check_terminal_pgrep() -> bool:
        """Fallback: use pgrep on Linux when Wine tasklist fails."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "terminal64.exe"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def environment(self) -> MT5Environment:
        return MT5Environment(
            terminal_exe=self.detect_terminal() or Path(self._wine_prefix) / _WINE_MT5_RELATIVE,
            bridge_script=Path("paper_trading/ops/mt5_bridge.py"),
            python_exe="wine python",
            wine_prefix=self._wine_prefix,
            use_xvfb=True,
            env_overrides={"WINEPREFIX": self._wine_prefix, "WINE_PREFIX": self._wine_prefix},
        )

    @property
    def display_name(self) -> str:
        return "Linux+Wine"


class NativeWindowsMT5Strategy(MT5LaunchStrategy):
    """MT5 strategy for native Windows (or Windows VPS).

    MT5 runs natively on Windows. The bridge also runs under native
    Python.  No Wine, no xvfb.
    """

    def __init__(self) -> None:
        self._terminal_exe: Path | None = None

    def detect_terminal(self) -> Path | None:
        # Check common installation paths
        candidates = [
            _WINDOWS_MT5,
            Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
            Path("C:/Program Files/MetaTrader 5/terminal.exe"),
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "MetaTrader 5" / "terminal64.exe",
            Path(os.environ.get("PROGRAMW6432", "C:/Program Files")) / "MetaTrader 5" / "terminal64.exe",
        ]

        # Check MT5_PATH env var first
        env_path = os.environ.get("MT5_PATH")
        if env_path:
            candidates.insert(0, Path(env_path))

        for candidate in candidates:
            if candidate.exists():
                self._terminal_exe = candidate
                return candidate

        logger.warning(
            "MT5 terminal not found. Checked: %s. Set MT5_PATH env var if installed elsewhere.",
            [str(c) for c in candidates],
        )
        return None

    def launch_terminal(self, terminal_path: Path) -> subprocess.Popen | None:
        logger.info("Launching MT5 terminal: %s", terminal_path)
        try:
            proc = subprocess.Popen(
                [str(terminal_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            logger.info("MT5 terminal started (PID %d)", proc.pid)
            return proc
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Failed to launch MT5 terminal: %s", e)
            return None

    def launch_bridge(self, bridge_script: Path) -> subprocess.Popen | None:
        python = sys.executable
        logger.info("Launching MT5 bridge: %s %s", python, bridge_script)
        try:
            proc = subprocess.Popen(
                [python, str(bridge_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            logger.info("MT5 bridge started (PID %d)", proc.pid)
            return proc
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Failed to launch MT5 bridge: %s", e)
            return None

    def is_terminal_running(self) -> bool:
        """Check running processes for MT5 terminal on Windows."""
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq terminal64.exe"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "terminal64.exe" in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def environment(self) -> MT5Environment:
        return MT5Environment(
            terminal_exe=self.detect_terminal() or _WINDOWS_MT5,
            bridge_script=Path("paper_trading/ops/mt5_bridge.py"),
            python_exe=sys.executable,
            wine_prefix=None,
            use_xvfb=False,
        )

    @property
    def display_name(self) -> str:
        return "WindowsNative"


# ── Strategy factory ─────────────────────────────────────────────────────────


def get_strategy() -> MT5LaunchStrategy:
    """Detect the current platform and return the appropriate strategy.

    Returns:
        - ``WineMT5Strategy`` on Linux + Wine.
        - ``NativeWindowsMT5Strategy`` on native Windows.
        - ``NoopMT5Strategy`` on Linux without Wine (or unknown platforms).
    """
    plat = _detect()
    if plat.is_windows:
        return NativeWindowsMT5Strategy()
    if plat.is_linux:
        if plat.is_wine:
            return WineMT5Strategy()
        return NoopMT5Strategy()
    return NoopMT5Strategy()
