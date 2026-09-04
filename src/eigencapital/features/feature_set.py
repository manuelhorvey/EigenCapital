"""FeatureSet — auditable research object for computed feature values.

A FeatureSet is NOT a dict[str, float]. It is a versioned, provenance-tracked,
point-in-time-safe container for a collection of features computed for a single
instrument at a specific decision timestamp.

Critical invariants:
- availability_timestamp <= decision_timestamp for every feature
- FeatureSet is immutable once created
- Provenance hash is deterministic and reproducible
- Missing features are explicitly recorded as UNAVAILABLE, never silently zeroed
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class FeatureStatus(str, Enum):
    """Status of a feature within a FeatureSet."""

    COMPUTED = "computed"
    UNAVAILABLE = "unavailable"  # insufficient warm-up
    STALE = "stale"  # availability > decision time
    FAILED = "failed"  # computation error


@dataclass(frozen=True)
class FeatureEntry:
    """A single feature entry within a FeatureSet.

    Tracks both the feature value (if computed) and its status.
    This allows explicit recording of missing/failed features
    rather than silent substitution with zeros.
    """

    feature_id: str
    feature_version: str
    status: FeatureStatus
    value: float | None = None
    availability_timestamp: str = ""
    config_hash: str = ""
    provenance_hash: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "status": self.status.value,
            "value": self.value,
            "availability_timestamp": self.availability_timestamp,
            "config_hash": self.config_hash,
            "provenance_hash": self.provenance_hash,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FeatureEntry:
        """Deserialize from dict."""
        return cls(
            feature_id=d["feature_id"],
            feature_version=d["feature_version"],
            status=FeatureStatus(d["status"]),
            value=d.get("value"),
            availability_timestamp=d.get("availability_timestamp", ""),
            config_hash=d.get("config_hash", ""),
            provenance_hash=d.get("provenance_hash", ""),
            error_message=d.get("error_message", ""),
        )

    @property
    def is_computed(self) -> bool:
        """Check if this feature was successfully computed."""
        return self.status == FeatureStatus.COMPUTED

    @property
    def is_usable(self) -> bool:
        """Check if this feature's value is available for use."""
        return self.status == FeatureStatus.COMPUTED and self.value is not None


@dataclass(frozen=True)
class FeatureSet:
    """Auditable research object for a collection of computed features.

    A FeatureSet represents the complete feature state for a single instrument
    at a specific decision timestamp. It is immutable and fully provenance-tracked.

    Critical invariant:
        For every computed feature:
            feature.availability_timestamp <= decision_timestamp

    This prevents look-ahead bias at the pipeline level, not just at the
    individual feature level.

    Attributes:
        instrument_id: Which instrument these features are for
        decision_timestamp: When the decision is being made (ISO-8601 UTC)
        timestamp_utc: The bar timestamp this FeatureSet is computed from
        entries: Dict mapping feature_id → FeatureEntry
        dataset_version: Which dataset version was used
        universe_version: Which universe definition was used
        provenance_hash: Deterministic hash of all inputs and outputs
        metadata: Free-form additional metadata
    """

    instrument_id: str
    decision_timestamp: str  # When the decision is made
    timestamp_utc: str  # The bar timestamp
    entries: Dict[str, FeatureEntry] = field(default_factory=dict)
    dataset_version: str = ""
    universe_version: str = ""
    provenance_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate timestamps
        if "T" not in self.decision_timestamp:
            raise ValueError(f"decision_timestamp must be ISO-8601, got: {self.decision_timestamp}")
        if "T" not in self.timestamp_utc:
            raise ValueError(f"timestamp_utc must be ISO-8601, got: {self.timestamp_utc}")
        if self.timestamp_utc > self.decision_timestamp:
            raise ValueError(
                f"timestamp_utc ({self.timestamp_utc}) must be <= "
                f"decision_timestamp ({self.decision_timestamp}). "
                f"Features cannot be computed from future bars."
            )

    def get_value(self, feature_id: str) -> float | None:
        """Get a feature value by ID.

        Returns None if the feature is missing, unavailable, or failed.
        This is the safe way to access feature values.
        """
        entry = self.entries.get(feature_id)
        if entry is None or not entry.is_usable:
            return None
        return entry.value

    def get_entry(self, feature_id: str) -> FeatureEntry | None:
        """Get a feature entry by ID."""
        return self.entries.get(feature_id)

    @property
    def computed_features(self) -> Dict[str, float]:
        """Get all successfully computed feature values."""
        return {fid: entry.value for fid, entry in self.entries.items() if entry.is_usable and entry.value is not None}

    @property
    def unavailable_features(self) -> List[str]:
        """Get list of features that were unavailable (insufficient warm-up)."""
        return [fid for fid, entry in self.entries.items() if entry.status == FeatureStatus.UNAVAILABLE]

    @property
    def failed_features(self) -> List[str]:
        """Get list of features that failed computation."""
        return [fid for fid, entry in self.entries.items() if entry.status == FeatureStatus.FAILED]

    @property
    def feature_count(self) -> int:
        """Total number of features in the set."""
        return len(self.entries)

    @property
    def computed_count(self) -> int:
        """Number of successfully computed features."""
        return sum(1 for e in self.entries.values() if e.is_computed)

    @property
    def data_quality(self) -> Dict[str, int]:
        """Summary of feature status counts."""
        counts: Dict[str, int] = {}
        for entry in self.entries.values():
            status = entry.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "instrument_id": self.instrument_id,
            "decision_timestamp": self.decision_timestamp,
            "timestamp_utc": self.timestamp_utc,
            "entries": {fid: entry.to_dict() for fid, entry in sorted(self.entries.items())},
            "dataset_version": self.dataset_version,
            "universe_version": self.universe_version,
            "metadata": dict(sorted(self.metadata.items())),
        }

    def compute_provenance_hash(self) -> str:
        """Compute deterministic hash of all inputs and outputs."""
        data = self.to_dict()
        # Remove provenance_hash from entries to avoid circular reference
        for entry_data in data["entries"].values():
            entry_data.pop("provenance_hash", None)
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def with_provenance(self) -> FeatureSet:
        """Return a new FeatureSet with provenance hash computed."""
        provenance = self.compute_provenance_hash()
        return FeatureSet(
            instrument_id=self.instrument_id,
            decision_timestamp=self.decision_timestamp,
            timestamp_utc=self.timestamp_utc,
            entries=self.entries,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            provenance_hash=provenance,
            metadata=self.metadata,
        )

    def __contains__(self, feature_id: str) -> bool:
        return feature_id in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)
