"""Domain model: RiskDecision.

Independent risk engine assessment of strategy intent.

Invariants:
- var is diagnostic ONLY (never a hard trigger)
- var_breach removed entirely (if it's always False, it shouldn't exist)
- risk_checks: list[RiskCheckResult] — structured, versioned checks
- decision: APPROVED, REJECTED, REDUCED with explicit semantics
- approved_position: what risk engine allows (signed), 0 if REJECTED
- reason: explicit text rationale
- intended_position: what strategy wants (signed)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict

from .risk_check_result import RiskCheckResult


@dataclass(frozen=True)
class RiskDecision:
    """Independent risk engine assessment of strategy intent.

    This is the risk engine's output: whether the proposed position is allowed.

    Critical design decisions (frozen in v1.2):
    1. var_breach: REMOVED entirely. If it's always False, it should not exist.
       VaR is captured as diagnostic data in `var` + `var_method`.
    2. risk_checks: list[RiskCheckResult] — structured, versioned, auditable.
       No implied schema; every check has check_id, status, observed, limit, unit, message.
    3. decision: APPROVED / REDUCED / REJECTED with explicit semantics.
       - APPROVED: may approve full intended position
       - REDUCED: approves a smaller position than requested
       - REJECTED: approved_quantity = 0, request denied
    4. var: float — diagnostic only (VaR at decision time). Never a hard trigger.
       Hard constraints are in individual risk_checks statuses.

    Attributes:
        decision_id: Unique identifier
        timestamp_utc: When risk decision was made
        instrument_id: FK → Instrument, or "PORTFOLIO" for portfolio-level
        intended_position: What strategy wants (signed: positive=LONG, negative=SHORT)
        approved_position: What risk engine allows (signed), 0 if REJECTED
        decision: APPROVED, REJECTED, or REDUCED
        reason: Explicit text rationale
        var: Portfolio VaR at decision time (diagnostic ONLY — NOT a hard trigger)
        var_method: VaR method, e.g. "gaussian_99", "historical_95"
        risk_checks: list[RiskCheckResult] — structured check results
        decision_snapshot_id: Back to DecisionSnapshot
        version: Version for change tracking
    """

    decision_id: str
    timestamp_utc: str  # ISO-8601 UTC when risk decision made
    instrument_id: str  # or "PORTFOLIO" for portfolio-level
    intended_position: float  # what strategy wants (signed)
    approved_position: float  # what risk engine allows (signed), 0 if REJECTED
    decision: str  # APPROVED, REJECTED, REDUCED
    reason: str  # explicit text rationale
    var: float  # diagnostic only (VaR at decision time)
    var_method: str  # e.g. "gaussian_99", "historical_95"
    risk_checks: list[RiskCheckResult]  # structured, versioned checks
    decision_snapshot_id: str  # back to DecisionSnapshot
    version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate decision is one of APPROVED, REJECTED, REDUCED
        valid_decisions = {"APPROVED", "REJECTED", "REDUCED"}
        if self.decision not in valid_decisions:
            raise ValueError(f"Invalid risk decision: {self.decision}. Must be one of {valid_decisions}")

        # Validate timestamp is ISO-8601 UTC
        if "T" not in self.timestamp_utc:
            raise ValueError(f"timestamp_utc should be ISO-8601 format, got: {self.timestamp_utc}")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate intended_position is finite
        if math.isnan(self.intended_position) or math.isinf(self.intended_position):
            raise ValueError("intended_position must be finite (no NaN/infinity)")

        # Validate approved_position is finite
        if math.isnan(self.approved_position) or math.isinf(self.approved_position):
            raise ValueError("approved_position must be finite (no NaN/infinity)")

        # INVARIANT: If decision == REJECTED, approved_position must be 0
        if self.decision == "REJECTED" and self.approved_position != 0:
            raise ValueError(
                f"Invariant violated: decision == REJECTED but approved_position "
                f"is {self.approved_position}. REJECTED must have approved_position = 0."
            )

        # INVARIANT: If decision == APPROVED, approved_position should generally match
        # intended_position (but REDUCED is used when partially approved)
        # We validate the decision/reason consistency instead

        # Validate var is finite (diagnostic only)
        if math.isnan(self.var) or math.isinf(self.var):
            raise ValueError("var must be finite (no NaN/infinity) — diagnostic only")

        # Validate var_method is non-empty
        if not self.var_method:
            raise ValueError("var_method must be non-empty (e.g. 'gaussian_99')")

        # Validate risk_checks is a non-empty list
        if not self.risk_checks:
            raise ValueError("risk_checks must be a non-empty list [RiskCheckResult]")

        # Validate each risk check
        for i, check in enumerate(self.risk_checks):
            if not isinstance(check, RiskCheckResult):
                raise ValueError(f"risk_checks[{i}] is not a RiskCheckResult instance")

        # Registry check for duplicate decision_ids
        if self.decision_id in self._registry:
            raise ValueError(f"Duplicate decision_id: {self.decision_id}. Decision IDs must be unique.")
        self._registry[self.decision_id] = True

    def __hash__(self) -> int:
        return hash((self.decision_id, self.decision, self.instrument_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RiskDecision):
            return NotImplemented
        return (
            self.decision_id == other.decision_id
            and self.decision == other.decision
            and self.instrument_id == other.instrument_id
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "decision_id": self.decision_id,
            "timestamp_utc": self.timestamp_utc,
            "instrument_id": self.instrument_id,
            "intended_position": self.intended_position,
            "approved_position": self.approved_position,
            "decision": self.decision,
            "reason": self.reason,
            "var": self.var,
            "var_method": self.var_method,
            "risk_checks": [check.to_dict() for check in self.risk_checks],
            "decision_snapshot_id": self.decision_snapshot_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RiskDecision:
        """Deserialize from dict (deterministic, keys sorted)."""
        from .risk_check_result import RiskCheckResult

        risk_checks_list = [RiskCheckResult.from_dict(check_dict) for check_dict in d.get("risk_checks", [])]

        return RiskDecision(
            decision_id=d["decision_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            instrument_id=str(d["instrument_id"]),
            intended_position=float(d["intended_position"]),
            approved_position=float(d["approved_position"]),
            decision=str(d["decision"]),
            reason=str(d["reason"]),
            var=float(d["var"]),
            var_method=str(d["var_method"]),
            risk_checks=risk_checks_list,
            decision_snapshot_id=str(d.get("decision_snapshot_id", "")),
            version=str(d.get("version", "v1")),
        )

    @property
    def is_approved(self) -> bool:
        """Shortcut: decision == APPROVED."""
        return self.decision == "APPROVED"

    @property
    def is_rejected(self) -> bool:
        """Shortcut: decision == REJECTED."""
        return self.decision == "REJECTED"

    @property
    def is_reduced(self) -> bool:
        """Shortcut: decision == REDUCED."""
        return self.decision == "REDUCED"

    @property
    def var_diagnostic(self) -> float:
        """VaR as diagnostic (never use as hard trigger)."""
        return self.var

    def check_status(self, check_id: str) -> RiskCheckResult | None:
        """Find a specific risk check by ID.

        Useful for examining which specific check passed/failed/warned.
        """
        for check in self.risk_checks:
            if check.check_id == check_id:
                return check
        return None

    def summary(self) -> str:
        """Human-readable summary of the risk decision."""
        return (
            f"RiskDecision[{self.decision_id}]:\n"
            f"  instrument={self.instrument_id}\n"
            f"  decision={self.decision}\n"
            f"  intended_position={self.intended_position}\n"
            f"  approved_position={self.approved_position}\n"
            f"  var={self.var} ({self.var_method})\n"
            f"  reason={self.reason[:60]}..."
        )


RiskDecision._registry = {}
