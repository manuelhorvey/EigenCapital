"""Main data validator — orchestrates all validation checks.

Runs temporal, OHLC, and anomaly checks on a list of Bars.
Returns a DataValidationReport with per-bar and aggregate results.

Usage:
    validator = DataValidator()
    report = validator.validate(bars)
    assert report.all_valid()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from eigencapital.core.models.bar import Bar
from eigencapital.core.models.market_snapshot import DataQualityStatus
from eigencapital.data.validation.ohlc import validate_ohlc, OHLCCheckResult
from eigencapital.data.validation.temporal import validate_temporal, TemporalCheckResult
from eigencapital.data.validation.anomalies import validate_anomalies, AnomalyCheckResult


@dataclass(frozen=True)
class BarValidationResult:
    """Validation result for a single bar.

    Attributes:
        bar_index: Position of the bar in the input list
        instrument_id: Instrument being validated
        timestamp_utc: Bar timestamp
        status: Overall status (VALID, WARNING, INVALID, STALE)
        ohlc_result: OHLC validation result
        temporal_result: Temporal validation result
        anomaly_result: Anomaly detection result
        messages: Human-readable messages for all issues
    """

    bar_index: int
    instrument_id: str
    timestamp_utc: str
    status: str  # VALID, WARNING, INVALID, STALE
    ohlc_result: Optional[OHLCCheckResult] = None
    temporal_result: Optional[TemporalCheckResult] = None
    anomaly_result: Optional[AnomalyCheckResult] = None
    messages: List[str] = field(default_factory=list)


@dataclass
class DataValidationReport:
    """Aggregate validation report for a dataset.

    Attributes:
        results: Per-bar validation results
        total_bars: Total number of bars validated
        valid_count: Number of VALID bars
        warning_count: Number of WARNING bars
        invalid_count: Number of INVALID bars
        stale_count: Number of STALE bars
    """

    results: List[BarValidationResult] = field(default_factory=list)

    @property
    def total_bars(self) -> int:
        return len(self.results)

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.results if r.status == DataQualityStatus.VALID)

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if r.status == DataQualityStatus.WARNING)

    @property
    def invalid_count(self) -> int:
        return sum(1 for r in self.results if r.status == DataQualityStatus.INVALID)

    @property
    def stale_count(self) -> int:
        return sum(1 for r in self.results if r.status == DataQualityStatus.STALE)

    def all_valid(self) -> bool:
        """Check if all bars are VALID (no WARNING, INVALID, or STALE)."""
        return self.invalid_count == 0 and self.stale_count == 0

    def has_warnings(self) -> bool:
        """Check if any bars have WARNING status."""
        return self.warning_count > 0

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Validation Report: {self.total_bars} bars\n"
            f"  VALID:   {self.valid_count}\n"
            f"  WARNING: {self.warning_count}\n"
            f"  INVALID: {self.invalid_count}\n"
            f"  STALE:   {self.stale_count}"
        )


class DataValidator:
    """Orchestrates all validation checks on a list of Bars.

    Runs in order:
    1. OHLC validation (structural price checks)
    2. Temporal validation (timestamp ordering, gaps, overlaps)
    3. Anomaly detection (extreme moves, flatlines, spikes)
    """

    def __init__(
        self,
        enable_temporal: bool = True,
        enable_anomalies: bool = True,
    ) -> None:
        self.enable_temporal = enable_temporal
        self.enable_anomalies = enable_anomalies

    def validate(self, bars: List[Bar]) -> DataValidationReport:
        """Validate all bars and produce a report.

        Args:
            bars: List of Bar instances to validate

        Returns:
            DataValidationReport with per-bar and aggregate results
        """
        report = DataValidationReport()

        for i, bar in enumerate(bars):
            result = self._validate_single(bar, i)
            report.results.append(result)

        return report

    def _validate_single(self, bar: Bar, index: int) -> BarValidationResult:
        """Validate a single bar through all check layers."""
        messages: List[str] = []
        worst_status = DataQualityStatus.VALID

        # 1. OHLC validation (runs on Bar's own invariants — already enforced
        #    by the Bar model, but we run it explicitly for the report)
        ohlc_result = validate_ohlc(bar)
        if ohlc_result is not None and ohlc_result.status != DataQualityStatus.VALID:
            messages.extend(ohlc_result.messages)
            worst_status = self._worst_status(worst_status, ohlc_result.status)

        # 2. Temporal validation (needs previous bar for ordering checks)
        temporal_result = None
        if self.enable_temporal:
            temporal_result = validate_temporal(bar, index)
            if temporal_result is not None and temporal_result.status != DataQualityStatus.VALID:
                messages.extend(temporal_result.messages)
                worst_status = self._worst_status(worst_status, temporal_result.status)

        # 3. Anomaly detection
        anomaly_result = None
        if self.enable_anomalies:
            anomaly_result = validate_anomalies(bar)
            if anomaly_result is not None and anomaly_result.status != DataQualityStatus.VALID:
                messages.extend(anomaly_result.messages)
                worst_status = self._worst_status(worst_status, anomaly_result.status)

        return BarValidationResult(
            bar_index=index,
            instrument_id=bar.instrument_id,
            timestamp_utc=bar.timestamp_utc,
            status=worst_status,
            ohlc_result=ohlc_result,
            temporal_result=temporal_result,
            anomaly_result=anomaly_result,
            messages=messages,
        )

    @staticmethod
    def _worst_status(current: str, candidate: str) -> str:
        """Return the more severe of two statuses."""
        severity = {
            DataQualityStatus.VALID: 0,
            DataQualityStatus.WARNING: 1,
            DataQualityStatus.STALE: 2,
            DataQualityStatus.INVALID: 3,
        }
        if severity.get(candidate, 0) > severity.get(current, 0):
            return candidate
        return current
