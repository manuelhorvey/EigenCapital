"""Tests for the triple-barrier YAML loader (Phase 6)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def loader_mod():
    return importlib.import_module("configs.domain_models.triple_barrier")


@pytest.fixture(scope="module")
def loaded(loader_mod):
    return loader_mod.load_triple_barrier_params()


def test_loader_resolves_active_assets(loaded):
    assert "BTC" in loaded
    assert "GC" in loaded
    assert "USDCAD" in loaded
    assert "EURAUD" in loaded


def test_loader_resolves_removed_assets(loaded):
    # Kept in YAML for backtest reproducibility but flagged
    assert "EURUSD" in loaded
    assert "AUDCHF" in loaded


def test_loader_records_notes(loaded):
    if "note" in loaded["EURUSD"]:
        assert "REMOVED" in loaded["EURUSD"]["note"]


def test_loader_respects_yaml_defaults(loader_mod, tmp_path: Path):
    """When entries are missing vol_method / atr_period, defaults kick in."""
    yaml_path = tmp_path / "triple_barrier.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "legacy": {"default_vol_method": "custom_default", "default_atr_period": 21},
                "assets": {"DEMO1": {"pt": 1.0, "sl": 0.5}},
            }
        )
    )
    out = loader_mod.load_triple_barrier_params(yaml_path)
    assert out["DEMO1"]["vol_method"] == "custom_default"
    assert out["DEMO1"]["atr_period"] == 21
    assert out["DEMO1"]["pt"] == 1.0


def test_loader_falls_back_to_legacy_when_yaml_missing(loader_mod, tmp_path: Path):
    """When YAML path doesn't exist, loader returns legacy hardcoded dict."""
    out = loader_mod.load_triple_barrier_params(tmp_path / "nope.yaml")
    # Legacy fallback has 36+ assets
    assert len(out) >= 30


def test_features_registry_sourcing_is_off_yaml():
    """features.registry.ASSET_LABEL_PARAMS must now source from YAML."""
    sys.path.insert(0, str(REPO_ROOT))
    import features.registry as reg

    yaml_data = yaml.safe_load((REPO_ROOT / "configs" / "domains" / "ml" / "triple_barrier.yaml").read_text())
    yaml_assets = yaml_data.get("assets") or {}

    # Every key in YAML must appear in the loaded dict
    for key in yaml_assets:
        assert key in reg.ASSET_LABEL_PARAMS, f"Missing key: {key}"


def test_features_registry_loaded_count_matches_yaml(loader_mod):
    """If YAML has N assets, ASSET_LABEL_PARAMS must have at least N."""
    yaml_path = REPO_ROOT / "configs" / "domains" / "ml" / "triple_barrier.yaml"
    yaml_data = yaml.safe_load(yaml_path.read_text())
    yaml_n = len(yaml_data["assets"])
    loaded_n = len(loader_mod.load_triple_barrier_params())
    assert loaded_n == yaml_n


def test_features_registry_loaded_pt_values_match_yaml():
    """pt values in the loaded dict must come from YAML."""
    import features.registry as reg

    yaml_data = yaml.safe_load((REPO_ROOT / "configs" / "domains" / "ml" / "triple_barrier.yaml").read_text())
    yaml_assets = yaml_data["assets"]
    for key, raw in yaml_assets.items():
        assert reg.ASSET_LABEL_PARAMS[key]["pt"] == raw["pt"]
        assert reg.ASSET_LABEL_PARAMS[key]["sl"] == raw["sl"]


def test_engine_runtime_drift_check_still_warns():
    """Confirm EngineInitializeService.initialize still has the runtime drift check
    for sl_mult/tp_mult != ASSET_LABEL_PARAMS["sl"]/["pt"].
    """
    src = (REPO_ROOT / "paper_trading" / "services" / "engine_initialize_service.py").read_text()
    assert "ASSET_LABEL_PARAMS.get(name)" in src
    assert 'registry_params["sl"]' in src
    assert 'registry_params["pt"]' in src


def test_loader_rejects_yaml_with_missing_required_fields(loader_mod, tmp_path: Path):
    """Each entry must have pt and sl."""
    yaml_path = tmp_path / "triple_barrier.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "assets": {"BROKEN": {"pt": 1.0}},
            }
        )
    )
    with pytest.raises(KeyError):
        loader_mod.load_triple_barrier_params(yaml_path)
