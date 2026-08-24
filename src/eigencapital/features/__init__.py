"""Feature infrastructure for alpha research.

The features layer provides:
- Canonical Feature model with availability tracking
- Feature family taxonomy
- Feature registry for version tracking
- FeatureSet for auditable research results
- Feature pipeline with dependency resolution
- Provenance tracking and verification

Critical invariant:
    availability_timestamp <= decision_timestamp

This prevents look-ahead bias in feature computation.
"""

from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureConfig, FeatureFamily, Normalization
from eigencapital.features.registry import FeatureRegistry, FeatureDefinition
from eigencapital.features.feature_set import FeatureSet, FeatureEntry, FeatureStatus
from eigencapital.features.dependencies import FeatureDAG, FeatureDependency, build_default_dag
from eigencapital.features.pipeline import FeaturePipeline, FeatureRequest, PipelineConfig
from eigencapital.features.provenance import ProvenanceRecord, build_provenance_record
from eigencapital.features.errors import (
    FeatureError,
    FeatureAvailabilityError,
    FeatureDuplicateError,
    FeatureValidationError,
    FeatureRegistryError,
)

__all__ = [
    "Feature",
    "FeatureConfig",
    "FeatureFamily",
    "Normalization",
    "FeatureRegistry",
    "FeatureDefinition",
    "FeatureSet",
    "FeatureEntry",
    "FeatureStatus",
    "FeatureDAG",
    "FeatureDependency",
    "build_default_dag",
    "FeaturePipeline",
    "FeatureRequest",
    "PipelineConfig",
    "ProvenanceRecord",
    "build_provenance_record",
    "FeatureError",
    "FeatureAvailabilityError",
    "FeatureDuplicateError",
    "FeatureValidationError",
    "FeatureRegistryError",
]
