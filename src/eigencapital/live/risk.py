"""Micro-Live Risk Envelope — stricter than normal production limits.

The micro-live envelope must be independently fingerprinted.
Any breach blocks new orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

from eigencapital.risk.checks.account_checks import (
    AccountState,
    run_all_account_checks,
)
from eigencapital.risk.policy import RiskPolicy


class StopReason(str, Enum):
    """Reason for stopping new orders."""

    DAILY_LOSS = "daily_loss"
    TOTAL_DRAWDOWN = "total_drawdown"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    BROKER_UNAVAILABLE = "broker_unavailable"
    DATA_STALE = "data_stale"
    SPREAD_EXCESSIVE = "spread_excessive"
    SLIPPAGE_EXCESSIVE = "slippage_excessive"
    UNEXPECTED_POSITION = "unexpected_position"
    UNEXPECTED_FILL = "unexpected_fill"
    RISK_UNAVAILABLE = "risk_unavailable"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    EXCESSIVE_REJECTION = "excessive_rejection"
    EXECUTION_DIVERGENCE = "execution_divergence"
    CLOCK_FAILURE = "clock_failure"
    ACCOUNT_MISMATCH = "account_mismatch"
    KILL_SWITCH = "kill_switch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MicroLiveLimits:
    """Micro-live risk envelope — stricter than normal production limits."""

    max_account_exposure: float = 10000.0
    max_position_size: float = 1000.0
    max_order_notional: float = 5000.0
    max_concurrent_positions: int = 3
    max_daily_loss: float = 500.0
    max_total_drawdown: float = 2000.0
    max_order_frequency: int = 10  # per hour
    max_spread: float = 0.01
    max_slippage: float = 0.005
    max_execution_divergence: float = 0.02

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_account_exposure": self.max_account_exposure,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_daily_loss": self.max_daily_loss,
            "max_total_drawdown": self.max_total_drawdown,
            "max_order_frequency": self.max_order_frequency,
            "max_spread": self.max_spread,
            "max_slippage": self.max_slippage,
            "max_execution_divergence": self.max_execution_divergence,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PreflightCheck:
    """Result of a preflight check."""

    check_name: str
    passed: bool
    severity: str = "CRITICAL"
    details: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class MicroLiveRiskEnvelope:
    """Independent micro-live risk envelope.

    Stricter than normal production limits.
    Any breach blocks new orders.
    """

    def __init__(
        self,
        limits: Optional[MicroLiveLimits] = None,
        policy: Optional[RiskPolicy] = None,
        require_exposure_maps: bool = True,
    ) -> None:
        self._limits = limits or MicroLiveLimits()
        # Single source of truth for account-level live risk decisions.
        self._policy = policy or RiskPolicy()
        self._require_exposure_maps = require_exposure_maps
        self._daily_pnl: float = 0.0
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._stop_reasons: List[StopReason] = []
        self._order_count_hour: int = 0

    def check_order(
        self,
        notional: float,
        current_positions: int,
        spread: float = 0.0,
        slippage: float = 0.0,
    ) -> Tuple[bool, str]:
        """Check if an order is allowed within the micro-live envelope.

        Returns:
            (allowed, reason)
        """
        # Check notional
        if notional > self._limits.max_order_notional:
            return (
                False,
                f"Order notional {notional} exceeds max {self._limits.max_order_notional}",
            )

        # Check position count
        if current_positions >= self._limits.max_concurrent_positions:
            return (
                False,
                f"Position count {current_positions} >= max {self._limits.max_concurrent_positions}",
            )

        # Check spread
        if spread > self._limits.max_spread:
            return (False, f"Spread {spread} exceeds max {self._limits.max_spread}")

        # Check slippage
        if slippage > self._limits.max_slippage:
            return (
                False,
                f"Slippage {slippage} exceeds max {self._limits.max_slippage}",
            )

        # Check daily loss
        if self._daily_pnl < -self._limits.max_daily_loss:
            return (
                False,
                f"Daily loss {self._daily_pnl} exceeds max {self._limits.max_daily_loss}",
            )

        # Check drawdown
        if self._peak_equity > 0:
            drawdown = self._peak_equity - self._current_equity
            if drawdown > self._limits.max_total_drawdown:
                return (
                    False,
                    f"Drawdown {drawdown} exceeds max {self._limits.max_total_drawdown}",
                )

        # Check order frequency
        if self._order_count_hour >= self._limits.max_order_frequency:
            return (
                False,
                f"Order frequency {self._order_count_hour} >= max {self._limits.max_order_frequency}",
            )

        return (True, "Order allowed")

    def check_policy_state(self, state: AccountState) -> tuple:
        """Authoritative account-level gate via EigenRisk RiskPolicy.

        Fail-closed on missing exposure maps whenever positions are open:
        a live runner may never silently skip concentration / asset-class
        enforcement by omitting the maps.

        Returns:
            (allowed, reason)
        """
        position_count = int(getattr(state, "position_count", 0) or 0)
        if self._require_exposure_maps and position_count > 0:
            for attr in ("instrument_exposures", "asset_class_exposures"):
                if not getattr(state, attr, None):
                    return (
                        False,
                        f"exposure_map_missing:{attr} "
                        f"(fail-closed; populate from open positions)",
                    )
        results = run_all_account_checks(state, self._policy)
        failures = [r.message for r in results if r.status == "FAIL"]
        if failures:
            return False, "; ".join(failures)
        return True, "policy checks passed"

    def update_pnl(self, daily_pnl: float, current_equity: float) -> None:
        """Update P&L state."""
        self._daily_pnl = daily_pnl
        self._current_equity = current_equity
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

    def record_order(self) -> None:
        """Record an order for frequency tracking."""
        self._order_count_hour += 1

    def reset_hourly(self) -> None:
        """Reset hourly order count."""
        self._order_count_hour = 0

    @property
    def is_stop(self) -> bool:
        """Check if any stop condition is active."""
        return len(self._stop_reasons) > 0

    def add_stop_reason(self, reason: StopReason) -> None:
        self._stop_reasons.append(reason)

    def clear_stop_reasons(self) -> None:
        self._stop_reasons.clear()

    @property
    def limits(self) -> MicroLiveLimits:
        return self._limits


class LivePreflight:
    """Live preflight checks before authorization."""

    def __init__(self) -> None:
        self._checks: List[PreflightCheck] = []

    def run_check(
        self,
        check_name: str,
        passed: bool,
        severity: str = "CRITICAL",
        details: str = "",
        timestamp: str = "",
    ) -> PreflightCheck:
        """Run and record a preflight check."""
        check = PreflightCheck(
            check_name=check_name,
            passed=passed,
            severity=severity,
            details=details,
            timestamp=timestamp,
        )
        self._checks.append(check)
        return check

    def get_checks(self) -> List[PreflightCheck]:
        return list(self._checks)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self._checks)

    @property
    def critical_failures(self) -> List[PreflightCheck]:
        return [c for c in self._checks if not c.passed and c.severity == "CRITICAL"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self._checks],
            "all_passed": self.all_passed,
            "critical_failures": len(self.critical_failures),
        }


class HealthGateAction:
    TRADE = "TRADE"
    MANAGE_ONLY = "MANAGE_ONLY"
    HALT = "HALT"


class HealthGate:
    """Enforcement wrapper: monitor verdict -> execution permission.

    HEALTHY -> TRADE; DEGRADED -> MANAGE_ONLY (no new entries);
    CRITICAL/FROZEN -> HALT. Any monitor exception, unparseable result,
    or non-operational report fails closed to HALT.
    """

    _ACTION_BY_STATE = {
        "healthy": HealthGateAction.TRADE,
        "degraded": HealthGateAction.MANAGE_ONLY,
        "critical": HealthGateAction.HALT,
        "frozen": HealthGateAction.HALT,
    }

    def __init__(self, monitor) -> None:
        self._monitor = monitor
        self._transitions: List[Dict[str, Any]] = []

    def evaluate(self, snapshot, **kwargs) -> tuple:
        try:
            report = self._monitor.assess(snapshot, **kwargs)
            state = str(getattr(report, "state", "")).split(".")[-1].lower()
            if not getattr(report, "is_operational", False) and state == "degraded":
                state = "critical"
            action = self._ACTION_BY_STATE.get(state, HealthGateAction.HALT)
        except Exception as exc:  # noqa: BLE001 - fail closed on ANY error
            return HealthGateAction.HALT, f"health_assessment_failed:{exc}"
        self._record(action, state)
        return action, getattr(report, "message", state)

    def _record(self, action: str, state: str) -> None:
        prev = self._transitions[-1]["digest"] if self._transitions else ""
        entry = {"action": action, "state": state}
        digest = hashlib.sha256(
            (prev + json.dumps(entry, sort_keys=True)).encode()
        ).hexdigest()
        self._transitions.append({**entry, "digest": digest})

    def verify_transition_integrity(self) -> bool:
        prev = ""
        for t in self._transitions:
            expect = hashlib.sha256(
                (
                    prev
                    + json.dumps({k: t[k] for k in ("action", "state")}, sort_keys=True)
                ).encode()
            ).hexdigest()
            if t["digest"] != expect:
                return False
            prev = expect
        return True

    @property
    def transitions(self) -> List[Dict[str, Any]]:
        return list(self._transitions)


class RecoveryState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONCILING = "reconciling"
    HALTED = "halted"
    RESUMED = "resumed"
    FROZEN = "frozen"


class DisconnectRecovery:
    """State machine for broker disconnect recovery. Reconnect never
    grants permission by itself; only the FULL sequence (reconnect ->
    reconciliation match -> freshness -> risk -> fingerprint -> healthy)
    resumes trading. Excessive recovery cycles escalate to FROZEN.
    """

    def __init__(self, max_recovery_attempts: int = 3) -> None:
        if max_recovery_attempts < 1:
            raise ValueError("max_recovery_attempts must be >= 1")
        self._state = RecoveryState.CONNECTED
        self._attempts = 0
        self._max = max_recovery_attempts
        self._mismatch: str = ""
        self._flatten_required = False
        self._reconciled = False

    @property
    def state(self) -> RecoveryState:
        return self._state

    def on_disconnect(self) -> str:
        self._attempts += 1
        if self._attempts > self._max:
            self._state = RecoveryState.FROZEN
            return "FROZEN_EXCESSIVE_DISCONNECTS"
        self._state = RecoveryState.DISCONNECTED
        self._reconciled = False
        return "HALT_NEW_ORDERS"

    def on_reconnect(self) -> str:
        if self._state is not RecoveryState.DISCONNECTED:
            return f"INVALID:{self._state.value}"
        self._state = RecoveryState.RECONCILING
        return "RECONCILIATION_REQUIRED"

    def submit_reconciliation(
        self,
        positions_match: bool,
        orders_match: bool,
        equity_match: bool,
        fingerprint_match: bool,
        details: str = "",
    ) -> str:
        if self._state is not RecoveryState.RECONCILING:
            return f"INVALID:{self._state.value}"
        if not (
            positions_match and orders_match and equity_match and fingerprint_match
        ):
            self._mismatch = details or "unspecified_broker_mismatch"
            self._state = RecoveryState.HALTED
            return "HALT_RECONCILE_OR_FLATTEN"
        self._reconciled = True
        return "RECONCILED_AWAITING_RESUME_CHECKS"

    def request_resume(
        self,
        data_fresh: bool,
        positions_reconciled: bool,
        no_unexpected_orders: bool,
        risk_limits_passing: bool,
        config_fingerprint_unchanged: bool,
        health_state: str = "healthy",
        kill_switch_active: bool = False,
    ) -> str:
        if self._state is not RecoveryState.RECONCILING:
            return f"INVALID:{self._state.value}"
        if not self._reconciled:
            return "INVALID:reconciliation_not_submitted"
        checks = [
            data_fresh,
            positions_reconciled,
            no_unexpected_orders,
            risk_limits_passing,
            config_fingerprint_unchanged,
            health_state.lower() == "healthy",
            not kill_switch_active,
        ]
        if all(checks):
            self._state = RecoveryState.RESUMED
            return "TRADING_RESUMED"
        self._state = RecoveryState.HALTED
        failed = [
            n
            for n, ok in zip(
                [
                    "data_fresh",
                    "positions_reconciled",
                    "no_unexpected_orders",
                    "risk_limits_passing",
                    "config_fingerprint_unchanged",
                    "health_healthy",
                    "no_kill_switch",
                ],
                checks,
            )
            if not ok
        ]
        return "HALT:" + ",".join(failed)

    def authorize_reset(self) -> str:
        if self._state is RecoveryState.FROZEN:
            self._attempts = 0
            self._state = RecoveryState.HALTED
            return "RESET_TO_HALTED_MANUAL_REVIEW_REQUIRED"
        return f"INVALID:{self._state.value}"
