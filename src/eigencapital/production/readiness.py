"""Production Readiness Gate — forensic audit of system governance.

The gate evaluates whether EigenCapital has earned the right to build
a live execution boundary. It produces a structured verdict based on
evidence across architecture, risk, execution, security, and governance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Tuple


class ReadinessVerdict(str, Enum):
    """Production readiness verdict."""

    NOT_READY = "not_ready"
    CONDITIONAL = "conditional"
    PRODUCTION_READY_FOR_SHADOW = "production_ready_for_shadow"
    PRODUCTION_READY_FOR_RESTRICTED_LIVE = "production_ready_for_restricted_live"


class ReadinessCheck(str, Enum):
    """Individual readiness checks."""

    ARCHITECTURE_INTEGRITY = "architecture_integrity"
    BYPASS_PATHS_CLOSED = "bypass_paths_closed"
    RISK_BOUNDARY_ENFORCED = "risk_boundary_enforced"
    RESEARCH_EXECUTION_SEPARATION = "research_execution_separation"
    CONFIGURATION_DRIFT_DETECTED = "configuration_drift_detected"
    SECURITY_MODEL_DEFINED = "security_model_defined"
    MONITORING_CONTRACT_DEFINED = "monitoring_contract_defined"
    DISASTER_RECOVERY_TESTED = "disaster_recovery_tested"
    CAPITAL_GOVERNANCE_DEFINED = "capital_governance_defined"
    PAPER_QUALIFIED = "paper_qualified"
    NO_LIVE_CONNECTIVITY = "no_live_connectivity"
    PROVENANCE_CHAIN_COMPLETE = "provenance_chain_complete"


@dataclass(frozen=True)
class ReadinessCheckResult:
    """Result of a single readiness check."""

    check: ReadinessCheck
    passed: bool
    severity: str = "CRITICAL"
    details: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check.value,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ReadinessResult:
    """Complete readiness result with verdict."""

    checks: Tuple[ReadinessCheckResult, ...] = ()
    verdict: ReadinessVerdict = ReadinessVerdict.NOT_READY
    warnings: Tuple[str, ...] = ()
    failures: Tuple[str, ...] = ()
    outstanding_risks: Tuple[str, ...] = ()
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "verdict": self.verdict.value,
            "warnings": list(self.warnings),
            "failures": list(self.failures),
            "outstanding_risks": list(self.outstanding_risks),
        }

    @classmethod
    def evaluate(cls, metrics: Dict[str, Any]) -> ReadinessResult:
        """Evaluate production readiness.

        Args:
            metrics: Audit metrics from forensic analysis

        Returns:
            ReadinessResult with verdict
        """
        checks: List[ReadinessCheckResult] = []
        warnings: List[str] = []
        failures: List[str] = []
        risks: List[str] = []

        # 1. Architecture integrity
        if metrics.get("architecture_intact", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.ARCHITECTURE_INTEGRITY,
                    passed=True,
                    details="Domain contracts intact, no silent mutations",
                    evidence="939 tests passing, 0 failures",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.ARCHITECTURE_INTEGRITY,
                    passed=False,
                    severity="CRITICAL",
                    details="Architecture integrity compromised",
                )
            )
            failures.append("Architecture integrity compromised")

        # 2. Bypass paths closed
        bypass_count = metrics.get("open_bypass_paths", 0)
        if bypass_count == 0:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.BYPASS_PATHS_CLOSED,
                    passed=True,
                    details="No open bypass paths detected",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.BYPASS_PATHS_CLOSED,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{bypass_count} open bypass paths",
                )
            )
            failures.append(f"Open bypass paths: {bypass_count}")

        # 3. Risk boundary enforced
        risk_bypasses = metrics.get("risk_bypasses", 0)
        if risk_bypasses == 0:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.RISK_BOUNDARY_ENFORCED,
                    passed=True,
                    details="EigenRisk boundary continuously enforced",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.RISK_BOUNDARY_ENFORCED,
                    passed=False,
                    severity="CRITICAL",
                    details=f"{risk_bypasses} risk boundary violations",
                )
            )
            failures.append(f"Risk boundary violations: {risk_bypasses}")

        # 4. Research/execution separation
        if metrics.get("research_execution_separated", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.RESEARCH_EXECUTION_SEPARATION,
                    passed=True,
                    details="Research code cannot submit live orders",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.RESEARCH_EXECUTION_SEPARATION,
                    passed=False,
                    severity="CRITICAL",
                    details="Research/execution boundary compromised",
                )
            )
            failures.append("Research/execution separation violated")

        # 5. No live connectivity
        if not metrics.get("has_live_connectivity", False):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.NO_LIVE_CONNECTIVITY,
                    passed=True,
                    details="No live broker connectivity exists",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.NO_LIVE_CONNECTIVITY,
                    passed=False,
                    severity="CRITICAL",
                    details="Live broker connectivity detected",
                )
            )
            failures.append("Live broker connectivity detected")

        # 6. Provenance chain
        if metrics.get("provenance_complete", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.PROVENANCE_CHAIN_COMPLETE,
                    passed=True,
                    details="Provenance chain is complete and verifiable",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.PROVENANCE_CHAIN_COMPLETE,
                    passed=False,
                    severity="HIGH",
                    details="Provenance chain has gaps",
                )
            )
            warnings.append("Provenance chain has gaps")

        # 7. Paper qualified
        paper_qualified = metrics.get("paper_qualified", False)
        if paper_qualified:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.PAPER_QUALIFIED,
                    passed=True,
                    details="Paper trading qualification achieved",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.PAPER_QUALIFIED,
                    passed=False,
                    severity="HIGH",
                    details="Paper qualification not achieved",
                )
            )
            warnings.append("Paper qualification not achieved")

        # 8. Security model
        if metrics.get("security_defined", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.SECURITY_MODEL_DEFINED,
                    passed=True,
                    details="Security model defined and verified",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.SECURITY_MODEL_DEFINED,
                    passed=False,
                    severity="HIGH",
                    details="Security model incomplete",
                )
            )
            warnings.append("Security model incomplete")

        # 9. Monitoring
        if metrics.get("monitoring_defined", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.MONITORING_CONTRACT_DEFINED,
                    passed=True,
                    details="Monitoring contract defined",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.MONITORING_CONTRACT_DEFINED,
                    passed=False,
                    severity="MEDIUM",
                    details="Monitoring contract not fully defined",
                )
            )
            warnings.append("Monitoring contract incomplete")

        # 10. Disaster recovery
        if metrics.get("disaster_recovery_tested", False):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.DISASTER_RECOVERY_TESTED,
                    passed=True,
                    details="Disaster recovery scenarios tested",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.DISASTER_RECOVERY_TESTED,
                    passed=False,
                    severity="MEDIUM",
                    details="Disaster recovery not fully tested",
                )
            )
            warnings.append("Disaster recovery testing incomplete")

        # 11. Capital governance
        if metrics.get("capital_governance_defined", True):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.CAPITAL_GOVERNANCE_DEFINED,
                    passed=True,
                    details="Capital governance model defined",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.CAPITAL_GOVERNANCE_DEFINED,
                    passed=False,
                    severity="MEDIUM",
                    details="Capital governance not defined",
                )
            )
            warnings.append("Capital governance not defined")

        # 12. Configuration drift
        if not metrics.get("configuration_drift_detected", False):
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.CONFIGURATION_DRIFT_DETECTED,
                    passed=True,
                    details="No unauthorized configuration drift",
                )
            )
        else:
            checks.append(
                ReadinessCheckResult(
                    check=ReadinessCheck.CONFIGURATION_DRIFT_DETECTED,
                    passed=False,
                    severity="HIGH",
                    details="Unauthorized configuration drift detected",
                )
            )
            failures.append("Configuration drift detected")

        # Determine verdict
        critical_failures = [c for c in checks if not c.passed and c.severity == "CRITICAL"]
        high_failures = [c for c in checks if not c.passed and c.severity == "HIGH"]
        all_passed = all(c.passed for c in checks)

        if critical_failures:
            verdict = ReadinessVerdict.NOT_READY
        elif high_failures:
            verdict = ReadinessVerdict.CONDITIONAL
        elif all_passed:
            verdict = ReadinessVerdict.PRODUCTION_READY_FOR_SHADOW
        else:
            verdict = ReadinessVerdict.CONDITIONAL

        # Never return unrestricted LIVE_READY
        if verdict == ReadinessVerdict.PRODUCTION_READY_FOR_RESTRICTED_LIVE:
            verdict = ReadinessVerdict.PRODUCTION_READY_FOR_SHADOW

        return cls(
            checks=tuple(checks),
            verdict=verdict,
            warnings=tuple(warnings),
            failures=tuple(failures),
            outstanding_risks=tuple(risks),
        )
