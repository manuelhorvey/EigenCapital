"""Data Quality Layer — unified quality assessment for all market data.

Produces a per-instrument quality score across multiple dimensions:
- Freshness: Is data recent?
- Completeness: Are all expected fields present?
- Continuity: Are there gaps in the time series?
- Spread: Is the bid-ask spread within normal bounds?
- Plausibility: Are prices within expected ranges?
- Timestamp integrity: Are timestamps monotonically increasing?
- Source consistency: Does data come from the expected source?

Design rules:
- Bad data can make a perfectly correct strategy behave incorrectly.
- Data quality must be an explicit, measurable concept — not an assumption.
- Each dimension produces a PASS/WARN/FAIL status.
- The overall score is the weighted sum of all dimensions.
- Quality assessment is additive — new dimensions can be added without breaking existing ones.

Integration:
    quality = DataQualityAssessor("EURUSD")
    result = quality.assess(snapshot=latest_tick, schedule=market_schedule)
    if result.overall != QualityGrade.GOOD:
        alert(f"Data quality degraded for EURUSD: {result.overall}")

    # Dashboard consumption
    dashboard_data["eurusd"]["data_quality"] = result.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Tuple

# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════


class QualityGrade(str, Enum):
    """Overall data quality grade."""

    GOOD = "GOOD"  # All dimensions pass
    DEGRADED = "DEGRADED"  # Some dimensions warn
    POOR = "POOR"  # At least one dimension fails
    UNKNOWN = "UNKNOWN"  # Cannot assess


class DimensionStatus(str, Enum):
    """Status of a single quality dimension."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"  # Dimension not applicable


class ExpectedDataState(str, Enum):
    """Whether missing/stale data is expected given market state.

    This is the critical bridge between MarketSchedule and DataQuality:
    Market CLOSED + No tick  → EXPECTED_MISSING → No alert
    Market OPEN   + No tick  → UNEXPECTED_MISSING → Alert
    Market OPEN   + Stale    → UNEXPECTED_STALE → Risk observation
    """

    EXPECTED = "EXPECTED"  # Data state matches market expectation
    EXPECTED_MISSING = "EXPECTED_MISSING"  # Market closed/maintenance — no data expected
    EXPECTED_STALE = "EXPECTED_STALE"  # Market closing/closed — stale data expected
    UNEXPECTED_MISSING = "UNEXPECTED_MISSING"  # Market open but data missing — problem
    UNEXPECTED_STALE = "UNEXPECTED_STALE"  # Market open but data stale — problem


# ═══════════════════════════════════════════════════════════════════
# Dimension Result
# ═══════════════════════════════════════════════════════════════════


@dataclass
class DimensionResult:
    """Result of a single quality dimension assessment."""

    dimension: str
    status: DimensionStatus
    score: float  # 0.0 = worst, 1.0 = best
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status.value,
            "score": round(self.score, 3),
            "message": self.message,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════════
# Quality Result
# ═══════════════════════════════════════════════════════════════════


@dataclass
class QualityResult:
    """Complete data quality assessment for an instrument."""

    instrument: str
    timestamp: datetime
    overall: QualityGrade
    score: float  # 0-100
    dimensions: List[DimensionResult] = field(default_factory=list)
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_good(self) -> bool:
        return self.overall == QualityGrade.GOOD

    @property
    def failing_dimensions(self) -> List[DimensionResult]:
        return [d for d in self.dimensions if d.status == DimensionStatus.FAIL]

    @property
    def warning_dimensions(self) -> List[DimensionResult]:
        return [d for d in self.dimensions if d.status == DimensionStatus.WARN]

    def dimension_status(self, name: str) -> DimensionStatus:
        """Get the status of a specific dimension."""
        for d in self.dimensions:
            if d.dimension == name:
                return d.status
        return DimensionStatus.SKIP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument": self.instrument,
            "timestamp": self.timestamp.isoformat(),
            "overall": self.overall.value,
            "score": round(self.score, 1),
            "source": self.source,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "failing": [d.dimension for d in self.failing_dimensions],
            "warning": [d.dimension for d in self.warning_dimensions],
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════
# Quality Assessor
# ═══════════════════════════════════════════════════════════════════


