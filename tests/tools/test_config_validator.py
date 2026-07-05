"""Tests for the upgraded configuration schema validator."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "tools"
REPO_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_DIR))

validator_mod = importlib.import_module("tools.check_config_schema")


def _load_registry_dict() -> dict:
    """Load config dict from PaperConfigRegistry."""
    from configs.paper_config_registry import PaperConfigRegistry

    return PaperConfigRegistry.load().as_legacy_dict()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Generate a synthetic legacy YAML file from PaperConfigRegistry."""
    dst = tmp_path / "paper_trading.yaml"
    dst.write_text(yaml.safe_dump(_load_registry_dict(), sort_keys=False))
    return dst


def _dump(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_validator_module_imports():
    assert hasattr(validator_mod, "validate")
    assert hasattr(validator_mod, "_check_label_consistency")


def test_passes_legacy_yaml(config_path):
    rc = validator_mod.validate(str(config_path))
    assert rc == 0


def test_allocation_overflow_fails(tmp_path):
    data = _load_registry_dict()
    data["assets"]["USDCAD"]["allocation"] = 5.0
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    assert validator_mod.validate(str(target)) != 0


def test_ticker_collision_fails(tmp_path):
    data = _load_registry_dict()
    data["assets"]["NZDUSD"]["ticker"] = "USDCAD=X"
    data["assets"]["USDCAD"]["ticker"] = "USDCAD=X"  # both pointing at same ticker
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    assert validator_mod.validate(str(target)) != 0


def test_label_drift_surfaces_soft_warning(tmp_path):
    data = _load_registry_dict()
    data["assets"]["USDCAD"]["tp_mult"] = data["assets"]["USDCAD"]["tp_mult"] * 2
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    rc = validator_mod.validate(str(target))
    assert rc == 0  # warn-only path; warnings kept out of exit code by default


def test_required_top_level_keys_present(config_path):
    data = yaml.safe_load(config_path.read_text())
    for key in ("capital", "position_size", "rebalance", "assets", "defaults"):
        assert key in data, f"missing required key: {key}"


def test_cpu_invocation_succeeds():
    proc = subprocess.run(
        [sys.executable, "tools/check_config_schema.py"],
        cwd=REPO_DIR,
        env={"PYTHONPATH": str(REPO_DIR), "PATH": sys.executable},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASSED" in proc.stdout


def test_mode_references_undeclared_fails(tmp_path):
    data = _load_registry_dict()
    data["mode"] = "unknown_mode"
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    assert validator_mod.validate(str(target)) != 0


def test_mt5_port_out_of_range_fails(tmp_path):
    data = _load_registry_dict()
    data["mt5"]["bridge_port"] = 70000
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    assert validator_mod.validate(str(target)) != 0


def test_session_gate_window_must_be_two_element_list(tmp_path):
    data = _load_registry_dict()
    data["defaults"]["session_gate"]["tiers"]["fx_major"] = 9
    target = tmp_path / "paper_trading.yaml"
    _dump(target, data)
    assert validator_mod.validate(str(target)) != 0
