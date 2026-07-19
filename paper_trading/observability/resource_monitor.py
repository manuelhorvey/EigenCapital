"""Resource monitor — lightweight memory and CPU usage tracking.

Provides periodic snapshots of the engine process's resource usage
for observability and alerting. Designed to be called from the engine
cycle or from a background timer thread.

Usage:
    from paper_trading.observability.resource_monitor import ResourceMonitor

    monitor = ResourceMonitor()
    monitor.sample()  # returns {...}

The monitor reads from ``/proc/self/status`` (Linux only). On other
platforms, it degrades gracefully to reporting ``None`` for unavailable
metrics.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("eigencapital.observability.resource_monitor")


@dataclass
class ResourceSample:
    """Single resource usage snapshot."""

    timestamp: float = 0.0
    memory_rss_mb: float | None = None  # Resident Set Size (physical RAM)
    memory_vms_mb: float | None = None  # Virtual Memory Size
    memory_pss_mb: float | None = None  # Proportional Set Size (if available)
    cpu_percent: float | None = None  # CPU utilization (0-100)
    fd_count: int | None = None  # Open file descriptors
    thread_count: int | None = None  # Active threads
    gc_objects: int | None = None  # Python GC tracked objects


class ResourceMonitor:
    """Periodic resource monitor for the engine process.

    Samples are stored in a circular buffer for trend analysis.
    Warnings are emitted when configurable thresholds are breached.
    """

    def __init__(
        self,
        memory_warn_mb: float = 2048.0,
        memory_critical_mb: float = 4096.0,
        cpu_warn_pct: float = 80.0,
        cpu_critical_pct: float = 95.0,
        max_samples: int = 60,
    ) -> None:
        self.memory_warn_mb = memory_warn_mb
        self.memory_critical_mb = memory_critical_mb
        self.cpu_warn_pct = cpu_warn_pct
        self.cpu_critical_pct = cpu_critical_pct
        self.max_samples = max_samples
        self._samples: list[ResourceSample] = []
        self._last_sample: ResourceSample | None = None
        self._last_cpu_time: float | None = None
        self._last_wall_time: float | None = None
        self._warning_cooldown: float = 300.0  # 5 min between warnings
        self._last_memory_warn: float = 0.0
        self._last_cpu_warn: float = 0.0

    def sample(self) -> ResourceSample:
        """Take a resource usage sample and return it.

        Appends to the internal circular buffer. Emits log warnings
        if thresholds are breached (rate-limited to 5 min intervals).
        """
        now = time.monotonic()
        sample = ResourceSample(timestamp=time.time())

        # ── Memory from /proc/self/status (Linux) ───────────────────
        sample.memory_rss_mb = self._read_proc_memory("VmRSS")
        sample.memory_vms_mb = self._read_proc_memory("VmSize")

        # ── CPU utilization (delta-based) ──────────────────────────
        cpu_time = self._read_proc_cpu_time()
        if cpu_time is not None and self._last_cpu_time is not None and self._last_wall_time is not None:
            wall_delta = now - self._last_wall_time
            if wall_delta > 0:
                cpu_delta = cpu_time - self._last_cpu_time
                sample.cpu_percent = min(100.0, (cpu_delta / wall_delta) * 100.0)
        self._last_cpu_time = cpu_time
        self._last_wall_time = now

        # ── File descriptors ───────────────────────────────────────
        sample.fd_count = self._count_fds()

        # ── Thread count ───────────────────────────────────────────
        try:
            import threading

            sample.thread_count = threading.active_count()
        except (ImportError, RuntimeError):
            pass

        # ── GC tracked objects ─────────────────────────────────────
        try:
            import gc

            sample.gc_objects = sum(gc.get_count())
        except (ImportError, RuntimeError):
            pass

        # ── Store sample ───────────────────────────────────────────
        self._samples.append(sample)
        if len(self._samples) > self.max_samples:
            self._samples.pop(0)
        self._last_sample = sample

        # ── Threshold checks (rate-limited) ────────────────────────
        self._check_thresholds(sample, now)

        return sample

    def _read_proc_memory(self, key: str) -> float | None:
        """Read a memory value from /proc/self/status."""
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith(f"{key}:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            # Value is in kB; convert to MB
                            return float(parts[1]) / 1024.0
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            pass
        return None

    def _read_proc_cpu_time(self) -> float | None:
        """Read total CPU time (user + system) from /proc/self/stat."""
        try:
            with open("/proc/self/stat") as f:
                parts = f.read().split()
                # utime (14th field) + stime (15th field) in clock ticks
                utime = float(parts[13])
                stime = float(parts[14])
                clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                return (utime + stime) / clk_tck
        except (FileNotFoundError, PermissionError, OSError, ValueError, AttributeError):
            pass
        return None

    def _count_fds(self) -> int | None:
        """Count open file descriptors via /proc/self/fd."""
        try:
            return len(os.listdir("/proc/self/fd"))
        except (FileNotFoundError, PermissionError, OSError):
            return None

    def _check_thresholds(self, sample: ResourceSample, now: float) -> None:
        """Emit warnings if resource thresholds are breached (rate-limited)."""
        if sample.memory_rss_mb is not None:
            if sample.memory_rss_mb > self.memory_critical_mb and now - self._last_memory_warn > self._warning_cooldown:
                logger.critical(
                    "RESOURCE_CRITICAL: RSS=%.0f MB exceeds critical threshold (%.0f MB)",
                    sample.memory_rss_mb,
                    self.memory_critical_mb,
                )
                self._last_memory_warn = now
            elif sample.memory_rss_mb > self.memory_warn_mb and now - self._last_memory_warn > self._warning_cooldown:
                logger.warning(
                    "RESOURCE_WARN: RSS=%.0f MB exceeds warning threshold (%.0f MB)",
                    sample.memory_rss_mb,
                    self.memory_warn_mb,
                )
                self._last_memory_warn = now

        if sample.cpu_percent is not None:
            if sample.cpu_percent > self.cpu_critical_pct and now - self._last_cpu_warn > self._warning_cooldown:
                logger.critical(
                    "RESOURCE_CRITICAL: CPU=%.0f%% exceeds critical threshold (%.0f%%)",
                    sample.cpu_percent,
                    self.cpu_critical_pct,
                )
                self._last_cpu_warn = now
            elif sample.cpu_percent > self.cpu_warn_pct and now - self._last_cpu_warn > self._warning_cooldown:
                logger.warning(
                    "RESOURCE_WARN: CPU=%.0f%% exceeds warning threshold (%.0f%%)",
                    sample.cpu_percent,
                    self.cpu_warn_pct,
                )
                self._last_cpu_warn = now

    def get_latest(self) -> ResourceSample | None:
        """Return the most recent sample, or None if none taken yet."""
        return self._last_sample

    def get_trend(self, n_samples: int = 5) -> list[ResourceSample]:
        """Return the last *n_samples* samples for trend analysis."""
        return self._samples[-n_samples:] if self._samples else []

    def get_summary(self) -> dict[str, Any]:
        """Return a dict summary suitable for embedding into state.json."""
        latest = self.get_latest()
        if latest is None:
            return {"available": False}
        trend = self.get_trend(5)
        avg_rss = (
            sum(s.memory_rss_mb for s in trend if s.memory_rss_mb is not None) / max(len(trend), 1) if trend else None
        )
        avg_cpu = sum(s.cpu_percent for s in trend if s.cpu_percent is not None) / max(len(trend), 1) if trend else None
        return {
            "available": True,
            "latest": asdict(latest),
            "avg_rss_mb_5": round(avg_rss, 1) if avg_rss else None,
            "avg_cpu_pct_5": round(avg_cpu, 1) if avg_cpu else None,
            "fd_count": latest.fd_count,
            "thread_count": latest.thread_count,
            "gc_objects": latest.gc_objects,
        }


# ── Module-level singleton ──────────────────────────────────────────────

_default_monitor: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    """Return the global ResourceMonitor singleton (created on first call)."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = ResourceMonitor()
    return _default_monitor


def sample_resources() -> dict[str, Any]:
    """Convenience: take a resource sample and return its summary dict."""
    monitor = get_resource_monitor()
    monitor.sample()
    return monitor.get_summary()
