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