class DataQualityAssessor:
    """Unified data quality assessment for a single instrument.

    Usage:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=last_tick_time,
            bid=1.0850,
            ask=1.0852,
            mid=1.0851,
            volume=1000,
            expected_spread_max=0.0005,
            price_low=0.5,
            price_high=2.0,
            recent_timestamps=[...],
            expected_source="MT5",
            actual_source="MT5",
        )
    """

    def __init__(
        self,
        instrument: str,
        *,
        thresholds: Dict[str, Any] | None = None,
        asset_class: str | None = None,
    ) -> None:
        """Initialize assessor for an instrument.

        Freshness tolerances default to 30s (warn) / 120s (fail) but can be
        overridden per instrument via ``thresholds`` (QualityThresholds-style
        dict) or by asset class (looked up in QualityThresholds).
        """
        self.instrument = instrument
        if thresholds is None and asset_class is not None:
            thresholds = QualityThresholds.for_asset_class(asset_class)
        thresholds = thresholds or {}
        self._freshness_warn_seconds = float(thresholds.get("freshness_warn_seconds", 30.0))
        self._freshness_fail_seconds = float(thresholds.get("freshness_fail_seconds", 120.0))

    def assess(
        self,
        price_timestamp: datetime | None = None,
        bid: float | None = None,
        ask: float | None = None,
        mid: float | None = None,
        volume: float | None = None,
        expected_spread_max: float | None = None,
        price_low: float | None = None,
        price_high: float | None = None,
        recent_timestamps: List[datetime] | None = None,
        expected_source: str | None = None,
        actual_source: str | None = None,
        now: datetime | None = None,
    ) -> QualityResult:
        """Run all quality dimensions and produce a result."""
        now = now or datetime.now(UTC)
        dimensions: List[DimensionResult] = []

        # 1. Freshness
        dimensions.append(
            self._check_freshness(
                price_timestamp,
                now,
                warn_seconds=self._freshness_warn_seconds,
                fail_seconds=self._freshness_fail_seconds,
            )
        )

        # 2. Completeness
        dimensions.append(self._check_completeness(bid, ask, mid, volume))

        # 3. Spread quality
        if bid is not None and ask is not None and expected_spread_max is not None:
            dimensions.append(self._check_spread(bid, ask, expected_spread_max))

        # 4. Price plausibility
        price = mid or (bid if bid is not None else ask)
        if price is not None and price_low is not None and price_high is not None:
            dimensions.append(self._check_plausibility(price, price_low, price_high))

        # 5. Timestamp integrity
        if recent_timestamps and len(recent_timestamps) >= 2:
            dimensions.append(self._check_timestamp_integrity(recent_timestamps))

        # 6. Source consistency
        if expected_source is not None and actual_source is not None:
            dimensions.append(self._check_source_consistency(expected_source, actual_source))

        # 7. Continuity (if we have timestamps)
        if recent_timestamps and len(recent_timestamps) >= 2:
            dimensions.append(self._check_continuity(recent_timestamps))

        # Compute overall
        overall, score = self._compute_overall(dimensions)

        return QualityResult(
            instrument=self.instrument,
            timestamp=now,
            overall=overall,
            score=score,
            dimensions=dimensions,
            source=actual_source or "",
        )

    def _check_freshness(
        self,
        ts: datetime | None,
        now: datetime,
        warn_seconds: float = 30.0,
        fail_seconds: float = 120.0,
    ) -> DimensionResult:
        """Is data recent?

        Thresholds default to 30s (warn) / 120s (fail) and are overridable
        per instrument (Q9) — see __init__ thresholds/asset_class args.
        """
        if ts is None:
            return DimensionResult(
                dimension="freshness",
                status=DimensionStatus.FAIL,
                score=0.0,
                message="No timestamp available",
            )

        age = (now - ts).total_seconds()

        if age < warn_seconds:
            return DimensionResult(
                dimension="freshness",
                status=DimensionStatus.PASS,
                score=1.0,
                message=f"Data is {age:.0f}s old",
                details={"age_seconds": age},
            )
        elif age < fail_seconds:
            score = max(0.0, 1.0 - (age - warn_seconds) / max(fail_seconds - warn_seconds, 1.0))
            return DimensionResult(
                dimension="freshness",
                status=DimensionStatus.WARN,
                score=score,
                message=f"Data is {age:.0f}s old (approaching stale)",
                details={"age_seconds": age},
            )
        else:
            return DimensionResult(
                dimension="freshness",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Data is stale ({age:.0f}s old)",
                details={"age_seconds": age},
            )

    def _check_completeness(
        self,
        bid: float | None,
        ask: float | None,
        mid: float | None,
        volume: float | None,
    ) -> DimensionResult:
        """Are all expected fields present?"""
        fields = {"bid": bid, "ask": ask, "mid": mid, "volume": volume}
        present = sum(1 for v in fields.values() if v is not None)
        total = len(fields)

        if present == total:
            return DimensionResult(
                dimension="completeness",
                status=DimensionStatus.PASS,
                score=1.0,
                message=f"All {total} fields present",
            )
        elif present >= total - 1:
            missing = [k for k, v in fields.items() if v is None]
            return DimensionResult(
                dimension="completeness",
                status=DimensionStatus.WARN,
                score=present / total,
                message=f"Missing: {', '.join(missing)}",
                details={"missing": missing},
            )
        else:
            missing = [k for k, v in fields.items() if v is None]
            return DimensionResult(
                dimension="completeness",
                status=DimensionStatus.FAIL,
                score=present / total,
                message=f"Multiple missing: {', '.join(missing)}",
                details={"missing": missing},
            )

    def _check_spread(self, bid: float, ask: float, max_spread: float) -> DimensionResult:
        """Is the bid-ask spread within normal bounds?"""
        spread = ask - bid
        if spread < 0:
            return DimensionResult(
                dimension="spread",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Negative spread ({spread:.6f})",
                details={"spread": spread},
            )

        ratio = spread / max_spread if max_spread > 0 else float("inf")

        if ratio <= 1.0:
            return DimensionResult(
                dimension="spread",
                status=DimensionStatus.PASS,
                score=1.0 - ratio * 0.3,  # 0.7-1.0 score
                message=f"Spread {spread:.6f} within limit ({max_spread:.6f})",
                details={"spread": spread, "max_spread": max_spread, "ratio": ratio},
            )
        elif ratio <= 3.0:
            return DimensionResult(
                dimension="spread",
                status=DimensionStatus.WARN,
                score=max(0.3, 1.0 - ratio * 0.2),
                message=f"Spread {spread:.6f} elevated (limit: {max_spread:.6f})",
                details={"spread": spread, "max_spread": max_spread, "ratio": ratio},
            )
        else:
            return DimensionResult(
                dimension="spread",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Spread {spread:.6f} excessive (limit: {max_spread:.6f})",
                details={"spread": spread, "max_spread": max_spread, "ratio": ratio},
            )

    def _check_plausibility(self, price: float, low: float, high: float) -> DimensionResult:
        """Is the price within expected bounds?"""
        if price < low:
            return DimensionResult(
                dimension="plausibility",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Price {price} below minimum {low}",
                details={"price": price, "low": low, "high": high},
            )
        if price > high:
            return DimensionResult(
                dimension="plausibility",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Price {price} above maximum {high}",
                details={"price": price, "low": low, "high": high},
            )

        # Score based on distance from boundaries
        range_size = high - low
        if range_size > 0:
            margin = min(price - low, high - price) / range_size
            score = 0.5 + 0.5 * min(margin * 4, 1.0)  # 0.5-1.0
        else:
            score = 1.0

        return DimensionResult(
            dimension="plausibility",
            status=DimensionStatus.PASS,
            score=score,
            message=f"Price {price} within [{low}, {high}]",
            details={"price": price, "low": low, "high": high},
        )

    def _check_timestamp_integrity(self, timestamps: List[datetime]) -> DimensionResult:
        """Are timestamps monotonically increasing?"""
        if len(timestamps) < 2:
            return DimensionResult(
                dimension="timestamp_integrity",
                status=DimensionStatus.SKIP,
                score=1.0,
                message="Insufficient timestamps for check",
            )

        violations = 0
        for i in range(1, len(timestamps)):
            if timestamps[i] < timestamps[i - 1]:
                violations += 1

        if violations == 0:
            return DimensionResult(
                dimension="timestamp_integrity",
                status=DimensionStatus.PASS,
                score=1.0,
                message="Timestamps monotonically increasing",
            )
        elif violations <= 2:
            return DimensionResult(
                dimension="timestamp_integrity",
                status=DimensionStatus.WARN,
                score=max(0.3, 1.0 - violations / len(timestamps)),
                message=f"{violations} timestamp order violations",
                details={"violations": violations, "total": len(timestamps)},
            )
        else:
            return DimensionResult(
                dimension="timestamp_integrity",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Severe timestamp disorder ({violations} violations)",
                details={"violations": violations, "total": len(timestamps)},
            )

    def _check_source_consistency(self, expected: str, actual: str) -> DimensionResult:
        """Does data come from the expected source?"""
        if expected == actual:
            return DimensionResult(
                dimension="source_consistency",
                status=DimensionStatus.PASS,
                score=1.0,
                message=f"Source matches expected ({actual})",
            )
        else:
            return DimensionResult(
                dimension="source_consistency",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Source mismatch: expected {expected}, got {actual}",
                details={"expected": expected, "actual": actual},
            )

    def _check_continuity(self, timestamps: List[datetime]) -> DimensionResult:
        """Are there gaps in the time series?"""
        if len(timestamps) < 2:
            return DimensionResult(
                dimension="continuity",
                status=DimensionStatus.SKIP,
                score=1.0,
                message="Insufficient timestamps for check",
            )

        # Avoid re-sorting when input is already monotonic (P2) — the
        # timestamp_integrity dimension already scans the same list.
        if all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1)):
            sorted_ts = timestamps
        else:
            sorted_ts = sorted(timestamps)
        gaps: List[float] = []
        for i in range(1, len(sorted_ts)):
            gap = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds()
            gaps.append(gap)

        if not gaps:
            return DimensionResult(
                dimension="continuity",
                status=DimensionStatus.PASS,
                score=1.0,
                message="No gaps detected",
            )

        max_gap = max(gaps)
        avg_gap = sum(gaps) / len(gaps)

        # A gap is "large" if it's more than 3x the average
        large_gaps = sum(1 for g in gaps if g > avg_gap * 3) if avg_gap > 0 else 0

        if large_gaps == 0:
            return DimensionResult(
                dimension="continuity",
                status=DimensionStatus.PASS,
                score=1.0,
                message=f"No significant gaps (max: {max_gap:.0f}s)",
                details={"max_gap_seconds": max_gap, "avg_gap_seconds": avg_gap},
            )
        elif large_gaps <= 1:
            return DimensionResult(
                dimension="continuity",
                status=DimensionStatus.WARN,
                score=max(0.4, 1.0 - large_gaps / len(gaps)),
                message=f"{large_gaps} gap(s) detected (max: {max_gap:.0f}s)",
                details={
                    "max_gap_seconds": max_gap,
                    "avg_gap_seconds": avg_gap,
                    "large_gaps": large_gaps,
                },
            )
        else:
            return DimensionResult(
                dimension="continuity",
                status=DimensionStatus.FAIL,
                score=0.0,
                message=f"Multiple gaps detected ({large_gaps} large gaps)",
                details={
                    "max_gap_seconds": max_gap,
                    "avg_gap_seconds": avg_gap,
                    "large_gaps": large_gaps,
                },
            )

    def _compute_overall(self, dimensions: List[DimensionResult]) -> Tuple[QualityGrade, float]:
        """Compute overall grade and score from dimensions."""
        if not dimensions:
            return QualityGrade.UNKNOWN, 0.0

        # Filter out SKIP dimensions
        active = [d for d in dimensions if d.status != DimensionStatus.SKIP]
        if not active:
            return QualityGrade.UNKNOWN, 0.0

        # Check for any FAIL
        has_fail = any(d.status == DimensionStatus.FAIL for d in active)
        has_warn = any(d.status == DimensionStatus.WARN for d in active)

        # Weighted average score
        total_score = sum(d.score for d in active)
        avg_score = total_score / len(active)
        pct = avg_score * 100

        if has_fail:
            grade = QualityGrade.POOR
        elif has_warn:
            grade = QualityGrade.DEGRADED
        else:
            grade = QualityGrade.GOOD

        return grade, pct


