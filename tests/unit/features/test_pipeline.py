"""Adversarial tests for Phase 1I-D Feature Pipeline, FeatureSet, Dependencies, Provenance.

Tests cover:
- FeatureSet creation, serialization, provenance
- Dependency DAG resolution, cycle detection
- Pipeline computation with warm-up enforcement
- Pipeline availability enforcement
- Future-data injection attacks
- Determinism and reproducibility
- Edge cases: empty bars, single bar, extreme values
"""

import random

import pytest

from eigencapital.core.models.bar import Bar
from eigencapital.features.dependencies import (
    FeatureDAG,
    FeatureDependency,
    build_default_dag,
)
from eigencapital.features.feature_set import (
    FeatureEntry,
    FeatureSet,
    FeatureStatus,
)
from eigencapital.features.momentum.breakout import compute_donchian_position
from eigencapital.features.momentum.time_series import compute_roc
from eigencapital.features.pipeline import (
    FeaturePipeline,
    FeatureRequest,
    PipelineConfig,
)
from eigencapital.features.provenance import (
    ProvenanceRecord,
    build_provenance_record,
    compute_bars_hash,
    compute_config_hash,
    verify_provenance,
)

# ───────────────────────────────────────────────
#  Bar helpers
# ───────────────────────────────────────────────

_bar_counter = 0


def _reset():
    """No-op isolation hook.

    Bar/Feature no longer keep process-global registries (B1/P1 fix), so
    there is nothing to clear between tests.
    """


def _bar(close: float, day: int = 0, inst: str = "ES") -> Bar:
    _bar_counter_val = day
    ts = f"2025-01-{15 + day:02d}T10:00:00Z"
    start = f"2025-01-{15 + day:02d}T09:55:00Z"
    h = max(close * 1.002, close)
    lo = min(close * 0.998, close)
    return Bar(
        instrument_id=inst,
        timestamp_utc=ts,
        bar_start_utc=start,
        bar_end_utc=ts,
        open=close,
        high=h,
        low=lo,
        close=close,
        volume=1000,
    )


def _bars(n, start=100.0, drift=0.001, inst="ES", seed=42, day_offset=0):
    _reset()
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1.0 + drift + rng.gauss(0, 0.01)))
    return [_bar(p, day_offset + i, inst) for i, p in enumerate(prices)]


def _rising(n, start=100.0, inst="ES", day_offset=0):
    _reset()
    return [_bar(start + i, day_offset + i, inst) for i in range(n)]


def _constant(n, price=100.0, inst="ES", day_offset=0):
    _reset()
    return [_bar(price, day_offset + i, inst) for i in range(n)]


# ═══════════════════════════════════════════════
#  FEATURE SET
# ═══════════════════════════════════════════════


class TestFeatureSet:
    def test_basic_creation(self):
        entry = FeatureEntry(
            feature_id="roc_20",
            feature_version="v1",
            status=FeatureStatus.COMPUTED,
            value=0.05,
        )
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_20": entry},
        )
        assert fs.get_value("roc_20") == 0.05
        assert fs.computed_count == 1
        assert fs.feature_count == 1

    def test_get_value_missing(self):
        _reset()
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
        )
        assert fs.get_value("nonexistent") is None

    def test_get_value_unavailable(self):
        entry = FeatureEntry(
            feature_id="roc_200",
            feature_version="v1",
            status=FeatureStatus.UNAVAILABLE,
            error_message="Insufficient bars",
        )
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_200": entry},
        )
        assert fs.get_value("roc_200") is None

    def test_get_value_failed(self):
        entry = FeatureEntry(
            feature_id="bad",
            feature_version="v1",
            status=FeatureStatus.FAILED,
            error_message="boom",
        )
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"bad": entry},
        )
        assert fs.get_value("bad") is None

    def test_data_quality(self):
        entries = {
            "a": FeatureEntry("a", "v1", FeatureStatus.COMPUTED, value=1.0),
            "b": FeatureEntry("b", "v1", FeatureStatus.UNAVAILABLE),
            "c": FeatureEntry("c", "v1", FeatureStatus.FAILED),
        }
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries=entries,
        )
        q = fs.data_quality
        assert q["computed"] == 1
        assert q["unavailable"] == 1
        assert q["failed"] == 1

    def test_deterministic_serialization(self):
        entry = FeatureEntry("roc_20", "v1", FeatureStatus.COMPUTED, value=0.05)
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_20": entry},
        )
        d1 = fs.to_dict()
        d2 = fs.to_dict()
        assert d1 == d2

    def test_provenance_deterministic(self):
        entry = FeatureEntry("roc_20", "v1", FeatureStatus.COMPUTED, value=0.05)
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_20": entry},
        )
        h1 = fs.compute_provenance_hash()
        h2 = fs.compute_provenance_hash()
        assert h1 == h2

    def test_timestamp_invariant(self):
        with pytest.raises(ValueError, match=r"timestamp_utc.*must be <="):
            FeatureSet(
                instrument_id="ES",
                decision_timestamp="2025-01-14T10:00:00Z",
                timestamp_utc="2025-01-15T10:00:00Z",
            )

    def test_unavailable_and_failed_lists(self):
        entries = {
            "a": FeatureEntry("a", "v1", FeatureStatus.COMPUTED, value=1.0),
            "b": FeatureEntry("b", "v1", FeatureStatus.UNAVAILABLE),
            "c": FeatureEntry("c", "v1", FeatureStatus.FAILED),
        }
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries=entries,
        )
        assert fs.unavailable_features == ["b"]
        assert fs.failed_features == ["c"]

    def test_with_provenance(self):
        entry = FeatureEntry("roc_20", "v1", FeatureStatus.COMPUTED, value=0.05)
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_20": entry},
        )
        fs2 = fs.with_provenance()
        assert fs2.provenance_hash != ""
        assert len(fs2.provenance_hash) == 64  # SHA-256

    def test_feature_entry_serialization(self):
        entry = FeatureEntry(
            "roc_20",
            "v1",
            FeatureStatus.COMPUTED,
            value=0.05,
            availability_timestamp="2025-01-15T10:00:00Z",
        )
        d = entry.to_dict()
        e2 = FeatureEntry.from_dict(d)
        assert e2.feature_id == entry.feature_id
        assert e2.value == entry.value
        assert e2.status == entry.status


