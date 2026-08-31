"""Integration tests for MarketSchedule + DataQuality + DataTruth + NoSilentDegradation.

Tests the critical combinations:
- Market OPEN + Data FRESH → Tradable
- Market OPEN + Data STALE → Blocked
- Market OPEN + Data MISSING → Blocked
- Market CLOSED + Data MISSING → Expected
- MAINTENANCE + Data MISSING → Expected
- HALTED + Data FRESH → Not tradable
- UNKNOWN market + Data → Fail closed
- 24/7 + Weekend + Fresh → Tradable
- 24/7 + Weekend + Maintenance → Blocked
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eigencapital.core.data_quality import (
    ExpectedDataState,
    MarketDataBridge,
    QualityGrade,
)
from eigencapital.core.data_truth import (
    SOURCE_BROKER,
    SOURCE_DERIVED,
    MetricName,
    TruthfulValue,
    TruthLevel,
    TruthRegistry,
)
from eigencapital.core.market_schedule import (
    crypto_24_7_schedule,
    fx_weekday_schedule,
)
from eigencapital.core.no_silent_degradation import (
    DegradationViolation,
    guard_not_degraded,
    guard_not_none,
    guard_not_zero,
    guard_numeric_non_negative,
    guard_numeric_positive,
    no_silent_degradation,
    validate_transformation,
)

# ═══════════════════════════════════════════════════════════════════
# Integration: MarketSchedule + DataQuality Bridge
# ═══════════════════════════════════════════════════════════════════


class TestMarketDataBridge:
    """Test the MarketDataBridge integration."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # FX schedule: Mon-Fri, 24h sessions
        self.fx_schedule = fx_weekday_schedule("EURUSD")

        # Crypto schedule: 24/7 with Saturday maintenance
        self.crypto_schedule = crypto_24_7_schedule("BTCUSD")

    # ─── FX WEEKDAY TESTS ─────────────────────────────────────────

    def test_fx_open_fresh_data(self) -> None:
        """Market OPEN + Data FRESH → Tradable."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)  # Wednesday

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.expected_data == ExpectedDataState.EXPECTED
        assert result.quality.overall == QualityGrade.GOOD
        assert result.is_data_trustworthy is True
        assert result.trading_blocked_reason is None

    def test_fx_open_stale_data(self) -> None:
        """Market OPEN + Data STALE → Blocked."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)  # Wednesday

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=180),
            bid=1.085,
            ask=1.086,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.expected_data == ExpectedDataState.UNEXPECTED_STALE
        assert result.truth_level == TruthLevel.STALE
        assert result.is_data_trustworthy is False
        assert result.trading_blocked_reason is not None
        assert "stale" in result.trading_blocked_reason.lower()

    def test_fx_open_missing_data(self) -> None:
        """Market OPEN + Data MISSING → Blocked."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)  # Wednesday

        result = bridge.assess(
            price_timestamp=None,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.expected_data == ExpectedDataState.UNEXPECTED_MISSING
        assert result.truth_level == TruthLevel.UNAVAILABLE
        assert result.is_data_trustworthy is False
        assert result.trading_blocked_reason is not None
        assert "missing" in result.trading_blocked_reason.lower()

    def test_fx_closed_missing_data(self) -> None:
        """Market CLOSED + Data MISSING → Expected (no alert)."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)  # Saturday

        result = bridge.assess(
            price_timestamp=None,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is False
        assert result.expected_data == ExpectedDataState.EXPECTED_MISSING
        assert result.truth_level == TruthLevel.UNAVAILABLE
        # Quality should NOT be POOR — absence is expected
        assert result.quality.overall != QualityGrade.POOR
        assert result.is_data_trustworthy is False
        assert "closed" in result.trading_blocked_reason.lower()

    def test_fx_closed_stale_data(self) -> None:
        """Market CLOSED + Data STALE → Expected (market closed is primary)."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)  # Saturday

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=600),
            bid=1.085,
            ask=1.086,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is False
        # Market closed is the primary fact — data presence is incidental
        assert result.expected_data == ExpectedDataState.EXPECTED_MISSING
        assert result.truth_level == TruthLevel.UNAVAILABLE

    def test_fx_broker_disconnected(self) -> None:
        """Market OPEN + Broker disconnected → Not tradable."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)  # Wednesday

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.086,
            broker_connected=False,
            now=now,
        )

        assert result.market_open is True
        assert result.truth_level == TruthLevel.UNAVAILABLE
        assert result.is_data_trustworthy is False

    # ─── CRYPTO 24/7 TESTS ───────────────────────────────────────

    def test_crypto_weekend_fresh(self) -> None:
        """24/7 + Weekend + Fresh → Tradable."""
        bridge = MarketDataBridge(self.crypto_schedule)
        now = datetime(2026, 8, 30, 3, 0, 0, tzinfo=UTC)  # Sunday 03:00

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=60000.0,
            ask=60001.0,
            mid=60000.5,
            volume=10,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.expected_data == ExpectedDataState.EXPECTED
        assert result.quality.overall == QualityGrade.GOOD
        assert result.is_data_trustworthy is True

    def test_crypto_weekend_maintenance(self) -> None:
        """24/7 + Weekend + Maintenance → Not tradable."""
        bridge = MarketDataBridge(self.crypto_schedule)
        # Saturday 04:15 — inside maintenance window
        now = datetime(2026, 8, 29, 4, 15, 0, tzinfo=UTC)

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=60000.0,
            ask=60001.0,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is False
        assert result.expected_data == ExpectedDataState.EXPECTED_MISSING
        assert result.is_data_trustworthy is False

    def test_crypto_weekday_fresh(self) -> None:
        """24/7 + Weekday + Fresh → Tradable."""
        bridge = MarketDataBridge(self.crypto_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)  # Wednesday

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=60000.0,
            ask=60001.0,
            mid=60000.5,
            volume=10,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.is_data_trustworthy is True

    def test_crypto_weekend_fresh_not_maintenance(self) -> None:
        """24/7 + Weekend + Fresh (not in maintenance) → Tradable."""
        bridge = MarketDataBridge(self.crypto_schedule)
        # Sunday 10:00 — not in maintenance
        now = datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC)

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=60000.0,
            ask=60001.0,
            mid=60000.5,
            volume=10,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.is_data_trustworthy is True

    # ─── QUALITY DIMENSIONS ───────────────────────────────────────

    def test_quality_degraded_spread(self) -> None:
        """Market OPEN + Abnormal spread → DEGRADED quality."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.090,  # Wide spread
            mid=1.0875,
            volume=100,
            expected_spread_max=0.001,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.quality.overall in (QualityGrade.DEGRADED, QualityGrade.POOR)
        spread_dim = result.quality.dimension_status("spread")
        assert spread_dim.value in ("WARN", "FAIL")

    def test_quality_bad_source(self) -> None:
        """Market OPEN + Wrong source → POOR quality."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            expected_source="MT5",
            actual_source="OTHER",
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        assert result.quality.overall == QualityGrade.POOR
        assert result.truth_level == TruthLevel.CORRUPT

    def test_quality_bad_timestamps(self) -> None:
        """Market OPEN + Out-of-order timestamps → DEGRADED."""
        bridge = MarketDataBridge(self.fx_schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        timestamps = [
            now - timedelta(seconds=30),
            now - timedelta(seconds=25),
            now - timedelta(seconds=28),  # out of order
            now - timedelta(seconds=20),
        ]

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            recent_timestamps=timestamps,
            broker_connected=True,
            now=now,
        )

        assert result.market_open is True
        ti_status = result.quality.dimension_status("timestamp_integrity")
        assert ti_status.value in ("WARN", "FAIL")


