"""Tests for dataset storage policy and persistence."""

import json

import pytest

from eigencapital.data.loaders.base import RawRecord
from eigencapital.data.storage import (
    DatasetStore,
    StorageEngineUnavailableError,
    StorageFormat,
    StorageRecommendation,
    dataset_is_numeric_only,
    detect_engines,
    profile_columns,
    raw_records_to_rows,
    recommend_format,
)

NO_ENGINES = {
    "pandas": False,
    "pyarrow": False,
    "fastparquet": False,
    "tables": False,
}
PANDAS_ONLY = {"pandas": True, "pyarrow": False, "fastparquet": False, "tables": False}
PARQUET_ENGINES = {
    "pandas": True,
    "pyarrow": True,
    "fastparquet": False,
    "tables": False,
}
HDF5_ENGINES = {"pandas": True, "pyarrow": False, "fastparquet": False, "tables": True}


class TestRecommendFormat:
    """Format selection matrix per ML4T Ch.2 guidance."""

    def test_numeric_prefers_hdf5_when_available(self):
        rec = recommend_format(True, HDF5_ENGINES)
        assert rec.preferred == StorageFormat.HDF5
        assert "HDF5" in rec.reason

    def test_mixed_prefers_parquet_when_available(self):
        rec = recommend_format(False, PARQUET_ENGINES)
        assert rec.preferred == StorageFormat.PARQUET

    def test_degrades_to_csv_without_engines(self):
        rec = recommend_format(True, NO_ENGINES)
        assert rec.preferred == StorageFormat.CSV
        assert "degraded" in rec.reason

    def test_pandas_alone_insufficient(self):
        assert recommend_format(True, PANDAS_ONLY).preferred == StorageFormat.CSV
        assert recommend_format(False, PANDAS_ONLY).preferred == StorageFormat.CSV

    def test_fallbacks_ordered_and_available(self):
        rec = recommend_format(False, PARQUET_ENGINES)
        assert rec.preferred == StorageFormat.PARQUET
        assert rec.fallbacks[-1] == StorageFormat.CSV

    def test_mixed_with_only_hdf5_degrades_to_hdf5(self):
        rec = recommend_format(False, HDF5_ENGINES)
        assert rec.preferred == StorageFormat.HDF5
        assert rec.fallbacks == (StorageFormat.CSV,)

    def test_serialization_round_stable(self):
        rec = recommend_format(True, NO_ENGINES)
        d1 = rec.to_dict()
        d2 = StorageRecommendation(**d1).to_dict()
        assert d1 == d2


class TestProfileColumns:
    """Column classification."""

    def test_all_numeric(self):
        rows = [{"a": 1, "b": 2.5}, {"a": 3, "b": None}]
        assert dataset_is_numeric_only(rows) is True

    def test_string_makes_mixed(self):
        rows = [{"a": 1}, {"a": "hello"}]
        assert dataset_is_numeric_only(rows) is False

    def test_bool_not_numeric(self):
        assert dataset_is_numeric_only([{"flag": True}]) is False

    def test_per_column_profile(self):
        rows = [{"a": 1.0, "s": "x"}, {"a": 2, "s": "y"}]
        profile = profile_columns(rows)
        assert profile == {"a": True, "s": False}

    def test_empty_dataset_numeric_vacuously(self):
        assert dataset_is_numeric_only([]) is True


class TestDatasetStoreCSV:
    """CSV roundtrip (always available)."""

    def _store(self, tmp_path):
        return DatasetStore(tmp_path / "datasets")

    def test_save_load_roundtrip(self, tmp_path):
        store = self._store(tmp_path)
        rows = [
            {"instrument_id": "ES", "open": 100.0, "volume": 10},
            {"instrument_id": "NQ", "open": 200.5, "volume": 20},
        ]
        path = store.save("bars", rows, metadata={"source": "test"})
        loaded = {r["instrument_id"]: r for r in store.load("bars")}
        assert path.exists()
        assert float(loaded["ES"]["open"]) == 100.0
        assert loaded["NQ"]["instrument_id"] == "NQ"

    def test_metadata_sidecar_written(self, tmp_path):
        store = self._store(tmp_path)
        store.save("bars", [{"a": 1}], metadata={"run": "R4"})
        meta = json.loads((tmp_path / "datasets" / "bars.meta.json").read_text())
        assert meta["metadata"]["run"] == "R4"
        assert meta["rows"] == 1
        assert meta["columns"] == ["a"]

    def test_empty_dataset_refused(self, tmp_path):
        with pytest.raises(ValueError):
            self._store(tmp_path).save("empty", [])

    def test_missing_dataset_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            self._store(tmp_path).load("nonexistent")

    def test_forced_unavailable_engine_raises(self, tmp_path):
        engines_available_now = detect_engines()
        parquet_usable = engines_available_now["pandas"] and (
            engines_available_now["pyarrow"] or engines_available_now["fastparquet"]
        )
        if parquet_usable:
            pytest.skip("parquet engine installed; unavailable-path not exercisable")
        store = DatasetStore(tmp_path / "d", fmt=StorageFormat.PARQUET)
        with pytest.raises(StorageEngineUnavailableError, match="pip install"):
            store.save("bars", [{"a": 1}])


class TestParquetRoundtrip:
    """Full Parquet roundtrip when engines are installed."""

    def test_roundtrip_if_available(self, tmp_path):
        engines = detect_engines()
        if not (engines["pandas"] and (engines["pyarrow"] or engines["fastparquet"])):
            pytest.skip("pandas + pyarrow/fastparquet not installed")
        store = DatasetStore(tmp_path / "d")
        rows = [{"sym": "ES", "px": 100.5}, {"sym": "NQ", "px": 200.25}]
        path = store.save("mixed", rows)
        assert str(path).endswith(".parquet")
        loaded = store.load("mixed")
        assert sorted(r["sym"] for r in loaded) == ["ES", "NQ"]
        assert abs(float(loaded[0]["px"]) - 100.5) < 1e-9


class TestRawRecordConversion:
    """RawRecord flattening for storage."""

    def test_flatten_includes_data_fields(self):
        record = RawRecord(
            source="csv",
            instrument_id="ES",
            timestamp="2026-01-05T09:30:00Z",
            data={"open": 1.0},
        )
        rows = raw_records_to_rows([record])
        assert rows[0] == {
            "source": "csv",
            "instrument_id": "ES",
            "timestamp": "2026-01-05T09:30:00Z",
            "open": 1.0,
        }
