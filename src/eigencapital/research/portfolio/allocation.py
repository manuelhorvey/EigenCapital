"""Allocation Experiment — portfolio-level research identity.

Every portfolio combination is itself a new research hypothesis and must be
independently registered, executed, validated and stress-tested.

This module defines:
- AllocationExperiment: portfolio-level experiment identity
- AllocationMethod: weighting methodology
- AllocationResult: result of a portfolio allocation experiment
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple


class AllocationMethod(str, Enum):
    """Portfolio allocation methodology."""

    EQUAL_WEIGHT = "equal_weight"
    RISK_SCALD = "risk_scaled"  # Fixed: should be RISK_SCALED
    MINIMUM_VARIANCE = "minimum_variance"
    RISK_PARITY = "risk_parity"
    HRP = "hrp"  # Hierarchical Risk Parity
    MAX_SHARPE = "max_sharpe"
    EQUAL_RISK_CONTRIBUTION = "equal_risk_contribution"


class AllocationStatus(str, Enum):
    """Lifecycle status of an allocation experiment."""

    REGISTERED = "registered"
    COMPUTING = "computing"
    VALIDATING = "validating"
    STRESS_TESTING = "stress_testing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class AllocationExperiment:
    """Portfolio-level experiment identity.

    Every portfolio combination must have an explicit claim and be
    independently registered before execution.

    Attributes:
        experiment_id: Unique identifier
        hypothesis_id: Link to portfolio hypothesis
        constituents: Tuple of candidate IDs included
        allocation_method: Weighting methodology
        parameters: Allocation parameters (lookback, constraints, etc.)
        rebalance_frequency: How often weights are updated
        cost_model_id: Cost model identifier
        dataset_version: Dataset version
        universe: Universe definition
        trial_group_id: Trial family assignment
        trial_index: Position within trial family
        status: Lifecycle status
        provenance_hash: Deterministic hash
        result: Experiment results
        created_at: ISO-8601 creation timestamp
    """

    experiment_id: str
    hypothesis_id: str
    constituents: Tuple[str, ...]
    allocation_method: AllocationMethod
    parameters: Dict[str, Any] = field(default_factory=dict)
    rebalance_frequency: str = "monthly"
    cost_model_id: str = "moderate_v1"
    dataset_version: str = ""
    universe: Dict[str, Any] = field(default_factory=dict)
    trial_group_id: str = ""
    trial_index: int = 1
    status: AllocationStatus = AllocationStatus.REGISTERED
    provenance_hash: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id must be non-empty")
        if not self.hypothesis_id:
            raise ValueError("hypothesis_id must be non-empty")
        if not self.constituents:
            raise ValueError("constituents must not be empty")
        if not isinstance(self.trial_index, int) or self.trial_index < 1:
            raise ValueError(f"trial_index must be int >= 1, got {self.trial_index!r}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "constituents": list(self.constituents),
            "allocation_method": self.allocation_method.value,
            "parameters": dict(sorted(self.parameters.items())),
            "rebalance_frequency": self.rebalance_frequency,
            "cost_model_id": self.cost_model_id,
            "dataset_version": self.dataset_version,
            "universe": dict(sorted(self.universe.items())),
            "trial_group_id": self.trial_group_id,
            "trial_index": self.trial_index,
            "status": self.status.value,
            "result": dict(sorted(self.result.items())),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AllocationExperiment:
        """Deserialize from dict."""
        method_str = d.get("allocation_method", "equal_weight")
        try:
            method = AllocationMethod(method_str)
        except ValueError:
            method = AllocationMethod.EQUAL_WEIGHT

        status_str = d.get("status", "registered")
        try:
            status = AllocationStatus(status_str)
        except ValueError:
            status = AllocationStatus.REGISTERED

        return cls(
            experiment_id=d["experiment_id"],
            hypothesis_id=d["hypothesis_id"],
            constituents=tuple(d.get("constituents", [])),
            allocation_method=method,
            parameters=d.get("parameters", {}),
            rebalance_frequency=d.get("rebalance_frequency", "monthly"),
            cost_model_id=d.get("cost_model_id", "moderate_v1"),
            dataset_version=d.get("dataset_version", ""),
            universe=d.get("universe", {}),
            trial_group_id=d.get("trial_group_id", ""),
            trial_index=d.get("trial_index", 1),
            status=status,
            result=d.get("result", {}),
            created_at=d.get("created_at", ""),
        )

    def compute_provenance_hash(self) -> str:
        """Compute deterministic hash of all inputs."""
        data = self.to_dict()
        data.pop("result", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