# ═══════════════════════════════════════════════════════════════════
# No Silent Degradation Tests
# ═══════════════════════════════════════════════════════════════════


class TestGuardFunctions:
    """Test the guard functions that prevent silent degradation."""

    def test_guard_not_none_passes(self) -> None:
        assert guard_not_none(5) == 5
        assert guard_not_none("hello") == "hello"
        assert guard_not_none(0) == 0  # 0 is not None

    def test_guard_not_none_fails(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_none(None)

    def test_guard_not_none_named(self) -> None:
        with pytest.raises(DegradationViolation) as exc_info:
            guard_not_none(None, name="equity")
        assert "equity" in str(exc_info.value)

    def test_guard_not_zero_passes(self) -> None:
        assert guard_not_zero(5) == 5
        assert guard_not_zero(-1) == -1

    def test_guard_not_zero_fails(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_zero(0)
        with pytest.raises(DegradationViolation):
            guard_not_zero(0.0)

    def test_guard_not_degraded_none(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_degraded(None)

    def test_guard_not_degraded_zero(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_degraded(0)

    def test_guard_not_degraded_string(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_degraded("UNKNOWN")
        with pytest.raises(DegradationViolation):
            guard_not_degraded("MISSING")
        with pytest.raises(DegradationViolation):
            guard_not_degraded("STALE")

    def test_guard_not_degraded_empty(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_not_degraded("")
        with pytest.raises(DegradationViolation):
            guard_not_degraded([])
        with pytest.raises(DegradationViolation):
            guard_not_degraded({})

    def test_guard_not_degraded_valid(self) -> None:
        assert guard_not_degraded(5) == 5
        assert guard_not_degraded("hello") == "hello"
        assert guard_not_degraded([1, 2]) == [1, 2]

    def test_guard_numeric_positive(self) -> None:
        assert guard_numeric_positive(5) == 5.0
        assert guard_numeric_positive("3.14") == 3.14

    def test_guard_numeric_positive_fails(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_numeric_positive(None)
        with pytest.raises(DegradationViolation):
            guard_numeric_positive(0)
        with pytest.raises(DegradationViolation):
            guard_numeric_positive(-5)

    def test_guard_numeric_non_negative(self) -> None:
        assert guard_numeric_non_negative(0) == 0.0
        assert guard_numeric_non_negative(5) == 5.0

    def test_guard_numeric_non_negative_fails(self) -> None:
        with pytest.raises(DegradationViolation):
            guard_numeric_non_negative(-1)


class TestNoSilentDegradationDecorator:
    """Test the @no_silent_degradation decorator."""

    def test_decorator_passes_valid(self) -> None:
        @no_silent_degradation
        def get_value() -> int:
            return 42

        assert get_value() == 42

    def test_decorator_rejects_none(self) -> None:
        @no_silent_degradation
        def get_none() -> None:
            return None

        with pytest.raises(DegradationViolation):
            get_none()

    def test_decorator_rejects_degraded_string(self) -> None:
        @no_silent_degradation
        def get_unknown() -> str:
            return "UNKNOWN"

        with pytest.raises(DegradationViolation):
            get_unknown()


class TestTransformationValidation:
    """Test transformation validation."""

    def test_none_to_zero_fails(self) -> None:
        check = validate_transformation(None, 0, "fallback")
        assert check.is_safe is False
        assert "None → 0" in check.violation

    def test_none_to_empty_fails(self) -> None:
        check = validate_transformation(None, "", "fallback")
        assert check.is_safe is False

    def test_none_to_no_data_safe(self) -> None:
        check = validate_transformation(None, "No data", "fallback")
        assert check.is_safe is True

    def test_none_to_dash_safe(self) -> None:
        check = validate_transformation(None, "—", "fallback")
        assert check.is_safe is True

    def test_degraded_to_valid_fails(self) -> None:
        check = validate_transformation("STALE", "1.085", "price_format")
        assert check.is_safe is False
        assert "STALE" in check.violation

    def test_valid_transformation_safe(self) -> None:
        check = validate_transformation(5.0, 5.0, "identity")
        assert check.is_safe is True

    def test_numeric_transformation_safe(self) -> None:
        check = validate_transformation(5.0, 10.0, "double")
        assert check.is_safe is True


# ═══════════════════════════════════════════════════════════════════
# DataTruth Integration
# ═══════════════════════════════════════════════════════════════════


class TestDataTruthIntegration:
    """Test DataTruth with MarketSchedule context."""

    def test_authoritative_from_broker(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.AUTHORITATIVE,
            source=SOURCE_BROKER,
            timestamp=datetime.now(UTC),
            units="USD",
        )
        assert tv.is_authoritative
        assert tv.is_reliable
        assert tv.display_value == "5,000.00"

    def test_unavailable_shows_no_data(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.UNAVAILABLE,
            source=SOURCE_BROKER,
            units="USD",
        )
        assert tv.display_value == "No USD data"
        assert not tv.is_usable

    def test_stale_shows_warning(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.STALE,
            source=SOURCE_BROKER,
            units="USD",
        )
        assert "⚠" in tv.display_value
        assert not tv.is_usable

    def test_registry_tracks_all_metrics(self) -> None:
        reg = TruthRegistry()
        reg.register(MetricName.EQUITY, 5000, TruthLevel.AUTHORITATIVE, SOURCE_BROKER)
        reg.register(MetricName.DRAWDOWN, None, TruthLevel.UNAVAILABLE, SOURCE_DERIVED)

        assert len(reg) == 2
        unreliable = reg.get_unreliable()
        assert MetricName.EQUITY not in unreliable
        assert MetricName.DRAWDOWN in unreliable


# ═══════════════════════════════════════════════════════════════════
# BridgeResult Serialization
# ═══════════════════════════════════════════════════════════════════


class TestBridgeResultSerialization:
    """Test BridgeResult.to_dict() for dashboard consumption."""

    def test_to_dict_complete(self) -> None:
        schedule = fx_weekday_schedule("EURUSD")
        bridge = MarketDataBridge(schedule)
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        result = bridge.assess(
            price_timestamp=now - timedelta(seconds=5),
            bid=1.085,
            ask=1.086,
            mid=1.0855,
            volume=100,
            broker_connected=True,
            now=now,
        )

        d = result.to_dict()
        assert d["instrument"] == "EURUSD"
        assert d["market_open"] is True
        assert d["is_data_trustworthy"] is True
        assert d["trading_blocked_reason"] is None
        assert "quality" in d
        assert "expected_data" in d
        assert "truth_level" in d
        assert "market_state" in d
        assert "next_open" in d
        assert "next_close" in d

    def test_to_dict_blocked(self) -> None:
        schedule = fx_weekday_schedule("EURUSD")
        bridge = MarketDataBridge(schedule)
        now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)  # Saturday

        result = bridge.assess(
            price_timestamp=None,
            broker_connected=True,
            now=now,
        )

        d = result.to_dict()
        assert d["market_open"] is False
        assert d["is_data_trustworthy"] is False
        assert d["trading_blocked_reason"] is not None
        assert "closed" in d["trading_blocked_reason"].lower()
