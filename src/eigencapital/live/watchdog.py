"""Independent watchdog — blind-window detection and containment.

C4 of the P0 Safety Remediation campaign. Addresses the observed 9.5-hour
window (2026-08-25 15:13Z -> 00:20Z) during which the trading loop was blind,
no reduction path existed, and nothing escalated.

Pure decision engine over injected probes (fully testable offline):

  NORMAL -> DEGRADED  (process dead OR audit trail stale OR equity read failed)
         -> BLIND     (DEGRADED persists past blind_after_seconds, or broker
                       probe fails while process evidence is also stale)
         -> CONTAIN   (BLIND persists past contain_after_seconds: authorize
                       flatten-on-reconnect; no new trading authorization)
  Reconnect path requires reconciliation BEFORE resuming (A9):
  CONTAIN -> RECONCILING -> RESUMED only if reconcile() passes; else HALTED.

Every decision carries broker-state evidence hash + probe details (A7).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class WatchState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    BLIND = "BLIND"
    CONTAIN = "CONTAIN"
    RECONCILING = "RECONCILING"
    HALTED = "HALTED"
    RESUMED = "RESUMED"


@dataclass(frozen=True)
class ProbeResult:
    process_alive: bool
    trail_age_seconds: float | None  # age of decisions.jsonl / heartbeat
    equity_read_ok: bool
    broker_reachable: bool
    evidence_hash: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WatchDecision:
    state: WatchState
    previous_state: WatchState
    authorize_trading: bool
    authorize_flatten_on_reconnect: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


class Watchdog:
    """Threshold-driven escalation with sticky containment.

    ID-008: State Machine Invariants
    ================================

    Trading authorization requires BOTH machines to agree:

    INVARIANT 1: Trading authorized IFF
        watchdog.state == NORMAL
        AND disconnect_recovery.state in {CONNECTED, RESUMED}

    INVARIANT 2: Escalation is monotonic (no spontaneous de-escalation)
        NORMAL → DEGRADED → BLIND → CONTAIN (forward only)
        De-escalation only via explicit reset or reconciliation

    INVARIANT 3: CONTAIN is sticky
        Once CONTAIN is reached, only manual reset or clean
        reconciliation can restore NORMAL. Automatic recovery
        from CONTAIN is NOT possible.

    INVARIANT 4: DisconnectRecovery RECONCILING requires clean reconcile
        RECONCILING → RESUMED only if all reconciliation checks pass
        RECONCILING → HALTED on any failure

    INVARIANT 5: HALTED is terminal until manual intervention
        HALTED cannot be exited automatically.
        Operator must call request_resume() with explicit conditions.
    """

    def __init__(
        self,
        stale_after_seconds: float,
        blind_after_seconds: float,
        contain_after_seconds: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (0 < stale_after_seconds <= blind_after_seconds <= contain_after_seconds):
            raise ValueError("thresholds must satisfy 0 < stale <= blind <= contain")
        self._stale_after = stale_after_seconds
        self._blind_after = blind_after_seconds
        self._contain_after = contain_after_seconds
        self._now = now
        self.state = WatchState.NORMAL
        self._degraded_since: float | None = None
        self._blind_since: float | None = None
        self._contain_since: float | None = None

    # ── helpers ────────────────────────────────────────────────────
    def _duration(self, since: float | None) -> float:
        return 0.0 if since is None else self._now() - since

    def reset_for_reconciliation(self) -> None:
        self.state = WatchState.RECONCILING

    def complete_reconciliation(self, clean: bool) -> WatchDecision:
        prev = self.state
        if self.state not in (
            WatchState.RECONCILING,
            WatchState.CONTAIN,
            WatchState.HALTED,
        ):
            return WatchDecision(
                self.state,
                prev,
                False,
                False,
                "reconciliation requested outside CONTAIN/HALT",
            )
        if clean:
            self.state = WatchState.RESUMED
            return WatchDecision(self.state, prev, True, False, "reconciled clean; trading re-authorized")
        self.state = WatchState.HALTED
        return WatchDecision(
            self.state,
            prev,
            False,
            True,
            "reconciliation FAILED — HALTED, flatten intent retained",
        )

    # ── main tick ──────────────────────────────────────────────────
    def evaluate(self, probe: ProbeResult) -> WatchDecision:
        prev = self.state
        now = self._now()
        ev = {
            "probe": {
                "process_alive": probe.process_alive,
                "trail_age_s": probe.trail_age_seconds,
                "equity_read_ok": probe.equity_read_ok,
                "broker_reachable": probe.broker_reachable,
            },
            "evidence_hash": probe.evidence_hash,
            **probe.details,
        }

        # Sticky terminal states
        if self.state is WatchState.HALTED:
            return WatchDecision(
                WatchState.HALTED,
                prev,
                False,
                True,
                "HALTED is sticky; manual review required",
                ev,
            )
        if self.state is WatchState.CONTAIN:
            return WatchDecision(
                WatchState.CONTAIN,
                prev,
                False,
                True,
                "CONTAIN sticky until reconciliation",
                ev,
            )

        # Severity model:
        #   degraded = any unhealthy probe (process/trail/equity/reachability)
        #   severe   = evidence untrustworthy NOW (broker unreachable, or trail
        #              older than the blind threshold) -> BLIND immediately;
        #              duration drives CONTAIN escalation, not re-classification.
        degraded_signal = (
            (not probe.process_alive)
            or (not probe.broker_reachable)
            or (not probe.equity_read_ok)
            or (probe.trail_age_seconds is not None and probe.trail_age_seconds > self._stale_after)
        )
        blind_signal = degraded_signal and (
            (not probe.broker_reachable)
            or (probe.trail_age_seconds is not None and probe.trail_age_seconds > self._blind_after)
        )

        if not degraded_signal:
            self._degraded_since = None
            self._blind_since = None
            self._contain_since = None
            self.state = WatchState.NORMAL
            return WatchDecision(WatchState.NORMAL, prev, True, False, "all probes healthy", ev)

        if self._degraded_since is None:
            self._degraded_since = now
        deg_dur = self._duration(self._degraded_since)

        if blind_signal:
            if self._blind_since is None:
                self._blind_since = now
        else:
            self._blind_since = None
        blind_dur = self._duration(self._blind_since)

        if deg_dur >= self._contain_after:
            self.state = WatchState.CONTAIN
            self._contain_since = now
            return WatchDecision(
                self.state,
                prev,
                False,
                True,
                f"abnormal condition persisted {max(blind_dur, deg_dur):.0f}s "
                f"(>={self._contain_after:.0f}s): containment authorized",
                ev,
            )
        if blind_signal:
            self.state = WatchState.BLIND
            return WatchDecision(
                self.state,
                prev,
                False,
                False,
                f"untrustworthy evidence (blind {blind_dur:.0f}s)",
                ev,
            )
        self.state = WatchState.DEGRADED
        return WatchDecision(
            self.state,
            prev,
            False,
            False,
            f"degraded for {deg_dur:.0f}s (process/trail/equity probe unhealthy)",
            ev,
        )


# ── filesystem/broker probe adapters (thin IO layer) ───────────────


def trail_age_seconds(audit_file: Path, now_s: float | None = None) -> float | None:
    """Compute audit trail age from last record's timestamp (P1-007).

    Reads the last line of the JSONL audit file and extracts the "timestamp"
    field. Falls back to file mtime if JSON parsing fails (e.g., on network
    filesystems where mtime may be unreliable).
    """
    import json as _json
    from datetime import datetime as _dt

    ref = time.time() if now_s is None else now_s
    try:
        # Read last non-empty line from JSONL file
        last_line = ""
        with open(audit_file, "rb") as f:
            f.seek(0, 2)  # seek to end
            fsize = f.tell()
            # Read last 4KB to find the final record
            read_size = min(4096, fsize)
            f.seek(max(0, fsize - read_size))
            tail = f.read().decode("utf-8", errors="replace")
            for line in reversed(tail.split("\n")):
                line = line.strip()
                if line:
                    last_line = line
                    break

        if last_line:
            record = _json.loads(last_line)
            ts_str = record.get("timestamp", "")
            if ts_str:
                # Parse ISO timestamp
                last_ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                return max(0.0, ref - last_ts)
    except (OSError, _json.JSONDecodeError, ValueError, KeyError):
        pass

    # Fallback: file mtime (less reliable on network FS)
    try:
        mtime = audit_file.stat().st_mtime
        return max(0.0, ref - mtime)
    except OSError:
        return None


def process_alive(pattern: str = "r4_rebalance_loop") -> bool:
    import subprocess

    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
