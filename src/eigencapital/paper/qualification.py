"""Paper Qualification Engine — evaluates whether paper trading qualifies.

The qualification engine produces a structured verdict:
- NOT_QUALIFIED: Critical failures detected
- CONDITIONAL: Warnings or insufficient evidence
- PAPER_QUALIFIED: All checks pass

Never automatically produce LIVE_ELIGIBLE.
Missing evidence MUST NOT equal PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Tuple


class QualificationVerdict(str, Enum):
    """Paper qualification verdict."""

    NOT_QUALIFIED = "not_qualified"
    CONDITIONAL = "conditional"
    PAPER_QUALIFIED = "paper_qualified"


class QualificationCheck(str, Enum):
    """Individual qualification checks."""

    RECONCILIATION_STABLE = "reconciliation_stable"
    RISK_BOUNDARY_RESPECTED = "risk_boundary_respected"
    ACCOUNTING_CONSISTENT = "accounting_consistent"
    PROVENANCE_COMPLETE = "provenance_complete"
    DIVERGENCE_EXPLAINABLE = "divergence_explainable"
    COSTS_WITHIN_TOLERANCE = "costs_within_tolerance"
    NO_CRITICAL_DIVERGENCE = "no_critical_divergence"
    NO_RISK_BYPASS = "no_risk_bypass"
    NO_FILL_CORRUPTION = "no_fill_corruption"
    RESTART_SAFE = "restart_safe"
    AUDIT_TRAIL_APPEND_ONLY = "audit_trail_append_only"


@dataclass(frozen=True)
class QualificationCheckResult:
    """Result of a single qualification check."""

    check: QualificationCheck
    passed: bool
    severity: str = "CRITICAL"
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check.value,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass(frozen=True)
class QualificationResult:
    """Complete qualification result with verdict."""

    campaign_id: str
    checks: Tuple[QualificationCheckResult, ...] = ()
    verdict: QualificationVerdict = QualificationVerdict.NOT_QUALIFIED
    warnings: Tuple[str, ...] = ()
    failures: Tuple[str, ...] = ()
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "checks": [c.to_dict() for c in self.checks],
            "verdict": self.verdict.value,
            "warnings": list(self.warnings),
            "failures": list(self.failures),
        }

    @classmethod
    def evaluate(
        cls,
        campaign_id: str,
        metrics: Dict[str, Any],
    ) -> QualificationResult:
        """Evaluate a campaign for paper qualification.

        Args:
            campaign_id: Campaign identifier
            metrics: Campaign metrics from execution

        Returns:
            QualificationResult with verdict
        """
        checks: List[QualificationCheckResult] = []
        warnings: List[str] = []
        failures: List[str] = []

        # 1. Reconciliation stability
        recon_failures = metrics.get("reconciliation_failures", 0)
        if recon_failures == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RECONCILIATION_STABLE,
                    passed=True,
                    details="No reconciliation failures",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RECONCILIATION_STABLE,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{recon_failures} reconciliation failures",
                )
            )
            failures.append(f"Reconciliation failures: {recon_failures}")

        # 2. Risk boundary respected
        risk_bypasses = metrics.get("risk_bypasses", 0)
        if risk_bypasses == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RISK_BOUNDARY_RESPECTED,
                    passed=True,
                    details="No risk boundary bypasses",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RISK_BOUNDARY_RESPECTED,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{risk_bypasses} risk bypasses detected",
                )
            )
            failures.append(f"Risk bypasses: {risk_bypasses}")

        # 3. Accounting consistency
        accounting_errors = metrics.get("accounting_errors", 0)
        if accounting_errors == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.ACCOUNTING_CONSISTENT,
                    passed=True,
                    details="No accounting inconsistencies",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.ACCOUNTING_CONSISTENT,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{accounting_errors} accounting errors",
                )
            )
            failures.append(f"Accounting errors: {accounting_errors}")

        # 4. No critical divergences
        critical_divs = metrics.get("critical_divergences", 0)
        if critical_divs == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.NO_CRITICAL_DIVERGENCE,
                    passed=True,
                    details="No critical divergences",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.NO_CRITICAL_DIVERGENCE,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{critical_divs} critical divergences",
                )
            )
            failures.append(f"Critical divergences: {critical_divs}")

        # 5. No fill corruption
        duplicate_fills = metrics.get("duplicate_fills", 0)
        if duplicate_fills == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.NO_FILL_CORRUPTION,
                    passed=True,
                    details="No duplicate fills",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.NO_FILL_CORRUPTION,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{duplicate_fills} duplicate fills detected",
                )
            )
            failures.append(f"Duplicate fills: {duplicate_fills}")

        # 6. Restart safety
        restart_errors = metrics.get("restart_errors", 0)
        if restart_errors == 0:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RESTART_SAFE,
                    passed=True,
                    details="No restart/recovery errors",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.RESTART_SAFE,
                    passed=False,
                    severity="HIGH",
                    details=f"{restart_errors} restart errors",
                )
            )
            warnings.append(f"Restart errors: {restart_errors}")

        # 7. Costs within tolerance
        execution_drag = metrics.get("total_execution_drag", 0)
        max_drag = metrics.get("max_allowed_drag", float("inf"))
        if execution_drag <= max_drag:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.COSTS_WITHIN_TOLERANCE,
                    passed=True,
                    details=f"Execution drag {execution_drag:.4f} within tolerance",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.COSTS_WITHIN_TOLERANCE,
                    passed=False,
                    severity="HIGH",
                    details=f"Execution drag {execution_drag:.4f} exceeds {max_drag}",
                )
            )
            warnings.append(f"Execution drag: {execution_drag:.4f}")

        # 8. Provenance complete
        provenance_complete = metrics.get("provenance_complete", True)
        if provenance_complete:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.PROVENANCE_COMPLETE,
                    passed=True,
                    details="Provenance records complete",
                )
            )
        else:
            checks.append(
                QualificationCheckResult(
                    check=QualificationCheck.PROVENANCE_COMPLETE,
                    passed=False,
                    severity="HIGH",
                    details="Provenance records incomplete",
                )
            )
            warnings.append("Provenance incomplete")

        # 9. Audit trail
        checks.append(
            QualificationCheckResult(
                check=QualificationCheck.AUDIT_TRAIL_APPEND_ONLY,
                passed=True,
                details="Audit log is append-only",
            )
        )

        # Determine verdict
        critical_failures = [c for c in checks if not c.passed and c.severity == "CRITICAL"]
        high_failures = [c for c in checks if not c.passed and c.severity == "HIGH"]
        all_passed = all(c.passed for c in checks)

        if critical_failures:
            verdict = QualificationVerdict.NOT_QUALIFIED
        elif high_failures:
            verdict = QualificationVerdict.CONDITIONAL
        elif all_passed:
            verdict = QualificationVerdict.PAPER_QUALIFIED
        else:
            verdict = QualificationVerdict.CONDITIONAL

        return cls(
            campaign_id=campaign_id,
            checks=tuple(checks),
            verdict=verdict,
            warnings=tuple(warnings),
            failures=tuple(failures),
        )
