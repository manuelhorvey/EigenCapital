"""Alert delivery (Phase 1U item 6) - structured, durable, operator-visible.

Strictly DOWNSTREAM of enforcement: dispatch failures are swallowed and
reported via return value only. An alerting outage can never alter a
safety decision (halt/blocked states remain exactly as decided).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional


class Severity:
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class Alert:
    severity: str
    event: str
    message: str
    ts_utc: str = ""
    details: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"severity": self.severity, "event": self.event,
             "message": self.message, "ts_utc": self.ts_utc}
        if self.details is not None:
            d["details"] = self.details
        return d


class AlertDispatcher:
    """Durable JSONL sink + operator-visible stderr mirror."""

    def __init__(self, path: str = "reports/alerts.jsonl",
                 mirror_stderr: bool = True) -> None:
        self.path = path
        self.mirror_stderr = mirror_stderr

    def dispatch(self, alert: Alert) -> bool:
        """Deliver one alert. NEVER raises - delivery failure is not a
        safety input. Returns True when durably written."""
        line = json.dumps(alert.to_dict(), sort_keys=True)
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            return False
        if self.mirror_stderr and alert.severity in (
                Severity.CRITICAL, Severity.WARNING):
            print(line, file=sys.stderr)
        return True

    def dispatch_all(self, alerts: List[Alert]) -> int:
        return sum(1 for a in alerts if self.dispatch(a))

    def read_durable(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]


def alert_for_stop_reason(reason: str) -> Alert:
    sev = Severity.CRITICAL if reason not in (
        "RECONCILIATION_REQUIRED",) else Severity.WARNING
    return Alert(severity=sev, event="live_runner_stop", message=reason,
                 ts_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
