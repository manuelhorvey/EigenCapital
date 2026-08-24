"""Live/Shadow/Backtest Comparison — divergence analysis layer.

Compare BACKTEST vs PAPER vs SHADOW vs LIVE for each decision/event.

Divergence classification:
- MATCH
- EXPECTED_DIVERGENCE
- DATA_DIVERGENCE
- TIMING_DIVERGENCE
- EXECUTION_DIVERGENCE
- RISK_DIVERGENCE
- SYSTEM_ERROR
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Any


class DivergenceCategory(str, Enum):
    """Categories of divergence between execution modes."""

    MATCH = "match"
    EXPECTED_DIVERGENCE = "expected_divergence"
    DATA_DIVERGENCE = "data_divergence"
    TIMING_DIVERGENCE = "timing_divergence"
    EXECUTION_DIVERGENCE = "execution_divergence"
    RISK_DIVERGENCE = "risk_divergence"
    SYSTEM_ERROR = "system_error"


class DivergenceSeverity(str, Enum):
    """Divergence severity."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DivergenceRecord:
    """Immutable record of a divergence between execution modes."""

    divergence_id: str
    timestamp: str
    instrument_id: str
    category: str
    severity: str
    expected: str
    observed: str
    magnitude: float
    explanation: str = ""
    source_mode: str = ""
    target_mode: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "divergence_id": self.divergence_id,
            "timestamp": self.timestamp,
            "instrument_id": self.instrument_id,
            "category": self.category,
            "severity": self.severity,
            "expected": self.expected,
            "observed": self.observed,
            "magnitude": self.magnitude,
            "explanation": self.explanation,
            "source_mode": self.source_mode,
            "target_mode": self.target_mode,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ComparisonResult:
    """Result of comparing two execution modes."""

    comparison_id: str
    source_mode: str
    target_mode: str
    timestamp: str
    total_divergences: int
    matches: int
    critical_divergences: int
    warnings: int
    divergences: tuple  # tuple of DivergenceRecord

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "source_mode": self.source_mode,
            "target_mode": self.target_mode,
            "timestamp": self.timestamp,
            "total_divergences": self.total_divergences,
            "matches": self.matches,
            "critical_divergences": self.critical_divergences,
            "warnings": self.warnings,
            "divergence_count": len(self.divergences),
        }


