"""Research Manifest — machine-readable experiment identity.

Every experiment produces a manifest that fully describes
what produced a research result.

Usage:
    manifest = ResearchManifest.from_experiment(exp)
    yaml_str = manifest.to_yaml()
    h = manifest.provenance_hash
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from typing import Any, Dict

from eigencapital.research.provenance.hashing import compute_provenance_hash


@dataclass(frozen=True)
class ResearchManifest:
    """Machine-readable experiment identity.

    Attributes:
        experiment_id: Unique identifier
        hypothesis_id: Link to hypothesis
        code_git_commit: Code state
        code_package_version: Package version
        dataset_id: Dataset identifier
        dataset_version: Dataset version
        dataset_hash: Dataset content hash
        strategy_id: Strategy identifier
        strategy_version: Strategy version
        strategy_config_hash: Hash of strategy parameters
        strategy_artifact_hash: Hash of strategy code
        parameters: Strategy configuration
        cost_model_id: Cost model identifier
        cost_model_version: Cost model version
        periods: Train/validation/test periods
        random_seed: For reproducibility
        environment: Platform info
        provenance_hash: Deterministic identity hash
    """

    experiment_id: str
    hypothesis_id: str = ""
    code_git_commit: str = ""
    code_package_version: str = "0.1.0"
    dataset_id: str = ""
    dataset_version: str = ""
    dataset_hash: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    strategy_config_hash: str = ""
    strategy_artifact_hash: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    cost_model_id: str = "zero"
    cost_model_version: str = "v1"
    periods: Dict[str, Dict[str, str]] = field(default_factory=dict)
    random_seed: int | None = None
    environment: Dict[str, str] = field(default_factory=dict)
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id must be non-empty")
        # Auto-compute provenance_hash if not provided
        if not self.provenance_hash:
            hash_input = {
                "experiment_id": self.experiment_id,
                "code_git_commit": self.code_git_commit,
                "dataset_id": self.dataset_id,
                "dataset_hash": self.dataset_hash,
                "strategy_id": self.strategy_id,
                "strategy_config_hash": self.strategy_config_hash,
                "strategy_artifact_hash": self.strategy_artifact_hash,
                "parameters": self.parameters,
                "cost_model_id": self.cost_model_id,
                "periods": self.periods,
                "random_seed": self.random_seed,
            }
            object.__setattr__(self, "provenance_hash", compute_provenance_hash(hash_input))

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "code_git_commit": self.code_git_commit,
            "code_package_version": self.code_package_version,
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
            "periods": self.periods,
            "random_seed": self.random_seed,
            "environment": self.environment,
            "provenance_hash": self.provenance_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        """Produce deterministic JSON manifest."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_experiment(cls, exp: Any) -> ResearchManifest:
        """Build a manifest from an ExperimentRecord."""
        periods = {}
        if exp.train_start and exp.train_end:
            periods["train"] = {"start": exp.train_start, "end": exp.train_end}
        if exp.validation_start and exp.validation_end:
            periods["validation"] = {
                "start": exp.validation_start,
                "end": exp.validation_end,
            }
        if exp.test_start and exp.test_end:
            periods["test"] = {"start": exp.test_start, "end": exp.test_end}

        env = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        }

        manifest = cls(
            experiment_id=exp.experiment_id,
            hypothesis_id=exp.hypothesis_id,
            code_git_commit=exp.git_commit,
            dataset_id=exp.dataset_id,
            dataset_version=exp.dataset_version,
            dataset_hash=exp.dataset_hash,
            strategy_id=exp.strategy_id,
            strategy_version=exp.strategy_version,
            strategy_config_hash=exp.strategy_config_hash,
            strategy_artifact_hash=exp.strategy_artifact_hash,
            parameters=exp.parameters,
            cost_model_id=exp.cost_model_id,
            cost_model_version=exp.cost_model_version,
            periods=periods,
            random_seed=exp.random_seed,
            environment=env,
        )

        # Compute provenance hash (excluding environment-dependent fields)
        hash_input = {
            "experiment_id": manifest.experiment_id,
            "code_git_commit": manifest.code_git_commit,
            "dataset_id": manifest.dataset_id,
            "dataset_hash": manifest.dataset_hash,
            "strategy_id": manifest.strategy_id,
            "strategy_config_hash": manifest.strategy_config_hash,
            "strategy_artifact_hash": manifest.strategy_artifact_hash,
            "parameters": manifest.parameters,
            "cost_model_id": manifest.cost_model_id,
            "periods": manifest.periods,
            "random_seed": manifest.random_seed,
        }
        provenance_hash = compute_provenance_hash(hash_input)

        return cls(**{**manifest.__dict__, "provenance_hash": provenance_hash})

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ResearchManifest:
        """Deserialize from dict."""
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})