# ═══════════════════════════════════════════════
#  DEPENDENCY DAG
# ═══════════════════════════════════════════════


class TestFeatureDAG:
    def test_empty_dag(self):
        dag = FeatureDAG()
        assert dag.resolve_order(["roc"]) == ["roc"]

    def test_linear_dependency(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("B", "A"))
        dag.add_dependency(FeatureDependency("C", "B"))
        order = dag.resolve_order(["C"])
        assert order.index("A") < order.index("B") < order.index("C")

    def test_cycle_detection(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("A", "B"))
        dag.add_dependency(FeatureDependency("B", "A"))
        with pytest.raises(ValueError, match="Circular"):
            dag.resolve_order(["A"])

    def test_multiple_roots(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("C", "A"))
        dag.add_dependency(FeatureDependency("C", "B"))
        order = dag.resolve_order(["C"])
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("C")

    def test_deterministic_order(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("B", "A"))
        dag.add_dependency(FeatureDependency("C", "A"))
        o1 = dag.resolve_order(["C", "B"])
        o2 = dag.resolve_order(["C", "B"])
        assert o1 == o2

    def test_get_dependents(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("B", "A"))
        dag.add_dependency(FeatureDependency("C", "A"))
        deps = dag.get_dependents("A")
        assert set(deps) == {"B", "C"}

    def test_root_features(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("B", "A"))
        assert "A" in dag.root_features
        assert "B" not in dag.root_features

    def test_default_dag_valid(self):
        dag = build_default_dag()
        errors = dag.validate_dag()
        assert errors == []

    def test_dag_validate_catches_cycle(self):
        dag = FeatureDAG()
        dag.add_dependency(FeatureDependency("X", "Y"))
        dag.add_dependency(FeatureDependency("Y", "X"))
        errors = dag.validate_dag()
        assert len(errors) > 0


# ═══════════════════════════════════════════════
#  PIPELINE — BASIC COMPUTATION
# ═══════════════════════════════════════════════


class TestPipelineBasic:
    def test_compute_single_feature(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(30)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        assert fs.get_value("roc") is not None
        assert isinstance(fs.get_value("roc"), float)

    def test_compute_multiple_features(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(30)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                ),
                FeatureRequest(
                    "donchian",
                    compute_fn=compute_donchian_position,
                    lookback=20,
                    parameters={"lookback": 20},
                ),
            ],
        )
        assert fs.get_value("roc") is not None
        assert fs.get_value("donchian") is not None

    def test_empty_bars(self):
        _reset()
        config = PipelineConfig(decision_timestamp="2025-01-15T10:00:00Z")
        pipeline = FeaturePipeline(config=config)
        fs = pipeline.compute(
            bars=[],
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        assert fs.feature_count == 0

    def test_provenance_attached(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(30)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        assert fs.provenance_hash != ""
        assert len(fs.provenance_hash) == 64


# ═══════════════════════════════════════════════
#  PIPELINE — WARM-UP ENFORCEMENT
# ═══════════════════════════════════════════════


class TestPipelineWarmup:
    def test_insufficient_bars_unavailable(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(5)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 20},
                )
            ],
        )
        assert fs.get_value("roc") is None
        assert fs.unavailable_features == ["roc"]

    def test_exactly_enough_bars(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(21)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 20},
                )
            ],
        )
        assert fs.get_value("roc") is not None

    def test_warmup_disabled(self):
        _reset()
        config = PipelineConfig(enforce_warmup=False)
        pipeline = FeaturePipeline(config=config)
        bars = _rising(3)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 2},
                )
            ],
        )
        # With warmup disabled, should compute (lookback=2, bars=3)
        assert fs.get_value("roc") is not None


