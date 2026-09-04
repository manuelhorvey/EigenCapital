"""Unit tests for Bar normalizer."""

import pytest

from eigencapital.data.loaders.base import RawRecord
from eigencapital.data.normalization.bars import BarNormalizer, NormalizationError


def _make_raw_record(**overrides):
    defaults = dict(
        source="test_source",
        instrument_id="ES",
        timestamp="2024-03-15T09:35:00Z",
        data={
            "open": "4500.0",
            "high": "4510.0",
            "low": "4495.0",
            "close": "4505.0",
            "volume": "1000",
        },
    )
    defaults.update(overrides)
    return RawRecord(**defaults)


class TestBarNormalizer:
    def test_normalize_single(self):
        normalizer = BarNormalizer(instrument_id="ES", bar_interval="1d")
        record = _make_raw_record()
        bars = normalizer.normalize([record])
        assert len(bars) == 1
        bar = bars[0]
        assert bar.instrument_id == "ES"
        assert bar.open == 4500.0
        assert bar.high == 4510.0
        assert bar.low == 4495.0
        assert bar.close == 4505.0
        assert bar.volume == 1000
        assert bar.bar_interval == "1d"

    def test_normalize_multiple(self):
        normalizer = BarNormalizer(instrument_id="ES")
        records = [
            _make_raw_record(
                timestamp=f"2024-03-15T09:3{i}:00Z",
                data={
                    "open": "4500.0",
                    "high": "4510.0",
                    "low": "4495.0",
                    "close": "4505.0",
                    "volume": "1000",
                },
            )
            for i in range(3)
        ]
        bars = normalizer.normalize(records)
        assert len(bars) == 3

    def test_missing_field_raises(self):
        normalizer = BarNormalizer(instrument_id="ES")
        record = _make_raw_record(data={"open": "4500.0"})  # missing high, low, close
        with pytest.raises(NormalizationError, match="Missing required field"):
            normalizer.normalize([record])

    def test_invalid_float_raises(self):
        normalizer = BarNormalizer(instrument_id="ES")
        record = _make_raw_record(
            data={
                "open": "not_a_number",
                "high": "4510.0",
                "low": "4495.0",
                "close": "4505.0",
                "volume": "1000",
            }
        )
        with pytest.raises(NormalizationError, match="Cannot parse"):
            normalizer.normalize([record])

    def test_empty_timestamp_raises(self):
        normalizer = BarNormalizer(instrument_id="ES")
        record = _make_raw_record(timestamp="")
        with pytest.raises(NormalizationError, match="Empty timestamp"):
            normalizer.normalize([record])

    def test_vwap_optional(self):
        normalizer = BarNormalizer(instrument_id="ES")
        record = _make_raw_record(
            data={
                "open": "4500.0",
                "high": "4510.0",
                "low": "4495.0",
                "close": "4505.0",
                "volume": "1000",
                "vwap": "4503.5",
            }
        )
        bars = normalizer.normalize([record])
        assert bars[0].vwap == 4503.5

    def test_source_attribution(self):
        normalizer = BarNormalizer(instrument_id="ES", source="provider_x")
        record = _make_raw_record(source="")  # empty source → falls back to normalizer
        bars = normalizer.normalize([record])
        assert bars[0].source == "provider_x"

    def test_timestamp_normalization(self):
        normalizer = BarNormalizer(instrument_id="ES")
        # Space separator → T
        record = _make_raw_record(timestamp="2024-03-15 09:35:00Z")
        bars = normalizer.normalize([record])
        assert "T" in bars[0].timestamp_utc
