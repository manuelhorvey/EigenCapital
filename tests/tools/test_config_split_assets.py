"""Tests for tools/config_split_assets — per-asset YAML splitter."""

import tempfile
from pathlib import Path

import yaml

from tools.config_split_assets import split


_SAMPLE_LEGACY = {
    "assets": {
        "EURUSD": {
            "ticker": "EURUSD=X",
            "allocation": 0.05,
            "sl_mult": 1.0,
            "tp_mult": 2.0,
            "spread_tier": "fx_major",
            "regime_geometry": {"GREEN": {"sl_mult": 1.0, "tp_mult": 1.0}},
        },
        "GBPUSD": {
            "ticker": "GBPUSD=X",
            "allocation": 0.05,
            "sl_mult": 1.0,
            "tp_mult": 2.0,
            "spread_tier": "fx_major",
        },
    },
}


class TestSplit:
    def test_splits_assets_into_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            rc = split(None, out_dir)
            assert rc == 0
            # Should have written _defaults.yaml
            assert (out_dir / "_defaults.yaml").exists()
            # Registry has many assets
            files = list(out_dir.glob("*.yaml"))
            assert len(files) >= 2  # _defaults.yaml + at least one asset

    def test_splits_legacy_assets(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_SAMPLE_LEGACY, f)
            lpath = f.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                rc = split(Path(lpath), out_dir)
                assert rc == 0
                assert (out_dir / "_defaults.yaml").exists()
                assert (out_dir / "EURUSD.yaml").exists()
                assert (out_dir / "GBPUSD.yaml").exists()
        finally:
            import os
            os.unlink(lpath)

    def test_defaults_yaml_has_expected_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_SAMPLE_LEGACY, f)
            lpath = f.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                split(Path(lpath), out_dir)
                defaults = yaml.safe_load((out_dir / "_defaults.yaml").read_text())
                assert "shadow_sltp" in defaults
                assert "dynamic_sltp" in defaults
                assert "adaptive_exit" in defaults
                assert defaults["adaptive_exit"]["enabled"] is True
        finally:
            import os
            os.unlink(lpath)

    def test_per_asset_file_has_unique_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_SAMPLE_LEGACY, f)
            lpath = f.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                split(Path(lpath), out_dir)
                eurusd = yaml.safe_load((out_dir / "EURUSD.yaml").read_text())
                assert eurusd["ticker"] == "EURUSD=X"
                assert eurusd["allocation"] == 0.05
                assert eurusd["regime_geometry"]["GREEN"]["sl_mult"] == 1.0
        finally:
            import os
            os.unlink(lpath)

    def test_no_assets_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                yaml.dump({"assets": {}}, f)
                lpath = f.name
            try:
                rc = split(Path(lpath), out_dir)
                assert rc == 1
            finally:
                import os
                os.unlink(lpath)
