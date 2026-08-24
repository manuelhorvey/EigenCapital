"""Unit tests for dataset versioning."""

import pytest
from eigencapital.data.normalization.dataset import DatasetMetadata


class TestDatasetMetadata:
    def test_creation(self):
        ds = DatasetMetadata(
            dataset_id="equities_daily_v1",
            dataset_version="1.0.0",
            source="provider_x",
            instrument_universe=["SPY", "QQQ"],
            bar_interval="1d",
            start_date="2015-01-01T00:00:00Z",
            end_date="2025-12-31T00:00:00Z",
            record_count=2520,
        )
        assert ds.dataset_id == "equities_daily_v1"
        assert ds.record_count == 2520
        assert len(ds.instrument_universe) == 2

    def test_required_fields(self):
        with pytest.raises(ValueError, match="dataset_id"):
            DatasetMetadata(
                dataset_id="",
                dataset_version="1.0.0",
                source="x",
                instrument_universe=["ES"],
                bar_interval="1d",
                start_date="2024-01-01T00:00:00Z",
                end_date="2024-12-31T00:00:00Z",
                record_count=100,
            )

    def test_empty_universe(self):
        with pytest.raises(ValueError, match="instrument_universe"):
            DatasetMetadata(
                dataset_id="test",
                dataset_version="1.0.0",
                source="x",
                instrument_universe=[],
                bar_interval="1d",
                start_date="2024-01-01T00:00:00Z",
                end_date="2024-12-31T00:00:00Z",
                record_count=100,
            )

    def test_negative_record_count(self):
        with pytest.raises(ValueError, match="record_count"):
            DatasetMetadata(
                dataset_id="test",
                dataset_version="1.0.0",
                source="x",
                instrument_universe=["ES"],
                bar_interval="1d",
                start_date="2024-01-01T00:00:00Z",
                end_date="2024-12-31T00:00:00Z",
                record_count=-1,
            )

    def test_content_hash_deterministic(self):
        ds = DatasetMetadata(
            dataset_id="test",
            dataset_version="1.0.0",
            source="x",
            instrument_universe=["ES"],
            bar_interval="1d",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-12-31T00:00:00Z",
            record_count=100,
        )
        h1 = ds.compute_content_hash()
        h2 = ds.compute_content_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_to_dict_sorted(self):
        ds = DatasetMetadata(
            dataset_id="test",
            dataset_version="1.0.0",
            source="x",
            instrument_universe=["SPY", "QQQ"],
            bar_interval="1d",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-12-31T00:00:00Z",
            record_count=100,
        )
        d = ds.to_dict()
        assert d["instrument_universe"] == ["QQQ", "SPY"]  # sorted

    def test_validation_stats(self):
        ds = DatasetMetadata(
            dataset_id="test",
            dataset_version="1.0.0",
            source="x",
            instrument_universe=["ES"],
            bar_interval="1d",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-12-31T00:00:00Z",
            record_count=100,
            validation_stats={"valid": 95, "warning": 3, "invalid": 2},
        )
        assert ds.validation_stats["valid"] == 95
