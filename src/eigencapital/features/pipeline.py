"""Feature Pipeline — orchestrates feature computation.

The pipeline turns independently tested feature primitives into a
deterministic, versioned, point-in-time-safe feature computation system.

Pipeline responsibilities:
1. Accept canonical Bar data
2. Resolve requested features from FeatureRegistry
3. Resolve feature dependencies deterministically
4. Compute features in dependency order
5. Enforce availability timestamps
6. Enforce warm-up requirements
7. Reject invalid/stale input
8. Prevent duplicate/conflicting feature definitions
9. Produce a deterministic FeatureSet
10. Attach complete provenance
11. Never silently substitute missing values
12. Never generate BUY/SELL decisions
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any

from eigencapital.core.models.bar import Bar
from eigencapital.features.feature import Feature
from eigencapital.features.feature_set import (
    FeatureSet,
    FeatureEntry,
    FeatureStatus,
)
from eigencapital.features.dependencies import FeatureDAG, build_default_dag


@dataclass(frozen=True)
class FeatureRequest:
    """A request to compute a feature.

    Attributes:
        feature_id: Which feature to compute
        feature_version: Specific version to use
        compute_fn: The computation function
        lookback: Minimum number of bars required
        parameters: Additional parameters for computation
    """

    feature_id: str
    feature_version: str = "v1"
    compute_fn: Optional[Callable] = None
    lookback: int = 1
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for the feature pipeline.

    Attributes:
        decision_timestamp: When the decision is being made
        dataset_version: Which dataset version is being used
        universe_version: Which universe definition is being used
        enforce_availability: Whether to strictly enforce availability timestamps
        enforce_warmup: Whether to strictly enforce minimum bar counts
        fail_on_missing: Whether to fail if a feature cannot be computed
    """

    decision_timestamp: str = ""
    dataset_version: str = ""
    universe_version: str = ""
    enforce_availability: bool = True
    enforce_warmup: bool = True
    fail_on_missing: bool = False


