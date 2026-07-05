"""Equivalence tests for the Phase 4 ConfigRegistry.

Uses a synthetic legacy dict built from PaperConfigRegistry
since the actual legacy ``paper_trading.yaml`` was deleted in Phase 12.7.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def registry_legacy() -> dict:
    """Build a synthetic legacy dict from PaperConfigRegistry."""
    mod = importlib.import_module("configs.paper_config_registry")
    return mod.PaperConfigRegistry.load().as_legacy_dict()


@pytest.fixture(scope="module")
def registry(tmp_path_factory, registry_legacy):
    """Build a ConfigRegistry from a synthetic legacy file."""
    tmp_dir = tmp_path_factory.mktemp("legacy")
    leg_path = _make_legacy_file(registry_legacy, tmp_dir)
    loader = importlib.import_module("configs.domain_loader")
    return loader.ConfigRegistry.load(legacy_path=leg_path)


def _make_legacy_file(registry_legacy: dict, tmp_path: Path) -> Path:
    """Write a temporary legacy file from the synthetic dict."""
    import yaml as _yaml
    target = tmp_path / "paper_trading.yaml"
    target.write_text(_yaml.safe_dump(registry_legacy, sort_keys=False))
    return target


def test_registry_loads_without_error(registry):
    assert registry is not None


def test_registry_summary_shape(registry):
    summary = registry.summary()
    assert summary["assets"] == 22
    assert summary["sell_only"] == ["CADCHF", "EURAUD", "NZDCHF"]
    assert summary["sizing_fields"] == 27


def test_as_legacy_dict_round_trips_capital(registry, registry_legacy):
    out = registry.as_legacy_dict()
    assert out["capital"] == registry_legacy["capital"]
    assert out["position_size"] == registry_legacy["position_size"]
    assert out["portfolio_drawdown_limit"] == registry_legacy["portfolio_drawdown_limit"]


def test_as_legacy_dict_round_trips_sizing(registry, registry_legacy):
    out = registry.as_legacy_dict()
    legacy_defaults = registry_legacy["defaults"]
    typed_defaults = out["defaults"]

    for k in (
        "rolling_window_bars",
        "max_risk_per_trade_pct",
        "net_short_concentration_threshold",
        "size_taper_min",
        "mt5_enable_max_risk_per_trade_pct",
        "min_confidence",
    ):
        assert typed_defaults[k] == legacy_defaults[k], f"{k} mismatch"


def test_as_legacy_dict_round_trips_sell_only(registry, registry_legacy):
    out = registry.as_legacy_dict()
    assert out["defaults"]["sell_only_assets"] == sorted(
        registry_legacy["defaults"]["sell_only_assets"]
    )


def test_as_legacy_dict_round_trips_adaptive_exit(registry, registry_legacy):
    out = registry.as_legacy_dict()
    legacy_ae = registry_legacy["defaults"]["adaptive_exit"]
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


def test_as_legacy_dict_round_trips_assets(registry, registry_legacy):
    out = registry.as_legacy_dict()
    typed_assets = out["assets"]
    legacy_assets = registry_legacy["assets"]
    assert set(typed_assets) == set(legacy_assets)
    for name, raw in legacy_assets.items():
        rebuilt = typed_assets[name]
        assert rebuilt["ticker"] == raw["ticker"]
        assert rebuilt["allocation"] == raw["allocation"]
        assert rebuilt["sl_mult"] == raw["sl_mult"]
        assert rebuilt["tp_mult"] == raw["tp_mult"]


def test_registry_extras_carry_legacy_only_keys(registry, registry_legacy):
    """Extras bag carries keys that have not been promoted."""
    from configs.paper_config_registry import PaperConfigRegistry
    paper_reg = PaperConfigRegistry.load()
    extras = set(paper_reg.legacy_extras.keys())
    for k in extras:
        assert k in registry.legacy_extras


def test_registry_uses_domain_overrides_when_present(tmp_path: Path, registry_legacy):
    """When a sizing domain file has an override, it wins."""
    loader = importlib.import_module("configs.domain_loader")
    leg_path = _make_legacy_file(registry_legacy, tmp_path)

    src_sizing = REPO_ROOT / "configs" / "domains" / "risk" / "sizing.yaml"
    dst_sizing = tmp_path / "risk" / "sizing.yaml"
    dst_sizing.parent.mkdir(parents=True)
    text = src_sizing.read_text()
    text = text.replace("max_risk_per_trade_pct: 2.0", "max_risk_per_trade_pct: 0.5")
    dst_sizing.write_text(text)

    for src, dst in (
        (REPO_ROOT / "configs" / "domains" / "risk" / "capital.yaml", tmp_path / "risk" / "capital.yaml"),
        (REPO_ROOT / "configs" / "domains" / "risk" / "exits.yaml", tmp_path / "risk" / "exits.yaml"),
    ):
        if src.exists():
            (tmp_path / "risk").mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text())

    reg = loader.ConfigRegistry.load(
        legacy_path=leg_path,
        domains_dir=tmp_path,
    )
    assert reg.risk.sizing.max_risk_per_trade_pct == 0.5
    assert reg.risk.sizing.min_confidence == 55.0


def test_registry_falls_back_to_legacy_when_domain_file_missing(tmp_path: Path, registry_legacy):
    """When domain files are absent, legacy YAML is the sole source."""
    loader = importlib.import_module("configs.domain_loader")
    leg_path = _make_legacy_file(registry_legacy, tmp_path)
    reg = loader.ConfigRegistry.load(
        legacy_path=leg_path,
        domains_dir=tmp_path,
    )
    assert reg.risk.sizing.max_risk_per_trade_pct == 2.0


def test_registry_audit_message_is_informative(capsys, registry):
    summary = registry.summary()
    json.dumps(summary)
    assert summary["assets"] == 22
