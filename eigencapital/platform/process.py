"""Cross-platform process management.

Provides process discovery, termination, and health checking that works
identically across Linux and Windows.

On Linux, uses ``psutil`` for robust process information.
On Windows, uses ``psutil`` (which wraps Windows API calls).

When psutil is unavailable, falls back to:
- Linux: ``/proc`` filesystem parsing
- Windows: ``tasklist`` / ``taskkill`` via subprocess
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from eigencapital.platform.detector import detect as _detect

logger = logging.getLogger("eigencapital.platform.process")

_PSUTIL_AVAILABLE: bool | None = None


def _has_psutil() -> bool:
    global _PSUTIL_AVAILABLE
    if _PSUTIL_AVAILABLE is None:
        try:
            import psutil  # noqa: F401

            _PSUTIL_AVAILABLE = True
        except ImportError:
            _PSUTIL_AVAILABLE = False
    return _PSUTIL_AVAILABLE


@dataclass
class ProcessInfo:
    """Describes a running process."""

    pid: int
    name: str
    cmdline: str = ""
    create_time: float = 0.0
    status: str = ""


def find_process_by_name(name_pattern: str) -> list[ProcessInfo]:
    """Find processes whose name or command line contains *name_pattern*.

    Uses psutil when available; falls back to platform-specific methods.

    Args:
        name_pattern: Substring to match against process name or command line.

    Returns:
        List of matching ProcessInfo objects (empty if none found).
    """
    if _has_psutil():
        return _find_process_psutil(name_pattern)

    plat = _detect()
    if plat.is_linux:
        return _find_process_procfs(name_pattern)
    elif plat.is_windows:
        return _find_process_tasklist(name_pattern)

    return []


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    Cross-platform: uses psutil if available, otherwise ``os.kill``.
    """
    if _has_psutil():
        import psutil

        return psutil.pid_exists(pid)

    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def kill_process(pid: int, force: bool = False) -> bool:
    """Terminate a process by PID.

    Args:
        pid: Process ID to terminate.
        force: If True, send SIGKILL (Linux) or TerminateProcess (Windows).
               If False, send SIGTERM (Linux) or Ctrl+C simulation (Windows).

    Returns:
        True if the process was terminated, False if it didn't exist.
    """
    if _has_psutil():
        import psutil

        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
            proc.wait(timeout=5)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            return False
        except psutil.AccessDenied:
            logger.warning("Access denied killing PID %d", pid)
            return False

    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        # Wait briefly for the process to exit
        for _ in range(50):
            if not is_process_running(pid):
                return True
            time.sleep(0.1)
        if force:
            return True
        # Graceful didn't work — caller should retry with force
        return False
    except (OSError, ProcessLookupError):
        return False


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
    """Wait until a TCP port is accepting connections.

    Args:
        port: TCP port number.
        host: Host to check (default: 127.0.0.1).
        timeout: Maximum time to wait in seconds.

    Returns:
        True if the port became available, False if timeout elapsed.
    """
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except (OSError, ConnectionRefusedError, TimeoutError):
            time.sleep(1.0)
    return False


def _find_process_psutil(name_pattern: str) -> list[ProcessInfo]:
    import psutil

    results: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "status"]):
        try:
            pinfo = proc.info
            cmdline = " ".join(pinfo.get("cmdline") or [])
            proc_name = pinfo.get("name") or ""
            if name_pattern.lower() in proc_name.lower() or name_pattern.lower() in cmdline.lower():
                results.append(
                    ProcessInfo(
                        pid=pinfo["pid"],
                        name=proc_name,
                        cmdline=cmdline[:200],
                        create_time=pinfo.get("create_time", 0.0),
                        status=pinfo.get("status", ""),
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return results


def _find_process_procfs(name_pattern: str) -> list[ProcessInfo]:
    """Fallback: parse /proc on Linux when psutil is unavailable."""
    results: list[ProcessInfo] = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                with open(f"/proc/{pid}/comm") as f:
                    comm = f.read().strip()
                with open(f"/proc/{pid}/cmdline") as f:
                    raw = f.read().strip().replace("\0", " ")
                if name_pattern.lower() in comm.lower() or name_pattern.lower() in raw.lower():
                    results.append(
                        ProcessInfo(
                            pid=pid,
                            name=comm,
                            cmdline=raw[:200],
                        )
                    )
            except (OSError, FileNotFoundError):
                continue
    except (OSError, FileNotFoundError):
        pass
    return results


def _find_process_tasklist(name_pattern: str) -> list[ProcessInfo]:
    """Fallback: use ``tasklist`` on Windows when psutil is unavailable."""
    results: list[ProcessInfo] = []
    try:
        output = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        for line in output.strip().split("\n"):
            parts = line.strip('"').split('","')
            if len(parts) >= 2:
                proc_name = parts[0].strip('"')
                pid_str = parts[1].strip('"')
                if name_pattern.lower() in proc_name.lower():
                    try:
                        results.append(
                            ProcessInfo(
                                pid=int(pid_str),
                                name=proc_name,
                            )
                        )
                    except ValueError:
                        continue
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    return results


# The MT5BridgeManager (in eigencapital.platform.mt5_bridge_manager)
# provides the primary managed-process lifecycle for the MT5 terminal
# and bridge.  A general-purpose ProcessManager for other child
# processes can be added here when needed.
