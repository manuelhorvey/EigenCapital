"""Dataset Versioning — reproducible dataset identity.

Every normalized dataset has a unique identity with content hashing
for reproducibility. This is critical for EigenCapital's research
integrity.

Usage:
    metadata = DatasetMetadata(
        dataset_id="equities_daily_v1",
        dataset_version="1.0.0",
        source="provider_x",
        instrument_universe=["SPY", "QQQ"],
        bar_interval="1d",
        start_date="2015-01-01T00:00:00Z",
        end_date="2025-12-31T00:00:00Z",
        record_count=2520,
        validation_stats={"valid": 2500, "warning": 20},
    )
    h = metadata.content_hash
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eigencapital.core.models.canonical_serialization import canonical_hash_hex


@dataclass(frozen=True)
class DatasetMetadata:
    """Immutable dataset metadata for versioning and reproducibility.

    Attributes:
        dataset_id: Unique identifier (e.g., "equities_daily_v1")
        dataset_version: Semantic version
        source: Data provider identifier
        instrument_universe: List of instrument_ids in dataset
        bar_interval: Resolution of bars (e.g., "1d", "5m")
        start_date: First bar timestamp (ISO-8601 UTC)
        end_date: Last bar timestamp (ISO-8601 UTC)
        record_count: Total number of bars
        validation_stats: Counts of VALID/WARNING/INVALID/STALE
        created_at: ISO-8601 UTC creation timestamp
        content_hash: SHA-256 of normalized content (computed)
    """

    dataset_id: str
    dataset_version: str
    source: str
    instrument_universe: List[str]
    bar_interval: str
    start_date: str
    end_date: str
    record_count: int
    validation_stats: Dict[str, int] = field(default_factory=dict)
    created_at: str = ""  # ISO-8601 UTC
    content_hash: str = ""  # Computed on creation

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("dataset_id must be non-empty")
        if not self.dataset_version:
            raise ValueError("dataset_version must be non-empty")
        if not self.source:
            raise ValueError("source must be non-empty")
        if not self.instrument_universe:
            raise ValueError("instrument_universe must be non-empty")
        if not self.bar_interval:
            raise ValueError("bar_interval must be non-empty")
        if self.record_count < 0:
            raise ValueError(f"record_count must be >= 0, got {self.record_count}")

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "source": self.source,
            "instrument_universe": sorted(self.instrument_universe),
            "bar_interval": self.bar_interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "record_count": self.record_count,
            "validation_stats": dict(sorted(self.validation_stats.items())),
            "created_at": self.created_at,
            "content_hash": self.content_hash,
        }

    def compute_content_hash(self) -> str:
        """Compute deterministic content hash from metadata fields."""
        data = self.to_dict()
        # Exclude content_hash itself from the hash
        data.pop("content_hash", None)
        return canonical_hash_hex(data)
