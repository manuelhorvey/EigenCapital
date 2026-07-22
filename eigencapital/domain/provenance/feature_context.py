"""FeatureContext — frozen snapshot of the feature vector at decision time.

Contains the actual feature values used for model inference, the feature
hash (for causal boundary tracing), and metadata about the feature pipeline
version and schema that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FeatureContext:
    feature_hash: str
    feature_vector: dict[str, float] = field(default_factory=dict)
    feature_schema_version: str = ""
    feature_names: list[str] = field(default_factory=list)
    n_features: int = 0
    n_missing: int = 0
    missing_features: list[str] = field(default_factory=list)
    feature_pipeline_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_hash": self.feature_hash,
            "feature_vector": self.feature_vector,
            "feature_schema_version": self.feature_schema_version,
            "feature_names": self.feature_names,
            "n_features": self.n_features,
            "n_missing": self.n_missing,
            "missing_features": self.missing_features,
            "feature_pipeline_version": self.feature_pipeline_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureContext:
        return cls(**data)
