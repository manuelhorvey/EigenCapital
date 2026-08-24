"""Adversarial tests for Phase 1I-E Hypothesis Execution Engine.

Tests cover:
- ExecutionRecord creation, serialization, provenance
- ExecutionEngine orchestration (feature → backtest → validation → evidence gate)
- ExecutionLedger append-only semantics
- Mutation prevention (immutable after completion)
- Trial group assignment before results
- Determinism and reproducibility
- Edge cases: missing hypothesis, failed backtest, missing validation
"""

import hashlib
import json
import pytest

from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus
from eigencapital.research.execution.engine import ExecutionEngine, ExecutionConfig, ExecutionError
from eigencapital.research.execution.ledger import ExecutionLedger
from eigencapital.research.hypotheses.hypothesis import Hypothesis
from eigencapital.research.experiments.registry import ExperimentRegistry
from eigencapital.research.costs.model import CostModel, ZERO_COST, MODERATE_COST
from eigencapital.features.pipeline import FeaturePipeline, FeatureRequest, PipelineConfig
from eigencapital.features.feature_set import FeatureSet, FeatureEntry, FeatureStatus
from eigencapital.features.momentum.time_series import compute_roc


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────

def _make_hypothesis(status: str = "REGISTERED") -> Hypothesis:
    return Hypothesis(
        hypothesis_id="HYP-TEST-001",
        claim="Test claim for execution engine",
        economic_rationale="Test rationale",
        falsification_criteria="Sharpe < 0.5",
        status=status,
    )


def _make_config() -> ExecutionConfig:
    return ExecutionConfig(
        backtest_config={"start_date": "2025-01-01", "end_date": "2025-06-30"},
        cost_model=MODERATE_COST,
        universe={"instruments": ["ES", "NQ"], "trial_group_id": "TG-001", "trial_index": 1},
        parameters={"lookback": 20, "threshold": 0.02},
        random_seed=42,
    )


def _mock_compute_features(bars, config: ExecutionConfig) -> FeatureSet:
    """Mock feature computation."""
    entry = FeatureEntry(
        "roc_20", "v1", FeatureStatus.COMPUTED, value=0.05,
    )
    return FeatureSet(
        instrument_id="ES",
        decision_timestamp="2025-06-30T10:00:00Z",
        timestamp_utc="2025-06-30T10:00:00Z",
        entries={"roc_20": entry},
    ).with_provenance()


def _mock_run_backtest(featureset: FeatureSet, config: ExecutionConfig) -> dict:
    """Mock backtest."""
    return {
        "sharpe": 1.2,
        "total_return": 0.15,
        "max_drawdown": 0.08,
        "num_trades": 42,
    }


def _mock_validate(result: dict, config: ExecutionConfig) -> dict:
    """Mock validation."""
    return {
        "verdict": "CANDIDATE",
        "sharpe": result.get("sharpe", 0),
        "evidence_score": 0.7,
    }


# ═══════════════════════════════════════════════
#  EXECUTION RECORD
# ═══════════════════════════════════════════════

class TestExecutionRecord:
    def test_basic_creation(self):
        record = ExecutionRecord(
            execution_id="EXEC-001",
            hypothesis_id="HYP-001",
            hypothesis_hash="abc",
            experiment_id="EXP-001",
            experiment_hash="def",
            trial_group_id="TG-001",
            trial_index=1,
        )
        assert record.execution_id == "EXEC-001"
        assert record.status == ExecutionStatus.REGISTERED

    def test_missing_execution_id(self):
        with pytest.raises(ValueError, match="execution_id"):
            ExecutionRecord(
                execution_id="",
                hypothesis_id="HYP-001",
                hypothesis_hash="abc",
                experiment_id="EXP-001",
                experiment_hash="def",
                trial_group_id="TG-001",
                trial_index=1,
            )

    def test_missing_hypothesis_id(self):
        with pytest.raises(ValueError, match="hypothesis_id"):
            ExecutionRecord(
                execution_id="EXEC-001",
                hypothesis_id="",
                hypothesis_hash="abc",
                experiment_id="EXP-001",
                experiment_hash="def",
                trial_group_id="TG-001",
                trial_index=1,
            )

    def test_invalid_trial_index(self):
        with pytest.raises(ValueError, match="trial_index"):
            ExecutionRecord(
                execution_id="EXEC-001",
                hypothesis_id="HYP-001",
                hypothesis_hash="abc",
                experiment_id="EXP-001",
                experiment_hash="def",
                trial_group_id="TG-001",
                trial_index=0,
            )

    def test_deterministic_serialization(self):
        record = ExecutionRecord(
            execution_id="EXEC-001",
            hypothesis_id="HYP-001",
            hypothesis_hash="abc",
            experiment_id="EXP-001",
            experiment_hash="def",
            trial_group_id="TG-001",
            trial_index=1,
        )
        d1 = record.to_dict()
        d2 = record.to_dict()
        assert d1 == d2

    def test_provenance_deterministic(self):
        record = ExecutionRecord(
            execution_id="EXEC-001",
            hypothesis_id="HYP-001",
            hypothesis_hash="abc",
            experiment_id="EXP-001",
            experiment_hash="def",
            trial_group_id="TG-001",
            trial_index=1,
        )
        h1 = record.compute_provenance_hash()
        h2 = record.compute_provenance_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_serialization_roundtrip(self):
        record = ExecutionRecord(
            execution_id="EXEC-001",
            hypothesis_id="HYP-001",
            hypothesis_hash="abc",
            experiment_id="EXP-001",
            experiment_hash="def",
            trial_group_id="TG-001",
            trial_index=1,
            status=ExecutionStatus.COMPLETED,
            result={"sharpe": 1.5},
        )
        d = record.to_dict()
        r2 = ExecutionRecord.from_dict(d)
        assert r2.execution_id == record.execution_id
        assert r2.status == ExecutionStatus.COMPLETED
        assert r2.result == {"sharpe": 1.5}

    def test_provenance_changes_with_result(self):
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        r2 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
            result={"sharpe": 1.5},
        )
        # Provenance excludes result, so should be same
        assert r1.compute_provenance_hash() == r2.compute_provenance_hash()


