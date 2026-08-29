"""Tests for the Data Truth Hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eigencapital.core.data_truth import (
    MetricName,
    SOURCE_BROKER,
    SOURCE_DERIVED,
    SOURCE_RISK_ENGINE,
    STALENESS_ACCOUNT,
    STALENESS_POSITION,
    STALENESS_PRICE,
    TruthLevel,
    TruthRegistry,
    TruthfulValue,
)


class TestTruthLevel:
    """Test TruthLevel enum values."""

    def test_all_levels_defined(self) -> None:
        levels = [
            TruthLevel.AUTHORITATIVE,
            TruthLevel.DERIVED,
            TruthLevel.ESTIMATED,
            TruthLevel.STALE,
            TruthLevel.UNAVAILABLE,
            TruthLevel.CORRUPT,
            TruthLevel.UNKNOWN,
        ]
        assert len(levels) == 7

    def test_authoritative_is_best(self) -> None:
        assert TruthLevel.AUTHORITATIVE.value == "AUTHORITATIVE"

    def test_string_values(self) -> None:
        assert TruthLevel.STALE.value == "STALE"
        assert TruthLevel.UNAVAILABLE.value == "UNAVAILABLE"
        assert TruthLevel.CORRUPT.value == "CORRUPT"


class TestTruthfulValue:
    """Test TruthfulValue data class."""

    def test_authoritative_value(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5_account_state",
            timestamp=datetime.now(UTC),
            units="USD",
            precision=2,
        )
        assert tv.is_authoritative is True
        assert tv.is_derived is False
        assert tv.is_reliable is True
        assert tv.is_usable is True
        assert tv.display_value == "5,000.00"

    def test_derived_value(self) -> None:
        tv = TruthfulValue(
            value=250.0,
            level=TruthLevel.DERIVED,
            source="risk_engine",
            units="USD",
        )
        assert tv.is_derived is True
        assert tv.is_reliable is True
        assert tv.is_usable is True
        assert tv.display_value == "250.00"

    def test_estimated_value(self) -> None:
        tv = TruthfulValue(
            value=0.15,
            level=TruthLevel.ESTIMATED,
            source="var_model",
        )
        assert tv.is_estimated is True
        assert tv.is_reliable is False
        assert tv.is_usable is True

    def test_stale_value(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.STALE,
            source="mt5_account_state",
            units="USD",
        )
        assert tv.is_stale is True
        assert tv.is_reliable is False
        assert tv.is_usable is False
        assert "⚠" in tv.display_value

    def test_unavailable_value(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.UNAVAILABLE,
            source="mt5_account_state",
            units="USD",
        )
        assert tv.is_usable is False
        assert tv.display_value == "No USD data"

    def test_corrupt_value(self) -> None:
        tv = TruthfulValue(
            value="not_a_number",
            level=TruthLevel.CORRUPT,
            source="mt5_account_state",
        )
        assert tv.is_usable is False
        assert tv.display_value == "⚠ CORRUPT"

    def test_unknown_value(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.UNKNOWN,
        )
        assert tv.is_usable is False
        assert tv.display_value == "—"

    def test_none_value_unavailable(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
        )
        # Even AUTHORITATIVE with None value should show unavailable
        assert "No data" in tv.display_value

    def test_stale_detection_by_age(self) -> None:
        """A value becomes stale when its age exceeds stale_after_seconds."""
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
            timestamp=datetime.now(UTC) - timedelta(seconds=120),
            stale_after_seconds=60.0,
        )
        assert tv.is_stale is True

    def test_not_stale_when_fresh(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
            timestamp=datetime.now(UTC) - timedelta(seconds=10),
            stale_after_seconds=60.0,
        )
        assert tv.is_stale is False

    def test_stale_check_ignores_non_authoritative(self) -> None:
        """Staleness check only applies to AUTHORITATIVE/DERIVED values."""
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.ESTIMATED,
            source="model",
            timestamp=datetime.now(UTC) - timedelta(hours=1),
            stale_after_seconds=60.0,
        )
        assert tv.is_stale is False  # ESTIMATED doesn't go stale

    def test_promote_to(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.STALE,
            source="mt5",
        )
        tv.promote_to(TruthLevel.AUTHORITATIVE)
        assert tv.level == TruthLevel.AUTHORITATIVE

    def test_to_dict(self) -> None:
        tv = TruthfulValue(
            value=5000.00,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
            units="USD",
        )
        d = tv.to_dict()
        assert d["value"] == 5000.00
        assert d["level"] == "AUTHORITATIVE"
        assert d["source"] == "mt5"
        assert d["units"] == "USD"
        assert d["is_reliable"] is True

    def test_display_value_precision(self) -> None:
        tv = TruthfulValue(
            value=1.08512345,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
            precision=5,
        )
        assert tv.display_value == "1.08512"

    def test_display_value_integer(self) -> None:
        tv = TruthfulValue(
            value=42,
            level=TruthLevel.AUTHORITATIVE,
            source="mt5",
        )
        assert tv.display_value == "42"

    def test_unavailable_no_units(self) -> None:
        tv = TruthfulValue(
            value=None,
            level=TruthLevel.UNAVAILABLE,
        )
        assert tv.display_value == "No data"


class TestTruthRegistry:
    """Test TruthRegistry for tracking all metrics."""

    def test_register_and_get(self) -> None:
        reg = TruthRegistry()
        reg.register(
            "account.equity",
            5000.00,
            TruthLevel.AUTHORITATIVE,
            SOURCE_BROKER,
        )
        tv = reg.get("account.equity")
        assert tv is not None
        assert tv.value == 5000.00
        assert tv.level == TruthLevel.AUTHORITATIVE

    def test_get_nonexistent(self) -> None:
        reg = TruthRegistry()
        assert reg.get("nonexistent") is None

    def test_get_all(self) -> None:
        reg = TruthRegistry()
        reg.register("a", 1, TruthLevel.AUTHORITATIVE, "src")
        reg.register("b", 2, TruthLevel.DERIVED, "src")
        assert len(reg.get_all()) == 2

    def test_get_unreliable(self) -> None:
        reg = TruthRegistry()
        reg.register("good", 1, TruthLevel.AUTHORITATIVE, "src")
        reg.register("bad", None, TruthLevel.UNAVAILABLE, "src")
        reg.register("stale", 2, TruthLevel.STALE, "src")

        unreliable = reg.get_unreliable()
        assert "good" not in unreliable
        assert "bad" in unreliable
        assert "stale" in unreliable

    def test_get_summary(self) -> None:
        reg = TruthRegistry()
        reg.register("equity", 5000, TruthLevel.AUTHORITATIVE, "mt5")
        summary = reg.get_summary()
        assert "equity" in summary
        assert "AUTHORITATIVE" in summary["equity"]

    def test_clear(self) -> None:
        reg = TruthRegistry()
        reg.register("a", 1, TruthLevel.AUTHORITATIVE, "src")
        assert len(reg) == 1
        reg.clear()
        assert len(reg) == 0

    def test_contains(self) -> None:
        reg = TruthRegistry()
        reg.register("a", 1, TruthLevel.AUTHORITATIVE, "src")
        assert "a" in reg
        assert "b" not in reg

    def test_overwrite(self) -> None:
        reg = TruthRegistry()
        reg.register("a", 1, TruthLevel.AUTHORITATIVE, "src1")
        reg.register("a", 2, TruthLevel.DERIVED, "src2")
        tv = reg.get("a")
        assert tv is not None
        assert tv.value == 2
        assert tv.level == TruthLevel.DERIVED


class TestMetricNames:
    """Test canonical metric names are defined."""

    def test_account_metrics(self) -> None:
        assert MetricName.BALANCE == "account.balance"
        assert MetricName.EQUITY == "account.equity"
        assert MetricName.DRAWDOWN == "account.drawdown"
        assert MetricName.DAILY_PNL == "account.daily_pnl"

    def test_position_metrics(self) -> None:
        assert MetricName.POSITION_COUNT == "positions.count"
        assert MetricName.UNREALIZED_PNL == "positions.unrealized_pnl"

    def test_risk_metrics(self) -> None:
        assert MetricName.RISK_OVERALL == "risk.overall"
        assert MetricName.RISK_AUTHORIZATION == "risk.authorization"

    def test_health_metrics(self) -> None:
        assert MetricName.HEALTH_OVERALL == "health.overall"
        assert MetricName.HEALTH_AUTHORIZATION == "health.authorization"

    def test_build_metrics(self) -> None:
        assert MetricName.BUILD_ID == "system.build_id"
        assert MetricName.FINGERPRINT == "system.fingerprint"


class TestStalenessThresholds:
    """Test standard staleness thresholds."""

    def test_account_is_30s(self) -> None:
        assert STALENESS_ACCOUNT == 30.0

    def test_price_is_60s(self) -> None:
        assert STALENESS_PRICE == 60.0

    def test_position_is_300s(self) -> None:
        assert STALENESS_POSITION == 300.0

    def test_build_is_infinite(self) -> None:
        from eigencapital.core.data_truth import STALENESS_BUILD
        assert STALENESS_BUILD == float("inf")


class TestSourceConstants:
    """Test standard source constants."""

    def test_sources_defined(self) -> None:
        assert SOURCE_BROKER == "broker"
        assert SOURCE_RISK_ENGINE == "risk_engine"
        assert SOURCE_DERIVED == "derived"
