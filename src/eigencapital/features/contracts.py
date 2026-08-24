"""Feature family taxonomy and normalization contracts.

Defines the canonical feature families and normalization methods
used across EigenCapital's research infrastructure.

Every feature must belong to exactly one family and use exactly
one normalization method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Set


# ── Feature Families ──────────────────────────────────────────────


class FeatureFamily:
    """Canonical feature families.

    Each family represents a distinct category of alpha research.
    New families should be added here, not scattered across modules.
    """

    # Base / primitive features
    RETURNS = "returns"
    VOLATILITY = "volatility"
    RANGES = "ranges"
    VOLUME = "volume"

    # Alpha research families
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    CROSS_SECTIONAL = "cross_sectional"
    VOLATILITY_REGIME = "volatility_regime"
    CROSS_ASSET = "cross_asset"

    # Derived / structural
    STRUCTURAL = "structural"
    DERIVED = "derived"

    ALL_FAMILIES: Set[str] = {
        RETURNS,
        VOLATILITY,
        RANGES,
        VOLUME,
        MOMENTUM,
        MEAN_REVERSION,
        CROSS_SECTIONAL,
        VOLATILITY_REGIME,
        CROSS_ASSET,
        STRUCTURAL,
        DERIVED,
    }

    @classmethod
    def is_valid(cls, family: str) -> bool:
        """Check if a family string is valid."""
        return family in cls.ALL_FAMILIES

    @classmethod
    def register(cls, family: str) -> None:
        """Register a new feature family (for extensibility)."""
        cls.ALL_FAMILIES.add(family)


# ── Normalization Methods ─────────────────────────────────────────


class Normalization:
    """Canonical normalization methods.

    Every feature must declare its normalization method.
    This ensures reproducibility and comparability.
    """

    NONE = "none"
    ZSCORE = "zscore"
    RANK = "rank"
    PCT_CHANGE = "pct_change"
    LOG_RETURN = "log_return"
    MIN_MAX = "min_max"
    WINSORIZE = "winsorize"
    DIFFERENCING = "differencing"

    ALL_METHODS: Set[str] = {
        NONE,
        ZSCORE,
        RANK,
        PCT_CHANGE,
        LOG_RETURN,
        MIN_MAX,
        WINSORIZE,
        DIFFERENCING,
    }

    @classmethod
    def is_valid(cls, method: str) -> bool:
        """Check if a normalization method is valid."""
        return method in cls.ALL_METHODS


# ── Feature Configuration ─────────────────────────────────────────


@dataclass(frozen=True)
class FeatureConfig:
    """Configuration for feature computation.

    Every feature must have a configuration that fully specifies
    how it was computed. This enables:
    - Deterministic recomputation
    - Provenance tracking
    - Version comparison
    - Configuration hashing

    Attributes:
        feature_family: Which family this feature belongs to
        normalization: How the feature is normalized
        lookback: Number of bars used in computation
        parameters: Additional parameters (e.g., window sizes, thresholds)
        description: Human-readable description
    """

    feature_family: str
    normalization: str = Normalization.NONE
    lookback: int = 1
    parameters: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not FeatureFamily.is_valid(self.feature_family):
            raise ValueError(
                f"Invalid feature_family: {self.feature_family}. "
                f"Must be one of {sorted(FeatureFamily.ALL_FAMILIES)}"
            )
        if not Normalization.is_valid(self.normalization):
            raise ValueError(
                f"Invalid normalization: {self.normalization}. "
                f"Must be one of {sorted(Normalization.ALL_METHODS)}"
            )
        if self.lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {self.lookback}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for hashing."""
        return {
            "feature_family": self.feature_family,
            "normalization": self.normalization,
            "lookback": self.lookback,
            "parameters": dict(sorted(self.parameters.items())),
            "description": self.description,
        }
