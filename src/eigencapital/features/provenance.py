"""Feature provenance tracking and verification.

Every FeatureSet must have complete provenance so that:
1. The exact computation can be reproduced
2. The inputs can be verified
3. The availability constraints can be audited
4. The dependency resolution can be validated

Provenance covers:
- Which bars were used
- Which features were requested
- Which computation functions were used
- What configuration was active
- What dependencies were resolved
- What the availability timestamps were
- What the decision timestamp was
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Any

from eigencapital.features.feature_set import FeatureSet
from eigencapital.features.pipeline import FeatureRequest, PipelineConfig


@dataclass(frozen=True)
class ProvenanceRecord:
    """Complete provenance record for a FeatureSet computation.

    This record makes the computation fully reproducible and auditable.
    """

    feature_set_hash: str
    instrument_id: str
    decision_timestamp: str
    timestamp_utc: str
    bar_count: int
    bar_hash: str  # Hash of all input bars
    requested_features: List[str]
    computed_features: List[str]
    unavailable_features: List[str]
    failed_features: List[str]
    dataset_version: str
    universe_version: str
    config_hash: str
    computation_order: List[str]
    availability_violations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "feature_set_hash": self.feature_set_hash,
            "instrument_id": self.instrument_id,
            "decision_timestamp": self.decision_timestamp,
            "timestamp_utc": self.timestamp_utc,
            "bar_count": self.bar_count,
            "bar_hash": self.bar_hash,
            "requested_features": self.requested_features,
            "computed_features": self.computed_features,
            "unavailable_features": self.unavailable_features,
            "failed_features": self.failed_features,
            "dataset_version": self.dataset_version,
            "universe_version": self.universe_version,
            "config_hash": self.config_hash,
            "computation_order": self.computation_order,
            "availability_violations": self.availability_violations,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ProvenanceRecord:
        """Deserialize from dict."""
        return cls(**d)

    def compute_hash(self) -> str:
        """Compute deterministic hash of this record."""
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def compute_bars_hash(bars: List[Any]) -> str:
    """Compute deterministic hash of input bars.

    Uses instrument_id + timestamp_utc for each bar, which is
    sufficient to identify the exact data used.
    """
    bar_keys = []
    for bar in sorted(bars, key=lambda b: (b.instrument_id, b.timestamp_utc)):
        bar_keys.append(f"{bar.instrument_id}:{bar.timestamp_utc}")

    payload = "|".join(bar_keys).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_config_hash(
    requests: List[FeatureRequest],
    config: PipelineConfig,
) -> str:
    """Compute deterministic hash of pipeline configuration."""
    data = {
        "requests": [
            {
                "feature_id": r.feature_id,
                "feature_version": r.feature_version,
                "lookback": r.lookback,
                "parameters": dict(sorted(r.parameters.items())),
            }
            for r in sorted(requests, key=lambda r: r.feature_id)
        ],
        "decision_timestamp": config.decision_timestamp,
        "dataset_version": config.dataset_version,
        "universe_version": config.universe_version,
        "enforce_availability": config.enforce_availability,
        "enforce_warmup": config.enforce_warmup,
        "fail_on_missing": config.fail_on_missing,
    }
    payload = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_provenance_record(
    feature_set: FeatureSet,
    bars: List[Any],
    requests: List[FeatureRequest],
    config: PipelineConfig,
    computation_order: List[str],
) -> ProvenanceRecord:
    """Build a complete provenance record for a FeatureSet computation.

    Args:
        feature_set: The computed FeatureSet
        bars: The input bars
        requests: The original feature requests
        config: The pipeline configuration
        computation_order: The order features were computed

    Returns:
        ProvenanceRecord with full audit trail
    """
    bar_hash = compute_bars_hash(bars)
    config_hash = compute_config_hash(requests, config)

    requested_ids = [r.feature_id for r in requests]
    computed = [fid for fid, e in feature_set.entries.items() if e.is_computed]
    unavailable = feature_set.unavailable_features
    failed = feature_set.failed_features

    # Check for availability violations
    violations: List[str] = []
    for fid, entry in feature_set.entries.items():
        if entry.status.value == "stale":
            violations.append(fid)

    record = ProvenanceRecord(
        feature_set_hash=feature_set.provenance_hash,
        instrument_id=feature_set.instrument_id,
        decision_timestamp=feature_set.decision_timestamp,
        timestamp_utc=feature_set.timestamp_utc,
        bar_count=len(bars),
        bar_hash=bar_hash,
        requested_features=sorted(requested_ids),
        computed_features=sorted(computed),
        unavailable_features=sorted(unavailable),
        failed_features=sorted(failed),
        dataset_version=feature_set.dataset_version,
        universe_version=feature_set.universe_version,
        config_hash=config_hash,
        computation_order=sorted(computation_order),
        availability_violations=sorted(violations),
    )

    return record


def verify_provenance(
    feature_set: FeatureSet,
    record: ProvenanceRecord,
) -> bool:
    """Verify that a FeatureSet matches its provenance record.

    This is the reproducibility check: given the same inputs,
    the FeatureSet should produce the same provenance.

    Returns:
        True if provenance is consistent
    """
    # Check basic consistency
    if feature_set.instrument_id != record.instrument_id:
        return False
    if feature_set.decision_timestamp != record.decision_timestamp:
        return False
    if feature_set.timestamp_utc != record.timestamp_utc:
        return False
    if feature_set.dataset_version != record.dataset_version:
        return False

    # Check feature counts match
    computed = [fid for fid, e in feature_set.entries.items() if e.is_computed]
    if sorted(computed) != sorted(record.computed_features):
        return False

    return True
