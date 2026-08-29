"""Tests for the Data Quality Layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eigencapital.core.data_quality import (
    DataQualityAssessor,
    DimensionStatus,
    QualityGrade,
    QualityResult,
    QualityThresholds,
)


class TestQualityGrade:
    """Test QualityGrade enum."""

    def test_grades_defined(self) -> None:
        assert QualityGrade.GOOD.value == "GOOD"
        assert QualityGrade.DEGRADED.value == "DEGRADED"
        assert QualityGrade.POOR.value == "POOR"
        assert QualityGrade.UNKNOWN.value == "UNKNOWN"


class TestDimensionStatus:
    """Test DimensionStatus enum."""

    def test_statuses_defined(self) -> None:
        assert DimensionStatus.PASS.value == "PASS"
        assert DimensionStatus.WARN.value == "WARN"
        assert DimensionStatus.FAIL.value == "FAIL"
        assert DimensionStatus.SKIP.value == "SKIP"


class TestFreshnessDimension:
    """Test freshness dimension of quality assessment."""

    def test_fresh_data(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=5),
            now=now,
        )
        dim = result.dimensions[0]
        assert dim.dimension == "freshness"
        assert dim.status == DimensionStatus.PASS
        assert dim.score == 1.0

    def test_approaching_stale(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=60),
            now=now,
        )
        dim = result.dimensions[0]
        assert dim.dimension == "freshness"
        assert dim.status == DimensionStatus.WARN

    def test_stale_data(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=300),
            now=now,
        )
        dim = result.dimensions[0]
        assert dim.dimension == "freshness"
        assert dim.status == DimensionStatus.FAIL
        assert dim.score == 0.0

    def test_no_timestamp(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(price_timestamp=None)
        dim = result.dimensions[0]
        assert dim.status == DimensionStatus.FAIL
        assert "No timestamp" in dim.message


class TestCompletenessDimension:
    """Test completeness dimension."""

    def test_all_fields_present(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(bid=1.085, ask=1.086, mid=1.0855, volume=100)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["completeness"].status == DimensionStatus.PASS
        assert dims["completeness"].score == 1.0

    def test_one_missing(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(bid=1.085, ask=1.086, mid=None, volume=100)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["completeness"].status == DimensionStatus.WARN
        assert "mid" in dims["completeness"].message

    def test_multiple_missing(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(bid=None, ask=None, mid=None, volume=None)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["completeness"].status == DimensionStatus.FAIL


class TestSpreadDimension:
    """Test spread quality dimension."""

    def test_normal_spread(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=1.085, ask=1.0855, expected_spread_max=0.001
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["spread"].status == DimensionStatus.PASS

    def test_elevated_spread(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=1.085, ask=1.087, expected_spread_max=0.001
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["spread"].status == DimensionStatus.WARN

    def test_excessive_spread(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=1.085, ask=1.090, expected_spread_max=0.001
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["spread"].status == DimensionStatus.FAIL

    def test_negative_spread(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=1.090, ask=1.085, expected_spread_max=0.001
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["spread"].status == DimensionStatus.FAIL


class TestPlausibilityDimension:
    """Test price plausibility dimension."""

    def test_price_in_range(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=1.085, ask=1.086, price_low=0.5, price_high=2.0
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["plausibility"].status == DimensionStatus.PASS

    def test_price_too_low(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=0.1, ask=0.2, price_low=0.5, price_high=2.0
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["plausibility"].status == DimensionStatus.FAIL

    def test_price_too_high(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            bid=5.0, ask=5.1, price_low=0.5, price_high=2.0
        )
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["plausibility"].status == DimensionStatus.FAIL


class TestTimestampIntegrity:
    """Test timestamp integrity dimension."""

    def test_monotonic_timestamps(self) -> None:
        base = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        timestamps = [base + timedelta(seconds=i * 5) for i in range(5)]
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(recent_timestamps=timestamps)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["timestamp_integrity"].status == DimensionStatus.PASS

    def test_out_of_order_timestamps(self) -> None:
        base = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        timestamps = [
            base,
            base + timedelta(seconds=5),
            base + timedelta(seconds=2),  # out of order
            base + timedelta(seconds=10),
        ]
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(recent_timestamps=timestamps)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["timestamp_integrity"].status == DimensionStatus.WARN

    def test_single_timestamp_skipped(self) -> None:
        base = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(recent_timestamps=[base])
        # Single timestamp — timestamp_integrity dimension is not added (< 2 timestamps)
        dim_names = [d.dimension for d in result.dimensions]
        assert "timestamp_integrity" not in dim_names


class TestSourceConsistency:
    """Test source consistency dimension."""

    def test_source_matches(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(expected_source="MT5", actual_source="MT5")
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["source_consistency"].status == DimensionStatus.PASS

    def test_source_mismatch(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(expected_source="MT5", actual_source="OTHER")
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["source_consistency"].status == DimensionStatus.FAIL


class TestContinuityDimension:
    """Test continuity dimension."""

    def test_regular_timestamps(self) -> None:
        base = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        timestamps = [base + timedelta(seconds=i * 5) for i in range(10)]
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(recent_timestamps=timestamps)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["continuity"].status == DimensionStatus.PASS

    def test_gap_in_timestamps(self) -> None:
        base = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        timestamps = [
            base,
            base + timedelta(seconds=5),
            base + timedelta(seconds=10),
            base + timedelta(seconds=60),  # big gap
            base + timedelta(seconds=65),
        ]
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(recent_timestamps=timestamps)
        dims = {d.dimension: d for d in result.dimensions}
        assert dims["continuity"].status == DimensionStatus.WARN


class TestOverallGrade:
    """Test overall grade computation."""

    def test_all_pass(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=datetime.now(UTC),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
        )
        assert result.overall == QualityGrade.GOOD
        assert result.is_good is True
        assert result.score > 50

    def test_freshness_fail_overall_poor(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=300),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            now=now,
        )
        assert result.overall == QualityGrade.POOR

    def test_no_timestamps_only_skips(self) -> None:
        """With no timestamps, continuity and timestamp_integrity are skipped."""
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(price_timestamp=datetime.now(UTC))
        dim_names = [d.dimension for d in result.dimensions]
        assert "continuity" not in dim_names
        assert "timestamp_integrity" not in dim_names

    def test_failing_dimensions_list(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=300),
            bid=None,
            ask=None,
            mid=None,
            volume=None,
            now=now,
        )
        assert len(result.failing_dimensions) > 0

    def test_warning_dimensions_list(self) -> None:
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=now - timedelta(seconds=60),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            now=now,
        )
        assert len(result.warning_dimensions) > 0

    def test_to_dict(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(
            price_timestamp=datetime.now(UTC),
            bid=1.085,
            ask=1.086,
        )
        d = result.to_dict()
        assert d["instrument"] == "EURUSD"
        assert "dimensions" in d
        assert "overall" in d
        assert "score" in d


class TestQualityThresholds:
    """Test per-asset-class quality thresholds."""

    def test_fx_major(self) -> None:
        t = QualityThresholds.for_asset_class("forex")
        assert t["freshness_warn_seconds"] == 30.0

    def test_crypto(self) -> None:
        t = QualityThresholds.for_asset_class("crypto")
        assert t["max_spread_ratio"] == 50.0

    def test_unknown_defaults_to_fx(self) -> None:
        t = QualityThresholds.for_asset_class("unknown")
        assert t["freshness_warn_seconds"] == 30.0


class TestQualityResultProperties:
    """Test QualityResult helper properties."""

    def test_dimension_status_lookup(self) -> None:
        assessor = DataQualityAssessor("EURUSD")
        result = assessor.assess(price_timestamp=datetime.now(UTC))
        # freshness should be PASS
        assert result.dimension_status("freshness") == DimensionStatus.PASS
        # nonexistent should be SKIP
        assert result.dimension_status("nonexistent") == DimensionStatus.SKIP
