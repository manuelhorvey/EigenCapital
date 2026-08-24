"""Stress test result model — structured output from scenario execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass(frozen=True)
class StressTestResult:
    """Result of a single stress test scenario.

    Attributes:
        scenario_id: Unique scenario identifier
        scenario_version: Scenario version
        status: PASS, FAIL, or INCONCLUSIVE
        severity: CRITICAL, HIGH, MEDIUM, LOW
        description: What was tested
        perturbation: What was changed
        expected_behavior: What should happen
        actual_behavior: What actually happened
        violated_invariants: List of violated invariants
        risk_controls_triggered: Which risk controls activated
        maximum_loss: Worst-case loss under scenario
        maximum_exposure: Maximum exposure created
        reconciliation_status: State consistency check
        is_strategy_failure: True if strategy degraded (expected)
        is_system_failure: True if system behaved incorrectly
        evidence: Supporting evidence
    """

    scenario_id: str = ""
    scenario_version: str = "v1"
    status: str = "PASS"
    severity: str = "HIGH"
    description: str = ""
    perturbation: str = ""
    expected_behavior: str = ""
    actual_behavior: str = ""
    violated_invariants: List[str] = field(default_factory=list)
    risk_controls_triggered: List[str] = field(default_factory=list)
    maximum_loss: float = 0.0
    maximum_exposure: float = 0.0
    reconciliation_status: str = "HEALTHY"
    is_strategy_failure: bool = False
    is_system_failure: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "status": self.status,
            "severity": self.severity,
            "description": self.description,
            "perturbation": self.perturbation,
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "violated_invariants": self.violated_invariants,
            "risk_controls_triggered": self.risk_controls_triggered,
            "maximum_loss": self.maximum_loss,
            "maximum_exposure": self.maximum_exposure,
            "reconciliation_status": self.reconciliation_status,
            "is_strategy_failure": self.is_strategy_failure,
            "is_system_failure": self.is_system_failure,
        }

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"

    @property
    def is_critical(self) -> bool:
        return self.severity == "CRITICAL" and self.failed