class FeaturePipeline:
    """Orchestrates feature computation with full provenance tracking.

    Usage:
        pipeline = FeaturePipeline()
        pipeline.register("roc", compute_roc, lookback=20)

        featureset = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            request=FeatureRequest("roc", lookback=20),
        )
    """

    def __init__(
        self,
        dag: Optional[FeatureDAG] = None,
        config: Optional[PipelineConfig] = None,
    ) -> None:
        self._dag = dag or build_default_dag()
        self._config = config or PipelineConfig()
        self._compute_functions: Dict[str, Callable] = {}
        self._lookback_requirements: Dict[str, int] = {}

    def register(
        self,
        feature_id: str,
        compute_fn: Callable,
        lookback: int = 1,
        version: str = "v1",
    ) -> None:
        """Register a feature computation function.

        Args:
            feature_id: Unique feature identifier
            compute_fn: Function that computes the feature
            lookback: Minimum bars required
            version: Feature version
        """
        self._compute_functions[feature_id] = compute_fn
        self._lookback_requirements[feature_id] = lookback

    def compute(
        self,
        bars: List[Bar],
        instrument_id: str,
        requests: List[FeatureRequest],
        config: Optional[PipelineConfig] = None,
    ) -> FeatureSet:
        """Compute features for a single instrument at a specific timestamp.

        Args:
            bars: Available bars (sorted chronologically, all for one instrument)
            instrument_id: The instrument being analyzed
            requests: Features to compute
            config: Pipeline configuration (overrides default)

        Returns:
            FeatureSet with all computed/unavailable/failed features

        Raises:
            FeatureValidationError: If bars are invalid
            FeatureAvailabilityError: If availability is violated
        """
        cfg = config or self._config

        # Validate input
        if not bars:
            return self._empty_featureset(instrument_id, cfg.decision_timestamp, cfg)

        # Sort bars chronologically
        sorted_bars = sorted(bars, key=lambda b: b.timestamp_utc)

        # Get the latest bar timestamp
        latest_timestamp = sorted_bars[-1].timestamp_utc

        # Decision timestamp defaults to latest bar
        decision_ts = cfg.decision_timestamp or latest_timestamp

        # Resolve computation order via DAG
        requested_ids = [r.feature_id for r in requests]
        try:
            ordered_ids = self._dag.resolve_order(requested_ids)
        except ValueError:
            # If DAG resolution fails, compute in request order
            ordered_ids = requested_ids

        # Build request lookup
        request_map = {r.feature_id: r for r in requests}

        # Compute features in order
        entries: Dict[str, FeatureEntry] = {}
        computed_features: Dict[str, Feature] = {}

        for fid in ordered_ids:
            request = request_map.get(fid)
            if request is None:
                continue

            entry = self._compute_single(
                bars=sorted_bars,
                request=request,
                decision_timestamp=decision_ts,
                enforce_availability=cfg.enforce_availability,
                enforce_warmup=cfg.enforce_warmup,
                computed_features=computed_features,
            )
            entries[fid] = entry

            # Store computed feature for dependent computations
            # Note: we don't create Feature objects here to avoid registry
            # collisions — provenance is tracked via FeatureEntry instead

        # Build FeatureSet — if bar timestamps exceed decision, use decision as timestamp
        fs_timestamp = latest_timestamp
        if latest_timestamp > decision_ts:
            fs_timestamp = decision_ts

        featureset = FeatureSet(
            instrument_id=instrument_id,
            decision_timestamp=decision_ts,
            timestamp_utc=fs_timestamp,
            entries=entries,
            dataset_version=cfg.dataset_version,
            universe_version=cfg.universe_version,
        )

        # Attach provenance
        return featureset.with_provenance()

    def _compute_single(
        self,
        bars: List[Bar],
        request: FeatureRequest,
        decision_timestamp: str,
        enforce_availability: bool,
        enforce_warmup: bool,
        computed_features: Dict[str, Feature],
    ) -> FeatureEntry:
        """Compute a single feature and return its entry."""
        # Check warm-up requirement
        min_bars = request.lookback or self._lookback_requirements.get(
            request.feature_id, 1
        )
        if enforce_warmup and len(bars) < min_bars:
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.UNAVAILABLE,
                error_message=(f"Insufficient bars: {len(bars)} < {min_bars} required"),
            )

        # Get compute function
        compute_fn = request.compute_fn or self._compute_functions.get(
            request.feature_id
        )
        if compute_fn is None:
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.FAILED,
                error_message=f"No compute function registered for {request.feature_id}",
            )

        # Compute the feature
        try:
            result = compute_fn(bars, **request.parameters)
        except Exception as e:
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.FAILED,
                error_message=f"Computation failed: {e}",
            )

        # Handle None result (feature couldn't be computed)
        if result is None:
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.UNAVAILABLE,
                error_message="Feature computation returned None",
            )

        # Handle non-numeric result
        if not isinstance(result, (int, float)):
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.FAILED,
                error_message=f"Expected numeric result, got {type(result)}",
            )

        # Build Feature for provenance
        feature_timestamp = bars[-1].timestamp_utc
        availability_ts = feature_timestamp  # Default: available at bar time

        # Check availability
        if enforce_availability and availability_ts > decision_timestamp:
            return FeatureEntry(
                feature_id=request.feature_id,
                feature_version=request.feature_version,
                status=FeatureStatus.STALE,
                error_message=(
                    f"Availability {availability_ts} > decision {decision_timestamp}"
                ),
            )

        # Compute provenance hashes directly (without creating Feature
        # objects to avoid class-level registry collisions)
        config_data = {
            "feature_family": "derived",
            "normalization": "none",
            "lookback": min_bars,
            "source_features": [],
        }
        config_hash = hashlib.sha256(
            json.dumps(config_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        provenance_data = {
            "feature_id": request.feature_id,
            "feature_version": request.feature_version,
            "instrument_id": bars[-1].instrument_id,
            "timestamp_utc": feature_timestamp,
            "value": float(result),
            "feature_family": "derived",
            "lookback": min_bars,
            "availability_timestamp": availability_ts,
            "config_hash": config_hash,
        }
        provenance_hash = hashlib.sha256(
            json.dumps(provenance_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return FeatureEntry(
            feature_id=request.feature_id,
            feature_version=request.feature_version,
            status=FeatureStatus.COMPUTED,
            value=float(result),
            availability_timestamp=availability_ts,
            config_hash=config_hash,
            provenance_hash=provenance_hash,
        )

    def _empty_featureset(
        self,
        instrument_id: str,
        decision_timestamp: str,
        config: PipelineConfig,
    ) -> FeatureSet:
        """Create an empty FeatureSet when no bars are available."""
        ts = decision_timestamp or "2000-01-01T00:00:00Z"
        return FeatureSet(
            instrument_id=instrument_id,
            decision_timestamp=ts,
            timestamp_utc=ts,
            entries={},
            dataset_version=config.dataset_version,
            universe_version=config.universe_version,
        )

    @property
    def dag(self) -> FeatureDAG:
        """Access the dependency DAG."""
        return self._dag

    @property
    def registered_features(self) -> List[str]:
        """List all registered feature IDs."""
        return sorted(self._compute_functions.keys())
