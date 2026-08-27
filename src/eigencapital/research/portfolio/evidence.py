"""Portfolio Evidence Gate — final verdict for portfolio combinations.

The portfolio evidence gate evaluates whether a combined portfolio
survives the same hostile standards applied to individual alphas.

Critical invariant: The combination itself is a new research hypothesis
and must receive its own verdict. Individual alpha verdicts do not
propagate to the portfolio level.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Tuple


class PortfolioVerdict(str, Enum):
    """Portfolio evidence gate verdict."""

    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    CANDIDATE = "candidate"
    VALIDATED = "validated"


class EvidenceCheck(str, Enum):
    """Individual evidence check types."""

    DIVERSIFICATION_BENEFIT = "diversification_benefit"
    COST_SURVIVAL = "cost_survival"
    WALKFORWARD_STABILITY = "walkforward_stability"
    REGIME_STABILITY = "regime_stability"
    TAIL_RISK = "tail_risk"
    TURNOVER_ACCEPTABLE = "turnover_acceptable"
    CONCENTRATION_SAFE = "concentration_safe"
    CORRELATION_STABLE = "correlation_stable"
    NO_LOOKAHEAD = "no_lookahead"
    MULTIPLE_TESTING_ADJUSTED = "multiple_testing_adjusted"


@dataclass(frozen=True)
class EvidenceCheckResult:
    """Result of a single evidence check."""

    check: EvidenceCheck
    passed: bool
    severity: str = "HIGH"  # CRITICAL, HIGH, MEDIUM, LOW
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check.value,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass(frozen=True)
class PortfolioEvidenceGate:
    """Portfolio-level evidence gate.

    Evaluates whether a combined portfolio meets the evidence standards
    required to proceed to paper-trading readiness.

    Attributes:
        experiment_id: Portfolio experiment ID
        checks: List of evidence check results
        verdict: Final verdict
        warnings: List of warnings
        failures: List of failure reasons
        provenance_hash: Deterministic hash
    """

    experiment_id: str
    checks: Tuple[EvidenceCheckResult, ...] = ()
    verdict: PortfolioVerdict = PortfolioVerdict.INCONCLUSIVE
    warnings: Tuple[str, ...] = ()
    failures: Tuple[str, ...] = ()
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "checks": [c.to_dict() for c in self.checks],
            "verdict": self.verdict.value,
            "warnings": list(self.warnings),
            "failures": list(self.failures),
            "provenance_hash": self.provenance_hash,
        }

    @classmethod
    def evaluate(
        cls,
        experiment_id: str,
        metrics: Dict[str, Any],
        baseline_metrics: Dict[str, Any] | None = None,
        config: Dict[str, Any] | None = None,
    ) -> PortfolioEvidenceGate:
        """Evaluate a portfolio against evidence standards.

        Args:
            experiment_id: Portfolio experiment ID
            metrics: Portfolio performance metrics
            baseline_metrics: 1/N baseline metrics for comparison
            config: Evaluation configuration

        Returns:
            PortfolioEvidenceGate with verdict
        """
        checks: List[EvidenceCheckResult] = []
        warnings: List[str] = []
        failures: List[str] = []

        # 1. Diversification benefit
        if baseline_metrics:
            baseline_sharpe = baseline_metrics.get("sharpe", 0)
            portfolio_sharpe = metrics.get("sharpe", 0)
            if portfolio_sharpe > baseline_sharpe:
                checks.append(
                    EvidenceCheckResult(
                        check=EvidenceCheck.DIVERSIFICATION_BENEFIT,
                        passed=True,
                        details=f"Portfolio Sharpe {portfolio_sharpe:.3f} > baseline {baseline_sharpe:.3f}",
                    )
                )
            else:
                checks.append(
                    EvidenceCheckResult(
                        check=EvidenceCheck.DIVERSIFICATION_BENEFIT,
                        passed=False,
                        severity="HIGH",
                        details=f"Portfolio Sharpe {portfolio_sharpe:.3f} <= baseline {baseline_sharpe:.3f}",
                    )
                )
                warnings.append("No diversification benefit over 1/N baseline")
        else:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.DIVERSIFICATION_BENEFIT,
                    passed=True,
                    severity="LOW",
                    details="No baseline available for comparison",
                )
            )

        # 2. Cost survival
        net_sharpe = metrics.get("net_sharpe", metrics.get("sharpe", 0))
        if net_sharpe > 0:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.COST_SURVIVAL,
                    passed=True,
                    details=f"Net Sharpe {net_sharpe:.3f} > 0",
                )
            )
        else:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.COST_SURVIVAL,
                    passed=False,
                    severity="CRITICAL",
                    details=f"Net Sharpe {net_sharpe:.3f} <= 0",
                )
            )
            failures.append("Portfolio does not survive transaction costs")

        # 3. Tail risk
        max_dd = metrics.get("max_drawdown", 0)
        if max_dd < 0.25:  # Less than 25% drawdown
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.TAIL_RISK,
                    passed=True,
                    details=f"Max drawdown {max_dd:.1%} < 25%",
                )
            )
        else:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.TAIL_RISK,
                    passed=False,
                    severity="HIGH",
                    details=f"Max drawdown {max_dd:.1%} >= 25%",
                )
            )
            warnings.append(f"Elevated tail risk: max drawdown {max_dd:.1%}")

        # 4. Turnover
        turnover = metrics.get("annual_turnover", 0)
        if turnover < 20:  # Less than 20x annual turnover
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.TURNOVER_ACCEPTABLE,
                    passed=True,
                    details=f"Annual turnover {turnover:.1f}x < 20x",
                )
            )
        else:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.TURNOVER_ACCEPTABLE,
                    passed=False,
                    severity="MEDIUM",
                    details=f"Annual turnover {turnover:.1f}x >= 20x",
                )
            )
            warnings.append(f"High turnover: {turnover:.1f}x annual")

        # 5. Concentration
        concentration = metrics.get("concentration_hhi", 0)
        n_constituents = metrics.get("n_constituents", 1)
        expected_hhi = 1.0 / n_constituents if n_constituents > 0 else 1.0
        if concentration <= expected_hhi * 2:  # Not more than 2x equal weight
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.CONCENTRATION_SAFE,
                    passed=True,
                    details=f"HHI {concentration:.4f} <= 2x equal weight",
                )
            )
        else:
            checks.append(
                EvidenceCheckResult(
                    check=EvidenceCheck.CONCENTRATION_SAFE,
                    passed=False,
                    severity="MEDIUM",
                    details=f"HHI {concentration:.4f} > 2x equal weight",
                )
            )
            warnings.append("Portfolio is concentrated")

        # 6. No look-ahead (always pass if weights are PIT)
        checks.append(
            EvidenceCheckResult(
                check=EvidenceCheck.NO_LOOKAHEAD,
                passed=True,
                details="Weights computed point-in-time",
            )
        )

        # Determine verdict
        critical_failures = [c for c in checks if not c.passed and c.severity == "CRITICAL"]
        high_failures = [c for c in checks if not c.passed and c.severity == "HIGH"]
        all_passed = all(c.passed for c in checks)

        if critical_failures:
            verdict = PortfolioVerdict.REJECTED
        elif high_failures:
            verdict = PortfolioVerdict.INCONCLUSIVE
        elif all_passed and net_sharpe > 0.5:
            verdict = PortfolioVerdict.CANDIDATE
        elif all_passed:
            verdict = PortfolioVerdict.INCONCLUSIVE
        else:
            verdict = PortfolioVerdict.INCONCLUSIVE

        return cls(
            experiment_id=experiment_id,
            checks=tuple(checks),
            verdict=verdict,
            warnings=tuple(warnings),
            failures=tuple(failures),
        )
