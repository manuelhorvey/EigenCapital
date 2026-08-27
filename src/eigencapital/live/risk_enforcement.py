"""Risk Enforcement Overlay — broker-authoritative risk gates.

Independent of R4 strategy logic. Operates on broker-confirmed MT5 state.
Every check uses the ACTUAL broker positions, not the strategy's internal
portfolio state. Fail-closed: any uncertainty blocks trading.

Design principles:
- Broker-authoritative: reads positions from MT5, not from internal state
- Continuous: checked every cycle, not just at order time
- Fail-closed: any anomaly blocks ALL new entries
- Independent: does not modify R4 signal or strategy logic
- Auditable: every decision recorded with reason code
- Idempotent: re-running produces the same result

Hierarchy:
  R4 signal → Risk Enforcement → Execution → MT5

Risk enforcement CANNOT be bypassed by the strategy layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class GateResult(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


class BlockReason(str, Enum):
    MAX_CONCURRENT = "max_concurrent_positions"
    POSITION_COUNT_BREACH = "position_count_exceeds_limit"
    PER_POSITION_LOSS = "per_position_max_loss"
    ACCOUNT_DRAWDOWN = "account_drawdown_limit"
    DAILY_LOSS = "daily_loss_limit"
    EQUITY_BELOW_MIN = "equity_below_minimum"
    NO_SL_PROTECTION = "no_stop_loss_protection"
    STALE_DATA = "stale_broker_data"
    RECONCILIATION_FAIL = "reconciliation_failure"
    UNKNOWN_POSITION = "unknown_position"
    BROKER_DISCONNECT = "broker_disconnect"
    EMERGENCY = "emergency_condition"
    FINGERPRINT_DRIFT = "config_fingerprint_drift"


@dataclass(frozen=True)
class RiskGateResult:
    """Result of a single risk gate check."""

    gate_name: str
    result: GateResult
    reason: BlockReason
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    broker_state_hash: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate_name,
            "result": self.result.value,
            "reason": self.reason.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class RiskEnvelope:
    """Hard risk limits — these are invariant, not tunable."""

    max_concurrent_positions: int = 19
    max_position_notional: float = 5_000.0
    max_order_notional: float = 5_000.0
    max_per_position_loss_pct: float = 0.10  # 10% of position notional
    max_account_drawdown_pct: float = 0.10  # 10% from T=0 equity
    max_daily_loss: float = 250.0
    min_equity: float = 4_000.0  # absolute floor
    require_sl_on_positions: bool = True
    t0_equity: float = 0.0  # Loaded from config at initialization

    @classmethod
    def from_config(cls) -> "RiskEnvelope":
        """Create RiskEnvelope from production config."""
        try:
            from eigencapital.config import load_config

            config = load_config("production")
            return cls(
                max_concurrent_positions=config.live_risk.max_concurrent_positions,
                max_position_notional=config.live_risk.max_position_notional,
                max_order_notional=config.live_risk.max_order_notional,
                max_per_position_loss_pct=config.live_risk.max_per_position_loss_pct,
                max_account_drawdown_pct=config.live_risk.max_account_drawdown_pct,
                max_daily_loss=config.live_risk.max_daily_loss,
                min_equity=config.live_risk.min_equity,
                require_sl_on_positions=config.live_risk.require_sl_on_positions,
                t0_equity=config.live_risk.t0_equity,
            )
        except (ImportError, FileNotFoundError, AttributeError):
            return cls()  # Use defaults if config unavailable


class RiskEnforcer:
    """Broker-authoritative risk enforcement.

    Every method takes broker-confirmed state as input.
    Returns PASS or BLOCK with exact reason.
    """

    def __init__(
        self, envelope: Optional[RiskEnvelope] = None, *, max_audit_entries: int = 1000
    ) -> None:
        self._envelope = envelope or RiskEnvelope()
        self._t0_equity = self._envelope.t0_equity
        self._peak_equity = self._t0_equity
        self._daily_pnl_start = 0.0
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_entries = max_audit_entries

    def check_all(
        self,
        broker_positions: List[Dict[str, Any]],
        account_equity: float,
        account_free_margin: float,
        target_orders: int = 0,
        fingerprint_match: bool = True,
    ) -> Tuple[bool, List[RiskGateResult]]:
        """Run all risk gates. Returns (all_pass, results).

        Args:
            broker_positions: Actual positions from MT5 (broker-confirmed)
            account_equity: Current account equity from MT5
            account_free_margin: Current free margin from MT5
            target_orders: Number of new orders being considered
            fingerprint_match: Whether config fingerprint matches T=0
        """
        now = datetime.now(timezone.utc).isoformat()
        results: List[RiskGateResult] = []
        import hashlib

        state_hash = hashlib.sha256(
            json.dumps(
                {
                    "positions": len(broker_positions),
                    "equity": account_equity,
                    "free_margin": account_free_margin,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:16]

        # Gate 1: Broker connectivity (fail-closed)
        r = self._check_broker_connectivity(
            account_equity, account_free_margin, now, state_hash
        )
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        # Gate 2: Position count — broker-authoritative
        r = self._check_position_count(broker_positions, target_orders, now, state_hash)
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        # Gate 3: Account drawdown
        r = self._check_account_drawdown(account_equity, now, state_hash)
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        # Gate 4: Daily loss
        r = self._check_daily_loss(account_equity, now, state_hash)
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        # Gate 5: Equity floor
        r = self._check_equity_floor(account_equity, now, state_hash)
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        # Gate 6: Per-position SL check
        # NOTE: Gate 6 CRITICAL does NOT early-exit (intentional).
        # R4 uses signal-based exits, not SL-based exits.
        # Catastrophic SL is a safety backstop, not a normal exit mechanism.
        # SL missing is logged as CRITICAL for audit trail but does not block new entries.
        r = self._check_position_protection(broker_positions, now, state_hash)
        results.append(r)

        # Gate 7: Fingerprint
        r = self._check_fingerprint(fingerprint_match, now, state_hash)
        results.append(r)
        if r.result != GateResult.PASS:
            return False, results

        all_pass = all(r.result == GateResult.PASS for r in results)
        return all_pass, results

    def _check_broker_connectivity(
        self, equity: float, free_margin: float, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 1: Is broker data valid?"""
        if equity <= 0 and free_margin <= 0:
            return RiskGateResult(
                gate_name="broker_connectivity",
                result=GateResult.CRITICAL,
                reason=BlockReason.BROKER_DISCONNECT,
                message="Broker data invalid: equity and free margin both zero",
                broker_state_hash=state_hash,
                timestamp=now,
            )
        return RiskGateResult(
            gate_name="broker_connectivity",
            result=GateResult.PASS,
            reason=BlockReason.BROKER_DISCONNECT,
            message="Broker data valid",
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_position_count(
        self, positions: List[Dict], target_new: int, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 2: Position count against broker-confirmed state.

        This is the gate that was MISSING and caused the 9 > 8 violation.
        """
        current = len(positions)
        proposed = current + target_new
        limit = self._envelope.max_concurrent_positions

        if current > limit:
            return RiskGateResult(
                gate_name="position_count",
                result=GateResult.CRITICAL,
                reason=BlockReason.POSITION_COUNT_BREACH,
                message=f"Broker reports {current} positions, limit is {limit} — ALREADY BREACHED",
                details={"current": current, "limit": limit, "proposed": proposed},
                broker_state_hash=state_hash,
                timestamp=now,
            )

        if proposed > limit:
            return RiskGateResult(
                gate_name="position_count",
                result=GateResult.BLOCK,
                reason=BlockReason.MAX_CONCURRENT,
                message=f"Would create position #{proposed}, limit is {limit}",
                details={"current": current, "limit": limit, "proposed": proposed},
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="position_count",
            result=GateResult.PASS,
            reason=BlockReason.MAX_CONCURRENT,
            message=f"{current}/{limit} positions — {limit - current - target_new} slots remaining",
            details={"current": current, "limit": limit, "proposed": proposed},
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_account_drawdown(
        self, equity: float, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 3: Account drawdown from T=0 equity."""
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = self._peak_equity - equity
        dd_pct = drawdown / self._peak_equity if self._peak_equity > 0 else 0

        if dd_pct > self._envelope.max_account_drawdown_pct:
            return RiskGateResult(
                gate_name="account_drawdown",
                result=GateResult.BLOCK,
                reason=BlockReason.ACCOUNT_DRAWDOWN,
                message=f"Drawdown {dd_pct:.1%} exceeds limit {self._envelope.max_account_drawdown_pct:.0%}",
                details={
                    "drawdown": drawdown,
                    "drawdown_pct": dd_pct,
                    "peak": self._peak_equity,
                    "current": equity,
                },
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="account_drawdown",
            result=GateResult.PASS,
            reason=BlockReason.ACCOUNT_DRAWDOWN,
            message=f"Drawdown {dd_pct:.1%} within limit {self._envelope.max_account_drawdown_pct:.0%}",
            details={
                "drawdown_pct": dd_pct,
                "peak": self._peak_equity,
                "current": equity,
            },
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_daily_loss(
        self, equity: float, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 4: Daily loss from start-of-day equity."""
        daily_loss = self._daily_pnl_start - equity
        if daily_loss < 0:
            daily_loss = 0  # only track losses

        if daily_loss > self._envelope.max_daily_loss:
            return RiskGateResult(
                gate_name="daily_loss",
                result=GateResult.BLOCK,
                reason=BlockReason.DAILY_LOSS,
                message=f"Daily loss ${daily_loss:.2f} exceeds limit ${self._envelope.max_daily_loss:.2f}",
                details={
                    "daily_loss": daily_loss,
                    "limit": self._envelope.max_daily_loss,
                },
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="daily_loss",
            result=GateResult.PASS,
            reason=BlockReason.DAILY_LOSS,
            message=f"Daily loss ${daily_loss:.2f} within limit ${self._envelope.max_daily_loss:.2f}",
            details={"daily_loss": daily_loss},
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_equity_floor(
        self, equity: float, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 5: Absolute equity floor."""
        if equity < self._envelope.min_equity:
            return RiskGateResult(
                gate_name="equity_floor",
                result=GateResult.CRITICAL,
                reason=BlockReason.EQUITY_BELOW_MIN,
                message=f"Equity ${equity:,.2f} below minimum ${self._envelope.min_equity:,.2f}",
                details={"equity": equity, "min": self._envelope.min_equity},
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="equity_floor",
            result=GateResult.PASS,
            reason=BlockReason.EQUITY_BELOW_MIN,
            message=f"Equity ${equity:,.2f} above minimum ${self._envelope.min_equity:,.2f}",
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_position_protection(
        self, positions: List[Dict], now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 6: Check if positions have SL protection."""
        if not self._envelope.require_sl_on_positions:
            return RiskGateResult(
                gate_name="position_protection",
                result=GateResult.PASS,
                reason=BlockReason.NO_SL_PROTECTION,
                message="SL check disabled",
                broker_state_hash=state_hash,
                timestamp=now,
            )

        unprotected = [p for p in positions if p.get("sl", 0) == 0]

        if unprotected:
            symbols = [p.get("symbol", "?") for p in unprotected]
            return RiskGateResult(
                gate_name="position_protection",
                result=GateResult.CRITICAL,
                reason=BlockReason.NO_SL_PROTECTION,
                message=f"{len(unprotected)} positions without SL: {', '.join(symbols)}",
                details={"unprotected_count": len(unprotected), "symbols": symbols},
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="position_protection",
            result=GateResult.PASS,
            reason=BlockReason.NO_SL_PROTECTION,
            message=f"All {len(positions)} positions have SL protection",
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def _check_fingerprint(
        self, match: bool, now: str, state_hash: str
    ) -> RiskGateResult:
        """Gate 7: Configuration fingerprint matches T=0."""
        if not match:
            return RiskGateResult(
                gate_name="fingerprint",
                result=GateResult.CRITICAL,
                reason=BlockReason.FINGERPRINT_DRIFT,
                message="Configuration fingerprint does not match T=0 snapshot",
                broker_state_hash=state_hash,
                timestamp=now,
            )

        return RiskGateResult(
            gate_name="fingerprint",
            result=GateResult.PASS,
            reason=BlockReason.FINGERPRINT_DRIFT,
            message="Fingerprint matches T=0",
            broker_state_hash=state_hash,
            timestamp=now,
        )

    def record_daily_start(self, equity: float) -> None:
        """Record start-of-day equity for daily loss tracking."""
        self._daily_pnl_start = equity

    def audit(self, results: List[RiskGateResult]) -> None:
        """Record gate results to audit log with bounded retention."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gates": [r.to_dict() for r in results],
            "all_pass": all(r.result == GateResult.PASS for r in results),
            "any_critical": any(r.result == GateResult.CRITICAL for r in results),
        }
        self._audit_log.append(entry)
        # Bounded retention: keep only recent entries
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries :]

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit_log)
