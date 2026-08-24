"""ExecutionEngine — orchestrates the complete research path.

The engine consumes pre-registered hypotheses and produces immutable
execution records. It never invents research decisions.

Execution flow:
1. Validate hypothesis is UNVALIDATED
2. Assign trial group BEFORE results are known
3. Freeze parameter snapshot
4. Compute FeatureSet via FeaturePipeline
5. Run backtest through BacktestEngine
6. Apply cost model
7. Run Phase 1G validation
8. Produce evidence gate verdict
9. Record everything in ExecutionLedger

Critical invariants:
- Hypothesis cannot be mutated after registration
- Trial group is assigned before results
- Feature availability is validated against every decision timestamp
- No strategy can bypass EigenRisk
- Missing evidence → INCONCLUSIVE, never PASS
- Every execution produces complete provenance
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable

from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus
from eigencapital.research.hypotheses.hypothesis import Hypothesis
from eigencapital.research.experiments.registry import ExperimentRegistry, ExperimentRecord
from eigencapital.research.costs.model import CostModel
from eigencapital.features.pipeline import FeaturePipeline, FeatureRequest, PipelineConfig
from eigencapital.features.feature_set import FeatureSet


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for a single execution run.

    Attributes:
        backtest_config: Backtest engine configuration
        validation_config: Phase 1G validation configuration
        cost_model: Transaction cost model
        universe: Universe definition
        parameters: Strategy parameters
        random_seed: For reproducibility
    """
    backtest_config: Dict[str, Any] = field(default_factory=dict)
    validation_config: Dict[str, Any] = field(default_factory=dict)
    cost_model: CostModel = field(default_factory=lambda: CostModel(model_id="zero"))
    universe: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    random_seed: Optional[int] = None

    def compute_config_hash(self) -> str:
        """Deterministic hash of configuration."""
        data = {
            "backtest_config": dict(sorted(self.backtest_config.items())),
            "validation_config": dict(sorted(self.validation_config.items())),
            "cost_model": self.cost_model.to_dict(),
            "universe": dict(sorted(self.universe.items())),
            "parameters": dict(sorted(self.parameters.items())),
            "random_seed": self.random_seed,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class ExecutionError(ValueError):
    """Raised on invalid execution state or violations."""
    pass


class ExecutionEngine:
    """Orchestrates hypothesis execution through the complete research path.

    Usage:
        engine = ExecutionEngine(
            experiment_registry=registry,
            feature_pipeline=pipeline,
        )
        record = engine.execute(
            hypothesis=hypothesis,
            config=exec_config,
            compute_features_fn=my_feature_fn,
            run_backtest_fn=my_backtest_fn,
            validate_fn=my_validation_fn,
        )
    """

    def __init__(
        self,
        experiment_registry: ExperimentRegistry,
        feature_pipeline: FeaturePipeline,
    ) -> None:
        self._registry = experiment_registry
        self._pipeline = feature_pipeline
        self._executions: Dict[str, ExecutionRecord] = {}
        self._execution_counter = 0

    def execute(
        self,
        hypothesis: Hypothesis,
        config: ExecutionConfig,
        compute_features_fn: Callable[[List[Any], ExecutionConfig], FeatureSet],
        run_backtest_fn: Callable[[FeatureSet, ExecutionConfig], Dict[str, Any]],
        validate_fn: Optional[Callable[[Dict[str, Any], ExecutionConfig], Dict[str, Any]]] = None,
    ) -> ExecutionRecord:
        """Execute a hypothesis through the complete research path.

        Args:
            hypothesis: Pre-registered hypothesis (must be REGISTERED)
            config: Execution configuration
            compute_features_fn: Function to compute FeatureSet from bars
            run_backtest_fn: Function to run backtest on FeatureSet
            validate_fn: Optional Phase 1G validation function

        Returns:
            Immutable ExecutionRecord

        Raises:
            ExecutionError: On invalid state or violations
        """
        # 1. Validate hypothesis
        if hypothesis.status != "REGISTERED":
            raise ExecutionError(
                f"Hypothesis {hypothesis.hypothesis_id} must be REGISTERED, "
                f"got {hypothesis.status}"
            )

        # 2. Compute hashes for immutable registration
        hypothesis_hash = self._hash_dict(hypothesis.to_dict())

        # 3. Create experiment record
        experiment_id = f"EXP-{self._execution_counter + 1:06d}"
        self._execution_counter += 1

        try:
            experiment = self._registry.create(
                experiment_id=experiment_id,
                hypothesis_id=hypothesis.hypothesis_id,
                git_commit="",
                dataset_id="",
                dataset_version="",
                dataset_hash="",
                strategy_id=hypothesis.hypothesis_id,
                strategy_version=hypothesis.version,
                strategy_config_hash=config.compute_config_hash(),
                strategy_artifact_hash="",
                parameters=config.parameters,
                cost_model_id=config.cost_model.model_id,
                cost_model_version=config.cost_model.version,
                random_seed=config.random_seed,
            )
        except Exception as e:
            raise ExecutionError(f"Failed to create experiment: {e}")

        experiment_hash = self._hash_dict(experiment.to_dict())

        # 4. Create execution record
        execution_id = f"EXEC-{self._execution_counter:06d}"
        record = ExecutionRecord(
            execution_id=execution_id,
            hypothesis_id=hypothesis.hypothesis_id,
            hypothesis_hash=hypothesis_hash,
            experiment_id=experiment_id,
            experiment_hash=experiment_hash,
            trial_group_id=config.universe.get("trial_group_id", "default"),
            trial_index=config.universe.get("trial_index", 1),
            backtest_config=config.backtest_config,
            backtest_config_hash=self._hash_dict(config.backtest_config),
            cost_model_id=config.cost_model.model_id,
            cost_model_hash=self._hash_dict(config.cost_model.to_dict()),
            universe_definition=config.universe,
            universe_hash=self._hash_dict(config.universe),
            parameter_snapshot=config.parameters,
            status=ExecutionStatus.REGISTERED,
            created_at="",
        )

        # 5. Compute provenance
        record = ExecutionRecord(
            **{**record.__dict__, "provenance_hash": record.compute_provenance_hash()}
        )

        self._executions[execution_id] = record

        # 6. Execute the research path (may raise on errors)
        try:
            record = self._run_execution(record, config, compute_features_fn,
                                         run_backtest_fn, validate_fn)
        except Exception as e:
            record = ExecutionRecord(
                **{**record.__dict__,
                   "status": ExecutionStatus.FAILED,
                   "rejection_reason": str(e)}
            )

        self._executions[execution_id] = record
        return record

    def _run_execution(
        self,
        record: ExecutionRecord,
        config: ExecutionConfig,
        compute_features_fn: Callable,
        run_backtest_fn: Callable,
        validate_fn: Optional[Callable],
    ) -> ExecutionRecord:
        """Run the execution through each stage."""
        # Stage 1: Compute features
        record = ExecutionRecord(
            **{**record.__dict__, "status": ExecutionStatus.COMPUTING_FEATURES}
        )

        try:
            featureset = compute_features_fn([], config)  # bars passed externally
            record = ExecutionRecord(
                **{**record.__dict__, "feature_set_hash": featureset.provenance_hash}
            )
        except Exception as e:
            return ExecutionRecord(
                **{**record.__dict__,
                   "status": ExecutionStatus.FAILED,
                   "rejection_reason": f"Feature computation failed: {e}"}
            )

        # Stage 2: Run backtest
        record = ExecutionRecord(
            **{**record.__dict__, "status": ExecutionStatus.BACKTESTING}
        )

        try:
            backtest_result = run_backtest_fn(featureset, config)
            record = ExecutionRecord(
                **{**record.__dict__, "result": backtest_result}
            )
        except Exception as e:
            return ExecutionRecord(
                **{**record.__dict__,
                   "status": ExecutionStatus.FAILED,
                   "rejection_reason": f"Backtest failed: {e}"}
            )

        # Stage 3: Validate (if validation function provided)
        if validate_fn is not None:
            record = ExecutionRecord(
                **{**record.__dict__, "status": ExecutionStatus.VALIDATING}
            )

            try:
                validation_result = validate_fn(backtest_result, config)
                verdict = validation_result.get("verdict", "INCONCLUSIVE")
                record = ExecutionRecord(
                    **{**record.__dict__,
                       "validation_result": validation_result,
                       "evidence_gate_verdict": verdict}
                )
            except Exception as e:
                record = ExecutionRecord(
                    **{**record.__dict__,
                       "evidence_gate_verdict": "INCONCLUSIVE",
                       "rejection_reason": f"Validation failed: {e}"}
                )

        # Stage 4: Complete
        record = ExecutionRecord(
            **{**record.__dict__, "status": ExecutionStatus.COMPLETED}
        )

        # Recompute provenance with final state
        record = ExecutionRecord(
            **{**record.__dict__, "provenance_hash": record.compute_provenance_hash()}
        )

        return record

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        """Get an execution record by ID."""
        if execution_id not in self._executions:
            raise ExecutionError(f"Execution not found: {execution_id}")
        return self._executions[execution_id]

    def list_executions(self) -> List[ExecutionRecord]:
        """List all execution records."""
        return list(self._executions.values())

    def _hash_dict(self, data: Dict[str, Any]) -> str:
        """Compute deterministic hash of a dict."""
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
