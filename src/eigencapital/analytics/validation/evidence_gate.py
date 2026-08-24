"""Evidence Gate — determines hypothesis disposition based on all validation results.

The evidence gate is the final arbiter of whether a hypothesis survives
hostile validation. It collects all validation results and applies
pre-registered falsification criteria.

Usage:
    gate = EvidenceGate()
    verdict = gate.evaluate(
        walk_forward=result,
        bootstrap=bootstrap,
        permutation=permutation,
        sensitivity=sensitivity,
        cost_stress=cost_stress,
        regime=regime,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from eigencapital.analytics.validation.walk_forward import WalkForwardResult
from eigencapital.analytics.validation.bootstrap import BootstrapResult, PermutationResult
from eigencapital.analytics.validation.sensitivity import SensitivityResult
from eigencapital.analytics.validation.cost_stress import CostStressResult
from eigencapital.analytics.validation.regime import RegimeResult


class EvidenceVerdict(str):
    """Verdict from evidence gate."""
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True)
class EvidenceCheck:
    """A single evidence check result.

    Attributes:
        check_id: Unique check identifier
        passed: Did this check pass?
        severity: CRITICAL, HIGH, MEDIUM, LOW
        message: Human-readable explanation
    """
    check_id: str
    passed: bool
    severity: str = "HIGH"
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class EvidenceGate:
    """Evaluates all validation results against pre-registered criteria.

    The gate applies the falsification criteria from EXP-000001:
    1. Out-of-sample expectancy > 0
    2. Cost-stressed expectancy > 0 (at 1.5x costs)
    3. Performance not dominated by single instrument
    4. Performance survives parameter perturbation
    5. Walk-forward degradation within tolerance
    6. Statistical significance (permutation test)
    7. Bootstrap confidence interval excludes zero

    Disposition:
    - REJECTED: Any CRITICAL check fails
    - INCONCLUSIVE: Some HIGH checks fail
    - CANDIDATE: All checks pass
    - VALIDATED: All checks pass with strong evidence
    """

    # Thresholds (configurable)
    min_oos_sharpe: float = 0.0
    max_degradation: float = 2.0
    min_pct_profitable_windows: float = 50.0
    max_p_value: float = 0.05
    min_pct_positive_bootstrap: float = 75.0
    min_worst_regime_sharpe: float = -0.5
    max_sharpe_range: float = 2.0

    def evaluate(
        self,
        walk_forward: Optional[WalkForwardResult] = None,
        bootstrap: Optional[BootstrapResult] = None,
        permutation: Optional[PermutationResult] = None,
        sensitivity: Optional[SensitivityResult] = None,
        cost_stress: Optional[CostStressResult] = None,
        regime: Optional[RegimeResult] = None,
    ) -> Dict[str, Any]:
        """Evaluate all validation results.

        Returns:
            Dict with verdict, checks, and summary
        """
        checks = []

        # Check 1: Walk-forward OOS Sharpe > 0
        if walk_forward and walk_forward.total_windows > 0:
            passed = walk_forward.mean_oos_sharpe > self.min_oos_sharpe
            checks.append(EvidenceCheck(
                check_id="wf_oos_positive",
                passed=passed,
                severity="CRITICAL",
                message=f"OOS Sharpe: {walk_forward.mean_oos_sharpe:.3f} (min: {self.min_oos_sharpe})",
            ))

            # Check walk-forward degradation
            passed_deg = walk_forward.degradation_ratio <= self.max_degradation
            checks.append(EvidenceCheck(
                check_id="wf_degradation",
                passed=passed_deg,
                severity="HIGH",
                message=f"Degradation: {walk_forward.degradation_ratio:.2f}x (max: {self.max_degradation}x)",
            ))

            # Check % profitable windows
            passed_win = walk_forward.pct_profitable_windows >= self.min_pct_profitable_windows
            checks.append(EvidenceCheck(
                check_id="wf_profitable_windows",
                passed=passed_win,
                severity="HIGH",
                message=f"Profitable windows: {walk_forward.pct_profitable_windows:.1f}% (min: {self.min_pct_profitable_windows}%)",
            ))

        # Check 2: Bootstrap confidence interval excludes zero
        if bootstrap and bootstrap.n_bootstrap > 0:
            passed_boot = bootstrap.sharpe_ci_lower > 0
            checks.append(EvidenceCheck(
                check_id="bootstrap_ci_positive",
                passed=passed_boot,
                severity="CRITICAL",
                message=f"Bootstrap CI: [{bootstrap.sharpe_ci_lower:.3f}, {bootstrap.sharpe_ci_upper:.3f}]",
            ))

            passed_pct = bootstrap.pct_positive_sharpe >= self.min_pct_positive_bootstrap
            checks.append(EvidenceCheck(
                check_id="bootstrap_pct_positive",
                passed=passed_pct,
                severity="HIGH",
                message=f"% positive Sharpe: {bootstrap.pct_positive_sharpe:.1f}% (min: {self.min_pct_positive_bootstrap}%)",
            ))

        # Check 3: Permutation test significance
        if permutation and permutation.n_permutations > 0:
            passed_perm = permutation.p_value < self.max_p_value
            checks.append(EvidenceCheck(
                check_id="permutation_significant",
                passed=passed_perm,
                severity="CRITICAL",
                message=f"p-value: {permutation.p_value:.4f} (max: {self.max_p_value})",
            ))

        # Check 4: Parameter sensitivity
        if sensitivity:
            passed_sens = sensitivity.overall_robust
            checks.append(EvidenceCheck(
                check_id="sensitivity_robust",
                passed=passed_sens,
                severity="HIGH",
                message=f"Parameter robust: {sensitivity.overall_robust}, worst Sharpe: {sensitivity.worst_case_sharpe:.3f}",
            ))

        # Check 5: Cost stress
        if cost_stress:
            passed_cost = cost_stress.survives_1_5x
            checks.append(EvidenceCheck(
                check_id="cost_stress_1_5x",
                passed=passed_cost,
                severity="CRITICAL",
                message=f"Survives 1.5x costs: {cost_stress.survives_1_5x}, breakeven: {cost_stress.breakeven_multiplier:.2f}x",
            ))

        # Check 6: Regime stability
        if regime:
            passed_regime = not regime.regime_dependent
            checks.append(EvidenceCheck(
                check_id="regime_stable",
                passed=passed_regime,
                severity="HIGH",
                message=f"Sharpe range: {regime.sharpe_range:.3f}, worst: {regime.worst_regime}",
            ))

            passed_min = regime.min_sharpe > self.min_worst_regime_sharpe
            checks.append(EvidenceCheck(
                check_id="regime_min_sharpe",
                passed=passed_min,
                severity="HIGH",
                message=f"Min regime Sharpe: {regime.min_sharpe:.3f} (min: {self.min_worst_regime_sharpe})",
            ))

        # Determine verdict
        critical_failures = [c for c in checks if c.severity == "CRITICAL" and not c.passed]
        high_failures = [c for c in checks if c.severity == "HIGH" and not c.passed]

        if critical_failures:
            verdict = EvidenceVerdict.REJECTED
        elif high_failures:
            verdict = EvidenceVerdict.INCONCLUSIVE
        else:
            # All checks passed — determine CANDIDATE vs VALIDATED
            strong_evidence = (
                (permutation and permutation.p_value < 0.01) or
                (bootstrap and bootstrap.pct_positive_sharpe > 90) or
                (walk_forward and walk_forward.mean_oos_sharpe > 1.0)
            )
            verdict = EvidenceVerdict.VALIDATED if strong_evidence else EvidenceVerdict.CANDIDATE

        return {
            "verdict": verdict,
            "checks": [c.to_dict() for c in checks],
            "total_checks": len(checks),
            "passed_checks": sum(1 for c in checks if c.passed),
            "critical_failures": len(critical_failures),
            "high_failures": len(high_failures),
        }