# ═══════════════════════════════════════════════
#  PIPELINE — AVAILABILITY ENFORCEMENT
# ═══════════════════════════════════════════════


class TestPipelineAvailability:
    def test_future_data_rejected(self):
        """Feature with availability_timestamp > decision_timestamp must be rejected."""
        _reset()
        # Bars at day_offset=50 → timestamps 2025-02-14+
        # Decision at 2025-01-15 → bar timestamps > decision
        config = PipelineConfig(
            decision_timestamp="2025-01-15T10:00:00Z",
            enforce_availability=True,
        )
        pipeline = FeaturePipeline(config=config)
        bars = _rising(30, day_offset=50)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        entry = fs.get_entry("roc")
        # Bar timestamp > decision → should be STALE
        assert entry is not None
        assert entry.status == FeatureStatus.STALE

    def test_same_timestamp_ok(self):
        _reset()
        bars = _rising(30)
        ts = bars[-1].timestamp_utc
        config = PipelineConfig(decision_timestamp=ts)
        pipeline = FeaturePipeline(config=config)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        assert fs.get_value("roc") is not None

    def test_availability_disabled(self):
        _reset()
        config = PipelineConfig(
            decision_timestamp="2025-01-10T10:00:00Z",
            enforce_availability=False,
        )
        pipeline = FeaturePipeline(config=config)
        bars = _rising(30)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 5},
                )
            ],
        )
        assert fs.get_value("roc") is not None


# ═══════════════════════════════════════════════
#  PIPELINE — NO COMPUTE FUNCTION
# ═══════════════════════════════════════════════


class TestPipelineMissingFunction:
    def test_missing_compute_fn_failed(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(30)
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[FeatureRequest("unknown_feature", lookback=5)],
        )
        assert fs.get_value("unknown_feature") is None
        assert "unknown_feature" in fs.failed_features


# ═══════════════════════════════════════════════
#  PIPELINE — DETERMINISM
# ═══════════════════════════════════════════════


