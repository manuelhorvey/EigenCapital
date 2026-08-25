"""Validation Orchestrator — runs all validation tests and produces verdict.

Integrates: walk-forward, bootstrap, block-bootstrap, permutation,
multiple-testing, PBO, sensitivity, cost stress, regime, universe,
concentration, temporal stability.

Usage:
    engine = ValidationEngine()
    result = engine.validate(
        experiment_id="EXP-000001",
        equity_curve=equity_curve,
        instrument_returns=instrument_returns,
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from eigencapital.analytics.metrics import PerformanceMetrics, compute_metrics
from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult,
    purged_walk_forward,
)
from eigencapital.analytics.validation.bootstrap import (
    BootstrapResult,
    PermutationResult,
    bootstrap_test,
    permutation_test,
)
from eigencapital.analytics.validation.block_bootstrap import (
    BlockBootstrapResult,
    block_bootstrap,
)
from eigencapital.analytics.validation.sensitivity import (
    SensitivityResult,
    parameter_sensitivity,
)
from eigencapital.analytics.validation.cost_stress import (
    CostStressResult,
    cost_stress_test,
)
from eigencapital.analytics.validation.regime import RegimeResult, regime_analysis
from eigencapital.analytics.validation.evidence_gate import (
    EvidenceGate,
    EvidenceVerdict,
)
from eigencapital.analytics.validation.multiple_testing import MultipleTestingResult
from eigencapital.analytics.validation.pbo import PBOResult, compute_pbo
from eigencapital.analytics.validation.universe import (
    UniversePerturbationResult,
    universe_perturbation,
)
from eigencapital.analytics.validation.temporal import (
    TemporalStabilityResult,
    temporal_stability,
)


@dataclass(frozen=True)
class ValidationResult:
    """Complete validation result for an experiment."""

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
    missing_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "experiment_id": self.experiment_id,
            "verdict": self.verdict,
            "baseline_metrics": self.baseline_metrics.to_dict()
            if self.baseline_metrics
            else None,
            "walk_forward": self.walk_forward.to_dict() if self.walk_forward else None,
            "bootstrap_iid": self.bootstrap_iid.to_dict()
            if self.bootstrap_iid
            else None,
            "bootstrap_block": self.bootstrap_block.to_dict()
            if self.bootstrap_block
            else None,
            "permutation": self.permutation.to_dict() if self.permutation else None,
            "multiple_testing": self.multiple_testing.to_dict()
            if self.multiple_testing
            else None,
            "pbo": self.pbo.to_dict() if self.pbo else None,
            "sensitivity": self.sensitivity.to_dict() if self.sensitivity else None,
            "cost_stress": self.cost_stress.to_dict() if self.cost_stress else None,
            "regime": self.regime.to_dict() if self.regime else None,
            "universe": self.universe.to_dict() if self.universe else None,
            "temporal": self.temporal.to_dict() if self.temporal else None,
            "evidence_checks": self.evidence_checks,
            "missing_evidence": self.missing_evidence,
            "warnings": self.warnings,
        }

    def to_json(self, indent: int = 2) -> str:
        """Deterministic JSON serialization."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


