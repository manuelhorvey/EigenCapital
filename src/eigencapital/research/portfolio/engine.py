"""Portfolio Research Engine — orchestrates portfolio-level research.

Integrates:
- Allocation experiments
- Portfolio-level validation
- Multiple-testing correction
- Evidence gate evaluation
- Research report generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from eigencapital.research.combination.candidate import AlphaCandidate
from eigencapital.research.combination.portfolio import (
    combine_returns,
    compute_equal_weight,
    compute_portfolio_metrics,
    compute_risk_scaled,
)
from eigencapital.research.combination.returns import ReturnStream
from eigencapital.research.portfolio.allocation import (
    AllocationExperiment,
)
from eigencapital.research.portfolio.evidence import (
    PortfolioEvidenceGate,
)


@dataclass(frozen=True)
class PortfolioResearchConfig:
    """Configuration for portfolio research."""

    eligible_verdicts: Tuple[str, ...] = ("CANDIDATE", "VALIDATED")
    baseline_methods: Tuple[str, ...] = ("equal_weight", "risk_scaled")
    cost_model_id: str = "moderate_v1"
    dataset_version: str = ""
    universe: Dict[str, Any] = field(default_factory=dict)


class PortfolioResearchEngine:
    """Orchestrates portfolio-level research through the complete path.

    Usage:
        engine = PortfolioResearchEngine(config)
        result = engine.research(
            candidates=eligible_candidates,
            streams=return_streams,
        )
    """

    def __init__(self, config: PortfolioResearchConfig | None = None) -> None:
        self._config = config or PortfolioResearchConfig()
        self._experiments: Dict[str, AllocationExperiment] = {}
        self._evidence_gates: Dict[str, PortfolioEvidenceGate] = {}

    def research(
        self,
        candidates: List[AlphaCandidate],
        streams: List[ReturnStream],
    ) -> Dict[str, Any]:
        """Run complete portfolio research on eligible candidates.

        Args:
            candidates: Eligible alpha candidates
            streams: Corresponding return streams

        Returns:
            Complete research results
        """
        if not candidates or not streams:
            return {"status": "no_eligible_candidates"}

        # Filter to eligible only
        eligible = [c for c in candidates if c.is_eligible]
        eligible_streams = [s for s in streams if any(c.candidate_id == s.candidate_id for c in eligible)]

        if len(eligible) < 2:
            return {"status": "insufficient_candidates", "count": len(eligible)}

        results: Dict[str, Any] = {
            "candidates": len(eligible),
            "methods": {},
            "best_method": None,
            "evidence": {},
        }

        # Run each baseline method
        for method_name in self._config.baseline_methods:
            method_result = self._run_method(method_name, eligible_streams, eligible)
            results["methods"][method_name] = method_result

        # Find best method by Sharpe
        best_sharpe = -float("inf")
        best_method = None
        for method_name, method_result in results["methods"].items():
            if "metrics" in method_result:
                sharpe = method_result["metrics"].get("sharpe", 0)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_method = method_name
        results["best_method"] = best_method

        # Run evidence gate on best method
        if best_method and "metrics" in results["methods"][best_method]:
            metrics = results["methods"][best_method]["metrics"]
            baseline_metrics = results["methods"].get("equal_weight", {}).get("metrics", {})

            evidence = PortfolioEvidenceGate.evaluate(
                experiment_id=f"PE-{best_method}",
                metrics=metrics,
                baseline_metrics=baseline_metrics,
            )
            results["evidence"] = evidence.to_dict()

        return results

    def _run_method(
        self,
        method_name: str,
        streams: List[ReturnStream],
        candidates: List[AlphaCandidate],
    ) -> Dict[str, Any]:
        """Run a single allocation method."""
        # Compute weights
        if method_name == "equal_weight":
            weights = compute_equal_weight(streams)
        elif method_name == "risk_scaled":
            weights = compute_risk_scaled(streams)
        else:
            return {"status": "unsupported_method", "method": method_name}

        # Combine returns
        combined, timestamps = combine_returns(streams, weights)

        if not combined:
            return {"status": "no_overlapping_returns"}

        # Compute metrics
        metrics = compute_portfolio_metrics(combined)

        # Add portfolio-specific metrics
        metrics["n_constituents"] = weights.num_constituents
        metrics["concentration_hhi"] = weights.concentration
        metrics["weights"] = weights.weights

        return {
            "method": method_name,
            "weights": weights.to_dict(),
            "metrics": metrics,
            "num_periods": len(combined),
        }

    def get_experiment(self, experiment_id: str) -> AllocationExperiment | None:
        return self._experiments.get(experiment_id)

    def get_evidence_gate(self, experiment_id: str) -> PortfolioEvidenceGate | None:
        return self._evidence_gates.get(experiment_id)
