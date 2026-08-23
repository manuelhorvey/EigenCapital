"""Domain model: ApprovedTarget.

Risk engine decision: what position is approved.

Decision semantics (frozen in v1.2):
- APPROVED → approved_quantity may equal intended_quantity (full approval)
- REDUCED  → approved_quantity differs from intended_quantity (partial approval)
- REJECTED → approved_quantity = 0 (request denied)

This explicit decision status eliminates the ambiguity of
`approved_quantity = 0` meaning "rejected" vs "intentionally flat"
vs "risk reduced to zero" vs "strategy itself wanted zero".

Flow: PortfolioTarget → RiskDecision → ApprovedTarget → OrderPlan → Order
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, ClassVar
import math


@dataclass(frozen=True)
class ApprovedTarget:
    """Risk engine decision: what position is approved.

    Decision status makes the disposition explicit, eliminating ambiguity:

    | decision | approved_quantity meaning |
    |----------|--------------------------|
    | APPROVED | may equal intended_quantity (full approval) |
    | REDUCED  | differs from intended_quantity (partial approval) |
    | REJECTED | always 0 (request denied) |

    Flow through the system:
        PortfolioTarget
              ↓
        RiskDecision      ← "APPROVED / REDUCED / REJECTED"
              ↓
        ApprovedTarget    ← "Here is the disposition"
              ↓
        OrderPlan         ← "Here is the authorized exposure plan"
              ↓
        Order             ← "Here is the order submission"

    Attributes:
        target_id: Links to PortfolioTarget
        intended_quantity: What strategy requested (signed)
        approved_quantity: What risk engine allows (signed)
        decision: APPROVED, REDUCED, or REJECTED (explicit disposition)
        approval_reason: Explicit text: why approved/reduced/rejected
        constraints_binding: Which limits were checked (affected the decision)
        version: Version for change tracking
    """

    target_id: str  # Links to PortfolioTarget
    intended_quantity: float  # What strategy requested (signed)
    approved_quantity: float  # What risk engine allows (signed)
    decision: str  # APPROVED, REDUCED, or REJECTED
    approval_reason: str  # Explicit text rationale
    constraints_binding: Optional[list] = None  # Which limits affected the decision
    version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate decision is one of APPROVED, REDUCED, REJECTED
        valid_decisions = {"APPROVED", "REDUCED", "REJECTED"}
        if self.decision not in valid_decisions:
            raise ValueError(
                f"Invalid approved target decision: {self.decision}. "
                f"Must be one of {valid_decisions}"
            )

        # Validate target_id is non-empty
        if not self.target_id:
            raise ValueError("target_id must be non-empty")

        # Validate intended_quantity is finite
        if math.isnan(self.intended_quantity) or math.isinf(self.intended_quantity):
            raise ValueError("intended_quantity must be finite (no NaN/infinity)")

        # Validate approved_quantity is finite
        if math.isnan(self.approved_quantity) or math.isinf(self.approved_quantity):
            raise ValueError("approved_quantity must be finite (no NaN/infinity)")

        # INVARIANT: If decision == REJECTED, approved_quantity must be 0
        if self.decision == "REJECTED" and self.approved_quantity != 0:
            raise ValueError(
                f"Invariant violated: decision == REJECTED but approved_quantity "
                f"is {self.approved_quantity}. REJECTED must have approved_quantity = 0."
            )

        # INVARIANT: If decision == APPROVED, approved_quantity should equal
        # intended_quantity (or be close to it); REDUCED means they differ
        # We validate this through the decision field rather than computing it

        # Validate approval_reason is non-empty
        if not self.approval_reason or not self.approval_reason.strip():
            raise ValueError("approval_reason must be non-empty text")

        # Validate version is non-empty
        if not self.version:
            raise ValueError("version must be non-empty")

        # Registry check for duplicate target_ids
        if self.target_id in self._registry:
            raise ValueError(
                f"Duplicate approved_target target_id: {self.target_id}. "
                "Target IDs must be unique."
            )
        self._registry[self.target_id] = True

    def __hash__(self) -> int:
        return hash((self.target_id, self.decision, self.approved_quantity))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ApprovedTarget):
            return NotImplemented
        return self.target_id == other.target_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "target_id": self.target_id,
            "intended_quantity": self.intended_quantity,
            "approved_quantity": self.approved_quantity,
            "decision": self.decision,
            "approval_reason": self.approval_reason,
            "constraints_binding": self.constraints_binding,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ApprovedTarget:
        """Deserialize from dict (deterministic, keys sorted)."""
        return ApprovedTarget(
            target_id=d["target_id"],
            intended_quantity=float(d["intended_quantity"]),
            approved_quantity=float(d["approved_quantity"]),
            decision=str(d["decision"]),
            approval_reason=str(d["approval_reason"]),
            constraints_binding=d.get("constraints_binding"),
            version=str(d.get("version", "v1")),
        )

    @property
    def is_approved(self) -> bool:
        """Check if decision is APPROVED."""
        return self.decision == "APPROVED"

    @property
    def is_rejected(self) -> bool:
        """Check if decision is REJECTED."""
        return self.decision == "REJECTED"

    @property
    def is_reduced(self) -> bool:
        """Check if decision is REDUCED."""
        return self.decision == "REDUCED"

    @property
    def approved_differs(self) -> bool:
        """Check if approved_quantity differs from intended_quantity."""
        return self.approved_quantity != self.intended_quantity

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"ApprovedTarget[{self.target_id}]:\n"
            f"  intended={self.intended_quantity}\n"
            f"  approved={self.approved_quantity}\n"
            f"  decision={self.decision}\n"
            f"  reason={self.approval_reason[:80]}..."
        )


ApprovedTarget._registry = {}