class ValidationEngine:
    """Main validation orchestrator.

    Runs all validation tests against a strategy's equity curve
    and produces a comprehensive verdict with evidence profile.
    """

    def __init__(
        self,
        walk_forward_train: int = 300,
        walk_forward_test: int = 100,
        walk_forward_purge: int = 10,
        walk_forward_embargo: int = 0,
        bootstrap_iterations: int = 500,
        permutation_iterations: int = 500,
        bootstrap_seed: int = 42,
        block_size: int = 21,
        temporal_window: int = 252,
        temporal_step: int = 63,
    ) -> None:
        self.wf_train = walk_forward_train
        self.wf_test = walk_forward_test
        self.wf_purge = walk_forward_purge
        self.wf_embargo = walk_forward_embargo
        self.bootstrap_iters = bootstrap_iterations
        self.perm_iters = permutation_iterations
        self.seed = bootstrap_seed
        self.block_size = block_size
        self.temporal_window = temporal_window
        self.temporal_step = temporal_step

    def validate(
        self,
        experiment_id: str = "",
        equity_curve: Optional[List[float]] = None,
        instrument_returns: Optional[Dict[str, List[float]]] = None,
        trades: Optional[List[float]] = None,
        pbo_candidates: Optional[List[Dict[str, float]]] = None,
        regime_returns: Optional[Dict[str, List[float]]] = None,
        sensitivity_data: Optional[Dict[str, List[float]]] = None,
        cost_stress_data: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Run full validation suite.

        MISSING evidence → INCONCLUSIVE (never PASS).
        """
        warnings = []

        if not equity_curve or len(equity_curve) < 10:
            return ValidationResult(
                experiment_id=experiment_id,
                verdict=EvidenceVerdict.REJECTED,
                warnings=["Insufficient equity curve data (minimum 10 observations)"],
                missing_evidence=["equity_curve"],
            )

        # ── 1. Baseline metrics ─────────────────────────────────────
        baseline = None
        try:
            baseline = compute_metrics(equity_curve, trades)
        except ValueError as e:
            warnings.append(f"Baseline metrics error: {e}")

        # ── 2. Compute returns ──────────────────────────────────────
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                returns.append((equity_curve[i] / equity_curve[i - 1]) - 1.0)

        # ── 3. Walk-forward ─────────────────────────────────────────
        wf = purged_walk_forward(
            equity_curve,
            self.wf_train,
            self.wf_test,
            self.wf_purge,
            embargo_bars=self.wf_embargo,
        )
        if wf.total_windows == 0:
            warnings.append("Walk-forward: insufficient data for any complete window")
        elif wf.mean_oos_sharpe <= 0:
            warnings.append(
                f"Walk-forward: OOS Sharpe is non-positive ({wf.mean_oos_sharpe:.3f})"
            )
        if wf.total_windows > 0 and wf.degradation_ratio > 2.0:
            warnings.append(
                f"Walk-forward: high degradation ({wf.degradation_ratio:.2f}x)"
            )

        # ── 4. Bootstrap (IID + Block) ──────────────────────────────
        boot_iid = (
            bootstrap_test(returns, self.bootstrap_iters, seed=self.seed)
            if returns
            else None
        )
        boot_block = (
            block_bootstrap(
                returns, self.block_size, self.bootstrap_iters, seed=self.seed
            )
            if returns
            else None
        )

        # ── 5. Permutation test ─────────────────────────────────────
        perm = (
            permutation_test(returns, self.perm_iters, seed=self.seed)
            if returns
            else None
        )

        # ── 6. Sensitivity ──────────────────────────────────────────
        sens = None
        if sensitivity_data and baseline:
            sens = parameter_sensitivity(baseline.sharpe_ratio, sensitivity_data)

        # ── 7. Cost stress ──────────────────────────────────────────
        cost = None
        if cost_stress_data and baseline:
            cost = cost_stress_test(
                baseline.sharpe_ratio,
                cost_stress_data.get("multipliers", []),
                cost_stress_data.get("sharpes", []),
            )

        # ── 8. Regime analysis ──────────────────────────────────────
        regime = regime_analysis(regime_returns) if regime_returns else None

        # ── 9. Universe perturbation ────────────────────────────────
        universe = (
            universe_perturbation(instrument_returns) if instrument_returns else None
        )

        # ── 10. Temporal stability ──────────────────────────────────
        temporal = temporal_stability(
            equity_curve, self.temporal_window, self.temporal_step
        )

        # ── 11. Multiple testing (placeholder — needs trial data) ───
        mt = None  # Only computed if trial data provided

        # ── 12. PBO ─────────────────────────────────────────────────
        pbo = compute_pbo(pbo_candidates) if pbo_candidates else None

        # ── 13. Evidence gate ───────────────────────────────────────
        gate = EvidenceGate()
        gate_result = gate.evaluate(
            walk_forward=wf,
            bootstrap=boot_iid,
            permutation=perm,
            sensitivity=sens,
            cost_stress=cost,
            regime=regime,
            universe=universe,
            temporal=temporal,
            multiple_testing=mt,
            pbo=pbo,
        )

        return ValidationResult(
            experiment_id=experiment_id,
            baseline_metrics=baseline,
            walk_forward=wf,
            bootstrap_iid=boot_iid,
            bootstrap_block=boot_block,
            permutation=perm,
            multiple_testing=mt,
            pbo=pbo,
            sensitivity=sens,
            cost_stress=cost,
            regime=regime,
            universe=universe,
            temporal=temporal,
            verdict=gate_result["verdict"],
            evidence_checks=gate_result["checks"],
            warnings=warnings,
            missing_evidence=gate_result.get("missing_evidence", []),
        )