# ═══════════════════════════════════════════════════════════════════
# Platform-wide quality thresholds
# ═══════════════════════════════════════════════════════════════════


class QualityThresholds:
    """Default quality thresholds per asset class.

    These can be overridden per instrument via config.
    """

    # FX majors — tight spread tolerance
    FX_MAJOR = {
        "freshness_warn_seconds": 30.0,
        "freshness_fail_seconds": 120.0,
        "max_spread_ratio": 1.5,  # 1.5 pips
        "expected_completeness": 4,  # bid, ask, mid, volume
    }

    # FX crosses — moderate spread
    FX_CROSS = {
        "freshness_warn_seconds": 30.0,
        "freshness_fail_seconds": 120.0,
        "max_spread_ratio": 3.0,
        "expected_completeness": 4,
    }

    # Metals
    METALS = {
        "freshness_warn_seconds": 60.0,
        "freshness_fail_seconds": 300.0,
        "max_spread_ratio": 5.0,
        "expected_completeness": 4,
    }

    # Crypto — wider tolerance (24/7, variable liquidity)
    CRYPTO = {
        "freshness_warn_seconds": 30.0,
        "freshness_fail_seconds": 120.0,
        "max_spread_ratio": 50.0,
        "expected_completeness": 4,
    }

    # Indices
    INDICES = {
        "freshness_warn_seconds": 30.0,
        "freshness_fail_seconds": 120.0,
        "max_spread_ratio": 5.0,
        "expected_completeness": 4,
    }

    @classmethod
    def for_asset_class(cls, asset_class: str) -> Dict[str, Any]:
        """Get thresholds for an asset class."""
        mapping = {
            "forex": cls.FX_MAJOR,
            "forex_excluded": cls.FX_CROSS,
            "metals": cls.METALS,
            "crypto": cls.CRYPTO,
            "indices": cls.INDICES,
            "energy": cls.METALS,
        }
        return mapping.get(asset_class, cls.FX_MAJOR)


