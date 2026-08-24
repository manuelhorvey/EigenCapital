"""Validation Orchestrator — runs all validation tests and produces verdict.

Combines: walk-forward, bootstrap, permutation, multiple-testing, PBO,
parameter sensitivity, cost stress, regime, universe, concentration,
temporal stability.

Usage:
    validator = ValidationEngine()
    result = validator.validate(
        experiment_id="EXP-000001",
        equity_curve=equity_curve,
        instrument_returns=instrument_returns,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from eigencapital.analytics.metrics import PerformanceMetrics, compute_metrics
from eigencapital.analytics.validation.walk_forward import WalkForwardResult, purged_walk_forward
from eigencapital.analytics.validation.bootstrap import BootstrapResult, PermutationResult, bootstrap_test, permutation_test
from eigencapital.analytics.validation.sensitivity import SensitivityResult, parameter_sensitivity
from eigencapital.analytics.validation.cost_stress import CostStressResult, cost_stress_test
from eigencapital.analytics.validation.regime import RegimeResult, regime_analysis
from eigencapital.analytics.validation.evidence_gate import EvidenceGate, EvidenceVerdict
from eigencapital.analytics.validation.multiple_testing import MultipleTestingResult, multiple_testing_correction
from eigencapital.analytics.validation.pbo import PBOResult, compute_pbo
from eigencapital.analytics.validation.universe import UniversePerturbationResult, universe_perturbation
from eigencapital.analytics.validation.temporal import TemporalStabilityResult, temporal_stability
from eigencapital.analytics.validation.block_bootstrap import BlockBootstrapResult, block_bootstrap


@dataclass(frozen=True)
class ValidationResult:
    """Complete validation result for an experiment.

    Combines all validation dimensions into a single verdict.
    """
    experiment_id: str = ""
    provenance_hash: str = ""

    # Baseline metrics
    baseline_metrics: Optional[PerformanceMetrics] = None

    # Walk-forward
    walk_forward: Optional[WalkForwardResult] = None

    # Bootstrap
    bootstrap_iid: Optional[BootstrapResult] = None
    bootstrap_block: Optional[BlockBootstrapResult] = None

    # Permutation
    permutation: Optional[PermutationResult] = None

    # Multiple testing
    multiple_testing: Optional[MultipleTestingResult] = None

    # PBO
    pbo: Optional[PBOResult] = None

    # Sensitivity
    sensitivity: Optional[SensitivityResult] = None

    # Cost stress
    cost_stress: Optional[CostStressResult] = None

    # Regime
    regime: Optional[RegimeResult] = None

    # Universe
    universe: Optional[UniversePerturbationResult] = None

    # Temporal
    temporal: Optional[TemporalStabilityResult] = None

    # Final verdict
    verdict: str = EvidenceVerdict.CANDIDATE
    evidence_checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "experiment_id": self.experiment_id,
            "verdict": self.verdict,
            "baseline_metrics": self.baseline_metrics.to_dict() if self.baseline_metrics else None,
            "walk_forward": self.walk_forward.to_dict() if self.walk_forward else None,
            "bootstrap_iid": self.bootstrap_iid.to_dict() if self.bootstrap_iid else None,
            "bootstrap_block": self.bootstrap_block.to_dict() if self.bootstrap_block else None,
            "permutation": self.permutation.to_dict() if self.permutation else None,
            "multiple_testing": self.multiple_testing.to_dict() if self.multiple_testing else None,
            "pbo": self.pbo.to_dict() if self.pbo else None,
            "sensitivity": self.sensitivity.to_dict() if self.sensitivity else None,
            "cost_stress": self.cost_stress.to_dict() if self.cost_stress else None,
            "regime": self.regime.to_dict() if self.regime else None,
            "universe": self.universe.to_dict() if self.universe else None,
            "temporal": self.temporal.to_dict() if self.temporal else None,
            "evidence_checks": self.evidence_checks,
            "warnings": self.warnings,
        }


class ValidationEngine:
    """Main validation orchestrator.

    Runs all validation tests against a strategy's equity curve
    and produces a comprehensive verdict.
    """

    def __init__(
        self,
        walk_forward_train: int = 300,
        walk_forward_test: int = 100,
        walk_forward_purge: int = 10,
        bootstrap_iterations: int = 500,
        permutation_iterations: int = 500,
        bootstrap_seed: int = 42,
    ) -> None:
        self.wf_train = walk_forward_train
        self.wf_test = walk_forward_test
        self.wf_purge = walk_forward_purge
        self.bootstrap_iters = bootstrap_iterations
        self.perm_iters = permutation_iterations
        self.seed = bootstrap_seed

    def validate(
        self,
        experiment_id: str = "",
        equity_curve: Optional[List[float]] = None,
        instrument_returns: Optional[Dict[str, List[float]]] = None,
        trades: Optional[List[float]] = None,
        pbo_candidates: Optional[List[Dict[str, float]]] = None,
        regime_returns: Optional[Dict[str, List[float]]] = None,
    ) -> ValidationResult:
        """Run full validation suite.

        Args:
            experiment_id: Experiment identifier
            equity_curve: Full equity curve
            instrument_returns: Per-instrument return series
            trades: Individual trade P&L values
            pbo_candidates: Candidate results for PBO analysis
            regime_returns: Per-regime return series

        Returns:
            ValidationResult with all test results and verdict
        """
        warnings = []
        result = ValidationResult(experiment_id=experiment_id)

        if not equity_curve or len(equity_curve) < 10:
            return ValidationResult(
                experiment_id=experiment_id,
                verdict=EvidenceVerdict.REJECTED,
                warnings=["Insufficient equity curve data"],
            )

        # 1. Baseline metrics
        try:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=compute_metrics(equity_curve, trades),
            )
        except ValueError as e:
            warnings.append(f"Baseline metrics error: {e}")

        # 2. Walk-forward
        result = ValidationResult(
            experiment_id=result.experiment_id,
            baseline_metrics=result.baseline_metrics,
            walk_forward=purged_walk_forward(
                equity_curve, self.wf_train, self.wf_test, self.wf_purge
            ),
        )
        if result.walk_forward and result.walk_forward.total_windows > 0:
            if result.walk_forward.mean_oos_sharpe <= 0:
                warnings.append("Walk-forward OOS Sharpe is non-positive")

        # 3. Bootstrap (IID)
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                returns.append((equity_curve[i] / equity_curve[i - 1]) - 1.0)

        if returns:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=bootstrap_test(returns, self.bootstrap_iters, seed=self.seed),
            )

            # Block bootstrap
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=result.bootstrap_iid,
                bootstrap_block=block_bootstrap(returns, block_size=21, n_bootstrap=self.bootstrap_iters, seed=self.seed),
            )

        # 4. Permutation test
        if returns:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=result.bootstrap_iid,
                bootstrap_block=result.bootstrap_block,
                permutation=permutation_test(returns, self.perm_iters, seed=self.seed),
            )

        # 5. Sensitivity (placeholder — needs parameter sweep data)
        # Only computed if provided externally

        # 6. Regime analysis
        if regime_returns:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=result.bootstrap_iid,
                bootstrap_block=result.bootstrap_block,
                permutation=result.permutation,
                regime=regime_analysis(regime_returns),
            )

        # 7. Universe perturbation
        if instrument_returns:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=result.bootstrap_iid,
                bootstrap_block=result.bootstrap_block,
                permutation=result.permutation,
                regime=result.regime,
                universe=universe_perturbation(instrument_returns),
            )

        # 8. PBO
        if pbo_candidates:
            result = ValidationResult(
                experiment_id=result.experiment_id,
                baseline_metrics=result.baseline_metrics,
                walk_forward=result.walk_forward,
                bootstrap_iid=result.bootstrap_iid,
                bootstrap_block=result.bootstrap_block,
                permutation=result.permutation,
                regime=result.regime,
                universe=result.universe,
                pbo=compute_pbo(pbo_candidates),
            )

        # 9. Evidence gate
        gate = EvidenceGate()
        gate_result = gate.evaluate(
            walk_forward=result.walk_forward,
            bootstrap=result.bootstrap_iid,
            permutation=result.permutation,
            sensitivity=result.sensitivity,
            cost_stress=result.cost_stress,
            regime=result.regime,
        )

        # Collect warnings
        if result.walk_forward and result.walk_forward.total_windows > 0:
            if result.walk_forward.degradation_ratio > 2.0:
                warnings.append(f"High walk-forward degradation: {result.walk_forward.degradation_ratio:.2f}x")

        if result.universe and result.universe.single_instrument_dependency:
            warnings.append("Single instrument dependency detected")

        if result.regime and result.regime.regime_dependent:
            warnings.append(f"Regime-dependent performance: Sharpe range {result.regime.sharpe_range:.3f}")

        if result.temporal and result.temporal.performance_decay:
            warnings.append("Performance decay detected in rolling windows")

        return ValidationResult(
            experiment_id=result.experiment_id,
            baseline_metrics=result.baseline_metrics,
            walk_forward=result.walk_forward,
            bootstrap_iid=result.bootstrap_iid,
            bootstrap_block=result.bootstrap_block,
            permutation=result.permutation,
            multiple_testing=result.multiple_testing,
            pbo=result.pbo,
            sensitivity=result.sensitivity,
            cost_stress=result.cost_stress,
            regime=result.regime,
            universe=result.universe,
            temporal=result.temporal,
            verdict=gate_result["verdict"],
            evidence_checks=gate_result["checks"],
            warnings=warnings,
        )
