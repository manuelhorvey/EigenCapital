"""Feature Registry — central registry for feature definitions.

Tracks feature versions, prevents duplicates, and ensures
deterministic feature identity.

Usage:
    registry = FeatureRegistry()
    registry.register(feature_config)
    config = registry.get("return_20")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from eigencapital.features.contracts import FeatureConfig
from eigencapital.features.errors import (
    FeatureDuplicateError,
    FeatureRegistryError,
)


@dataclass(frozen=True)
class FeatureDefinition:
    """A registered feature definition.

    Attributes:
        feature_id: Unique identifier for this feature type
        version: Version string
        config: Feature configuration
        compute_fn: Optional callable that computes this feature
        description: Human-readable description
    """

    feature_id: str
    version: str
    config: FeatureConfig
    compute_fn: Callable | None = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "feature_id": self.feature_id,
            "version": self.version,
            "config": self.config.to_dict(),
            "description": self.description,
        }


class FeatureRegistry:
    """Central registry for feature definitions.

    The registry:
    - Prevents duplicate feature_id registrations
    - Tracks feature versions
    - Stores feature configurations
    - Optionally stores computation functions

    The registry does NOT:
    - Compute features (that's the feature module's job)
    - Store computed feature values (that's the backtest's job)
    - Bypass provenance tracking
    """

    def __init__(self) -> None:
        self._definitions: Dict[str, Dict[str, FeatureDefinition]] = {}

    def register(
        self,
        feature_id: str,
        version: str,
        config: FeatureConfig,
        compute_fn: Callable | None = None,
        description: str = "",
    ) -> FeatureDefinition:
        """Register a feature definition.

        Args:
            feature_id: Unique identifier (e.g., "return_20")
            version: Version string (e.g., "v1")
            config: Feature configuration
            compute_fn: Optional computation function
            description: Human-readable description

        Returns:
            FeatureDefinition

        Raises:
            FeatureDuplicateError: If feature_id + version already exists
        """
        if feature_id in self._definitions:
            if version in self._definitions[feature_id]:
                raise FeatureDuplicateError(f"Feature {feature_id} version {version} already registered")

        definition = FeatureDefinition(
            feature_id=feature_id,
            version=version,
            config=config,
            compute_fn=compute_fn,
            description=description,
        )

        if feature_id not in self._definitions:
            self._definitions[feature_id] = {}
        self._definitions[feature_id][version] = definition

        return definition

    def get(self, feature_id: str, version: str | None = None) -> FeatureDefinition:
        """Get a feature definition.

        Args:
            feature_id: Feature identifier
            version: Specific version (default: latest)

        Returns:
            FeatureDefinition

        Raises:
            FeatureRegistryError: If feature not found
        """
        if feature_id not in self._definitions:
            raise FeatureRegistryError(f"Feature '{feature_id}' not found in registry")

        versions = self._definitions[feature_id]
        if version is None:
            # Return latest version
            latest = sorted(versions.keys())[-1]
            return versions[latest]

        if version not in versions:
            raise FeatureRegistryError(f"Feature '{feature_id}' version '{version}' not found")

        return versions[version]

    def list_features(self) -> List[str]:
        """List all registered feature IDs."""
        return sorted(self._definitions.keys())

    def list_versions(self, feature_id: str) -> List[str]:
        """List all versions of a feature."""
        if feature_id not in self._definitions:
            raise FeatureRegistryError(f"Feature '{feature_id}' not found")
        return sorted(self._definitions[feature_id].keys())

    def has_feature(self, feature_id: str) -> bool:
        """Check if a feature is registered."""
        return feature_id in self._definitions

    def has_version(self, feature_id: str, version: str) -> bool:
        """Check if a specific version is registered."""
        return feature_id in self._definitions and version in self._definitions[feature_id]

    def __len__(self) -> int:
        """Total number of feature definitions (all versions)."""
        return sum(len(versions) for versions in self._definitions.values())

    def __contains__(self, feature_id: str) -> bool:
        return feature_id in self._definitions
