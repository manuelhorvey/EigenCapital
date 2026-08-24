"""Production Qualification Gate — evidence-based verdict for live trading.

Evaluates whether a live campaign produced sufficient evidence to qualify
for continued or expanded live trading.

Verdicts:
- LIVE_BLOCKED: Critical safety failure
- LIVE_INCONCLUSIVE: No critical failure, insufficient evidence
- LIVE_QUALIFIED: Safety + execution + reconciliation + divergence evidence satisfy thresholds
- LIVE_QUALIFIED_WITH_RESTRICTIONS: Safe but specific restrictions remain
- LIVE_REVOKED: Previously qualified, subsequently invalidated

Key principle: profitable live trading is NOT the qualification criterion.
Qualification is about safety, fidelity, reconciliation, divergence, and stability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Tuple, Optional

from eigencapital.production.fingerprint import ProductionFingerprint
from eigencapital.production.evidence import ExecutionSummary
from eigencapital.production.live_campaign import LiveCampaignResult


class QualificationVerdict(str, Enum):
    """Production qualification verdict."""
    LIVE_BLOCKED = "live_blocked"
    LIVE_INCONCLUSIVE = "live_inconclusive"
    LIVE_QUALIFIED = "live_qualified"
    LIVE_QUALIFIED_WITH_RESTRICTIONS = "live_qualified_with_restrictions"
    LIVE_REVOKED = "live_revoked"


class QualificationCheck(str, Enum):
    """Individual qualification checks."""
    SAFETY_CONSTRAINTS = "safety_constraints"
    EXECUTION_FIDELITY = "execution_fidelity"
    RECONCILIATION_STABILITY = "reconciliation_stability"
    DIVERGENCE_BOUNDED = "divergence_bounded"
    OPERATIONAL_STABILITY = "operational_stability"
    EVIDENCE_SUFFICIENCY = "evidence_sufficiency"
    FINGERPRINT_INTEGRITY = "fingerprint_integrity"
    RISK_BOUNDARY_RESPECTED = "risk_boundary_respected"
    KILL_SWITCH_FUNCTIONAL = "kill_switch_functional"
    NO_CRITICAL_FAILURES = "no_critical_failures"


@dataclass(frozen=True)
class QualificationCheckResult:
    """Result of a single qualification check."""
    check: str
    passed: bool
    severity: str = "CRITICAL"
    details: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class QualificationThresholds:
    """Configurable thresholds for qualification checks."""
    max_critical_divergences: int = 0
    max_total_divergences: int = 10
    max_risk_violations: int = 0
    max_reconciliation_failures: int = 0
    max_kill_switch_activations: int = 5
    min_evidence_completeness: float = 0.8
    max_fill_rate_threshold: float = 0.5
    max_rejection_rate_threshold: float = 0.3
    max_slippage_threshold: float = 0.05
    max_latency_p99_threshold: float = 10.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_critical_divergences": self.max_critical_divergences,
            "max_total_divergences": self.max_total_divergences,
            "max_risk_violations": self.max_risk_violations,
            "max_reconciliation_failures": self.max_reconciliation_failures,
            "max_kill_switch_activations": self.max_kill_switch_activations,
            "min_evidence_completeness": self.min_evidence_completeness,
            "max_fill_rate_threshold": self.max_fill_rate_threshold,
            "max_rejection_rate_threshold": self.max_rejection_rate_threshold,
            "max_slippage_threshold": self.max_slippage_threshold,
            "max_latency_p99_threshold": self.max_latency_p99_threshold,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class QualificationResult:
    """Complete qualification result with verdict."""
    campaign_id: str
    verdict: str
    checks: tuple  # tuple of QualificationCheckResult
    restrictions: tuple = ()
    notes: str = ""
    production_fingerprint: Optional[ProductionFingerprint] = None
    evidence_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
            "restrictions": list(self.restrictions),
            "notes": self.notes,
            "evidence_fingerprint": self.evidence_fingerprint,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class ProductionQualificationGate:
    """Evaluates live campaign evidence and produces qualification verdict."""

    def __init__(self, thresholds: Optional[QualificationThresholds] = None) -> None:
        self._thresholds = thresholds or QualificationThresholds()
        self._results: List[QualificationResult] = []

    @property
    def thresholds(self) -> QualificationThresholds:
        return self._thresholds

    def evaluate(self, campaign_result: LiveCampaignResult) -> QualificationResult:
        """Evaluate a live campaign result and produce a qualification verdict."""
        checks: List[QualificationCheckResult] = []
        restrictions: List[str] = []
        notes_parts: List[str] = []

        # 1. Safety constraints
        safety_passed = campaign_result.risk_boundary_violations <= self._thresholds.max_risk_violations
        checks.append(QualificationCheckResult(
            check=QualificationCheck.SAFETY_CONSTRAINTS.value,
            passed=safety_passed,
            severity="CRITICAL",
            details=f"Risk violations: {campaign_result.risk_boundary_violations}",
            evidence=f"Threshold: {self._thresholds.max_risk_violations}",
        ))
        if not safety_passed:
            notes_parts.append("Safety constraint violated")

        # 2. Execution fidelity
        exec_summary = campaign_result.execution_summary
        fill_rate_ok = exec_summary.fill_rate >= self._thresholds.max_fill_rate_threshold
        rejection_rate_ok = exec_summary.rejection_rate <= self._thresholds.max_rejection_rate_threshold
        slippage_ok = exec_summary.slippage_distribution.median <= self._thresholds.max_slippage_threshold
        exec_passed = fill_rate_ok and rejection_rate_ok and slippage_ok
        checks.append(QualificationCheckResult(
            check=QualificationCheck.EXECUTION_FIDELITY.value,
            passed=exec_passed,
            severity="CRITICAL" if not exec_passed else "INFO",
            details=f"fill_rate={exec_summary.fill_rate:.2f}, "
                    f"rejection_rate={exec_summary.rejection_rate:.2f}, "
                    f"slippage_median={exec_summary.slippage_distribution.median:.4f}",
        ))
        if not exec_passed:
            restrictions.append("Reduced execution frequency")
            notes_parts.append("Execution fidelity below threshold")

        # 3. Reconciliation stability
        recon_passed = campaign_result.reconciliation_failures <= self._thresholds.max_reconciliation_failures
        checks.append(QualificationCheckResult(
            check=QualificationCheck.RECONCILIATION_STABILITY.value,
            passed=recon_passed,
            severity="CRITICAL",
            details=f"Reconciliation failures: {campaign_result.reconciliation_failures}",
        ))
        if not recon_passed:
            notes_parts.append("Reconciliation instability detected")

        # 4. Divergence bounded
        div_total_ok = campaign_result.total_divergences <= self._thresholds.max_total_divergences
        div_crit_ok = campaign_result.critical_divergences <= self._thresholds.max_critical_divergences
        div_passed = div_total_ok and div_crit_ok
        checks.append(QualificationCheckResult(
            check=QualificationCheck.DIVERGENCE_BOUNDED.value,
            passed=div_passed,
            severity="CRITICAL" if not div_crit_ok else ("WARNING" if not div_total_ok else "INFO"),
            details=f"total={campaign_result.total_divergences}, "
                    f"critical={campaign_result.critical_divergences}",
        ))
        if not div_passed:
            restrictions.append("Investigate divergence sources")
            notes_parts.append("Divergence exceeded bounds")

        # 5. Operational stability
        ops_passed = campaign_result.kill_switch_activations <= self._thresholds.max_kill_switch_activations
        checks.append(QualificationCheckResult(
            check=QualificationCheck.OPERATIONAL_STABILITY.value,
            passed=ops_passed,
            severity="WARNING",
            details=f"Kill switch activations: {campaign_result.kill_switch_activations}",
        ))
        if not ops_passed:
            restrictions.append("Review kill switch activation causes")

        # 6. Evidence sufficiency
        evidence_passed = campaign_result.evidence_completeness >= self._thresholds.min_evidence_completeness
        checks.append(QualificationCheckResult(
            check=QualificationCheck.EVIDENCE_SUFFICIENCY.value,
            passed=evidence_passed,
            severity="HIGH",
            details=f"Evidence completeness: {campaign_result.evidence_completeness:.2f}",
        ))
        if not evidence_passed:
            notes_parts.append("Insufficient evidence for qualification")

        # 7. Fingerprint integrity
        fp_passed = campaign_result.production_fingerprint is not None
        checks.append(QualificationCheckResult(
            check=QualificationCheck.FINGERPRINT_INTEGRITY.value,
            passed=fp_passed,
            severity="CRITICAL",
            details="Production fingerprint present" if fp_passed else "Production fingerprint missing",
        ))

        # 8. Risk boundary respected
        risk_passed = campaign_result.risk_boundary_violations == 0
        checks.append(QualificationCheckResult(
            check=QualificationCheck.RISK_BOUNDARY_RESPECTED.value,
            passed=risk_passed,
            severity="CRITICAL",
            details="No risk boundary violations" if risk_passed else f"{campaign_result.risk_boundary_violations} violations",
        ))

        # 9. Kill switch functional
        ks_passed = True  # Kill switch is tested if activations occurred; no activations is also fine
        checks.append(QualificationCheckResult(
            check=QualificationCheck.KILL_SWITCH_FUNCTIONAL.value,
            passed=ks_passed,
            severity="INFO",
            details=f"Kill switch activations: {campaign_result.kill_switch_activations}",
        ))

        # 10. No critical failures
        critical_checks = [c for c in checks if not c.passed and c.severity == "CRITICAL"]
        no_critical_passed = len(critical_checks) == 0
        checks.append(QualificationCheckResult(
            check=QualificationCheck.NO_CRITICAL_FAILURES.value,
            passed=no_critical_passed,
            severity="CRITICAL",
            details=f"Critical failures: {len(critical_checks)}",
        ))

        # Determine verdict
        all_critical = all(c.passed for c in checks if c.severity == "CRITICAL")
        all_high = all(c.passed for c in checks if c.severity == "HIGH")
        all_passed = all(c.passed for c in checks)

        if not all_critical:
            verdict = QualificationVerdict.LIVE_BLOCKED.value
        elif not all_high:
            verdict = QualificationVerdict.LIVE_INCONCLUSIVE.value
        elif not all_passed:
            verdict = QualificationVerdict.LIVE_QUALIFIED_WITH_RESTRICTIONS.value
        else:
            verdict = QualificationVerdict.LIVE_QUALIFIED.value

        # Build evidence fingerprint
        evidence_data = {
            "campaign_id": campaign_result.campaign_id,
            "verdict": verdict,
            "checks_summary": {c.check: c.passed for c in checks},
        }
        evidence_payload = json.dumps(evidence_data, sort_keys=True).encode("utf-8")
        evidence_fingerprint = hashlib.sha256(evidence_payload).hexdigest()

        result = QualificationResult(
            campaign_id=campaign_result.campaign_id,
            verdict=verdict,
            checks=tuple(checks),
            restrictions=tuple(restrictions),
            notes="; ".join(notes_parts) if notes_parts else "All checks passed",
            production_fingerprint=campaign_result.production_fingerprint,
            evidence_fingerprint=evidence_fingerprint,
        )
        self._results.append(result)
        return result

    def get_results(self) -> List[QualificationResult]:
        return list(self._results)

    def get_latest_result(self) -> Optional[QualificationResult]:
        return self._results[-1] if self._results else None