# ═══════════════════════════════════════════════════════════════════
# MarketDataBridge — connects MarketSchedule to DataQuality
# ═══════════════════════════════════════════════════════════════════


class MarketDataBridge:
    """Bridge between MarketSchedule and DataQuality.

    This is the critical integration point:
    - MarketSchedule explains whether data absence is EXPECTED
    - DataQuality determines whether received data is TRUSTWORTHY
    - Together they produce ExpectedDataState for downstream consumers

    Usage:
        from eigencapital.core.market_schedule import MarketSchedule
        bridge = MarketDataBridge(schedule)
        result = bridge.assess(
            price_timestamp=last_tick_time,
            bid=1.085,
            ask=1.086,
        )
        if result.expected_data == ExpectedDataState.UNEXPECTED_MISSING:
            alert(f"Market is open but data is missing for {instrument}")
    """

    def __init__(self, schedule: Any) -> None:
        """Initialize with a MarketSchedule instance."""
        self.schedule = schedule
        self.instrument = schedule.instrument
        self._assessor = DataQualityAssessor(self.instrument)

    def assess(
        self,
        price_timestamp: datetime | None = None,
        bid: float | None = None,
        ask: float | None = None,
        mid: float | None = None,
        volume: float | None = None,
        expected_spread_max: float | None = None,
        price_low: float | None = None,
        price_high: float | None = None,
        recent_timestamps: List[datetime] | None = None,
        expected_source: str | None = None,
        actual_source: str | None = None,
        broker_connected: bool = True,
        now: datetime | None = None,
    ) -> BridgeResult:
        """Assess data quality with market-context awareness.

        Returns a BridgeResult that includes:
        - The standard QualityResult (dimensions, score, grade)
        - ExpectedDataState (is missing data expected given market state?)
        - MarketContext (market availability state)
        """
        now = now or datetime.now(UTC)

        # Step 1: Determine market state
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        market_open = self.schedule.is_market_open(now)

        market_availability = MarketAvailability.OPEN if market_open else MarketAvailability.CLOSED

        broker_avail = BrokerAvailability.CONNECTED if broker_connected else BrokerAvailability.DISCONNECTED

        # Step 2: Determine expected data state
        expected = self._determine_expected_state(
            market_open=market_open,
            price_timestamp=price_timestamp,
            now=now,
        )

        # Step 3: Run quality assessment (skip freshness FAIL if data is expected to be missing)
        quality_result = self._assessor.assess(
            price_timestamp=price_timestamp,
            bid=bid,
            ask=ask,
            mid=mid,
            volume=volume,
            expected_spread_max=expected_spread_max,
            price_low=price_low,
            price_high=price_high,
            recent_timestamps=recent_timestamps,
            expected_source=expected_source,
            actual_source=actual_source,
            now=now,
        )

        # Step 4: Override freshness grade if data absence is expected
        if expected in (
            ExpectedDataState.EXPECTED_MISSING,
            ExpectedDataState.EXPECTED_STALE,
        ):
            # Don't let expected absence degrade quality
            quality_result = self._adjust_for_expected_absence(quality_result, expected)

        # Step 5: Determine truth level

        truth_level = self._determine_truth_level(
            quality_result=quality_result,
            expected=expected,
            market_open=market_open,
            broker_connected=broker_connected,
        )

        # Step 6: Build market state
        data_avail = self._determine_data_availability(
            price_timestamp=price_timestamp,
            now=now,
            expected=expected,
        )

        market_state = MarketState(
            instrument=self.instrument,
            market=market_availability,
            data=data_avail,
            broker=broker_avail,
            strategy=StrategyEligibility.ELIGIBLE if market_open else StrategyEligibility.SUPPRESSED,
            authorization="TRADING_AUTHORIZED" if market_open else "MARKET_CLOSED",
            timestamp=now.isoformat(),
        )

        return BridgeResult(
            instrument=self.instrument,
            timestamp=now,
            quality=quality_result,
            expected_data=expected,
            truth_level=truth_level,
            market_state=market_state,
            market_open=market_open,
            next_open=self.schedule.next_open(now),
            next_close=self.schedule.next_close(now),
            next_maintenance=self.schedule.next_maintenance(now),
        )

    def _determine_expected_state(
        self,
        market_open: bool,
        price_timestamp: datetime | None,
        now: datetime,
    ) -> ExpectedDataState:
        """Determine whether the current data state is expected."""
        if market_open:
            # Market is open — data should be fresh
            if price_timestamp is None:
                return ExpectedDataState.UNEXPECTED_MISSING
            age = (now - price_timestamp).total_seconds()
            if age > 120:
                return ExpectedDataState.UNEXPECTED_STALE
            if age > 60:
                return ExpectedDataState.EXPECTED_STALE  # Approaching stale
            return ExpectedDataState.EXPECTED
        else:
            # Market is closed — missing data is expected
            # The market being closed is the primary fact; data presence
            # is incidental (cached/stale) and doesn't change expectation.
            return ExpectedDataState.EXPECTED_MISSING

    def _determine_data_availability(
        self,
        price_timestamp: datetime | None,
        now: datetime,
        expected: ExpectedDataState,
    ) -> Any:
        """Determine DataAvailability from timestamp and expected state."""
        from eigencapital.core.market_schedule import DataAvailability

        if price_timestamp is None:
            if expected == ExpectedDataState.EXPECTED_MISSING:
                return DataAvailability.MISSING  # Expected
            return DataAvailability.MISSING

        age = (now - price_timestamp).total_seconds()
        if age < 120:
            return DataAvailability.FRESH
        if age < 300:
            return DataAvailability.STALE
        return DataAvailability.MISSING

    def _determine_truth_level(
        self,
        quality_result: QualityResult,
        expected: ExpectedDataState,
        market_open: bool,
        broker_connected: bool,
    ) -> Any:
        """Determine TruthLevel from quality and market context."""
        from eigencapital.core.data_truth import TruthLevel

        if expected == ExpectedDataState.EXPECTED_MISSING:
            # Market closed, no data — not a truth failure
            return TruthLevel.UNAVAILABLE
        if expected == ExpectedDataState.EXPECTED_STALE:
            return TruthLevel.STALE
        if expected == ExpectedDataState.UNEXPECTED_MISSING:
            return TruthLevel.UNAVAILABLE
        if expected == ExpectedDataState.UNEXPECTED_STALE:
            return TruthLevel.STALE

        # Data is present and expected
        if not broker_connected:
            return TruthLevel.UNAVAILABLE
        if quality_result.overall == QualityGrade.GOOD:
            return TruthLevel.AUTHORITATIVE
        if quality_result.overall == QualityGrade.DEGRADED:
            return TruthLevel.AUTHORITATIVE  # Still authoritative, just degraded
        if quality_result.overall == QualityGrade.POOR:
            return TruthLevel.CORRUPT
        return TruthLevel.UNKNOWN

    def _adjust_for_expected_absence(
        self,
        result: QualityResult,
        expected: ExpectedDataState,
    ) -> QualityResult:
        """Adjust quality result when data absence is expected.

        When market is closed or in maintenance, missing/stale data
        should not degrade the quality score. The overall grade becomes
        DEGRADED (informational) rather than POOR (operational failure).
        """
        # Mark freshness dimension as SKIP (expected, not a failure)
        adjusted_dims = []
        for dim in result.dimensions:
            if dim.dimension == "freshness" and dim.status == DimensionStatus.FAIL:
                adjusted_dims.append(
                    DimensionResult(
                        dimension="freshness",
                        status=DimensionStatus.SKIP,
                        score=1.0,
                        message=f"Data absent as expected ({expected.value})",
                        details={"expected_state": expected.value},
                    )
                )
            elif dim.dimension == "completeness" and dim.status in (
                DimensionStatus.FAIL,
                DimensionStatus.WARN,
            ):
                adjusted_dims.append(
                    DimensionResult(
                        dimension="completeness",
                        status=DimensionStatus.SKIP,
                        score=1.0,
                        message=f"Completeness not evaluated ({expected.value})",
                        details={"expected_state": expected.value},
                    )
                )
            else:
                adjusted_dims.append(dim)

        # Recompute overall
        overall, score = self._assessor._compute_overall(adjusted_dims)

        return QualityResult(
            instrument=result.instrument,
            timestamp=result.timestamp,
            overall=overall,
            score=score,
            dimensions=adjusted_dims,
            source=result.source,
            metadata={**result.metadata, "expected_data": expected.value},
        )


