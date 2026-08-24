"""Experiment Registry — lifecycle management and parameter freezing.

Manages experiment lifecycle:
    PRE_REGISTERED → RUNNING → COMPLETED → CANDIDATE | REJECTED

Critical invariant: Once test parameters are frozen, the experiment
becomes immutable. This prevents accidental research contamination.

Usage:
    registry = ExperimentRegistry()
    exp = registry.create(
        experiment_id="EXP-000001",
        hypothesis_id="HYP-000001",
        strategy_id="trend_v1",
        ...
    )
    exp = registry.freeze_test_parameters("EXP-000001")
    exp = registry.complete("EXP-000001", status="CANDIDATE")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from eigencapital.research.provenance.hashing import compute_provenance_hash
from eigencapital.research.provenance.manifest import ResearchManifest


class ExperimentError(ValueError):
    """Raised on invalid experiment state transitions or modifications."""

    def __init__(self, message: str, experiment_id: str = "") -> None:
        super().__init__(message)
        self.experiment_id = experiment_id


@dataclass
class ExperimentRecord:
    """A single experiment with full lifecycle.

    Attributes:
        experiment_id: Unique identifier (e.g., "EXP-000001")
        hypothesis_id: Link to pre-registered hypothesis
        git_commit: Code state at experiment start
        dataset_id: Dataset identifier
        dataset_version: Dataset version
        dataset_hash: Content hash of dataset
        strategy_id: Strategy identifier
        strategy_version: Strategy code version
        strategy_config_hash: Hash of strategy parameters
        strategy_artifact_hash: Hash of strategy implementation
        parameters: Strategy configuration dict
        cost_model_id: Cost model identifier
        cost_model_version: Cost model version
        random_seed: For stochastic reproducibility
        parent_experiment_id: Lineage — experiment this one extends ("" if none)
        trial_metadata: Multiple-testing accounting dict (see TrialMetadata):
            trial_group_id, trial_index, hypothesis_family, selection_method,
            trials_in_family, parameter_search_space
        train_start: Train period start (ISO-8601 UTC)
        train_end: Train period end
        validation_start: Validation period start
        validation_end: Validation period end
        test_start: Test period start
        test_end: Test period end
        status: Lifecycle status
        test_frozen: Whether test parameters are frozen
        provenance_hash: Deterministic hash of all inputs
        result: Outcome summary (Sharpe, etc.)
        rejection_reason: Why rejected (if applicable)
        created_at: ISO-8601 UTC creation timestamp
        updated_at: ISO-8601 UTC last update
    """

    experiment_id: str
    hypothesis_id: str
    git_commit: str
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    strategy_id: str
    strategy_version: str
    strategy_config_hash: str
    strategy_artifact_hash: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    cost_model_id: str = "zero"
    cost_model_version: str = "v1"
    random_seed: Optional[int] = None
    parent_experiment_id: str = ""
    trial_metadata: Dict[str, Any] = field(default_factory=dict)
    train_start: str = ""
    train_end: str = ""
    validation_start: str = ""
    validation_end: str = ""
    test_start: str = ""
    test_end: str = ""
    status: str = "PRE_REGISTERED"
    test_frozen: bool = False
    provenance_hash: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    rejection_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    # Mutable fields that can change before freeze
    _MODIFIABLE_BEFORE_FREEZE = {
        "parameters", "strategy_version", "strategy_config_hash",
        "strategy_artifact_hash", "cost_model_id", "cost_model_version",
        "random_seed", "result", "rejection_reason",
    }

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id must be non-empty")
        valid_statuses = {"PRE_REGISTERED", "RUNNING", "COMPLETED", "REJECTED", "CANDIDATE"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status: {self.status}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "git_commit": self.git_commit,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_artifact_hash": self.strategy_artifact_hash,
            "parameters": dict(sorted(self.parameters.items())),
            "cost_model_id": self.cost_model_id,
            "cost_model_version": self.cost_model_version,
            "random_seed": self.random_seed,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "status": self.status,
            "test_frozen": self.test_frozen,
            "provenance_hash": self.provenance_hash,
            "result": dict(sorted(self.result.items())),
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ExperimentRecord:
        """Deserialize from dict."""
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


class ExperimentRegistry:
    """Manages experiment lifecycle and enforces invariants.

    Lifecycle:
        PRE_REGISTERED → RUNNING → COMPLETED → CANDIDATE | REJECTED

    Freezing:
        Once freeze_test_parameters() is called, the experiment
        becomes immutable (except status and result updates).
    """

    def __init__(self) -> None:
        self._experiments: Dict[str, ExperimentRecord] = {}

    def create(self, **kwargs: Any) -> ExperimentRecord:
        """Create and register a new experiment.

        Raises:
            ExperimentError: if experiment_id already exists
        """
        exp = ExperimentRecord(**kwargs)
        if exp.experiment_id in self._experiments:
            raise ExperimentError(
                f"Duplicate experiment_id: {exp.experiment_id}",
                experiment_id=exp.experiment_id,
            )
        # Compute provenance hash
        exp.provenance_hash = compute_provenance_hash(exp.to_dict())
        self._experiments[exp.experiment_id] = exp
        return exp

    def get(self, experiment_id: str) -> ExperimentRecord:
        """Get an experiment by ID."""
        if experiment_id not in self._experiments:
            raise ExperimentError(f"Experiment not found: {experiment_id}", experiment_id)
        return self._experiments[experiment_id]

    def freeze_test_parameters(self, experiment_id: str) -> ExperimentRecord:
        """Freeze test parameters — experiment becomes immutable.

        This is the point of no return for parameter modification.
        """
        exp = self.get(experiment_id)
        if exp.test_frozen:
            raise ExperimentError("Test parameters already frozen", experiment_id)
        if exp.status != "PRE_REGISTERED":
            raise ExperimentError(
                f"Cannot freeze: status is {exp.status}", experiment_id
            )
        # Recompute provenance hash after freeze
        exp.test_frozen = True
        exp.provenance_hash = compute_provenance_hash(exp.to_dict())
        return exp

    def start(self, experiment_id: str) -> ExperimentRecord:
        """Transition to RUNNING status."""
        exp = self.get(experiment_id)
        if exp.status != "PRE_REGISTERED":
            raise ExperimentError(
                f"Cannot start: status is {exp.status}", experiment_id
            )
        exp.status = "RUNNING"
        return exp

    def complete(self, experiment_id: str, status: str = "COMPLETED",
                 result: Optional[Dict[str, Any]] = None) -> ExperimentRecord:
        """Complete an experiment with a final status."""
        exp = self.get(experiment_id)
        if exp.status != "RUNNING":
            raise ExperimentError(
                f"Cannot complete: status is {exp.status}", experiment_id
            )
        valid_final = {"COMPLETED", "CANDIDATE", "REJECTED"}
        if status not in valid_final:
            raise ExperimentError(
                f"Invalid final status: {status}. Must be one of {valid_final}",
                experiment_id,
            )
        exp.status = status
        if result:
            exp.result = result
        exp.provenance_hash = compute_provenance_hash(exp.to_dict())
        return exp

    def list_experiments(self) -> list[ExperimentRecord]:
        """List all experiments in creation order."""
        return list(self._experiments.values())

    def __len__(self) -> int:
        return len(self._experiments)
