"""Unit tests for CSV data loader."""

import pytest

from eigencapital.data.loaders.csv import CSVLoader


class TestCSVLoader:
    def test_load_basic_csv(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2024-03-15T09:30:00Z,4500.0,4510.0,4495.0,4505.0,1000\n"
            "2024-03-15T09:31:00Z,4505.0,4515.0,4500.0,4512.0,1200\n"
        )
        loader = CSVLoader(path=csv_file, instrument_id="ES")
        records = loader.load()
        assert len(records) == 2
        assert records[0].instrument_id == "ES"
        assert records[0].data["open"] == "4500.0"
        assert records[0].timestamp == "2024-03-15T09:30:00Z"

    def test_column_mapping(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Date,O,H,L,C,V\n2024-03-15,4500.0,4510.0,4495.0,4505.0,1000\n")
        loader = CSVLoader(
            path=csv_file,
            instrument_id="ES",
            column_map={
                "Date": "timestamp",
                "O": "open",
                "H": "high",
                "L": "low",
                "C": "close",
                "V": "volume",
            },
            timestamp_column="timestamp",
        )
        records = loader.load()
        assert len(records) == 1
        assert records[0].data["open"] == "4500.0"

    def test_file_not_found(self):
        loader = CSVLoader(path="/nonexistent/file.csv", instrument_id="ES")
        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_source_name(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("timestamp,open,high,low,close,volume\n")
        loader = CSVLoader(path=csv_file, instrument_id="ES")
        assert loader.source_name() == str(csv_file)

    def test_custom_source_name(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("timestamp,open,high,low,close,volume\n")
        loader = CSVLoader(path=csv_file, instrument_id="ES", source_name_="provider_x")
        assert loader.source_name() == "provider_x"
