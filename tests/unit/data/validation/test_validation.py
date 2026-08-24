"""Unit tests for data validation — OHLC, temporal, and anomaly checks."""

import pytest
from eigencapital.core.models.bar import Bar
from eigencapital.core.models.market_snapshot import DataQualityStatus
from eigencapital.data.validation.ohlc import validate_ohlc
from eigencapital.data.validation.temporal import validate_temporal
from eigencapital.data.validation.anomalies import validate_anomalies
from eigencapital.data.validation.validator import DataValidator


def _make_bar(**overrides):
    defaults = dict(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )
    defaults.update(overrides)
    return Bar(**defaults)


# ─── OHLC Tests ─────────────────────────────────────────────────────────────


class TestOHLCChecks:
    def test_valid_bar(self):
        bar = _make_bar()
        result = validate_ohlc(bar)
        assert result.status == DataQualityStatus.VALID
        assert len(result.messages) == 0

    def test_high_lt_low_rejected(self):
        """high < low should be caught by Bar model."""
        with pytest.raises(ValueError):
            _make_bar(high=4490.0, low=4510.0)

    def test_negative_volume_rejected(self):
        """negative volume should be caught by Bar model."""
        with pytest.raises(ValueError):
            _make_bar(volume=-1)


# ─── Temporal Tests ─────────────────────────────────────────────────────────


class TestTemporalChecks:
    def test_valid_timestamp(self):
        bar = _make_bar()
        result = validate_temporal(bar, 0)
        assert result.status == DataQualityStatus.VALID

    def test_bar_start_lt_end(self):
        bar = _make_bar(
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
        )
        result = validate_temporal(bar, 0)
        assert result.status == DataQualityStatus.VALID

    def test_bar_start_ge_end_rejected_by_model(self):
        """bar_start >= bar_end is caught by Bar model."""
        with pytest.raises(ValueError):
            _make_bar(
                bar_start_utc="2024-03-15T09:35:00Z",
                bar_end_utc="2024-03-15T09:30:00Z",
            )


# ─── Anomaly Tests ──────────────────────────────────────────────────────────


class TestAnomalyChecks:
    def test_no_anomalies(self):
        bar = _make_bar()
        result = validate_anomalies(bar)
        assert result.status == DataQualityStatus.VALID
        assert len(result.messages) == 0

    def test_flatlined_price(self):
        bar = _make_bar(open=4500.0, high=4500.0, low=4500.0, close=4500.0)
        result = validate_anomalies(bar)
        assert result.status == DataQualityStatus.WARNING
        assert any("Flatlined" in m for m in result.messages)

    def test_extreme_price_jump(self):
        bar = _make_bar(open=4500.0, close=5500.0, high=5500.0, low=4500.0)
        result = validate_anomalies(bar)
        assert result.status == DataQualityStatus.WARNING
        assert any("Extreme price jump" in m for m in result.messages)

    def test_zero_volume_warning(self):
        bar = _make_bar(volume=0)
        result = validate_anomalies(bar)
        assert result.status == DataQualityStatus.WARNING
        assert any("Zero volume" in m for m in result.messages)

    def test_normal_price_change_no_warning(self):
        bar = _make_bar(open=4500.0, close=4510.0, high=4515.0, low=4495.0)
        result = validate_anomalies(bar)
        assert result.status == DataQualityStatus.VALID


# ─── Full Validator Tests ───────────────────────────────────────────────────


class TestDataValidator:
    def test_validate_clean_dataset(self):
        from eigencapital.core.models.bar import Bar as BarCls

        BarCls._registry.clear()
        validator = DataValidator()
        bars = [
            _make_bar(
                timestamp_utc=f"2024-03-15T09:{30 + i}:00Z",
                bar_start_utc=f"2024-03-15T09:{25 + i}:00Z",
                bar_end_utc=f"2024-03-15T09:{30 + i}:00Z",
            )
            for i in range(5)
        ]
        report = validator.validate(bars)
        assert report.total_bars == 5
        assert report.all_valid()

    def test_report_summary(self):
        validator = DataValidator()
        bars = [_make_bar()]
        report = validator.validate(bars)
        summary = report.summary()
        assert "5 bars" not in summary  # only 1 bar
        assert "1 bars" in summary

    def test_validator_with_anomalies(self):
        from eigencapital.core.models.bar import Bar as BarCls

        BarCls._registry.clear()
        validator = DataValidator()
        bars = [
            _make_bar(),  # normal
            _make_bar(
                timestamp_utc="2024-03-15T09:36:00Z",
                bar_start_utc="2024-03-15T09:31:00Z",
                bar_end_utc="2024-03-15T09:36:00Z",
                volume=0,
            ),  # anomaly
        ]
        report = validator.validate(bars)
        assert report.total_bars == 2
        assert report.has_warnings()
