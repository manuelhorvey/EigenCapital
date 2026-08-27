"""Portfolio Health Monitoring — fail-closed operational state assessment.

The health monitor evaluates an account snapshot against the risk policy
and emits structured alerts into an immutable, hash-chained event log.

Design rules:
- Fail closed: missing/stale/unparseable inputs degrade the health state,
  never improve it.
- Hard-constraint breaches are CRITICAL; diagnostic threshold breaches are
  WARNING.
- The event log is append-only and hash-chained; any retroactive edit
  invalidates the chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from eigencapital.execution.account import AccountSnapshot
from eigencapital.risk.policy import RiskPolicy


class HealthState(str, Enum):
    """Overall portfolio health state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    FROZEN = "frozen"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


ALERT_SNAPSHOT_STALE = "snapshot_stale"
ALERT_SNAPSHOT_UNPARSEABLE = "snapshot_timestamp_unparseable"
ALERT_KILL_SWITCH = "kill_switch_active"
ALERT_MIN_EQUITY = "min_equity_breach"
ALERT_MAX_DRAWDOWN = "max_drawdown_breach"
ALERT_WARN_DRAWDOWN = "drawdown_warning"
ALERT_DAILY_LOSS = "daily_loss_breach"
ALERT_WARN_DAILY_LOSS = "daily_loss_warning"
ALERT_WEEKLY_LOSS = "weekly_loss_breach"
ALERT_GROSS_LEVERAGE = "gross_leverage_breach"
ALERT_WARN_GROSS_LEVERAGE = "gross_leverage_warning"
ALERT_POSITION_COUNT = "position_count_breach"
ALERT_CONCENTRATION = "concentration_breach"
ALERT_ASSET_CLASS_EXPOSURE = "asset_class_exposure_breach"


@dataclass(frozen=True)
class Alert:
    """A single structured alert."""

    severity: Severity
    code: str
    message: str
    observed: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class HealthReport:
    """Result of one health assessment."""

    state: HealthState
    alerts: Tuple[Alert, ...] = ()
    checks: Dict[str, bool] = field(default_factory=dict)
    assessed_at_utc: str = ""
    snapshot_age_seconds: Optional[float] = None

    @property
    def is_operational(self) -> bool:
        """Only HEALTHY and DEGRADED states permit continued operation."""
        return self.state in (HealthState.HEALTHY, HealthState.DEGRADED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "alerts": [a.to_dict() for a in self.alerts],
            "checks": dict(self.checks),
            "assessed_at_utc": self.assessed_at_utc,
            "snapshot_age_seconds": self.snapshot_age_seconds,
        }


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


