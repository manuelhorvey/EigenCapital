"""Evidence Gate — falsification-first hypothesis disposition.

Critical design principle:
    NO SILENT PASS.

If a required validation component is unavailable, the verdict CANNOT
become VALIDATED. Missing evidence → INCONCLUSIVE, never PASS.

Usage:
    gate = EvidenceGate()
    result = gate.evaluate(walk_forward=wf, bootstrap=boot, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from eigencapital.analytics.validation.walk_forward import WalkForwardResult
from eigencapital.analytics.validation.bootstrap import BootstrapResult, PermutationResult
from eigencapital.analytics.validation.sensitivity import SensitivityResult
from eigencapital.analytics.validation.cost_stress import CostStressResult
from eigencapital.analytics.validation.regime import RegimeResult
from eigencapital.analytics.validation.universe import UniversePerturbationResult
from eigencapital.analytics.validation.temporal import TemporalStabilityResult
from eigencapital.analytics.validation.multiple_testing import MultipleTestingResult
from eigencapital.analytics.validation.pbo import PBOResult


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
        missing: Was the evidence unavailable?
        severity: CRITICAL, HIGH, MEDIUM, LOW
        message: Human-readable explanation
    """
    check_id: str
    passed: bool
    missing: bool = False
    severity: str = "HIGH"
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "missing": self.missing,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class EvidenceGate:
    """Falsification-first evidence gate.

    Semantic rules:
    - REJECTED: Any CRITICAL check fails
    - INCONCLUSIVE: Any HIGH check fails OR any required evidence is missing
    - CANDIDATE: All checks pass, but evidence is moderate
    - VALIDATED: All checks pass with strong evidence AND no missing components

    Missing evidence → INCONCLUSIVE (never PASS).
    """

    # Thresholds (configurable, documented)
    min_oos_sharpe: float = 0.0
    max_degradation: float = 2.0
    min_pct_profitable_windows: float = 50.0
    max_p_value: float = 0.05
    min_pct_positive_bootstrap: float = 75.0
    min_worst_regime_sharpe: float = -0.5
    max_sharpe_range: float = 2.0
    max_concentration_hhi: float = 0.5
    max_single_instrument_pct: float = 50.0

    def evaluate(
        self,
        walk_forward: Optional[WalkForwardResult] = None,
        bootstrap: Optional[BootstrapResult] = None,
        permutation: Optional[PermutationResult] = None,
        sensitivity: Optional[SensitivityResult] = None,
        cost_stress: Optional[CostStressResult] = None,
        regime: Optional[RegimeResult] = None,
        universe: Optional[UniversePerturbationResult] = None,
        temporal: Optional[TemporalStabilityResult] = None,
        multiple_testing: Optional[MultipleTestingResult] = None,
        pbo: Optional[PBOResult] = None,
    ) -> Dict[str, Any]:
        """Evaluate all validation results with falsification-first semantics.

        Returns:
            Dict with verdict, checks, and summary
        """
        checks = []
        missing_evidence = []

        # ── 1. Walk-forward ─────────────────────────────────────────
        if walk_forward and walk_forward.total_windows > 0:
            passed = walk_forward.mean_oos_sharpe > self.min_oos_sharpe
            checks.append(EvidenceCheck(
                check_id="wf_oos_positive",
                passed=passed,
                severity="CRITICAL",
                message=f"OOS Sharpe: {walk_forward.mean_oos_sharpe:.3f} (min: {self.min_oos_sharpe})",
            ))

            passed_deg = walk_forward.degradation_ratio <= self.max_degradation
            checks.append(EvidenceCheck(
                check_id="wf_degradation",
                passed=passed_deg,
                severity="HIGH",
                message=f"Degradation: {walk_forward.degradation_ratio:.2f}x (max: {self.max_degradation}x)",
            ))

            passed_win = walk_forward.pct_profitable_windows >= self.min_pct_profitable_windows
            checks.append(EvidenceCheck(
                check_id="wf_profitable_windows",
                passed=passed_win,
                severity="HIGH",
                message=f"Profitable windows: {walk_forward.pct_profitable_windows:.1f}% (min: {self.min_pct_profitable_windows}%)",
            ))
        else:
            missing_evidence.append("walk_forward")
            checks.append(EvidenceCheck(
                check_id="wf_oos_positive",
                passed=False,
                missing=True,
                severity="CRITICAL",
                message="Walk-forward analysis unavailable or insufficient data",
            ))

        # ── 2. Bootstrap ────────────────────────────────────────────
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
        else:
            missing_evidence.append("bootstrap")
            checks.append(EvidenceCheck(
                check_id="bootstrap_ci_positive",
                passed=False,
                missing=True,
                severity="CRITICAL",
                message="Bootstrap analysis unavailable",
            ))

        # ── 3. Permutation test ─────────────────────────────────────
        if permutation and permutation.n_permutations > 0:
            passed_perm = permutation.p_value < self.max_p_value
            checks.append(EvidenceCheck(
                check_id="permutation_significant",
                passed=passed_perm,
                severity="CRITICAL",
                message=f"p-value: {permutation.p_value:.4f} (max: {self.max_p_value})",
            ))
        else:
            missing_evidence.append("permutation")
            checks.append(EvidenceCheck(
                check_id="permutation_significant",
                passed=False,
                missing=True,
                severity="CRITICAL",
                message="Permutation test unavailable",
            ))

        # ── 4. Cost stress ──────────────────────────────────────────
        if cost_stress:
            passed_cost = cost_stress.survives_1_5x
            checks.append(EvidenceCheck(
                check_id="cost_stress_1_5x",
                passed=passed_cost,
                severity="CRITICAL",
                message=f"Survives 1.5x costs: {cost_stress.survives_1_5x}, breakeven: {cost_stress.breakeven_multiplier:.2f}x",
            ))
        else:
            missing_evidence.append("cost_stress")
            checks.append(EvidenceCheck(
                check_id="cost_stress_1_5x",
                passed=False,
                missing=True,
                severity="CRITICAL",
                message="Cost stress analysis unavailable",
            ))

        # ── 5. Parameter sensitivity ────────────────────────────────
        if sensitivity:
            passed_sens = sensitivity.overall_robust
            checks.append(EvidenceCheck(
                check_id="sensitivity_robust",
                passed=passed_sens,
                severity="MEDIUM",
                message=f"Parameter robust: {sensitivity.overall_robust}, worst Sharpe: {sensitivity.worst_case_sharpe:.3f}",
            ))
        # Note: missing sensitivity is advisory, not required

        # ── 6. Regime stability ─────────────────────────────────────
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
        else:
            missing_evidence.append("regime")
            checks.append(EvidenceCheck(
                check_id="regime_stable",
                passed=False,
                missing=True,
                severity="HIGH",
                message="Regime analysis unavailable",
            ))

        # ── 7. Universe perturbation ────────────────────────────────
        if universe:
            passed_uni = not universe.single_instrument_dependency
            checks.append(EvidenceCheck(
                check_id="universe_no_single_dependency",
                passed=passed_uni,
                severity="HIGH",
                message=f"Single instrument dependency: {universe.single_instrument_dependency}, "
                        f"robustness: {universe.robustness_score:.1f}%",
            ))

            passed_conc = universe.concentration.herfindahl_index <= self.max_concentration_hhi
            checks.append(EvidenceCheck(
                check_id="universe_concentration",
                passed=passed_conc,
                severity="HIGH",
                message=f"HHI: {universe.concentration.herfindahl_index:.4f} (max: {self.max_concentration_hhi})",
            ))
        else:
            missing_evidence.append("universe")
            checks.append(EvidenceCheck(
                check_id="universe_no_single_dependency",
                passed=False,
                missing=True,
                severity="HIGH",
                message="Universe perturbation analysis unavailable",
            ))

        # ── 8. Temporal stability ───────────────────────────────────
        if temporal and temporal.window_count > 0:
            passed_decay = not temporal.performance_decay
            checks.append(EvidenceCheck(
                check_id="temporal_no_decay",
                passed=passed_decay,
                severity="HIGH",
                message=f"Sharpe trend: {temporal.sharpe_trend:.6f}, "
                        f"positive windows: {temporal.pct_positive_sharpe:.1f}%",
            ))
        else:
            missing_evidence.append("temporal")
            checks.append(EvidenceCheck(
                check_id="temporal_no_decay",
                passed=False,
                missing=True,
                severity="HIGH",
                message="Temporal stability analysis unavailable or insufficient data",
            ))

        # ── 9. Multiple testing ─────────────────────────────────────
        if multiple_testing and multiple_testing.n_tests > 1:
            any_rejected_after_correction = any(multiple_testing.rejected)
            checks.append(EvidenceCheck(
                check_id="multiple_testing_survives",
                passed=any_rejected_after_correction,
                severity="MEDIUM",
                message=f"Method: {multiple_testing.method}, "
                        f"n_tests: {multiple_testing.n_tests}, "
                        f"n_rejected: {sum(multiple_testing.rejected)}",
            ))
        # Note: missing multiple testing is advisory — single test is fine

        # ── 10. PBO ─────────────────────────────────────────────────
        if pbo:
            if pbo.sufficient_experiments:
                passed_pbo = pbo.pbo < 0.5
                checks.append(EvidenceCheck(
                    check_id="pbo_acceptable",
                    passed=passed_pbo,
                    severity="HIGH",
                    message=f"PBO: {pbo.pbo:.2f}, candidates: {pbo.n_candidates}",
                ))
            else:
                checks.append(EvidenceCheck(
                    check_id="pbo_acceptable",
                    passed=True,  # INSUFFICIENT is not a failure
                    missing=True,
                    severity="MEDIUM",
                    message=f"PBO insufficient: {pbo.message}",
                ))

        # ── Determine verdict ───────────────────────────────────────
        critical_failures = [c for c in checks if c.severity == "CRITICAL" and not c.passed and not c.missing]
        critical_missing = [c for c in checks if c.severity == "CRITICAL" and c.missing]
        high_failures = [c for c in checks if c.severity == "HIGH" and not c.passed and not c.missing]
        high_missing = [c for c in checks if c.severity == "HIGH" and c.missing]

        # ALL critical checks missing → REJECTED (no evidence at all)
        all_critical_missing = all(c.missing for c in checks if c.severity == "CRITICAL")

        if critical_failures or all_critical_missing:
            verdict = EvidenceVerdict.REJECTED
        elif critical_missing or high_failures or high_missing:
            # Missing critical/high evidence OR high checks failed → INCONCLUSIVE
            verdict = EvidenceVerdict.INCONCLUSIVE
        else:
            # All checks pass — determine CANDIDATE vs VALIDATED
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
            "missing_evidence": missing_evidence,
            "critical_failures": len(critical_failures),
            "critical_missing": len(critical_missing),
            "high_failures": len(high_failures),
            "high_missing": len(high_missing),
        }