@dataclass
class BridgeResult:
    """Result of a MarketDataBridge assessment.

    Combines quality assessment with market context to produce
    a complete picture of instrument data health.
    """

    instrument: str
    timestamp: datetime
    quality: QualityResult
    expected_data: ExpectedDataState
    truth_level: Any  # TruthLevel from data_truth module
    market_state: Any  # MarketState from market_schedule module
    market_open: bool
    next_open: datetime
    next_close: datetime
    next_maintenance: datetime | None

    @property
    def is_data_trustworthy(self) -> bool:
        """Is the data trustworthy for trading decisions?"""
        return (
            self.expected_data == ExpectedDataState.EXPECTED
            and self.quality.overall in (QualityGrade.GOOD, QualityGrade.DEGRADED)
            and self.market_open
        )

    @property
    def trading_blocked_reason(self) -> str | None:
        """Why is trading blocked, if at all?"""
        if self.is_data_trustworthy:
            return None
        if not self.market_open:
            return f"Market closed (next open: {self.next_open.strftime('%Y-%m-%d %H:%M UTC')})"
        if self.expected_data == ExpectedDataState.UNEXPECTED_MISSING:
            return "Market open but data missing"
        if self.expected_data == ExpectedDataState.UNEXPECTED_STALE:
            return "Market open but data stale"
        if self.quality.overall == QualityGrade.POOR:
            failing = [d.dimension for d in self.quality.failing_dimensions]
            return f"Data quality poor: {', '.join(failing)}"
        return "Data not available"

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "instrument": self.instrument,
            "timestamp": self.timestamp.isoformat(),
            "quality": self.quality.to_dict(),
            "expected_data": self.expected_data.value,
            "truth_level": (self.truth_level.value if hasattr(self.truth_level, "value") else str(self.truth_level)),
            "market_state": (
                self.market_state.to_dict() if hasattr(self.market_state, "to_dict") else str(self.market_state)
            ),
            "market_open": self.market_open,
            "is_data_trustworthy": self.is_data_trustworthy,
            "trading_blocked_reason": self.trading_blocked_reason,
            "next_open": self.next_open.isoformat(),
            "next_close": self.next_close.isoformat(),
            "next_maintenance": (self.next_maintenance.isoformat() if self.next_maintenance else None),
        }
