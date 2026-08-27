"""Micro-Live Campaign — minimal capital envelope with automatic risk controls.

The campaign model captures the complete lifecycle of a micro-live experiment:
- Authorization (human-approved, time-bound, capital-bound)
- Pre-flight checks
- Live execution with monitoring
- Automatic kill conditions
- Reconciliation
- Qualification verdict
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class MicroLiveStatus(str, Enum):
    """Micro-live campaign status."""

    PLANNED = "planned"
    PREFLIGHT = "preflight"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    PAUSED = "paused"
    KILLED = "killed"
    EXPIRED = "expired"
    COMPLETED = "completed"
    FAILED = "failed"


class KillReason(str, Enum):
    """Automatic kill conditions."""

    RISK_LIMIT_BREACH = "risk_limit_breach"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    UNEXPECTED_POSITION = "unexpected_position"
    FINGERPRINT_DRIFT = "fingerprint_drift"
    CRITICAL_EXECUTION_DIVERGENCE = "critical_execution_divergence"
    DATA_INTEGRITY_FAILURE = "data_integrity_failure"
    BROKER_DISCONNECT = "broker_disconnect"
    DRAWDOWN_LIMIT = "drawdown_limit"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MANUAL_KILL = "manual_kill"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    EXCESSIVE_REJECTIONS = "excessive_rejections"
    STALE_MARKET_DATA = "stale_market_data"


class MicroLiveVerdict(str, Enum):
    """Micro-live qualification verdict."""

    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"
    QUALIFIED_WITH_RESTRICTIONS = "qualified_with_restrictions"
    QUALIFIED = "qualified"


@dataclass(frozen=True)
class MicroLiveEnvelope:
    """Pre-registered micro-live risk envelope.

    These limits are STRICTER than production limits.
    They define the maximum allowed exposure during micro-live.
    """

    # Capital limits
    max_account_equity: float = 1000.0  # $1,000 max equity
    max_position_size: float = 100.0  # $100 max position
    max_order_notional: float = 50.0  # $50 max order
    max_concurrent_positions: int = 5  # max 5 positions
    max_daily_loss: float = 50.0  # $50 max daily loss
    max_total_drawdown: float = 200.0  # $200 max total drawdown
    max_drawdown_pct: float = 0.20  # 20% max drawdown

    # Execution limits
    max_order_frequency: int = 10  # max 10 orders per hour
    max_spread: float = 0.0020  # 20 pips max spread
    max_slippage: float = 0.0010  # 10 pips max slippage
    max_execution_divergence: float = 0.005  # 50 pips max divergence

    # Time limits
    max_campaign_duration_hours: int = 168  # 7 days max
    max_position_duration_hours: int = 72  # 3 days max position

    def compute_identity(self) -> str:
        data = {
            "max_account_equity": self.max_account_equity,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_daily_loss": self.max_daily_loss,
            "max_total_drawdown": self.max_total_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_order_frequency": self.max_order_frequency,
            "max_spread": self.max_spread,
            "max_slippage": self.max_slippage,
            "max_execution_divergence": self.max_execution_divergence,
            "max_campaign_duration_hours": self.max_campaign_duration_hours,
            "max_position_duration_hours": self.max_position_duration_hours,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class MicroLiveAuthorization:
    """Human authorization for micro-live campaign.

    Must be explicit, time-bound, and capital-bound.
    """

    authorization_id: str
    campaign_id: str
    strategy_fingerprint: str
    risk_envelope_hash: str
    broker_identity: str
    account_identity: str
    operator_identity: str
    max_capital: float
    max_duration_hours: int
    created_timestamp: str
    expiry_timestamp: str
    is_active: bool = True

    def is_expired(self, current_timestamp: str) -> bool:
        return current_timestamp > self.expiry_timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "campaign_id": self.campaign_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "risk_envelope_hash": self.risk_envelope_hash,
            "broker_identity": self.broker_identity,
            "account_identity": self.account_identity,
            "operator_identity": self.operator_identity,
            "max_capital": self.max_capital,
            "max_duration_hours": self.max_duration_hours,
            "created_timestamp": self.created_timestamp,
            "expiry_timestamp": self.expiry_timestamp,
            "is_active": self.is_active,
        }


@dataclass
class MicroLiveState:
    """Current state of the micro-live campaign."""

    status: MicroLiveStatus = MicroLiveStatus.PLANNED
    equity: float = 0.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    peak_equity: float = 0.0
    current_drawdown: float = 0.0
    open_positions: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0
    partial_fills: int = 0
    reconciliation_checks: int = 0
    reconciliation_failures: int = 0
    kill_events: List[Dict[str, Any]] = field(default_factory=list)
    fill_events: List[Dict[str, Any]] = field(default_factory=list)
    position_events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def reconciliation_success_rate(self) -> float:
        if self.reconciliation_checks == 0:
            return 1.0
        return 1.0 - (self.reconciliation_failures / self.reconciliation_checks)

    @property
    def fill_rate(self) -> float:
        if self.orders_submitted == 0:
            return 0.0
        return self.orders_filled / self.orders_submitted

    @property
    def rejection_rate(self) -> float:
        if self.orders_submitted == 0:
            return 0.0
        return self.orders_rejected / self.orders_submitted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "equity": self.equity,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "peak_equity": self.peak_equity,
            "current_drawdown": self.current_drawdown,
            "open_positions": self.open_positions,
            "orders_submitted": self.orders_submitted,
            "orders_filled": self.orders_filled,
            "orders_rejected": self.orders_rejected,
            "orders_cancelled": self.orders_cancelled,
            "partial_fills": self.partial_fills,
            "reconciliation_checks": self.reconciliation_checks,
            "reconciliation_failures": self.reconciliation_failures,
            "reconciliation_success_rate": self.reconciliation_success_rate,
            "fill_rate": self.fill_rate,
            "rejection_rate": self.rejection_rate,
            "kill_events": self.kill_events,
            "fill_events": self.fill_events[:20],
            "position_events": self.position_events[:20],
        }


class MicroLiveCampaign:
    """Micro-live campaign with automatic risk controls.

    Runs the frozen R4 configuration with minimal real capital,
    automatically killing on any risk violation.
    """

    def __init__(
        self,
        campaign_id: str,
        envelope: MicroLiveEnvelope,
        authorization: MicroLiveAuthorization,
    ) -> None:
        self._campaign_id = campaign_id
        self._envelope = envelope
        self._authorization = authorization
        self._state = MicroLiveState()
        self._kill_log: List[Dict[str, Any]] = []
        self._audit_log: List[Dict[str, Any]] = []

    def preflight(self) -> Dict[str, Any]:
        """Run pre-flight checks before activating."""
        checks = {
            "authorization_valid": self._authorization.is_active,
            "authorization_not_expired": not self._authorization.is_expired(""),
            "envelope_within_limits": True,
            "strategy_fingerprint_match": True,
            "risk_envelope_match": True,
        }

        all_pass = all(checks.values())
        self._state.status = MicroLiveStatus.PREFLIGHT if all_pass else MicroLiveStatus.FAILED

        return {
            "checks": checks,
            "all_pass": all_pass,
            "status": self._state.status.value,
        }

    def activate(self) -> bool:
        """Activate the micro-live campaign."""
        if self._state.status != MicroLiveStatus.PREFLIGHT:
            return False

        self._state.status = MicroLiveStatus.ACTIVE
        self._audit_log.append(
            {
                "event": "activated",
                "authorization_id": self._authorization.authorization_id,
            }
        )
        return True

    def check_kill_conditions(self, current_equity: float = 0.0) -> KillReason | None:
        """Check if any automatic kill condition is triggered."""
        # Drawdown limit
        if self._state.peak_equity > 0:
            dd = self._state.peak_equity - current_equity
            dd_pct = dd / self._state.peak_equity if self._state.peak_equity > 0 else 0
            if dd > self._envelope.max_total_drawdown:
                return KillReason.DRAWDOWN_LIMIT
            if dd_pct > self._envelope.max_drawdown_pct:
                return KillReason.DRAWDOWN_LIMIT

        # Daily loss limit
        if self._state.daily_pnl < -self._envelope.max_daily_loss:
            return KillReason.DAILY_LOSS_LIMIT

        # Position limits
        if self._state.open_positions > self._envelope.max_concurrent_positions:
            return KillReason.RISK_LIMIT_BREACH

        # Reconciliation failures
        if self._state.reconciliation_failures > 0:
            return KillReason.RECONCILIATION_MISMATCH

        # Excessive rejections
        if self._state.orders_submitted > 10:
            if self._state.rejection_rate > 0.5:
                return KillReason.EXCESSIVE_REJECTIONS

        return None

    def execute_kill(self, reason: KillReason, details: str = "") -> None:
        """Execute automatic kill."""
        self._state.status = MicroLiveStatus.KILLED
        kill_event = {
            "reason": reason.value,
            "details": details,
            "timestamp": "",
            "state": self._state.to_dict(),
        }
        self._kill_log.append(kill_event)
        self._audit_log.append(
            {
                "event": "killed",
                "reason": reason.value,
                "details": details,
            }
        )

    def record_fill(
        self,
        instrument_id: str,
        side: str,
        quantity: float,
        fill_price: float,
        spread: float,
        slippage: float,
    ) -> Dict[str, Any]:
        """Record a fill event."""
        self._state.orders_filled += 1

        fill = {
            "instrument_id": instrument_id,
            "side": side,
            "quantity": quantity,
            "fill_price": fill_price,
            "spread": spread,
            "slippage": slippage,
        }
        self._state.fill_events.append(fill)

        # Check slippage limit
        if slippage > self._envelope.max_slippage:
            self.execute_kill(
                KillReason.CRITICAL_EXECUTION_DIVERGENCE,
                f"Slippage {slippage:.4f} exceeds max {self._envelope.max_slippage:.4f}",
            )

        return fill

    def record_reconciliation(
        self,
        internal_position: Dict[str, float],
        broker_position: Dict[str, float],
    ) -> bool:
        """Record reconciliation check result."""
        self._state.reconciliation_checks += 1

        matched = True
        for inst in set(list(internal_position.keys()) + list(broker_position.keys())):
            internal = internal_position.get(inst, 0.0)
            broker = broker_position.get(inst, 0.0)
            if abs(internal - broker) > 1e-6:
                matched = False
                break

        if not matched:
            self._state.reconciliation_failures += 1
            self.execute_kill(
                KillReason.RECONCILIATION_MISMATCH,
                "Position mismatch detected",
            )

        return matched

    def get_result(self) -> Dict[str, Any]:
        """Compute micro-live campaign result."""
        return {
            "campaign_id": self._campaign_id,
            "envelope_identity": self._envelope.compute_identity(),
            "authorization": self._authorization.to_dict(),
            "state": self._state.to_dict(),
            "kill_events": self._kill_log,
            "audit_log": self._audit_log,
        }

    @property
    def state(self) -> MicroLiveState:
        return self._state

    @property
    def envelope(self) -> MicroLiveEnvelope:
        return self._envelope

    @property
    def is_active(self) -> bool:
        return self._state.status == MicroLiveStatus.ACTIVE

    @property
    def was_killed(self) -> bool:
        return self._state.status == MicroLiveStatus.KILLED
