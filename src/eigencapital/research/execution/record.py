"""ExecutionRecord — immutable record of a hypothesis execution.

Once registered, an ExecutionRecord cannot be modified. This prevents
post-hoc contamination of research results.

Every execution produces:
- hypothesis_hash (frozen at registration)
- experiment_hash (frozen at registration)
- feature_set_hash (computed deterministically)
- backtest_config_hash (frozen at registration)
- cost_model_hash (frozen at registration)
- provenance_hash (computed from all inputs)

The final evidence report answers:
> Exactly what did we test, with what data, features, parameters,
> costs, code, universe and validation procedure?
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any


class ExecutionStatus(str, Enum):
    """Lifecycle status of an execution record."""

    REGISTERED = "registered"
    COMPUTING_FEATURES = "computing_features"
    BACKTESTING = "backtesting"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionRecord:
    """Immutable record of a hypothesis execution.

    Critical invariant: Once status becomes COMPLETED or FAILED,
    no field may change. This prevents post-hoc contamination.

    Attributes:
        execution_id: Unique identifier (e.g., "EXEC-000001")
        hypothesis_id: Link to hypothesis
        hypothesis_hash: Hash of hypothesis at registration time
        experiment_id: Link to experiment
        experiment_hash: Hash of experiment at registration time
        trial_group_id: Trial family assignment
        trial_index: Position within trial family
        feature_requests: Features requested for this execution
        feature_set_hash: Hash of computed FeatureSet (set after computation)
        backtest_config: Backtest configuration snapshot
        backtest_config_hash: Hash of backtest config
        cost_model_id: Cost model identifier
        cost_model_hash: Hash of cost model
        universe_definition: Universe snapshot
        universe_hash: Hash of universe definition
        parameter_snapshot: Strategy parameters at registration
        status: Current lifecycle status
        result: Backtest results (set after completion)
        validation_result: Phase 1G validation result (set after validation)
        evidence_gate_verdict: Final evidence gate verdict
        rejection_reason: Why rejected (if applicable)
        provenance_hash: Deterministic hash of all inputs
        created_at: ISO-8601 UTC creation timestamp
        completed_at: ISO-8601 UTC completion timestamp
        metadata: Free-form additional metadata
    """

    execution_id: str
    hypothesis_id: str
    hypothesis_hash: str
    experiment_id: str
    experiment_hash: str
    trial_group_id: str
    trial_index: int
    feature_requests: List[Dict[str, Any]] = field(default_factory=list)
    feature_set_hash: str = ""
    backtest_config: Dict[str, Any] = field(default_factory=dict)
    backtest_config_hash: str = ""
    cost_model_id: str = ""
    cost_model_hash: str = ""
    universe_definition: Dict[str, Any] = field(default_factory=dict)
    universe_hash: str = ""
    parameter_snapshot: Dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.REGISTERED
    result: Dict[str, Any] = field(default_factory=dict)
    validation_result: Dict[str, Any] = field(default_factory=dict)
    evidence_gate_verdict: str = ""
    rejection_reason: str = ""
    provenance_hash: str = ""
    created_at: str = ""
    completed_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.execution_id:
            raise ValueError("execution_id must be non-empty")
        if not self.hypothesis_id:
            raise ValueError("hypothesis_id must be non-empty")
        if not self.experiment_id:
            raise ValueError("experiment_id must be non-empty")
        if not self.trial_group_id:
            raise ValueError("trial_group_id must be non-empty")
        if not isinstance(self.trial_index, int) or self.trial_index < 1:
            raise ValueError(f"trial_index must be int >= 1, got {self.trial_index!r}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "execution_id": self.execution_id,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "experiment_id": self.experiment_id,
            "experiment_hash": self.experiment_hash,
            "trial_group_id": self.trial_group_id,
            "trial_index": self.trial_index,
            "feature_requests": self.feature_requests,
            "feature_set_hash": self.feature_set_hash,
            "backtest_config": dict(sorted(self.backtest_config.items())),
            "backtest_config_hash": self.backtest_config_hash,
            "cost_model_id": self.cost_model_id,
            "cost_model_hash": self.cost_model_hash,
            "universe_definition": dict(sorted(self.universe_definition.items())),
            "universe_hash": self.universe_hash,
            "parameter_snapshot": dict(sorted(self.parameter_snapshot.items())),
            "status": self.status.value,
            "result": dict(sorted(self.result.items())),
            "validation_result": dict(sorted(self.validation_result.items())),
            "evidence_gate_verdict": self.evidence_gate_verdict,
            "rejection_reason": self.rejection_reason,
            "provenance_hash": self.provenance_hash,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": dict(sorted(self.metadata.items())),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ExecutionRecord:
        """Deserialize from dict."""
        status_str = d.get("status", "registered")
        try:
            status = ExecutionStatus(status_str)
        except ValueError:
            status = ExecutionStatus.REGISTERED
        return cls(
            execution_id=d["execution_id"],
            hypothesis_id=d["hypothesis_id"],
            hypothesis_hash=d.get("hypothesis_hash", ""),
            experiment_id=d["experiment_id"],
            experiment_hash=d.get("experiment_hash", ""),
            trial_group_id=d.get("trial_group_id", ""),
            trial_index=d.get("trial_index", 1),
            feature_requests=d.get("feature_requests", []),
            feature_set_hash=d.get("feature_set_hash", ""),
            backtest_config=d.get("backtest_config", {}),
            backtest_config_hash=d.get("backtest_config_hash", ""),
            cost_model_id=d.get("cost_model_id", ""),
            cost_model_hash=d.get("cost_model_hash", ""),
            universe_definition=d.get("universe_definition", {}),
            universe_hash=d.get("universe_hash", ""),
            parameter_snapshot=d.get("parameter_snapshot", {}),
            status=status,
            result=d.get("result", {}),
            validation_result=d.get("validation_result", {}),
            evidence_gate_verdict=d.get("evidence_gate_verdict", ""),
            rejection_reason=d.get("rejection_reason", ""),
            provenance_hash=d.get("provenance_hash", ""),
            created_at=d.get("created_at", ""),
            completed_at=d.get("completed_at", ""),
            metadata=d.get("metadata", {}),
        )

    def compute_provenance_hash(self) -> str:
        """Compute deterministic hash of all inputs."""
        data = self.to_dict()
        data.pop("provenance_hash", None)
        data.pop("result", None)
        data.pop("validation_result", None)
        data.pop("evidence_gate_verdict", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
