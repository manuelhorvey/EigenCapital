"""Domain model: RiskCheckResult.

Structured risk check result replacing unstructured dict.

Each check is versioned and auditable with explicit:
- check_id: identifier (e.g. "max_position", "leverage")
- status: PASS, WARN, FAIL
- observed: observed value
- limit: limit threshold
- unit: e.g. "x", "%", "contracts"
- message: human-readable rationale
- version: version of this check definition

Used in RiskDecision.risk_checks: list[RiskCheckResult].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import math


@dataclass(frozen=True)
class RiskCheckResult:
    """Structured result of a single risk check.

    Replaces unstructured dict with typed, versioned fields.
    Every check has explicit semantics, making metrics easier and
    audit trails more reliable.

    Attributes:
        check_id: Identifier for the check (e.g. "max_position", "leverage", "drawdown")
        status: PASS if observed within limit, WARN if near limit, FAIL if breached
        observed: Observed value at decision time
        limit: Limit threshold
        unit: Unit of measurement (e.g. "x", "%", "contracts", "bps")
        message: Human-readable rationale for the status
        version: Version of this check definition (for auditing policy changes)
    """

    check_id: str
    status: str  # PASS, WARN, FAIL
    observed: float
    limit: float
    unit: str
    message: str
    version: str = "v1"

    # Class-level registry for check definition consistency

    def __post_init__(self) -> None:
        # Validate status is one of PASS, WARN, FAIL
        valid_statuses = {"PASS", "WARN", "FAIL"}
        if self.status not in valid_statuses:
            raise ValueError(
                f"Invalid risk check status: {self.status}. "
                f"Must be one of {valid_statuses}"
            )

        # Validate check_id is non-empty
        if not self.check_id:
            raise ValueError("check_id must be non-empty")

        # Validate observed is finite
        if math.isnan(self.observed) or math.isinf(self.observed):
            raise ValueError(
                f"observed must be finite (no NaN/infinity), got {self.observed}"
            )

        # Validate limit is finite
        if math.isnan(self.limit) or math.isinf(self.limit):
            raise ValueError(
                f"limit must be finite (no NaN/infinity), got {self.limit}"
            )

        # Validate unit is non-empty
        if not self.unit:
            raise ValueError("unit must be non-empty")

        # Validate message is non-empty
        if not self.message:
            raise ValueError("message must be non-empty")

        # Validate version is non-empty
        if not self.version:
            raise ValueError("version must be non-empty")

        # Registry check for duplicate check_id definitions
        if self.check_id in self._registry:
            raise ValueError(
                f"Duplicate risk check_id: {self.check_id}. "
                f"Check IDs must be unique within a risk policy version."
            )
        self._registry[self.check_id] = True

    def __hash__(self) -> int:
        return hash((self.check_id, self.status, self.check_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RiskCheckResult):
            return NotImplemented
        return (
            self.check_id == other.check_id
            and self.status == other.status
            and self.observed == other.observed
            and self.limit == other.limit
            and self.unit == other.unit
            and self.message == other.message
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "check_id": self.check_id,
            "status": self.status,
            "observed": self.observed,
            "limit": self.limit,
            "unit": self.unit,
            "message": self.message,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RiskCheckResult:
        """Deserialize from dict (deterministic, keys sorted)."""
        return RiskCheckResult(
            check_id=str(d["check_id"]),
            status=str(d["status"]),
            observed=float(d["observed"]),
            limit=float(d["limit"]),
            unit=str(d["unit"]),
            message=str(d["message"]),
            version=str(d.get("version", "v1")),
        )

    @property
    def passed(self) -> bool:
        """Shortcut: status == PASS."""
        return self.status == "PASS"

    @property
    def failed(self) -> bool:
        """Shortcut: status == FAIL."""
        return self.status == "FAIL"

    @property
    def warned(self) -> bool:
        """Shortcut: status == WARN."""
        return self.status == "WARN"


# Pre-defined check IDs (versioned, auditable)
# These are the check IDs that EigenRisk supports; each has versioned semantics
RISK_CHECK_IDS = {
    "max_position",
    "gross_exposure",
    "net_exposure",
    "leverage",
    "drawdown",
    "daily_loss",
    "weekly_loss",
    "correlation",
    "asset_class",
    "liquidity",
    "volatility_shock",
    "concentration",
}


RiskCheckResult._registry = {}