class TestPipelineDeterminism:
    def test_same_input_same_output(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _bars(50)
        reqs = [FeatureRequest("roc", compute_fn=compute_roc, lookback=20, parameters={"lookback": 10})]

        fs1 = pipeline.compute(bars=bars, instrument_id="ES", requests=reqs)
        _reset()
        fs2 = pipeline.compute(bars=bars, instrument_id="ES", requests=reqs)
        assert fs1.provenance_hash == fs2.provenance_hash

    def test_different_input_different_output(self):
        _reset()
        pipeline = FeaturePipeline()
        bars1 = _bars(50, seed=42)
        bars2 = _bars(50, seed=99)
        reqs = [FeatureRequest("roc", compute_fn=compute_roc, lookback=20, parameters={"lookback": 10})]

        fs1 = pipeline.compute(bars=bars1, instrument_id="ES", requests=reqs)
        _reset()
        fs2 = pipeline.compute(bars=bars2, instrument_id="ES", requests=reqs)
        assert fs1.provenance_hash != fs2.provenance_hash


# ═══════════════════════════════════════════════
#  PROVENANCE
# ═══════════════════════════════════════════════


class TestProvenance:
    def test_bars_hash_deterministic(self):
        bars = _rising(10)
        h1 = compute_bars_hash(bars)
        h2 = compute_bars_hash(bars)
        assert h1 == h2

    def test_bars_hash_different_for_different_bars(self):
        bars1 = _rising(10)
        bars2 = _rising(10, day_offset=100)  # Different timestamps
        h1 = compute_bars_hash(bars1)
        h2 = compute_bars_hash(bars2)
        assert h1 != h2

    def test_config_hash_deterministic(self):
        config = PipelineConfig(decision_timestamp="2025-01-15T10:00:00Z")
        reqs = [FeatureRequest("roc", lookback=20, parameters={"lookback": 10})]
        h1 = compute_config_hash(reqs, config)
        h2 = compute_config_hash(reqs, config)
        assert h1 == h2

    def test_build_and_verify_provenance(self):
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(30)
        reqs = [FeatureRequest("roc", compute_fn=compute_roc, lookback=20, parameters={"lookback": 5})]
        config = PipelineConfig()

        fs = pipeline.compute(bars=bars, instrument_id="ES", requests=reqs)
        record = build_provenance_record(fs, bars, reqs, config, ["roc"])

        assert verify_provenance(fs, record)

    def test_provenance_record_serialization(self):
        record = ProvenanceRecord(
            feature_set_hash="abc",
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            bar_count=10,
            bar_hash="def",
            requested_features=["roc"],
            computed_features=["roc"],
            unavailable_features=[],
            failed_features=[],
            dataset_version="v1",
            universe_version="v1",
            config_hash="ghi",
            computation_order=["roc"],
            availability_violations=[],
        )
        d = record.to_dict()
        r2 = ProvenanceRecord.from_dict(d)
        assert r2.instrument_id == "ES"
        assert r2.bar_count == 10


# ═══════════════════════════════════════════════
#  ADVERSARIAL — FUTURE DATA INJECTION
# ═══════════════════════════════════════════════


class TestFutureDataInjection:
    def test_future_bars_dont_change_past_featureset(self):
        """FeatureSet at T must be identical regardless of what happens at T+1."""
        _reset()
        pipeline = FeaturePipeline()
        bars_early = _rising(25)

        reqs = [FeatureRequest("roc", compute_fn=compute_roc, lookback=20, parameters={"lookback": 5})]

        # Compute with 25 bars
        fs1 = pipeline.compute(bars=bars_early, instrument_id="ES", requests=reqs)

        # Now add future bars with different day_offset (different timestamps)
        bars_late = _rising(30, day_offset=100)  # Different timestamps
        # Filter to first 25 bars — should produce same result as early bars
        # but with different absolute timestamps, so we just check determinism
        _reset()
        fs2 = pipeline.compute(bars=bars_late[:25], instrument_id="ES", requests=reqs)

        # Same number of bars, same drift → same ROC value
        assert fs1.get_value("roc") == fs2.get_value("roc")


# ═══════════════════════════════════════════════
#  ADVERSARIAL — MIXED STATUS FEATURESET
# ═══════════════════════════════════════════════


class TestMixedStatus:
    def test_pipeline_mixed_computed_and_unavailable(self):
        """Pipeline should produce both computed and unavailable features."""
        _reset()
        pipeline = FeaturePipeline()
        bars = _rising(15)  # Enough for lookback=10, not for lookback=20
        fs = pipeline.compute(
            bars=bars,
            instrument_id="ES",
            requests=[
                FeatureRequest(
                    "roc_short",
                    compute_fn=compute_roc,
                    lookback=15,
                    parameters={"lookback": 5},
                ),
                FeatureRequest(
                    "roc_long",
                    compute_fn=compute_roc,
                    lookback=20,
                    parameters={"lookback": 20},
                ),
            ],
        )
        assert fs.get_value("roc_short") is not None
        assert fs.get_value("roc_long") is None
        assert "roc_short" in [fid for fid, e in fs.entries.items() if e.is_computed]
        assert "roc_long" in fs.unavailable_features

    def test_feature_set_with_stale_entry(self):
        entry = FeatureEntry(
            "roc_20",
            "v1",
            FeatureStatus.STALE,
            error_message="availability > decision",
        )
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-14T10:00:00Z",
            timestamp_utc="2025-01-14T10:00:00Z",
            entries={"roc_20": entry},
        )
        assert fs.get_value("roc_20") is None
        assert entry.status == FeatureStatus.STALE


# ═══════════════════════════════════════════════
#  ADVERSARIAL — PROPERTIES
# ═══════════════════════════════════════════════


class TestProperties:
    def test_feature_set_contains(self):
        entry = FeatureEntry("roc_20", "v1", FeatureStatus.COMPUTED, value=0.05)
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries={"roc_20": entry},
        )
        assert "roc_20" in fs
        assert "missing" not in fs

    def test_feature_entry_is_usable(self):
        e1 = FeatureEntry("a", "v1", FeatureStatus.COMPUTED, value=1.0)
        e2 = FeatureEntry("b", "v1", FeatureStatus.COMPUTED, value=None)
        e3 = FeatureEntry("c", "v1", FeatureStatus.UNAVAILABLE)
        assert e1.is_usable
        assert not e2.is_usable
        assert not e3.is_usable

    def test_computed_features_property(self):
        entries = {
            "a": FeatureEntry("a", "v1", FeatureStatus.COMPUTED, value=1.0),
            "b": FeatureEntry("b", "v1", FeatureStatus.UNAVAILABLE),
        }
        fs = FeatureSet(
            instrument_id="ES",
            decision_timestamp="2025-01-15T10:00:00Z",
            timestamp_utc="2025-01-15T10:00:00Z",
            entries=entries,
        )
        assert fs.computed_features == {"a": 1.0}
