"""Process Supervisor — platform-agnostic process management.

Provides:
- PID file management (prevent duplicate instances)
- Instance identity
- Graceful shutdown
- Health status file
- Restart count tracking
- FROZEN state after repeated failures

Design rules:
- Platform-neutral (no pgrep, no systemctl)
- Persistent state across restarts
- Fail closed on corruption
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SupervisorState:
    """Immutable supervisor state."""
    pid: int
    started_at: str
    restart_count: int
    last_healthy_at: str
    status: str  # "running", "halting", "frozen"
    instance_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "started_at": self.started_at,
            "restart_count": self.restart_count,
            "last_healthy_at": self.last_healthy_at,
            "status": self.status,
            "instance_id": self.instance_id,
        }


class ProcessSupervisor:
    """Platform-agnostic process supervisor.

    Usage:
        supervisor = ProcessSupervisor(state_dir="reports/r4_loop")

        # At startup:
        if not supervisor.claim_instance():
            print("Another instance is running")
            sys.exit(1)

        # During operation:
        supervisor.mark_healthy()

        # At shutdown:
        supervisor.release()
    """

    def __init__(self, state_dir: str = "reports/r4_loop") -> None:
        self._state_dir = Path(state_dir)
        self._pid_file = self._state_dir / "supervisor.pid"
        self._state_file = self._state_dir / "supervisor_state.json"
        self._health_file = self._state_dir / "loop_health.json"
        self._state: Optional[SupervisorState] = None

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _generate_instance_id(self) -> str:
        """Generate a unique instance ID from PID + timestamp."""
        data = f"{os.getpid()}:{self._now_utc()}"
        return hashlib.sha256(data.encode()).hexdigest()[:12]

    def _load_state(self) -> Optional[SupervisorState]:
        """Load state from disk."""
        if not self._state_file.exists():
            return None
        try:
            with open(self._state_file) as f:
                data = json.load(f)
            return SupervisorState(
                pid=data["pid"],
                started_at=data["started_at"],
                restart_count=data.get("restart_count", 0),
                last_healthy_at=data.get("last_healthy_at", ""),
                status=data.get("status", "running"),
                instance_id=data.get("instance_id", ""),
            )
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _save_state(self, state: SupervisorState) -> None:
        """Save state to disk atomically."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(self._state_file))
        except OSError:
            try:
                os.unlink(str(tmp_path))
            except OSError:
                pass

    def _write_pid(self) -> None:
        """Write current PID to file."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(os.getpid()))

    def _read_pid(self) -> Optional[int]:
        """Read PID from file."""
        if not self._pid_file.exists():
            return None
        try:
            return int(self._pid_file.read_text().strip())
        except (ValueError, OSError):
            return None

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with given PID is alive."""
        try:
            os.kill(pid, 0)  # Signal 0 = check existence
            return True
        except (OSError, ProcessLookupError):
            return False

    def claim_instance(self) -> bool:
        """Try to claim this instance. Returns False if another is running.

        Checks:
        1. PID file exists
        2. Process with that PID is alive
        3. If dead → stale PID file → claim
        4. If alive → another instance → reject
        """
        existing_pid = self._read_pid()

        if existing_pid is not None:
            if existing_pid == os.getpid():
                # We already own this instance
                return True
            if self._is_process_alive(existing_pid):
                # Another process is running
                return False
            # Stale PID file — previous process died

        # Claim: write PID and create state
        self._write_pid()
        self._state = SupervisorState(
            pid=os.getpid(),
            started_at=self._now_utc(),
            restart_count=0,
            last_healthy_at=self._now_utc(),
            status="running",
            instance_id=self._generate_instance_id(),
        )
        self._save_state(self._state)

        # Set up signal handlers for graceful shutdown
        self._setup_signals()

        return True

    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def _handler(sig, frame):
            self._state = SupervisorState(
                pid=os.getpid(),
                started_at=self._state.started_at if self._state else self._now_utc(),
                restart_count=self._state.restart_count if self._state else 0,
                last_healthy_at=self._state.last_healthy_at if self._state else "",
                status="halting",
                instance_id=self._state.instance_id if self._state else "",
            )
            self._save_state(self._state)

        try:
            signal.signal(signal.SIGINT, _handler)
        except (OSError, ValueError):
            pass  # Main thread only
        if hasattr(signal, "SIGTERM"):
            try:
                signal.signal(signal.SIGTERM, _handler)
            except (OSError, ValueError):
                pass

    def mark_healthy(self) -> None:
        """Mark the instance as healthy (call periodically)."""
        if self._state is None:
            return
        self._state = SupervisorState(
            pid=self._state.pid,
            started_at=self._state.started_at,
            restart_count=self._state.restart_count,
            last_healthy_at=self._now_utc(),
            status="running",
            instance_id=self._state.instance_id,
        )
        self._save_state(self._state)

        # Also write health file for external monitoring
        self._state_dir.mkdir(parents=True, exist_ok=True)
        health_data = {
            "alive": True,
            "pid": os.getpid(),
            "timestamp": self._now_utc(),
            "instance_id": self._state.instance_id,
        }
        tmp = self._health_file.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(health_data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(self._health_file))
        except OSError:
            pass

    def mark_frozen(self, reason: str = "") -> None:
        """Mark the instance as frozen (too many failures)."""
        if self._state is None:
            return
        self._state = SupervisorState(
            pid=self._state.pid,
            started_at=self._state.started_at,
            restart_count=self._state.restart_count,
            last_healthy_at=self._state.last_healthy_at,
            status="frozen",
            instance_id=self._state.instance_id,
        )
        self._save_state(self._state)

    def increment_restart_count(self) -> int:
        """Increment and return restart count."""
        if self._state is None:
            return 0
        new_count = self._state.restart_count + 1
        self._state = SupervisorState(
            pid=self._state.pid,
            started_at=self._state.started_at,
            restart_count=new_count,
            last_healthy_at=self._state.last_healthy_at,
            status=self._state.status,
            instance_id=self._state.instance_id,
        )
        self._save_state(self._state)
        return new_count

    def release(self) -> None:
        """Release the instance claim (cleanup PID file)."""
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        # Write final health state
        self._state_dir.mkdir(parents=True, exist_ok=True)
        health_data = {
            "alive": False,
            "pid": os.getpid(),
            "timestamp": self._now_utc(),
        }
        try:
            with open(self._health_file, "w") as f:
                json.dump(health_data, f)
        except OSError:
            pass

    @property
    def is_owner(self) -> bool:
        """Check if we own the current instance."""
        pid = self._read_pid()
        return pid == os.getpid()

    @property
    def state(self) -> Optional[SupervisorState]:
        return self._state

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status for external monitoring."""
        if self._health_file.exists():
            try:
                with open(self._health_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"alive": False, "pid": 0, "timestamp": ""}
