"""Research → Paper Parity Engine.

Compares research decisions against paper execution at every decision boundary.
Every divergence must be classified and recorded. Never silently ignore divergence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any


class ParityBoundary(str, Enum):
    """Decision boundaries where research and paper are compared."""

    FEATURE = "feature"
    SIGNAL = "signal"
    TARGET_WEIGHT = "target_weight"
    RISK_APPROVAL = "risk_approval"
    ORDER_INTENT = "order_intent"
    EXECUTION_PRICE = "execution_price"
    COST = "cost"
    POSITION = "position"
    CASH_EQUITY = "cash_equity"
    PNL = "pnl"
    RISK_METRICS = "risk_metrics"
    KILL_SWITCH = "kill_switch"


class DivergenceType(str, Enum):
    """Type of divergence between research and paper."""

    EXACT_MATCH = "exact_match"
    EXPECTED_DIFFERENCE = "expected_difference"  # intentional (e.g., crypto cap)
    TOLERABLE_DIVERGENCE = "tolerable_divergence"
    UNEXPLAINED_DIVERGENCE = "unexplained_divergence"
    CRITICAL_DIVERGENCE = "critical_divergence"


class ParityStatus(str, Enum):
    """Overall parity status for a check."""

    PASS = "pass"
    EXPECTED = "expected"  # intentional difference (e.g., risk cap)
    WARNING = "warning"
    FAIL = "fail"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ParityCheckResult:
    """Result of a single parity check at a decision boundary."""

    check_id: str
    boundary: ParityBoundary
    timestamp: str
    instrument_id: str
    research_value: Any
    paper_value: Any
    difference: float
    tolerance: float
    divergence_type: DivergenceType
    status: ParityStatus
    explanation: str = ""
    is_intentional: bool = False  # True if caused by frozen R4 risk architecture

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "boundary": self.boundary.value,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "research_value": str(self.research_value),
            "paper_value": str(self.paper_value),
            "difference": self.difference,
            "tolerance": self.tolerance,
            "divergence_type": self.divergence_type.value,
            "status": self.status.value,
            "explanation": self.explanation,
            "is_intentional": self.is_intentional,
        }


@dataclass(frozen=True)
class ParitySummary:
    """Aggregate parity statistics for a campaign."""

    total_checks: int = 0
    exact_matches: int = 0
    expected_differences: int = 0
    tolerable_divergences: int = 0
    unexplained_divergences: int = 0
    critical_divergences: int = 0
    overall_status: str = "pending"

    @property
    def match_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.exact_matches / self.total_checks

    @property
    def has_critical(self) -> bool:
        return self.critical_divergences > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "exact_matches": self.exact_matches,
            "expected_differences": self.expected_differences,
            "tolerable_divergences": self.tolerable_divergences,
            "unexplained_divergences": self.unexplained_divergences,
            "critical_divergences": self.critical_divergences,
            "match_rate": self.match_rate,
            "overall_status": self.overall_status,
        }


class ResearchPaperParityEngine:
    """Compares research decisions against paper execution.

    For every decision boundary, records whether research and paper match.
    Divergences are classified as:
    - EXACT_MATCH: values are identical
    - EXPECTED_DIFFERENCE: intentional difference from frozen R4 risk architecture
    - TOLERABLE_DIVERGENCE: within pre-registered tolerance
    - UNEXPLAINED_DIVERGENCE: outside tolerance, not intentional
    - CRITICAL_DIVERGENCE: material divergence requiring investigation
    """

    # Pre-registered tolerances (frozen before campaign)
    DEFAULT_TOLERANCES: Dict[ParityBoundary, float] = {
        ParityBoundary.FEATURE: 1e-10,  # exact (deterministic)
        ParityBoundary.SIGNAL: 1e-10,  # exact (deterministic)
        ParityBoundary.TARGET_WEIGHT: 0.001,  # 0.1% weight tolerance
        ParityBoundary.RISK_APPROVAL: 1e-10,  # exact (boolean)
        ParityBoundary.ORDER_INTENT: 1e-10,  # exact (deterministic)
        ParityBoundary.EXECUTION_PRICE: 0.001,  # 0.1% price tolerance
        ParityBoundary.COST: 0.0001,  # 1bp cost tolerance
        ParityBoundary.POSITION: 1e-6,  # near-exact position
        ParityBoundary.CASH_EQUITY: 0.01,  # 1% equity tolerance
        ParityBoundary.PNL: 0.01,  # 1% P&L tolerance
        ParityBoundary.RISK_METRICS: 0.01,  # 1% risk metric tolerance
        ParityBoundary.KILL_SWITCH: 1e-10,  # exact (boolean)
    }

    def __init__(
        self,
        campaign_id: str,
        tolerances: Optional[Dict[ParityBoundary, float]] = None,
    ) -> None:
        self._campaign_id = campaign_id
        self._tolerances = tolerances or dict(self.DEFAULT_TOLERANCES)
        self._results: List[ParityCheckResult] = []
        self._check_counter = 0

    def check(
        self,
        boundary: ParityBoundary,
        timestamp: str,
        instrument_id: str,
        research_value: Any,
        paper_value: Any,
        is_intentional: bool = False,
        explanation: str = "",
    ) -> ParityCheckResult:
        """Perform a parity check at a decision boundary.

        Args:
            boundary: which decision boundary to check
            timestamp: when the decision occurred
            instrument_id: which instrument
            research_value: what research expected
            paper_value: what paper produced
            is_intentional: True if difference is caused by frozen R4 risk architecture
            explanation: human-readable explanation of any divergence
        """
        self._check_counter += 1
        tolerance = self._tolerances.get(boundary, 1e-6)

        # Compute difference
        if isinstance(research_value, (int, float)) and isinstance(
            paper_value, (int, float)
        ):
            difference = abs(float(research_value) - float(paper_value))
        elif research_value == paper_value:
            difference = 0.0
        else:
            difference = float("inf")

        # Classify divergence
        if difference == 0.0:
            divergence_type = DivergenceType.EXACT_MATCH
            status = ParityStatus.PASS
        elif is_intentional:
            divergence_type = DivergenceType.EXPECTED_DIFFERENCE
            status = ParityStatus.EXPECTED
        elif difference <= tolerance:
            divergence_type = DivergenceType.TOLERABLE_DIVERGENCE
            status = ParityStatus.PASS
        elif difference <= tolerance * 10:
            divergence_type = DivergenceType.UNEXPLAINED_DIVERGENCE
            status = ParityStatus.WARNING
        else:
            divergence_type = DivergenceType.CRITICAL_DIVERGENCE
            status = ParityStatus.CRITICAL

        result = ParityCheckResult(
            check_id=f"CHK-{self._check_counter:06d}",
            boundary=boundary,
            timestamp=timestamp,
            instrument_id=instrument_id,
            research_value=research_value,
            paper_value=paper_value,
            difference=difference,
            tolerance=tolerance,
            divergence_type=divergence_type,
            status=status,
            explanation=explanation,
            is_intentional=is_intentional,
        )
        self._results.append(result)
        return result

    def check_weight(
        self,
        timestamp: str,
        instrument_id: str,
        research_weight: float,
        paper_weight: float,
        is_intentional: bool = False,
        explanation: str = "",
    ) -> ParityCheckResult:
        """Convenience: check target weight parity."""
        return self.check(
            ParityBoundary.TARGET_WEIGHT,
            timestamp,
            instrument_id,
            research_weight,
            paper_weight,
            is_intentional,
            explanation,
        )

    def check_signal(
        self,
        timestamp: str,
        instrument_id: str,
        research_signal: float,
        paper_signal: float,
        is_intentional: bool = False,
        explanation: str = "",
    ) -> ParityCheckResult:
        """Convenience: check signal parity."""
        return self.check(
            ParityBoundary.SIGNAL,
            timestamp,
            instrument_id,
            research_signal,
            paper_signal,
            is_intentional,
            explanation,
        )

    def check_position(
        self,
        timestamp: str,
        instrument_id: str,
        research_position: float,
        paper_position: float,
        is_intentional: bool = False,
        explanation: str = "",
    ) -> ParityCheckResult:
        """Convenience: check position parity."""
        return self.check(
            ParityBoundary.POSITION,
            timestamp,
            instrument_id,
            research_position,
            paper_position,
            is_intentional,
            explanation,
        )

    def check_pnl(
        self,
        timestamp: str,
        instrument_id: str,
        research_pnl: float,
        paper_pnl: float,
        is_intentional: bool = False,
        explanation: str = "",
    ) -> ParityCheckResult:
        """Convenience: check P&L parity."""
        return self.check(
            ParityBoundary.PNL,
            timestamp,
            instrument_id,
            research_pnl,
            paper_pnl,
            is_intentional,
            explanation,
        )

    def get_summary(self) -> ParitySummary:
        """Compute aggregate parity statistics."""
        total = len(self._results)
        exact = sum(
            1 for r in self._results if r.divergence_type == DivergenceType.EXACT_MATCH
        )
        expected = sum(
            1
            for r in self._results
            if r.divergence_type == DivergenceType.EXPECTED_DIFFERENCE
        )
        tolerable = sum(
            1
            for r in self._results
            if r.divergence_type == DivergenceType.TOLERABLE_DIVERGENCE
        )
        unexplained = sum(
            1
            for r in self._results
            if r.divergence_type == DivergenceType.UNEXPLAINED_DIVERGENCE
        )
        critical = sum(
            1
            for r in self._results
            if r.divergence_type == DivergenceType.CRITICAL_DIVERGENCE
        )

        if critical > 0:
            overall = "CRITICAL"
        elif unexplained > 0:
            overall = "WARNING"
        elif total == 0:
            overall = "pending"
        else:
            overall = "PASS"

        return ParitySummary(
            total_checks=total,
            exact_matches=exact,
            expected_differences=expected,
            tolerable_divergences=tolerable,
            unexplained_divergences=unexplained,
            critical_divergences=critical,
            overall_status=overall,
        )

    def get_results(
        self,
        boundary: Optional[ParityBoundary] = None,
        status: Optional[ParityStatus] = None,
    ) -> List[ParityCheckResult]:
        """Get results, optionally filtered."""
        results = self._results
        if boundary is not None:
            results = [r for r in results if r.boundary == boundary]
        if status is not None:
            results = [r for r in results if r.status == status]
        return results

    @property
    def has_critical(self) -> bool:
        return any(
            r.divergence_type == DivergenceType.CRITICAL_DIVERGENCE
            for r in self._results
        )

    @property
    def check_count(self) -> int:
        return len(self._results)
