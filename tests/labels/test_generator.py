"""Tests for labels/generator — LabelGenerator with file I/O."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from labels.generator import LabelGenerator


class FakeContract:
    """Minimal contract stub for testing LabelGenerator."""
    def __init__(self, name="TEST", ticker="TEST=X", label_params=None, label_version="abc123def456"):
        self.name = name
        self.ticker = ticker
        self.label_params = label_params or {"pt_sl": [2, 2], "vertical_barrier": 20}
        self.label_version = label_version


@pytest.fixture
def gen():
    with tempfile.TemporaryDirectory() as tmp:
        yield LabelGenerator(data_dir=tmp)


@pytest.fixture
def raw_data():
    rng = np.random.RandomState(42)
    return pd.DataFrame({
        "close": 100 + np.cumsum(rng.randn(300) * 0.5),
        "high": 100 + np.cumsum(rng.randn(300) * 0.5) * 1.01,
        "low": 100 + np.cumsum(rng.randn(300) * 0.5) * 0.99,
        "volume": rng.randint(100000, 1000000, 300),
    })


class TestLabelGenerator:
    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = LabelGenerator(data_dir=tmp)
            assert os.path.exists(os.path.join(tmp, "processed"))

    def test_generate_asset_labels_raises_on_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = LabelGenerator(data_dir=tmp)
            contract = FakeContract(name="NONEXISTENT")
            with pytest.raises(FileNotFoundError):
                gen.generate_asset_labels(contract)

    def test_generate_asset_labels_creates_parquet(self, gen, raw_data):
        # Write raw data
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        raw_path = os.path.join(raw_dir, "TEST_1d.parquet")
        raw_data.to_parquet(raw_path)

        contract = FakeContract(name="TEST")
        out_path = gen.generate_asset_labels(contract)
        assert os.path.exists(out_path)
        assert out_path.endswith(".parquet")

    def test_generated_labels_have_correct_columns(self, gen, raw_data):
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        raw_data.to_parquet(os.path.join(raw_dir, "TEST_1d.parquet"))

        contract = FakeContract(name="TEST")
        out_path = gen.generate_asset_labels(contract)
        df = pd.read_parquet(out_path)
        assert "label_new" in df.columns
        assert "label_shadow" in df.columns

    def test_skips_when_version_exists(self, gen, raw_data):
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        raw_data.to_parquet(os.path.join(raw_dir, "TEST_1d.parquet"))

        contract = FakeContract(name="TEST")
        # First call creates
        gen.generate_asset_labels(contract)
        # Second call should skip
        with patch("labels.generator.logger") as mock_log:
            gen.generate_asset_labels(contract)
            mock_log.info.assert_called_once()

    def test_force_regenerates(self, gen, raw_data):
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        raw_data.to_parquet(os.path.join(raw_dir, "TEST_1d.parquet"))

        contract = FakeContract(name="TEST")
        gen.generate_asset_labels(contract)
        # Force should recreate
        with patch("labels.generator.logger") as mock_log:
            gen.generate_asset_labels(contract, force=True)
            # force=True should skip the skip-log
            calls = [str(c) for c in mock_log.info.call_args_list]
            assert not any("Skipping" in c for c in calls)

    def test_try_alternate_naming(self, gen, raw_data):
        """When NAME_1d.parquet not found, try TICKER_1d.parquet."""
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        alt_path = os.path.join(raw_dir, "TEST=X_1d.parquet")
        raw_data.to_parquet(alt_path)

        contract = FakeContract(name="TEST", ticker="TEST=X")
        gen.generate_asset_labels(contract)
        # Should find the alt-named file and proceed
        processed_files = os.listdir(gen.processed_dir)
        assert len(processed_files) == 1

    def test_try_alternate_naming_without_suffix(self, gen, raw_data):
        """When both NAME and TICKER fail, try ticker without =X/=F suffix."""
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        alt_path = os.path.join(raw_dir, "TEST_1d.parquet")
        raw_data.to_parquet(alt_path)

        contract = FakeContract(name="NONEXISTENT", ticker="TEST=X")
        gen.generate_asset_labels(contract)
        processed_files = os.listdir(gen.processed_dir)
        assert len(processed_files) == 1


class TestVolMethod:
    def test_atr_vol_method_does_not_crash(self, gen, raw_data):
        """ATR vol method should not crash during label generation."""
        raw_dir = os.path.join(gen.raw_dir)
        os.makedirs(raw_dir, exist_ok=True)
        raw_data.to_parquet(os.path.join(raw_dir, "ATR_TEST_1d.parquet"))

        contract = FakeContract(
            name="ATR_TEST",
            label_params={"pt_sl": [2, 2], "vertical_barrier": 20, "vol_method": "atr", "atr_period": 14},
        )
        out_path = gen.generate_asset_labels(contract)
        assert os.path.exists(out_path)


class TestGenerateAll:
    def test_generate_all_does_not_crash_with_empty_registry(self, gen):
        with patch("labels.generator.FEATURE_REGISTRY", {}):
            result = gen.generate_all()
            assert result == {}

    def test_generate_all_handles_errors(self, gen):
        """When an asset fails to generate labels, generate_all logs the error
        and returns results without the failed ticker key."""
        from features.contract import FeatureContract
        mock_contract = FeatureContract(
            ticker="MISSING=X",
            name="MISSING",
            label_type="tb20",
            label_params={"pt_sl": [2, 2], "vertical_barrier": 20},
            macro_filters=(),
            price_mom_windows=(),
            vs_spy_windows=(),
        )
        with patch("labels.generator.FEATURE_REGISTRY", {"MISSING=X": mock_contract}):
            # Should not raise — exception is caught and logged
            result = gen.generate_all()
            assert isinstance(result, dict)
            # The ticker is not in result because generate_asset_labels
            # raises an exception before results[ticker] is assigned.
            assert "MISSING=X" not in result
