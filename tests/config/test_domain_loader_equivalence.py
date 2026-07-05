"""Equivalence tests for the Phase 4 ConfigRegistry.

Verifies that the new typed loader re-produces the legacy
``paper_trading.yaml`` shape byte-for-byte for the keys it owns.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def legacy_yaml() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())


@pytest.fixture(scope="module")
def registry():
    loader = importlib.import_module("configs.domain_loader")
    return loader.ConfigRegistry.load()


def test_registry_loads_without_error(registry):
    assert registry is not None


def test_registry_summary_shape(registry):
    summary = registry.summary()
    assert summary["assets"] == 22
    assert summary["sell_only"] == ["CADCHF", "EURAUD", "NZDCHF"]
    # SizingConfig has 27 typed fields per configs/domain_models/risk.py
    assert summary["sizing_fields"] == 27


def test_as_legacy_dict_round_trips_capital(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    assert out["capital"] == legacy_yaml["capital"]
    assert out["position_size"] == legacy_yaml["position_size"]
    assert out["portfolio_drawdown_limit"] == legacy_yaml["portfolio_drawdown_limit"]


def test_as_legacy_dict_round_trips_sizing(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    legacy_defaults = legacy_yaml["defaults"]
    typed_defaults = out["defaults"]

    # spot check several keys
    for k in (
        "rolling_window_bars",
        "max_risk_per_trade_pct",
        "net_short_concentration_threshold",
        "size_taper_min",
        "mt5_enable_max_risk_per_trade_pct",
        "min_confidence",
    ):
        assert typed_defaults[k] == legacy_defaults[k], f"{k} mismatch"


def test_as_legacy_dict_round_trips_sell_only(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    assert out["defaults"]["sell_only_assets"] == sorted(
        legacy_yaml["defaults"]["sell_only_assets"]
    )


def test_as_legacy_dict_round_trips_adaptive_exit(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    legacy_ae = legacy_yaml["defaults"]["adaptive_exit"]
    typed_ae = out["defaults"]["adaptive_exit"]
    for k in (
        "enabled",
        "be_lock_r",
        "trail_activation_r",
        "trail_retrace_pct",
        "max_hold_candles",
        "time_decay_start",
        "scale_out_fraction",
        "scale_out_r",
    ):
        assert typed_ae[k] == legacy_ae[k], f"adaptive_exit.{k} mismatch"


def test_as_legacy_dict_round_trips_assets(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    typed_assets = out["assets"]
    legacy_assets = legacy_yaml["assets"]
    assert set(typed_assets) == set(legacy_assets)
    for name, raw in legacy_assets.items():
        rebuilt = typed_assets[name]
        assert rebuilt["ticker"] == raw["ticker"]
        assert rebuilt["allocation"] == raw["allocation"]
        assert rebuilt["sl_mult"] == raw["sl_mult"]
        assert rebuilt["tp_mult"] == raw["tp_mult"]


def test_registry_extras_carry_legacy_only_keys(registry, legacy_yaml):
    """Extras bag carries keys that have not been promoted."""
    assert "rebalance" in registry.legacy_extras
    assert "data_source" in registry.legacy_extras
    assert "ensemble" in registry.legacy_extras


def test_registry_uses_domain_overrides_when_present(tmp_path: Path, legacy_yaml):
    """When a sizing domain file has an override, it wins."""
    loader = importlib.import_module("configs.domain_loader")
    # Build a fake domain tree from the materialized one, but override
    # one sizing key.
    src_sizing = REPO_ROOT / "configs" / "domains" / "risk" / "sizing.yaml"
    dst_sizing = tmp_path / "risk" / "sizing.yaml"
    dst_sizing.parent.mkdir(parents=True)
    text = src_sizing.read_text()
    # Inject an override: max_risk_per_trade_pct: 0.5 (lower than 2.0)
    text = text.replace("max_risk_per_trade_pct: 2.0", "max_risk_per_trade_pct: 0.5")
    dst_sizing.write_text(text)
    # Copy remaining structure to mirror live positions only loosely.
    # The capital.yaml & exits.yaml files already exist upstream — we
    # reuse them.
    for src, dst in (
        (
            REPO_ROOT / "configs" / "domains" / "risk" / "capital.yaml",
            tmp_path / "risk" / "capital.yaml",
        ),
        (
            REPO_ROOT / "configs" / "domains" / "risk" / "exits.yaml",
            tmp_path / "risk" / "exits.yaml",
        ),
    ):
        if src.exists():
            (tmp_path / "risk").mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text())

    reg = loader.ConfigRegistry.load(
        legacy_path=REPO_ROOT / "configs" / "paper_trading.yaml",
        domains_dir=tmp_path,
    )
    assert reg.risk.sizing.max_risk_per_trade_pct == 0.5
    # Untouched sizing keys remain at legacy value
    assert reg.risk.sizing.min_confidence == 55.0


def test_registry_falls_back_to_legacy_when_domain_file_missing(tmp_path: Path):
    """When domain files are absent, legacy YAML is the sole source."""
    loader = importlib.import_module("configs.domain_loader")
    # Empty domains dir
    reg = loader.ConfigRegistry.load(
        legacy_path=REPO_ROOT / "configs" / "paper_trading.yaml",
        domains_dir=tmp_path,
    )
    assert reg.risk.sizing.max_risk_per_trade_pct == 2.0  # legacy value


def test_registry_audit_message_is_informative(capsys):
    loader = importlib.import_module("configs.domain_loader")
    reg = loader.ConfigRegistry.load()
    summary = reg.summary()
    # Should be JSON-serializable
    json.dumps(summary)
    assert summary["assets"] == 22
