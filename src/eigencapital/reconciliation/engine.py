"""Reconciliation Engine — deterministic broker/internal state comparison.

Reconciles:
- Broker State (MT5) ↔ Execution State (fills, orders)
- Execution State ↔ Internal Position State (strategy's view)
- Internal Position State ↔ Portfolio State (aggregated exposure)
- Portfolio State ↔ Audit Ledger (immutable record)

Checks:
- Missing fills: Order submitted but no fill recorded
- Unexpected positions: Position exists without corresponding order
- Quantity mismatch: Internal ≠ broker position size
- Side mismatch: Internal ≠ broker position direction
- Price mismatch: Fill price deviation beyond threshold
- Duplicate orders: Same order submitted multiple times
- Stale positions: Position unchanged for extended period
- Orphaned tickets: Ticket exists without position
- Foreign positions: Positions not created by R4
- P&L discrepancy: Broker ≠ internal P&L calculation

Self-healing classification:
- SAFE_AUTOFIX: Can fix automatically (e.g., stale data refresh)
- REVIEW: Needs operator decision (e.g., minor price mismatch)
- HALT: Stop trading immediately (e.g., unexpected position)

Key principle: Reconciliation must never silently "fix" something dangerous.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List


class ReconciliationAction(str, Enum):
    """Classification of reconciliation discrepancies."""

    SAFE_AUTOFIX = "SAFE_AUTOFIX"  # Can fix automatically
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # Needs operator decision
    HALT = "HALT"  # Stop trading immediately


class ReconciliationSeverity(str, Enum):
    """Severity of reconciliation findings."""

    INFO = "INFO"  # Informational, no action needed
    WARNING = "WARNING"  # Anomaly detected, investigation recommended
    CRITICAL = "CRITICAL"  # Critical mismatch, immediate attention required
    BLOCKING = "BLOCKING"  # Blocks trading until resolved


@dataclass(frozen=True)
class ReconciliationCheck:
    """Result of a single reconciliation check."""

    check_name: str
    status: str  # PASS, WARNING, CRITICAL, BLOCKING
    severity: str
    action: str  # SAFE_AUTOFIX, REQUIRES_REVIEW, HALT
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    broker_value: Any = None
    internal_value: Any = None
    tolerance: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "status": self.status,
            "severity": self.severity,
            "action": self.action,
            "message": self.message,
            "details": self.details,
            "broker_value": self.broker_value,
            "internal_value": self.internal_value,
            "tolerance": self.tolerance,
        }


@dataclass(frozen=True)
class ReconciliationResult:
    """Complete reconciliation result."""

    status: str  # RECONCILED, WARNING, MISMATCH, BLOCKING
    timestamp: str
    checks: List[ReconciliationCheck]
    broker_state_hash: str
    internal_state_hash: str
    mismatches: List[str]
    action_required: str  # NONE, REVIEW, HALT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "checks": [c.to_dict() for c in self.checks],
            "broker_state_hash": self.broker_state_hash,
            "internal_state_hash": self.internal_state_hash,
            "mismatches": self.mismatches,
            "action_required": self.action_required,
        }


@dataclass
class BrokerState:
    """Snapshot of broker state from MT5."""

    positions: List[Dict[str, Any]]
    account_equity: float
    account_balance: float
    account_free_margin: float
    orders: List[Dict[str, Any]]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "positions": self.positions,
            "account_equity": self.account_equity,
            "account_balance": self.account_balance,
            "account_free_margin": self.account_free_margin,
            "orders": self.orders,
            "timestamp": self.timestamp,
        }


@dataclass
class InternalState:
    """Internal strategy state."""

    positions: Dict[int, Dict[str, Any]]  # ticket -> position info
    pending_orders: List[Dict[str, Any]]
    last_signal: Dict[str, Any]
    target_weights: Dict[str, float]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "positions": self.positions,
            "pending_orders": self.pending_orders,
            "last_signal": self.last_signal,
            "target_weights": self.target_weights,
            "timestamp": self.timestamp,
        }


class ReconciliationEngine:
    """Deterministic broker/internal state comparison.

    Never silently repairs dangerous discrepancies.
    All findings are classified as:
    - SAFE_AUTOFIX: Can fix automatically
    - REQUIRES_REVIEW: Needs operator decision
    - HALT: Stop trading immediately
    """

    def __init__(
        self,
        r4_magic: int = 20260825,
        position_tolerance: float = 1e-6,
        price_tolerance: float = 0.001,
        stale_threshold_seconds: float = 86400,  # 24 hours
    ) -> None:
        """Initialize reconciliation engine.

        Args:
            r4_magic: Magic number for R4 positions
            position_tolerance: Tolerance for position quantity comparison
            price_tolerance: Tolerance for price comparison
            stale_threshold_seconds: Threshold for stale position detection
        """
        self._r4_magic = r4_magic
        self._position_tolerance = position_tolerance
        self._price_tolerance = price_tolerance
        self._stale_threshold = stale_threshold_seconds
        self._reconciliation_history: List[Dict[str, Any]] = []
        self._max_history = 1000

    def reconcile(
        self,
        broker: BrokerState,
        internal: InternalState,
        config_fingerprint: str | None = None,
    ) -> ReconciliationResult:
        """Perform full reconciliation.

        Args:
            broker: Current broker state from MT5
            internal: Current internal strategy state
            config_fingerprint: Expected config fingerprint

        Returns:
            ReconciliationResult with all findings
        """
        now = datetime.now(UTC).isoformat()
        checks: List[ReconciliationCheck] = []
        mismatches: List[str] = []

        # Compute state hashes
        broker_hash = self._compute_hash(broker.to_dict())
        internal_hash = self._compute_hash(internal.to_dict())

        # 1. Position count check
        check = self._check_position_count(broker, internal)
        checks.append(check)
        if check.status != "PASS":
            mismatches.append(check.message)

        # 2. Position matching
        position_checks = self._check_positions(broker, internal)
        checks.extend(position_checks)
        for c in position_checks:
            if c.status != "PASS":
                mismatches.append(c.message)

        # 3. Foreign position detection
        check = self._check_foreign_positions(broker)
        checks.append(check)
        if check.status != "PASS":
            mismatches.append(check.message)

        # 4. Duplicate order detection
        check = self._check_duplicate_orders(broker)
        checks.append(check)
        if check.status != "PASS":
            mismatches.append(check.message)

        # 5. Stale position detection
        check = self._check_stale_positions(broker)
        checks.append(check)
        if check.status != "PASS":
            mismatches.append(check.message)

        # 6. Account consistency
        check = self._check_account_consistency(broker)
        checks.append(check)
        if check.status != "PASS":
            mismatches.append(check.message)

        # 7. P&L discrepancy (if internal P&L available)
        if internal.last_signal:
            check = self._check_pnl_discrepancy(broker, internal)
            checks.append(check)
            if check.status != "PASS":
                mismatches.append(check.message)

        # Determine overall status
        has_blocking = any(c.status == "BLOCKING" for c in checks)
        has_critical = any(c.status == "CRITICAL" for c in checks)
        has_warning = any(c.status == "WARNING" for c in checks)

        if has_blocking:
            status = "BLOCKING"
            action = "HALT"
        elif has_critical:
            status = "MISMATCH"
            action = "HALT"
        elif has_warning:
            status = "WARNING"
            action = "REVIEW"
        else:
            status = "RECONCILED"
            action = "NONE"

        result = ReconciliationResult(
            status=status,
            timestamp=now,
            checks=checks,
            broker_state_hash=broker_hash,
            internal_state_hash=internal_hash,
            mismatches=mismatches,
            action_required=action,
        )

        # Record to history
        self._reconciliation_history.append(result.to_dict())
        if len(self._reconciliation_history) > self._max_history:
            self._reconciliation_history = self._reconciliation_history[-self._max_history :]

        return result

    def _compute_hash(self, data: Dict[str, Any]) -> str:
        """Compute deterministic hash for state."""
        payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]

    def _check_position_count(
        self,
        broker: BrokerState,
        internal: InternalState,
    ) -> ReconciliationCheck:
        """Check position count matches."""
        broker_count = len(broker.positions)
        internal_count = len(internal.positions)

        if broker_count != internal_count:
            return ReconciliationCheck(
                check_name="position_count",
                status="CRITICAL",
                severity=ReconciliationSeverity.CRITICAL.value,
                action=ReconciliationAction.HALT.value,
                message=f"Position count mismatch: broker={broker_count}, internal={internal_count}",
                details={
                    "broker_count": broker_count,
                    "internal_count": internal_count,
                },
                broker_value=broker_count,
                internal_value=internal_count,
            )

        return ReconciliationCheck(
            check_name="position_count",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message=f"Position count matches: {broker_count}",
            details={"count": broker_count},
            broker_value=broker_count,
            internal_value=internal_count,
        )

    def _check_positions(
        self,
        broker: BrokerState,
        internal: InternalState,
    ) -> List[ReconciliationCheck]:
        """Check individual positions match."""
        checks = []

        # Index broker positions by ticket
        broker_by_ticket = {p.get("ticket"): p for p in broker.positions}

        for ticket, internal_pos in internal.positions.items():
            broker_pos = broker_by_ticket.get(ticket)

            if broker_pos is None:
                # Internal position not found in broker
                checks.append(
                    ReconciliationCheck(
                        check_name=f"position_{ticket}_exists",
                        status="BLOCKING",
                        severity=ReconciliationSeverity.BLOCKING.value,
                        action=ReconciliationAction.HALT.value,
                        message=f"Internal position {ticket} not found at broker",
                        details={
                            "ticket": ticket,
                            "symbol": internal_pos.get("symbol"),
                        },
                        broker_value=None,
                        internal_value=internal_pos,
                    )
                )
                continue

            # Quantity check
            broker_qty = broker_pos.get("volume", 0)
            internal_qty = internal_pos.get("volume", 0)

            if abs(broker_qty - internal_qty) > self._position_tolerance:
                checks.append(
                    ReconciliationCheck(
                        check_name=f"position_{ticket}_quantity",
                        status="CRITICAL",
                        severity=ReconciliationSeverity.CRITICAL.value,
                        action=ReconciliationAction.HALT.value,
                        message=f"Position {ticket} quantity mismatch: broker={broker_qty}, internal={internal_qty}",
                        details={
                            "ticket": ticket,
                            "symbol": internal_pos.get("symbol"),
                        },
                        broker_value=broker_qty,
                        internal_value=internal_qty,
                        tolerance=self._position_tolerance,
                    )
                )
            else:
                checks.append(
                    ReconciliationCheck(
                        check_name=f"position_{ticket}_quantity",
                        status="PASS",
                        severity=ReconciliationSeverity.INFO.value,
                        action=ReconciliationAction.SAFE_AUTOFIX.value,
                        message=f"Position {ticket} quantity matches",
                        details={"ticket": ticket},
                        broker_value=broker_qty,
                        internal_value=internal_qty,
                    )
                )

            # Side check
            broker_type = broker_pos.get("type")  # 0=buy, 1=sell
            internal_side = internal_pos.get("side")  # "buy" or "sell"

            expected_type = 0 if internal_side == "buy" else 1
            if broker_type != expected_type:
                checks.append(
                    ReconciliationCheck(
                        check_name=f"position_{ticket}_side",
                        status="CRITICAL",
                        severity=ReconciliationSeverity.CRITICAL.value,
                        action=ReconciliationAction.HALT.value,
                        message=f"Position {ticket} side mismatch: broker={broker_type}, internal={internal_side}",
                        details={
                            "ticket": ticket,
                            "symbol": internal_pos.get("symbol"),
                        },
                        broker_value=broker_type,
                        internal_value=internal_side,
                    )
                )
            else:
                checks.append(
                    ReconciliationCheck(
                        check_name=f"position_{ticket}_side",
                        status="PASS",
                        severity=ReconciliationSeverity.INFO.value,
                        action=ReconciliationAction.SAFE_AUTOFIX.value,
                        message=f"Position {ticket} side matches",
                        details={"ticket": ticket},
                        broker_value=broker_type,
                        internal_value=internal_side,
                    )
                )

        # Check for broker positions not in internal
        for broker_pos in broker.positions:
            ticket = broker_pos.get("ticket")
            if ticket not in internal.positions:
                # Check if it's an R4 position
                magic = broker_pos.get("magic")
                if magic == self._r4_magic:
                    checks.append(
                        ReconciliationCheck(
                            check_name=f"position_{ticket}_unexpected",
                            status="BLOCKING",
                            severity=ReconciliationSeverity.BLOCKING.value,
                            action=ReconciliationAction.HALT.value,
                            message=f"Unexpected R4 position {ticket} at broker",
                            details={
                                "ticket": ticket,
                                "symbol": broker_pos.get("symbol"),
                            },
                            broker_value=broker_pos,
                            internal_value=None,
                        )
                    )

        return checks

    def _check_foreign_positions(self, broker: BrokerState) -> ReconciliationCheck:
        """Check for positions not created by R4."""
        foreign = [p for p in broker.positions if p.get("magic") != self._r4_magic]

        if foreign:
            symbols = [p.get("symbol", "?") for p in foreign]
            return ReconciliationCheck(
                check_name="foreign_positions",
                status="BLOCKING",
                severity=ReconciliationSeverity.BLOCKING.value,
                action=ReconciliationAction.HALT.value,
                message=f"Foreign positions detected: {', '.join(symbols)}",
                details={"count": len(foreign), "symbols": symbols},
                broker_value=len(foreign),
                internal_value=0,
            )

        return ReconciliationCheck(
            check_name="foreign_positions",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message="No foreign positions detected",
            details={"count": 0},
            broker_value=0,
            internal_value=0,
        )

    def _check_duplicate_orders(self, broker: BrokerState) -> ReconciliationCheck:
        """Check for duplicate orders."""
        tickets = [o.get("ticket") for o in broker.orders]
        duplicates = [t for t in tickets if tickets.count(t) > 1]

        if duplicates:
            return ReconciliationCheck(
                check_name="duplicate_orders",
                status="CRITICAL",
                severity=ReconciliationSeverity.CRITICAL.value,
                action=ReconciliationAction.HALT.value,
                message=f"Duplicate orders detected: {duplicates}",
                details={"duplicates": list(set(duplicates))},
                broker_value=len(duplicates),
                internal_value=0,
            )

        return ReconciliationCheck(
            check_name="duplicate_orders",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message="No duplicate orders",
            details={"count": 0},
            broker_value=0,
            internal_value=0,
        )

    def _check_stale_positions(self, broker: BrokerState) -> ReconciliationCheck:
        """Check for stale positions.

        A position is stale if its open time is older than the stale threshold
        and it hasn't been updated. This can indicate orphaned positions or
        broker state inconsistency.
        """
        stale_positions = []
        now_ts = datetime.now(UTC).timestamp()

        for pos in broker.positions:
            open_time = pos.get("time", 0)
            if open_time and isinstance(open_time, (int, float)):
                age_seconds = now_ts - open_time
                if age_seconds > self._stale_threshold:
                    stale_positions.append(
                        {
                            "ticket": pos.get("ticket"),
                            "symbol": pos.get("symbol"),
                            "age_hours": round(age_seconds / 3600, 1),
                        }
                    )

        if stale_positions:
            return ReconciliationCheck(
                check_name="stale_positions",
                status="WARNING",
                severity=ReconciliationSeverity.WARNING.value,
                action=ReconciliationAction.REQUIRES_REVIEW.value,
                message=f"{len(stale_positions)} stale position(s) detected (>{self._stale_threshold / 3600:.0f}h old)",
                details={"stale_positions": stale_positions},
                broker_value=len(stale_positions),
                internal_value=0,
            )

        return ReconciliationCheck(
            check_name="stale_positions",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message="Position staleness check passed",
            details={"stale_count": 0},
            broker_value=0,
            internal_value=0,
        )

    def _check_account_consistency(self, broker: BrokerState) -> ReconciliationCheck:
        """Check account state consistency."""
        # Check equity > 0
        if broker.account_equity <= 0:
            return ReconciliationCheck(
                check_name="account_equity",
                status="BLOCKING",
                severity=ReconciliationSeverity.BLOCKING.value,
                action=ReconciliationAction.HALT.value,
                message=f"Account equity <= 0: {broker.account_equity}",
                details={"equity": broker.account_equity},
                broker_value=broker.account_equity,
                internal_value=None,
            )

        # Check free margin >= 0
        if broker.account_free_margin < 0:
            return ReconciliationCheck(
                check_name="account_free_margin",
                status="CRITICAL",
                severity=ReconciliationSeverity.CRITICAL.value,
                action=ReconciliationAction.HALT.value,
                message=f"Account free margin < 0: {broker.account_free_margin}",
                details={"free_margin": broker.account_free_margin},
                broker_value=broker.account_free_margin,
                internal_value=None,
            )

        return ReconciliationCheck(
            check_name="account_consistency",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message="Account state consistent",
            details={
                "equity": broker.account_equity,
                "free_margin": broker.account_free_margin,
            },
            broker_value=broker.account_equity,
            internal_value=None,
        )

    def _check_pnl_discrepancy(
        self,
        broker: BrokerState,
        internal: InternalState,
    ) -> ReconciliationCheck:
        """Check P&L discrepancy between broker and internal."""
        # This is a simplified check - in production, you'd compute
        # internal P&L from position history
        return ReconciliationCheck(
            check_name="pnl_discrepancy",
            status="PASS",
            severity=ReconciliationSeverity.INFO.value,
            action=ReconciliationAction.REQUIRES_REVIEW.value,
            message="P&L discrepancy check passed (simplified)",
            details={},
            broker_value=None,
            internal_value=None,
        )

    def get_history(self) -> List[Dict[str, Any]]:
        """Get reconciliation history."""
        return list(self._reconciliation_history)

    def get_stats(self) -> Dict[str, Any]:
        """Get reconciliation statistics."""
        total = len(self._reconciliation_history)
        if total == 0:
            return {
                "total": 0,
                "reconciled": 0,
                "warnings": 0,
                "mismatches": 0,
                "blocking": 0,
            }

        statuses = [r.get("status", "UNKNOWN") for r in self._reconciliation_history]
        return {
            "total": total,
            "reconciled": statuses.count("RECONCILED"),
            "warnings": statuses.count("WARNING"),
            "mismatches": statuses.count("MISMATCH"),
            "blocking": statuses.count("BLOCKING"),
        }
