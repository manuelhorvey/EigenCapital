"""CampaignRunner — executes a controlled set of hypotheses.

The runner consumes pre-registered hypotheses and executes each through
the complete research path. It produces:
1. Individual execution records
2. Campaign-level comparison
3. Reproducibility verification
4. Human-readable campaign report

Critical invariant: The runner never modifies hypotheses or results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from eigencapital.research.execution.engine import ExecutionConfig, ExecutionEngine
from eigencapital.research.execution.ledger import ExecutionLedger
from eigencapital.research.execution.record import ExecutionRecord
from eigencapital.research.hypotheses.hypothesis import Hypothesis


@dataclass(frozen=True)
class CampaignManifest:
    """Frozen manifest of a research campaign.

    Attributes:
        campaign_id: Unique identifier
        hypotheses: List of hypothesis IDs to execute
        description: Campaign description
        cost_model_id: Cost model to use
        universe: Universe definition
    """

    campaign_id: str
    hypotheses: List[str]
    description: str = ""
    cost_model_id: str = "moderate_v1"
    universe: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "hypotheses": self.hypotheses,
            "description": self.description,
            "cost_model_id": self.cost_model_id,
            "universe": dict(sorted(self.universe.items())),
        }


@dataclass(frozen=True)
class CampaignResult:
    """Result of a complete campaign execution."""

    campaign_id: str
    executions: List[ExecutionRecord] = field(default_factory=list)
    comparison: Dict[str, Any] = field(default_factory=dict)
    reproducibility: Dict[str, Any] = field(default_factory=dict)
    verdicts: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "executions": [e.to_dict() for e in self.executions],
            "comparison": self.comparison,
            "reproducibility": self.reproducibility,
            "verdicts": self.verdicts,
        }


class CampaignRunner:
    """Executes a controlled alpha research campaign.

    Usage:
        runner = CampaignRunner(
            engine=execution_engine,
            ledger=execution_ledger,
        )
        result = runner.run(
            manifest=campaign_manifest,
            hypotheses={"HYP-TREND-001": hypothesis_obj, ...},
            compute_features_fn=my_features,
            run_backtest_fn=my_backtest,
            validate_fn=my_validation,
        )
    """

    def __init__(
        self,
        engine: ExecutionEngine,
        ledger: ExecutionLedger,
    ) -> None:
        self._engine = engine
        self._ledger = ledger

    def run(
        self,
        manifest: CampaignManifest,
        hypotheses: Dict[str, Hypothesis],
        compute_features_fn: Callable,
        run_backtest_fn: Callable,
        validate_fn: Callable | None = None,
        cost_model: Any = None,
    ) -> CampaignResult:
        """Execute a complete campaign.

        Args:
            manifest: Campaign manifest (frozen)
            hypotheses: Dict mapping hypothesis_id → Hypothesis object
            compute_features_fn: Feature computation function
            run_backtest_fn: Backtest function
            validate_fn: Optional validation function
            cost_model: Cost model to use

        Returns:
            CampaignResult with all executions and comparison
        """
        executions: List[ExecutionRecord] = []
        verdicts: Dict[str, str] = {}

        for hyp_id in manifest.hypotheses:
            if hyp_id not in hypotheses:
                continue

            hypothesis = hypotheses[hyp_id]

            # Create execution config
            config = ExecutionConfig(
                universe={
                    "trial_group_id": f"{hyp_id}/campaign",
                    "trial_index": 1,
                    **manifest.universe,
                },
                parameters=hypothesis.to_dict(),
                cost_model=cost_model,
            )

            # Execute
            record = self._engine.execute(
                hypothesis=hypothesis,
                config=config,
                compute_features_fn=compute_features_fn,
                run_backtest_fn=run_backtest_fn,
                validate_fn=validate_fn,
            )

            executions.append(record)
            verdicts[hyp_id] = record.evidence_gate_verdict or record.status.value

            # Add to ledger
            self._ledger.append(record)

        # Build comparison
        comparison = self._build_comparison(executions)

        # Reproducibility test (re-run first hypothesis)
        reproducibility = self._test_reproducibility(
            manifest,
            hypotheses,
            executions,
            compute_features_fn,
            run_backtest_fn,
            validate_fn,
            cost_model,
        )

        return CampaignResult(
            campaign_id=manifest.campaign_id,
            executions=executions,
            comparison=comparison,
            reproducibility=reproducibility,
            verdicts=verdicts,
        )

    def _build_comparison(self, executions: List[ExecutionRecord]) -> Dict[str, Any]:
        """Build campaign-level comparison."""
        if not executions:
            return {}

        comparison = {
            "total_executions": len(executions),
            "by_verdict": {},
            "results": [],
        }

        for record in executions:
            verdict = record.evidence_gate_verdict or record.status.value
            comparison["by_verdict"][verdict] = comparison["by_verdict"].get(verdict, 0) + 1
            comparison["results"].append(
                {
                    "execution_id": record.execution_id,
                    "hypothesis_id": record.hypothesis_id,
                    "verdict": verdict,
                    "result": record.result,
                }
            )

        return comparison

    def _test_reproducibility(
        self,
        manifest: CampaignManifest,
        hypotheses: Dict[str, Hypothesis],
        original_executions: List[ExecutionRecord],
        compute_features_fn: Callable,
        run_backtest_fn: Callable,
        validate_fn: Callable | None,
        cost_model: Any,
    ) -> Dict[str, Any]:
        """Test reproducibility by re-executing the first hypothesis."""
        if not manifest.hypotheses or not original_executions:
            return {"status": "skipped", "reason": "no executions"}

        hyp_id = manifest.hypotheses[0]
        if hyp_id not in hypotheses:
            return {"status": "skipped", "reason": "hypothesis not found"}

        hypothesis = hypotheses[hyp_id]
        original = original_executions[0]

        config = ExecutionConfig(
            universe={
                "trial_group_id": f"{hyp_id}/reproducibility",
                "trial_index": 1,
                **manifest.universe,
            },
            parameters=hypothesis.to_dict(),
            cost_model=cost_model,
        )

        # Re-execute
        repro_record = self._engine.execute(
            hypothesis=hypothesis,
            config=config,
            compute_features_fn=compute_features_fn,
            run_backtest_fn=run_backtest_fn,
            validate_fn=validate_fn,
        )

        # Compare results (not provenance — experiment IDs differ)
        result_match = original.result == repro_record.result
        verdict_match = original.evidence_gate_verdict == repro_record.evidence_gate_verdict
        match = result_match and verdict_match

        return {
            "status": "passed" if match else "failed",
            "original_execution_id": original.execution_id,
            "reproduction_execution_id": repro_record.execution_id,
            "result_match": result_match,
            "verdict_match": verdict_match,
        }
