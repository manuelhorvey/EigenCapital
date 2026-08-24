"""AlphaCandidate — auditable representation of an eligible alpha source.

Only Phase 1I-F execution records with an explicit eligible evidence verdict
may enter portfolio-combination research. The candidate contract prevents
the portfolio layer from accidentally pulling arbitrary backtest results.

Eligibility rules:
- REJECTED       → EXCLUDE
- INCONCLUSIVE   → EXCLUDE
- CANDIDATE      → eligible (explicitly permitted)
- VALIDATED      → eligible
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class EligibilityStatus(str, Enum):
    """Whether an alpha candidate is eligible for combination research."""

    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    PENDING = "pending"


class ExclusionReason(str, Enum):
    """Why an alpha was excluded."""

    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    NOT_REGISTERED = "not_registered"
    MISSING_EXECUTION = "missing_execution"
    EXPLICIT_EXCLUSION = "explicit_exclusion"


@dataclass(frozen=True)
class AlphaCandidate:
    """Auditable alpha candidate for portfolio combination research.

    Attributes:
        candidate_id: Unique identifier (e.g., "AC-001")
        hypothesis_id: Link to hypothesis
        execution_record_id: Link to execution record
        evidence_verdict: Evidence gate verdict from 1I-F
        strategy_config_hash: Hash of strategy configuration
        feature_set_hash: Hash of FeatureSet used
        provenance_hash: Provenance hash from execution
        dataset_version: Dataset version used
        universe_definition: Universe definition snapshot
        return_stream_reference: Reference to return stream data
        eligibility_status: Whether eligible for combination
        eligibility_reason: Why included or excluded
        metadata: Free-form additional metadata
    """

    candidate_id: str
    hypothesis_id: str
    execution_record_id: str
    evidence_verdict: str
    strategy_config_hash: str = ""
    feature_set_hash: str = ""
    provenance_hash: str = ""
    dataset_version: str = ""
    universe_definition: Dict[str, Any] = field(default_factory=dict)
    return_stream_reference: str = ""
    eligibility_status: EligibilityStatus = EligibilityStatus.PENDING
    eligibility_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id must be non-empty")
        if not self.hypothesis_id:
            raise ValueError("hypothesis_id must be non-empty")
        if not self.execution_record_id:
            raise ValueError("execution_record_id must be non-empty")

    @classmethod
    def from_execution_record(
        cls,
        candidate_id: str,
        record: Any,  # ExecutionRecord
        eligible_verdicts: Optional[List[str]] = None,
    ) -> AlphaCandidate:
        """Create a candidate from an execution record with eligibility check.

        Args:
            candidate_id: Unique identifier for this candidate
            record: ExecutionRecord from 1I-F
            eligible_verdicts: List of verdicts that qualify (default: CANDIDATE, VALIDATED)

        Returns:
            AlphaCandidate with eligibility determined
        """
        if eligible_verdicts is None:
            eligible_verdicts = ["CANDIDATE", "VALIDATED"]

        verdict = record.evidence_gate_verdict or record.status.value

        if verdict in eligible_verdicts:
            status = EligibilityStatus.ELIGIBLE
            reason = f"Evidence verdict '{verdict}' is eligible"
        elif verdict == "REJECTED":
            status = EligibilityStatus.EXCLUDED
            reason = "REJECTED by evidence gate"
        elif verdict == "INCONCLUSIVE":
            status = EligibilityStatus.EXCLUDED
            reason = "INCONCLUSIVE — insufficient evidence"
        else:
            status = EligibilityStatus.EXCLUDED
            reason = f"Unknown verdict: {verdict}"

        return cls(
            candidate_id=candidate_id,
            hypothesis_id=record.hypothesis_id,
            execution_record_id=record.execution_id,
            evidence_verdict=verdict,
            strategy_config_hash=record.backtest_config_hash,
            feature_set_hash=record.feature_set_hash,
            provenance_hash=record.provenance_hash,
            dataset_version=record.universe_definition.get("dataset_version", ""),
            universe_definition=record.universe_definition,
            return_stream_reference=f"rs_{record.execution_id}",
            eligibility_status=status,
            eligibility_reason=reason,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "candidate_id": self.candidate_id,
            "hypothesis_id": self.hypothesis_id,
            "execution_record_id": self.execution_record_id,
            "evidence_verdict": self.evidence_verdict,
            "strategy_config_hash": self.strategy_config_hash,
            "feature_set_hash": self.feature_set_hash,
            "provenance_hash": self.provenance_hash,
            "dataset_version": self.dataset_version,
            "universe_definition": dict(sorted(self.universe_definition.items())),
            "return_stream_reference": self.return_stream_reference,
            "eligibility_status": self.eligibility_status.value,
            "eligibility_reason": self.eligibility_reason,
            "metadata": dict(sorted(self.metadata.items())),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AlphaCandidate:
        """Deserialize from dict."""
        status_str = d.get("eligibility_status", "pending")
        try:
            status = EligibilityStatus(status_str)
        except ValueError:
            status = EligibilityStatus.PENDING
        return cls(
            candidate_id=d["candidate_id"],
            hypothesis_id=d["hypothesis_id"],
            execution_record_id=d["execution_record_id"],
            evidence_verdict=d.get("evidence_verdict", ""),
            strategy_config_hash=d.get("strategy_config_hash", ""),
            feature_set_hash=d.get("feature_set_hash", ""),
            provenance_hash=d.get("provenance_hash", ""),
            dataset_version=d.get("dataset_version", ""),
            universe_definition=d.get("universe_definition", {}),
            return_stream_reference=d.get("return_stream_reference", ""),
            eligibility_status=status,
            eligibility_reason=d.get("eligibility_reason", ""),
            metadata=d.get("metadata", {}),
        )

    @property
    def is_eligible(self) -> bool:
        """Check if this candidate is eligible for combination."""
        return self.eligibility_status == EligibilityStatus.ELIGIBLE

    def compute_hash(self) -> str:
        """Compute deterministic hash of this candidate."""
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
