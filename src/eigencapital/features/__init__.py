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

from eigencapital.features.contracts import FeatureConfig, FeatureFamily, Normalization
from eigencapital.features.dependencies import (
    FeatureDAG,
    FeatureDependency,
    build_default_dag,
)
from eigencapital.features.errors import (
    FeatureAvailabilityError,
    FeatureDuplicateError,
    FeatureError,
    FeatureRegistryError,
    FeatureValidationError,
)
from eigencapital.features.feature import Feature
from eigencapital.features.feature_set import FeatureEntry, FeatureSet, FeatureStatus
from eigencapital.features.pipeline import (
    FeaturePipeline,
    FeatureRequest,
    PipelineConfig,
)
from eigencapital.features.provenance import ProvenanceRecord, build_provenance_record
from eigencapital.features.registry import FeatureDefinition, FeatureRegistry

__all__ = [
    "Feature",
    "FeatureAvailabilityError",
    "FeatureConfig",
    "FeatureDAG",
    "FeatureDefinition",
    "FeatureDependency",
    "FeatureDuplicateError",
    "FeatureEntry",
    "FeatureError",
    "FeatureFamily",
    "FeaturePipeline",
    "FeatureRegistry",
    "FeatureRegistryError",
    "FeatureRequest",
    "FeatureSet",
    "FeatureStatus",
    "FeatureValidationError",
    "Normalization",
    "PipelineConfig",
    "ProvenanceRecord",
    "build_default_dag",
    "build_provenance_record",
]