class PortfolioHealthMonitor:
    """Assesses account health against the risk policy. Fail-closed.

    Tracks peak equity across successive assessments for drawdown
    evaluation. Every assessment appends to the immutable event log.
    """

    def __init__(
        self,
        policy: RiskPolicy,
        *,
        max_snapshot_age_seconds: float = 300.0,
        clock: Optional[datetime] = None,
    ) -> None:
        if max_snapshot_age_seconds <= 0:
            raise ValueError("max_snapshot_age_seconds must be > 0")
        self._policy = policy
        self._max_age = max_snapshot_age_seconds
        self._clock = clock
        self._peak_equity: Optional[float] = None
        self._log: List[Dict[str, Any]] = []
        self._last_prev_hash: str = hashlib.sha256(b"genesis").hexdigest()

    # ── Assessment ────────────────────────────────────────────────────

    def assess(
        self,
        snapshot: AccountSnapshot,
        *,
        daily_pnl: Optional[float] = None,
        weekly_pnl: Optional[float] = None,
        position_notionals: Optional[Dict[str, float]] = None,
        asset_class_exposure: Optional[Dict[str, float]] = None,
        kill_switch_active: bool = False,
        now_utc: Optional[str] = None,
    ) -> HealthReport:
        """Evaluate one snapshot. Unknown inputs produce no pass."""
        p = self._policy
        parsed_now: Optional[datetime] = None
        if now_utc is not None:
            parsed_now = _parse_ts(now_utc)
        now = parsed_now or self._clock or datetime.now(timezone.utc)
        alerts: List[Alert] = []
        checks: Dict[str, bool] = {}
        age: Optional[float] = None

        snap_dt = _parse_ts(snapshot.timestamp_utc)
        if snap_dt is None:
            alerts.append(
                Alert(
                    Severity.CRITICAL,
                    ALERT_SNAPSHOT_UNPARSEABLE,
                    "Snapshot timestamp unparseable; cannot verify freshness",
                    observed=str(snapshot.timestamp_utc),
                )
            )
            checks["snapshot_fresh"] = False
        else:
            age = (now - snap_dt).total_seconds()
            fresh = 0.0 <= age <= self._max_age
            checks["snapshot_fresh"] = fresh
            if not fresh:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_SNAPSHOT_STALE,
                        f"Snapshot age {age:.0f}s exceeds limit {self._max_age:.0f}s",
                        observed=f"{age:.1f}",
                    )
                )

        if kill_switch_active:
            alerts.append(
                Alert(
                    Severity.CRITICAL,
                    ALERT_KILL_SWITCH,
                    "Kill switch active; all trading halted",
                )
            )

        equity = snapshot.equity
        if equity <= 0:
            alerts.append(
                Alert(
                    Severity.CRITICAL,
                    ALERT_MIN_EQUITY,
                    f"Equity {equity:.2f} <= 0; fail-closed",
                    observed=f"{equity:.2f}",
                )
            )
            checks["min_equity"] = False
        else:
            checks["min_equity"] = equity >= p.min_equity
            if not checks["min_equity"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_MIN_EQUITY,
                        f"Equity {equity:.2f} below floor {p.min_equity:.2f}",
                        observed=f"{equity:.2f}",
                    )
                )

            if self._peak_equity is None or equity > self._peak_equity:
                self._peak_equity = equity
            peak = self._peak_equity or equity
            dd_pct = max(0.0, (peak - equity) / peak * 100.0)

            checks["max_drawdown"] = dd_pct <= p.max_drawdown_pct
            if not checks["max_drawdown"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_MAX_DRAWDOWN,
                        f"Drawdown {dd_pct:.2f}% exceeds limit "
                        f"{p.max_drawdown_pct:.2f}%",
                        observed=f"{dd_pct:.4f}",
                    )
                )
            elif dd_pct > p.warn_drawdown_pct:
                alerts.append(
                    Alert(
                        Severity.WARNING,
                        ALERT_WARN_DRAWDOWN,
                        f"Drawdown {dd_pct:.2f}% above warning level "
                        f"{p.warn_drawdown_pct:.2f}%",
                        observed=f"{dd_pct:.4f}",
                    )
                )

            gross_lev = abs(snapshot.gross_exposure) / equity
            checks["gross_leverage"] = gross_lev <= p.max_gross_leverage
            if not checks["gross_leverage"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_GROSS_LEVERAGE,
                        f"Gross leverage {gross_lev:.3f} exceeds limit "
                        f"{p.max_gross_leverage:.3f}",
                        observed=f"{gross_lev:.4f}",
                    )
                )
            elif gross_lev > p.warn_gross_leverage:
                alerts.append(
                    Alert(
                        Severity.WARNING,
                        ALERT_WARN_GROSS_LEVERAGE,
                        f"Gross leverage {gross_lev:.3f} above warning level "
                        f"{p.warn_gross_leverage:.3f}",
                        observed=f"{gross_lev:.4f}",
                    )
                )

            checks["position_count"] = snapshot.num_positions <= p.max_position_count
            if not checks["position_count"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_POSITION_COUNT,
                        f"{snapshot.num_positions} positions exceeds limit "
                        f"{p.max_position_count}",
                        observed=str(snapshot.num_positions),
                    )
                )

            if position_notionals:
                worst_sym, worst_val = "", 0.0
                for sym, notional in sorted(position_notionals.items()):
                    conc = abs(notional) / equity * 100.0
                    if conc > worst_val:
                        worst_sym, worst_val = sym, conc
                checks["concentration"] = worst_val <= p.max_concentration_pct
                if not checks["concentration"]:
                    alerts.append(
                        Alert(
                            Severity.CRITICAL,
                            ALERT_CONCENTRATION,
                            f"{worst_sym} concentration {worst_val:.2f}% "
                            f"exceeds limit {p.max_concentration_pct:.2f}%",
                            observed=worst_sym,
                        )
                    )

            if asset_class_exposure:
                breached = {
                    cls: pct
                    for cls, pct in sorted(asset_class_exposure.items())
                    if abs(pct) / equity * 100.0 > p.max_asset_class_exposure_pct
                }
                checks["asset_class_exposure"] = not breached
                for cls, pct in breached.items():
                    alerts.append(
                        Alert(
                            Severity.CRITICAL,
                            ALERT_ASSET_CLASS_EXPOSURE,
                            f"{cls} exposure {abs(pct) / equity * 100.0:.2f}% "
                            f"exceeds cap "
                            f"{p.max_asset_class_exposure_pct:.2f}%",
                            observed=cls,
                        )
                    )

        if daily_pnl is not None:
            lost = -daily_pnl
            checks["daily_loss"] = lost <= p.daily_loss_limit
            if not checks["daily_loss"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_DAILY_LOSS,
                        f"Daily loss {lost:.2f} exceeds limit {p.daily_loss_limit:.2f}",
                        observed=f"{lost:.2f}",
                    )
                )
            elif lost > p.warn_daily_loss:
                alerts.append(
                    Alert(
                        Severity.WARNING,
                        ALERT_WARN_DAILY_LOSS,
                        f"Daily loss {lost:.2f} above warning level "
                        f"{p.warn_daily_loss:.2f}",
                        observed=f"{lost:.2f}",
                    )
                )

        if weekly_pnl is not None:
            lost = -weekly_pnl
            checks["weekly_loss"] = lost <= p.weekly_loss_limit
            if not checks["weekly_loss"]:
                alerts.append(
                    Alert(
                        Severity.CRITICAL,
                        ALERT_WEEKLY_LOSS,
                        f"Weekly loss {lost:.2f} exceeds limit "
                        f"{p.weekly_loss_limit:.2f}",
                        observed=f"{lost:.2f}",
                    )
                )

        has_critical = any(a.severity == Severity.CRITICAL for a in alerts)
        has_warning = any(a.severity == Severity.WARNING for a in alerts)
        if kill_switch_active:
            state = HealthState.FROZEN
        elif has_critical:
            state = HealthState.CRITICAL
        elif has_warning:
            state = HealthState.DEGRADED
        else:
            state = HealthState.HEALTHY

        report = HealthReport(
            state=state,
            alerts=tuple(alerts),
            checks=checks,
            assessed_at_utc=now.isoformat(),
            snapshot_age_seconds=age,
        )
        self._append_log("health_assessment", report.to_dict(), now)
        return report

    # ── Immutable event log ───────────────────────────────────────────

    def _append_log(self, kind: str, payload: Dict[str, Any], when: datetime) -> None:
        seq = len(self._log)
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        entry = {
            "seq": seq,
            "kind": kind,
            "timestamp_utc": when.isoformat(),
            "payload_sha256": hashlib.sha256(body).hexdigest(),
            "prev_entry_hash": self._last_prev_hash,
        }
        entry_hash = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode("utf-8")
        ).hexdigest()
        entry["entry_hash"] = entry_hash
        self._log.append(entry)
        self._last_prev_hash = entry_hash

    @property
    def event_log(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(self._log)

    def verify_log_integrity(self) -> bool:
        """Recompute the full hash chain over the public event log.

        Verification reads ``event_log`` so that any tampering visible
        to consumers is detectable, regardless of internal state.
        """
        prev = hashlib.sha256(b"genesis").hexdigest()
        for i, entry in enumerate(self.event_log):
            if entry["seq"] != i or entry["prev_entry_hash"] != prev:
                return False
            material = {k: v for k, v in entry.items() if k != "entry_hash"}
            expected = hashlib.sha256(
                json.dumps(material, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if entry["entry_hash"] != expected:
                return False
            prev = entry["entry_hash"]
        return True
