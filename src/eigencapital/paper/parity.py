"""Research vs Paper Parity — compares backtest decisions against paper execution.

Every divergence must be classified and recorded. Never silently ignore divergence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any


class DivergenceCategory(str, Enum):
    """Categories of research-vs-paper divergence."""

    SIGNAL = "signal_divergence"
    FEATURE = "feature_divergence"
    TIMESTAMP = "timestamp_divergence"
    RISK = "risk_divergence"
    TARGET = "target_divergence"
    ORDER = "order_divergence"
    FILL = "fill_divergence"
    POSITION = "position_divergence"
    ACCOUNTING = "accounting_divergence"
    RECONCILIATION = "reconciliation_divergence"
    DATA = "data_divergence"
    EXECUTION = "execution_divergence"


class DivergenceSeverity(str, Enum):
    """Severity of divergence."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DivergenceRecord:
    """Record of a single divergence between research and paper execution."""

    divergence_id: str
    campaign_id: str
    timestamp: str
    instrument_id: str
    category: DivergenceCategory
    expected: Any
    observed: Any
    magnitude: float = 0.0
    severity: DivergenceSeverity = DivergenceSeverity.WARNING
    explanation: str = ""
    resolution: str = "open"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "divergence_id": self.divergence_id,
            "campaign_id": self.campaign_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "category": self.category.value,
            "expected": str(self.expected),
            "observed": str(self.observed),
            "magnitude": self.magnitude,
            "severity": self.severity.value,
            "explanation": self.explanation,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class ExecutionAttribution:
    """Quantitative attribution of execution drag."""

    expected_entry_price: float = 0.0
    actual_fill_price: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    delay_cost: float = 0.0
    rejection_cost: float = 0.0
    total_execution_drag: float = 0.0
    implementation_shortfall: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_entry_price": self.expected_entry_price,
            "actual_fill_price": self.actual_fill_price,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "delay_cost": self.delay_cost,
            "rejection_cost": self.rejection_cost,
            "total_execution_drag": self.total_execution_drag,
            "implementation_shortfall": self.implementation_shortfall,
        }


class ParityChecker:
    """Compares research backtest against paper execution."""

    def __init__(self, campaign_id: str) -> None:
        self._campaign_id = campaign_id
        self._divergences: List[DivergenceRecord] = []
        self._divergence_counter = 0

    def check_signal(
        self,
        timestamp: str,
        instrument_id: str,
        expected: Any,
        observed: Any,
        tolerance: float = 1e-6,
    ) -> Optional[DivergenceRecord]:
        """Check signal parity."""
        if expected != observed:
            return self._record_divergence(
                timestamp,
                instrument_id,
                DivergenceCategory.SIGNAL,
                expected,
                observed,
                severity=DivergenceSeverity.WARNING,
                explanation="Signal mismatch between research and paper",
            )
        return None

    def check_position(
        self,
        timestamp: str,
        instrument_id: str,
        expected_qty: float,
        observed_qty: float,
        tolerance: float = 1e-6,
    ) -> Optional[DivergenceRecord]:
        """Check position parity."""
        diff = abs(expected_qty - observed_qty)
        if diff > tolerance:
            severity = (
                DivergenceSeverity.CRITICAL
                if diff > 1.0
                else DivergenceSeverity.WARNING
            )
            return self._record_divergence(
                timestamp,
                instrument_id,
                DivergenceCategory.POSITION,
                expected_qty,
                observed_qty,
                magnitude=diff,
                severity=severity,
                explanation=f"Position mismatch: expected={expected_qty}, observed={observed_qty}",
            )
        return None

    def check_order(
        self,
        timestamp: str,
        instrument_id: str,
        expected_side: str,
        expected_qty: float,
        observed_side: str,
        observed_qty: float,
    ) -> Optional[DivergenceRecord]:
        """Check order parity."""
        if expected_side != observed_side or abs(expected_qty - observed_qty) > 1e-6:
            return self._record_divergence(
                timestamp,
                instrument_id,
                DivergenceCategory.ORDER,
                f"{expected_side} {expected_qty}",
                f"{observed_side} {observed_qty}",
                severity=DivergenceSeverity.WARNING,
                explanation="Order mismatch",
            )
        return None

    def check_fill_price(
        self,
        timestamp: str,
        instrument_id: str,
        expected_price: float,
        actual_price: float,
        max_slippage: float = 0.01,
    ) -> Optional[DivergenceRecord]:
        """Check fill price parity and compute slippage."""
        slippage = abs(actual_price - expected_price)
        if slippage > max_slippage:
            return self._record_divergence(
                timestamp,
                instrument_id,
                DivergenceCategory.FILL,
                expected_price,
                actual_price,
                magnitude=slippage,
                severity=DivergenceSeverity.WARNING,
                explanation=f"Slippage {slippage:.4f} exceeds threshold {max_slippage}",
            )
        return None

    def compute_attribution(
        self,
        expected_price: float,
        actual_price: float,
        spread_cost: float = 0.0,
        delay_cost: float = 0.0,
    ) -> ExecutionAttribution:
        """Compute execution attribution."""
        slippage = abs(actual_price - expected_price)
        total_drag = spread_cost + slippage + delay_cost
        return ExecutionAttribution(
            expected_entry_price=expected_price,
            actual_fill_price=actual_price,
            spread_cost=spread_cost,
            slippage_cost=slippage,
            delay_cost=delay_cost,
            total_execution_drag=total_drag,
            implementation_shortfall=total_drag,
        )

    def get_divergences(
        self,
        severity: Optional[DivergenceSeverity] = None,
        category: Optional[DivergenceCategory] = None,
    ) -> List[DivergenceRecord]:
        """Get divergences, optionally filtered."""
        results = self._divergences
        if severity:
            results = [d for d in results if d.severity == severity]
        if category:
            results = [d for d in results if d.category == category]
        return results

    @property
    def has_critical(self) -> bool:
        return any(d.severity == DivergenceSeverity.CRITICAL for d in self._divergences)

    @property
    def divergence_count(self) -> int:
        return len(self._divergences)

    def _record_divergence(
        self,
        timestamp: str,
        instrument_id: str,
        category: DivergenceCategory,
        expected: Any,
        observed: Any,
        magnitude: float = 0.0,
        severity: DivergenceSeverity = DivergenceSeverity.WARNING,
        explanation: str = "",
    ) -> DivergenceRecord:
        self._divergence_counter += 1
        record = DivergenceRecord(
            divergence_id=f"DIV-{self._divergence_counter:06d}",
            campaign_id=self._campaign_id,
            timestamp=timestamp,
            instrument_id=instrument_id,
            category=category,
            expected=expected,
            observed=observed,
            magnitude=magnitude,
            severity=severity,
            explanation=explanation,
        )
        self._divergences.append(record)
        return record