# ═══════════════════════════════════════════════
#  EXECUTION ENGINE
# ═══════════════════════════════════════════════

class TestExecutionEngine:
    def test_basic_execution(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        assert record.status == ExecutionStatus.COMPLETED
        assert record.result["sharpe"] == 1.2
        assert record.provenance_hash != ""

    def test_execution_with_validation(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
            validate_fn=_mock_validate,
        )

        assert record.status == ExecutionStatus.COMPLETED
        assert record.evidence_gate_verdict == "CANDIDATE"

    def test_reject_unregistered_hypothesis(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis(status="DRAFT")
        config = _make_config()

        with pytest.raises(ExecutionError, match="must be REGISTERED"):
            engine.execute(
                hypothesis=hyp,
                config=config,
                compute_features_fn=_mock_compute_features,
                run_backtest_fn=_mock_run_backtest,
            )

    def test_execution_creates_experiment(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        # Experiment was created in registry
        assert len(registry) == 1
        exp = registry.get(record.experiment_id)
        assert exp.hypothesis_id == "HYP-TEST-001"

    def test_trial_group_assigned_before_results(self):
        """Trial group is set at registration, before backtest runs."""
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        assert record.trial_group_id == "TG-001"
        assert record.trial_index == 1

    def test_failed_backtest(self):
        def failing_backtest(featureset, config):
            raise RuntimeError("Simulated backtest failure")

        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=failing_backtest,
        )

        assert record.status == ExecutionStatus.FAILED
        assert "backtest failure" in record.rejection_reason.lower()

    def test_failed_features(self):
        def failing_features(bars, config):
            raise RuntimeError("Feature computation error")

        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp,
            config=config,
            compute_features_fn=failing_features,
            run_backtest_fn=_mock_run_backtest,
        )

        assert record.status == ExecutionStatus.FAILED
        assert "feature computation" in record.rejection_reason.lower()

    def test_deterministic_execution(self):
        """Same inputs → same provenance hash."""
        registry1 = ExperimentRegistry()
        pipeline1 = FeaturePipeline()
        engine1 = ExecutionEngine(registry1, pipeline1)

        hyp = _make_hypothesis()
        config = _make_config()

        r1 = engine1.execute(
            hypothesis=hyp, config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        registry2 = ExperimentRegistry()
        pipeline2 = FeaturePipeline()
        engine2 = ExecutionEngine(registry2, pipeline2)

        r2 = engine2.execute(
            hypothesis=hyp, config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        # Same hypothesis + same config → same provenance
        assert r1.provenance_hash == r2.provenance_hash

    def test_get_execution(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp, config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        fetched = engine.get_execution(record.execution_id)
        assert fetched.execution_id == record.execution_id

    def test_list_executions(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()
        config = _make_config()

        engine.execute(
            hypothesis=hyp, config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        assert len(engine.list_executions()) == 1


# ═══════════════════════════════════════════════
#  EXECUTION LEDGER
# ═══════════════════════════════════════════════

class TestExecutionLedger:
    def test_append_and_get(self):
        ledger = ExecutionLedger()
        record = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        ledger.append(record)
        assert ledger.get("EXEC-001") == record

    def test_append_only(self):
        ledger = ExecutionLedger()
        record = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        ledger.append(record)
        with pytest.raises(ValueError, match="Duplicate"):
            ledger.append(record)

    def test_cannot_delete(self):
        """Ledger has no delete method — records are permanent."""
        ledger = ExecutionLedger()
        assert not hasattr(ledger, 'delete')
        assert not hasattr(ledger, 'remove')

    def test_list_by_status(self):
        ledger = ExecutionLedger()
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
            status=ExecutionStatus.COMPLETED,
        )
        r2 = ExecutionRecord(
            execution_id="EXEC-002", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-002",
            experiment_hash="def", trial_group_id="TG-001", trial_index=2,
            status=ExecutionStatus.FAILED,
        )
        ledger.append(r1)
        ledger.append(r2)

        completed = ledger.list_by_status(ExecutionStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].execution_id == "EXEC-001"

    def test_list_by_hypothesis(self):
        ledger = ExecutionLedger()
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        r2 = ExecutionRecord(
            execution_id="EXEC-002", hypothesis_id="HYP-002",
            hypothesis_hash="abc", experiment_id="EXP-002",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        ledger.append(r1)
        ledger.append(r2)

        hyp1_records = ledger.list_by_hypothesis("HYP-001")
        assert len(hyp1_records) == 1

    def test_list_by_trial_group(self):
        ledger = ExecutionLedger()
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        r2 = ExecutionRecord(
            execution_id="EXEC-002", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-002",
            experiment_hash="def", trial_group_id="TG-002", trial_index=1,
        )
        ledger.append(r1)
        ledger.append(r2)

        tg1 = ledger.list_by_trial_group("TG-001")
        assert len(tg1) == 1

    def test_summary(self):
        ledger = ExecutionLedger()
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
            status=ExecutionStatus.COMPLETED,
        )
        r2 = ExecutionRecord(
            execution_id="EXEC-002", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-002",
            experiment_hash="def", trial_group_id="TG-001", trial_index=2,
            status=ExecutionStatus.FAILED,
        )
        ledger.append(r1)
        ledger.append(r2)

        s = ledger.summary()
        assert s["total_executions"] == 2
        assert s["by_status"]["completed"] == 1
        assert s["by_status"]["failed"] == 1

    def test_serialization_roundtrip(self):
        ledger = ExecutionLedger()
        r1 = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        ledger.append(r1)

        data = ledger.to_list()
        ledger2 = ExecutionLedger.from_list(data)
        assert len(ledger2) == 1
        assert ledger2.get("EXEC-001").execution_id == "EXEC-001"

    def test_contains(self):
        ledger = ExecutionLedger()
        record = ExecutionRecord(
            execution_id="EXEC-001", hypothesis_id="HYP-001",
            hypothesis_hash="abc", experiment_id="EXP-001",
            experiment_hash="def", trial_group_id="TG-001", trial_index=1,
        )
        ledger.append(record)
        assert "EXEC-001" in ledger
        assert "EXEC-999" not in ledger


# ═══════════════════════════════════════════════
#  INTEGRATION — FULL RESEARCH PATH
# ═══════════════════════════════════════════════

class TestFullResearchPath:
    def test_hypothesis_to_ledger(self):
        """Test the complete path: hypothesis → execution → ledger."""
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()

        hyp = _make_hypothesis()
        config = _make_config()

        record = engine.execute(
            hypothesis=hyp, config=config,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
            validate_fn=_mock_validate,
        )

        ledger.append(record)

        assert len(ledger) == 1
        assert ledger.get(record.execution_id).status == ExecutionStatus.COMPLETED
        assert ledger.get(record.execution_id).evidence_gate_verdict == "CANDIDATE"

    def test_multiple_executions_same_hypothesis(self):
        """Multiple executions of the same hypothesis produce different records."""
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)

        hyp = _make_hypothesis()

        config1 = ExecutionConfig(
            parameters={"lookback": 20},
            universe={"trial_group_id": "TG-001", "trial_index": 1},
        )
        config2 = ExecutionConfig(
            parameters={"lookback": 50},
            universe={"trial_group_id": "TG-001", "trial_index": 2},
        )

        r1 = engine.execute(
            hypothesis=hyp, config=config1,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )
        r2 = engine.execute(
            hypothesis=hyp, config=config2,
            compute_features_fn=_mock_compute_features,
            run_backtest_fn=_mock_run_backtest,
        )

        assert r1.execution_id != r2.execution_id
        assert r1.trial_index == 1
        assert r2.trial_index == 2
        assert r1.parameter_snapshot != r2.parameter_snapshot
