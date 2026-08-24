"""Feature infrastructure for alpha research.

The features layer provides:
- Canonical Feature model with availability tracking
- Feature family taxonomy
- Feature registry for version tracking
- Deterministic serialization and provenance

Critical invariant:
    availability_timestamp <= decision_timestamp

This prevents look-ahead bias in feature computation.
"""

from eigencapital.features.feature import Feature
from eigencapital.features.contracts import FeatureConfig, FeatureFamily, Normalization
from eigencapital.features.registry import FeatureRegistry, FeatureDefinition
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
    "FeatureError",
    "FeatureAvailabilityError",
    "FeatureDuplicateError",
    "FeatureValidationError",
    "FeatureRegistryError",
]