class DivergenceAnalyzer:
    """Compares execution modes and classifies divergences."""

    def __init__(self) -> None:
        self._divergences: List[DivergenceRecord] = []
        self._comparisons: List[ComparisonResult] = []

    def compare_decisions(
        self,
        source_decisions: List[Dict[str, Any]],
        target_decisions: List[Dict[str, Any]],
        source_mode: str,
        target_mode: str,
        comparison_id: str,
        timestamp: str = "",
    ) -> ComparisonResult:
        """Compare decisions between two execution modes."""
        divergences: List[DivergenceRecord] = []
        matches = 0

        # Compare by index (assuming aligned decisions)
        for i, (source, target) in enumerate(zip(source_decisions, target_decisions)):
            # Compare feature values
            source_features = source.get("features", {})
            target_features = target.get("features", {})
            if source_features != target_features:
                div = DivergenceRecord(
                    divergence_id=f"{comparison_id}-feat-{i}",
                    timestamp=timestamp,
                    instrument_id=source.get("instrument_id", ""),
                    category=DivergenceCategory.DATA_DIVERGENCE.value,
                    severity=DivergenceSeverity.WARNING.value,
                    expected=json.dumps(source_features, sort_keys=True),
                    observed=json.dumps(target_features, sort_keys=True),
                    magnitude=self._calculate_magnitude(
                        source_features, target_features
                    ),
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
                divergences.append(div)
            else:
                matches += 1

            # Compare strategy output
            source_intent = source.get("strategy_intent", {})
            target_intent = target.get("strategy_intent", {})
            if source_intent != target_intent:
                div = DivergenceRecord(
                    divergence_id=f"{comparison_id}-intent-{i}",
                    timestamp=timestamp,
                    instrument_id=source.get("instrument_id", ""),
                    category=DivergenceCategory.EXECUTION_DIVERGENCE.value,
                    severity=DivergenceSeverity.CRITICAL.value,
                    expected=json.dumps(source_intent, sort_keys=True),
                    observed=json.dumps(target_intent, sort_keys=True),
                    magnitude=1.0,
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
                divergences.append(div)
            else:
                matches += 1

            # Compare risk decision
            source_risk = source.get("risk_decision", {})
            target_risk = target.get("risk_decision", {})
            if source_risk != target_risk:
                div = DivergenceRecord(
                    divergence_id=f"{comparison_id}-risk-{i}",
                    timestamp=timestamp,
                    instrument_id=source.get("instrument_id", ""),
                    category=DivergenceCategory.RISK_DIVERGENCE.value,
                    severity=DivergenceSeverity.CRITICAL.value,
                    expected=json.dumps(source_risk, sort_keys=True),
                    observed=json.dumps(target_risk, sort_keys=True),
                    magnitude=1.0,
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
                divergences.append(div)
            else:
                matches += 1

        critical_count = sum(
            1 for d in divergences if d.severity == DivergenceSeverity.CRITICAL.value
        )
        warning_count = sum(
            1 for d in divergences if d.severity == DivergenceSeverity.WARNING.value
        )

        result = ComparisonResult(
            comparison_id=comparison_id,
            source_mode=source_mode,
            target_mode=target_mode,
            timestamp=timestamp,
            total_divergences=len(divergences),
            matches=matches,
            critical_divergences=critical_count,
            warnings=warning_count,
            divergences=tuple(divergences),
        )
        self._comparisons.append(result)
        self._divergences.extend(divergences)
        return result

    def compare_execution_prices(
        self,
        intended_prices: Dict[str, float],
        actual_prices: Dict[str, float],
        comparison_id: str,
        timestamp: str = "",
        source_mode: str = "backtest",
        target_mode: str = "live",
    ) -> ComparisonResult:
        """Compare execution prices between modes."""
        divergences: List[DivergenceRecord] = []
        matches = 0

        for instrument_id in intended_prices:
            intended = intended_prices[instrument_id]
            actual = actual_prices.get(instrument_id)
            if actual is None:
                div = DivergenceRecord(
                    divergence_id=f"{comparison_id}-price-{instrument_id}",
                    timestamp=timestamp,
                    instrument_id=instrument_id,
                    category=DivergenceCategory.EXECUTION_DIVERGENCE.value,
                    severity=DivergenceSeverity.CRITICAL.value,
                    expected=str(intended),
                    observed="MISSING",
                    magnitude=float("inf"),
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
                divergences.append(div)
            elif abs(actual - intended) / max(abs(intended), 1e-10) > 0.01:
                magnitude = abs(actual - intended) / max(abs(intended), 1e-10)
                severity = (
                    DivergenceSeverity.WARNING.value
                    if magnitude < 0.05
                    else DivergenceSeverity.CRITICAL.value
                )
                div = DivergenceRecord(
                    divergence_id=f"{comparison_id}-price-{instrument_id}",
                    timestamp=timestamp,
                    instrument_id=instrument_id,
                    category=DivergenceCategory.EXECUTION_DIVERGENCE.value,
                    severity=severity,
                    expected=str(intended),
                    observed=str(actual),
                    magnitude=magnitude,
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
                divergences.append(div)
            else:
                matches += 1

        critical_count = sum(
            1 for d in divergences if d.severity == DivergenceSeverity.CRITICAL.value
        )
        warning_count = sum(
            1 for d in divergences if d.severity == DivergenceSeverity.WARNING.value
        )

        result = ComparisonResult(
            comparison_id=comparison_id,
            source_mode=source_mode,
            target_mode=target_mode,
            timestamp=timestamp,
            total_divergences=len(divergences),
            matches=matches,
            critical_divergences=critical_count,
            warnings=warning_count,
            divergences=tuple(divergences),
        )
        self._comparisons.append(result)
        self._divergences.extend(divergences)
        return result

    def _calculate_magnitude(
        self,
        source: Dict[str, Any],
        target: Dict[str, Any],
    ) -> float:
        """Calculate magnitude of divergence between two dicts."""
        if not source:
            return 1.0
        diff_count = 0
        for key in source:
            if key not in target:
                diff_count += 1
            elif source[key] != target[key]:
                diff_count += 1
        return diff_count / max(len(source), 1)

    def get_all_divergences(self) -> List[DivergenceRecord]:
        return list(self._divergences)

    def get_critical_divergences(self) -> List[DivergenceRecord]:
        return [
            d
            for d in self._divergences
            if d.severity == DivergenceSeverity.CRITICAL.value
        ]

    def get_comparisons(self) -> List[ComparisonResult]:
        return list(self._comparisons)
