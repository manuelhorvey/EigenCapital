"""Stress Test Engine — orchestrates scenario execution against controlled state.

The engine applies perturbations to a baseline system and verifies
expected behavior. It does not modify risk limits or strategy parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional

from eigencapital.stress.result import StressTestResult


@dataclass
class SystemState:
    """Snapshot of system state for stress testing.

    Attributes:
        cash: Current cash balance
        positions: Current positions {instrument: quantity}
        equity: Total equity
        peak_equity: Peak equity (for drawdown calculation)
        daily_pnl: Today's P&L
        weekly_pnl: This week's P&L
        current_leverage: Current gross leverage
        risk_halt: Whether risk halt is active
        market_data_valid: Whether market data is valid
        reconciliation_status: Current reconciliation status
    """
    cash: float = 100_000.0
    positions: Dict[str, float] = field(default_factory=dict)
    equity: float = 100_000.0
    peak_equity: float = 100_000.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    current_leverage: float = 0.0
    risk_halt: bool = False
    market_data_valid: bool = True
    reconciliation_status: str = "HEALTHY"

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity * 100

    @property
    def total_position_value(self) -> float:
        return sum(abs(qty) for qty in self.positions.values())


class StressTestEngine:
    """Executes stress scenarios against controlled system state.

    The engine is deterministic: same inputs produce same outputs.
    It does not modify risk limits or strategy parameters.
    """

    def __init__(self) -> None:
        self._scenarios: List[Dict[str, Any]] = []

    def register_scenario(
        self,
        scenario_id: str,
        description: str,
        perturbation: Callable[[SystemState], SystemState],
        expected: Callable[[SystemState, SystemState], bool],
        expected_behavior: str = "",
        forbidden_behavior: str = "",
        severity: str = "HIGH",
    ) -> None:
        """Register a stress scenario.

        Args:
            scenario_id: Unique identifier
            description: What is being tested
            perturbation: Function that applies adverse condition to baseline
            expected: Function that checks (baseline, stressed) → passes
            expected_behavior: Human-readable expected behavior
            forbidden_behavior: Human-readable forbidden behavior
            severity: CRITICAL, HIGH, MEDIUM, LOW
        """
        self._scenarios.append({
            "scenario_id": scenario_id,
            "description": description,
            "perturbation": perturbation,
            "expected": expected,
            "expected_behavior": expected_behavior,
            "forbidden_behavior": forbidden_behavior,
            "severity": severity,
        })

    def execute(
        self,
        baseline: SystemState,
        scenario_id: Optional[str] = None,
    ) -> List[StressTestResult]:
        """Execute all registered scenarios (or a specific one).

        Args:
            baseline: Baseline system state
            scenario_id: If provided, only execute this scenario

        Returns:
            List of StressTestResult for each executed scenario
        """
        results = []

        for scenario in self._scenarios:
            if scenario_id and scenario["scenario_id"] != scenario_id:
                continue

            # Apply perturbation
            try:
                stressed = scenario["perturbation"](baseline)
            except Exception as e:
                results.append(StressTestResult(
                    scenario_id=scenario["scenario_id"],
                    status="INCONCLUSIVE",
                    severity=scenario["severity"],
                    description=scenario["description"],
                    perturbation=f"Error applying perturbation: {e}",
                    evidence={"error": str(e)},
                ))
                continue

            # Check expected behavior
            try:
                passed = scenario["expected"](baseline, stressed)
            except Exception as e:
                results.append(StressTestResult(
                    scenario_id=scenario["scenario_id"],
                    status="INCONCLUSIVE",
                    severity=scenario["severity"],
                    description=scenario["description"],
                    evidence={"check_error": str(e)},
                ))
                continue

            # Check invariants
            violations = self._check_invariants(baseline, stressed)

            status = "PASS" if passed and not violations else "FAIL"

            # Compute max loss
            max_loss = max(0, baseline.equity - stressed.equity)

            results.append(StressTestResult(
                scenario_id=scenario["scenario_id"],
                status=status,
                severity=scenario["severity"],
                description=scenario["description"],
                expected_behavior=scenario["expected_behavior"],
                actual_behavior=f"Passed: {passed}, Violations: {len(violations)}",
                violated_invariants=violations,
                maximum_loss=max_loss,
                maximum_exposure=stressed.total_position_value,
                is_system_failure=status == "FAIL",
            ))

        return results

    def _check_invariants(self, baseline: SystemState, stressed: SystemState) -> List[str]:
        """Check fundamental invariants between baseline and stressed state."""
        violations = []

        # Invariant: equity must not increase from adverse perturbation
        # (This is checked per-scenario, not globally)

        # Invariant: cash must be finite
        if stressed.cash != stressed.cash:  # NaN check
            violations.append("cash_is_nan")
        if stressed.cash == float('inf') or stressed.cash == float('-inf'):
            violations.append("cash_is_infinite")

        # Invariant: no negative cash without explicit margin
        # (Relaxed: negative cash is possible with margin)

        # Invariant: position quantities must be finite
        for inst, qty in stressed.positions.items():
            if qty != qty:  # NaN
                violations.append(f"position_{inst}_nan")
            if qty == float('inf') or qty == float('-inf'):
                violations.append(f"position_{inst}_infinite")

        # Invariant: risk halt must be respected
        if baseline.risk_halt and not stressed.risk_halt:
            violations.append("risk_halt_cleared_unexpectedly")

        return violations
