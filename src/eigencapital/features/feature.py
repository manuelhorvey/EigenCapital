"""Canonical Feature model — the core domain contract.

Every feature in EigenCapital must conform to this model.
The critical invariant is:

    availability_timestamp <= decision_timestamp

A feature that mathematically uses only historical bars can still
leak information if the underlying data wasn't actually available
at the decision time.

Usage:
    feature = Feature(
        feature_id="return_20_ES",
        feature_version="v1",
        instrument_id="ES",
        timestamp_utc="2025-01-01T10:00:00Z",
        value=0.05,
        feature_family="returns",
        lookback=20,
        source_features=["close"],
        normalization="none",
        config_hash="abc123",
        provenance_hash="def456",
        availability_timestamp="2025-01-01T10:00:00Z",
    )
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List

from eigencapital.features.contracts import FeatureFamily, Normalization
from eigencapital.features.errors import (
    FeatureAvailabilityError,
    FeatureValidationError,
)


@dataclass(frozen=True)
class Feature:
    """Canonical feature with provenance and availability tracking.

    Critical invariant: availability_timestamp <= decision_timestamp.
    This prevents look-ahead bias in feature computation.

    Attributes:
        feature_id: Unique identifier (e.g., "return_20_ES")
        feature_version: Version string (e.g., "v1")
        instrument_id: FK → Instrument
        timestamp_utc: The bar timestamp this feature is computed from
        value: The feature value (scalar)
        feature_family: Which family (returns, momentum, etc.)
        lookback: How many bars were used
        source_features: Which raw fields fed this feature
        normalization: How the feature is normalized
        availability_timestamp: When this feature became computable
        config_hash: Hash of feature configuration parameters
        provenance_hash: Deterministic hash of all inputs
        metadata: Free-form additional metadata
    """

    feature_id: str
    feature_version: str
    instrument_id: str
    timestamp_utc: str
    value: float
    feature_family: str
    lookback: int
    source_features: List[str] = field(default_factory=list)
    normalization: str = Normalization.NONE
    availability_timestamp: str = ""
    config_hash: str = ""
    provenance_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate feature_id is non-empty
        if not self.feature_id:
            raise ValueError("feature_id must be non-empty")

        # Validate feature_version is non-empty
        if not self.feature_version:
            raise ValueError("feature_version must be non-empty")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate timestamp is ISO-8601
        if "T" not in self.timestamp_utc:
            raise ValueError(f"timestamp_utc should be ISO-8601 format, got: {self.timestamp_utc}")

        # Validate value is finite
        if math.isnan(self.value) or math.isinf(self.value):
            raise FeatureValidationError(f"Feature value must be finite, got {self.value}")

        # Validate feature_family
        if not FeatureFamily.is_valid(self.feature_family):
            raise ValueError(
                f"Invalid feature_family: {self.feature_family}. Must be one of {sorted(FeatureFamily.ALL_FAMILIES)}"
            )

        # Validate lookback
        if self.lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {self.lookback}")

        # Validate normalization
        if not Normalization.is_valid(self.normalization):
            raise ValueError(
                f"Invalid normalization: {self.normalization}. Must be one of {sorted(Normalization.ALL_METHODS)}"
            )

        # Validate availability_timestamp is ISO-8601
        if self.availability_timestamp and "T" not in self.availability_timestamp:
            raise ValueError(f"availability_timestamp should be ISO-8601 format, got: {self.availability_timestamp}")

        # INVARIANT: availability_timestamp <= timestamp_utc
        if self.availability_timestamp and self.timestamp_utc and self.availability_timestamp > self.timestamp_utc:
            raise FeatureAvailabilityError(
                f"availability_timestamp ({self.availability_timestamp}) "
                f"> timestamp_utc ({self.timestamp_utc}). "
                f"This feature would constitute look-ahead bias."
            )

    def __hash__(self) -> int:
        return hash((self.feature_id, self.feature_version, self.timestamp_utc))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Feature):
            return NotImplemented
        return (
            self.feature_id == other.feature_id
            and self.feature_version == other.feature_version
            and self.timestamp_utc == other.timestamp_utc
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "value": self.value,
            "feature_family": self.feature_family,
            "lookback": self.lookback,
            "source_features": sorted(self.source_features),
            "normalization": self.normalization,
            "availability_timestamp": self.availability_timestamp,
            "config_hash": self.config_hash,
            "provenance_hash": self.provenance_hash,
            "metadata": dict(sorted(self.metadata.items())),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Feature:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Feature(
            feature_id=d["feature_id"],
            feature_version=d["feature_version"],
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            value=float(d["value"]),
            feature_family=d["feature_family"],
            lookback=int(d["lookback"]),
            source_features=d.get("source_features", []),
            normalization=d.get("normalization", Normalization.NONE),
            availability_timestamp=d.get("availability_timestamp", ""),
            config_hash=d.get("config_hash", ""),
            provenance_hash=d.get("provenance_hash", ""),
            metadata=d.get("metadata", {}),
        )

    def compute_config_hash(self) -> str:
        """Compute deterministic hash of feature configuration."""
        config_data = {
            "feature_family": self.feature_family,
            "normalization": self.normalization,
            "lookback": self.lookback,
            "source_features": sorted(self.source_features),
        }
        payload = json.dumps(config_data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def compute_provenance_hash(self) -> str:
        """Compute deterministic hash of all feature inputs."""
        data = self.to_dict()
        # Remove provenance_hash itself to avoid circular reference
        data.pop("provenance_hash", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def is_available(self) -> bool:
        """Check if this feature is available (has an availability timestamp)."""
        return bool(self.availability_timestamp)

    @property
    def has_provenance(self) -> bool:
        """Check if this feature has provenance tracking."""
        return bool(self.provenance_hash)
