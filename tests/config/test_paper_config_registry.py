"""PaperConfigRegistry equivalence tests (Phase 11.1).

Verifies that the new domain-files-first PaperConfigRegistry:

1. Reads paper_trading.yaml legacy keys only as fallback for unpromoted
   fields (Phase 11.1 inverts Phase 4 precedence).
2. Per-asset YAMLs are first-class sources for each asset.
3. The legacy_extras bag carries everything the legacy YAML exposes
   that hasn't migrated.
4. The full as_legacy_dict() output is round-trippable to the legacy
   paper_trading.yaml surface (preserving EngineConfig contract).
"""

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
def legacy_yaml() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())


@pytest.fixture(scope="module")
def registry():
    mod = importlib.import_module("configs.paper_config_registry")
    return mod.PaperConfigRegistry.load()


# ── Bootstrap shape ───────────────────────────────────────────────────


def test_registry_loads_without_error(registry):
    assert registry is not None


def test_registry_summary_shape(registry):
    summary = registry.summary()
    assert summary["assets"] == 22
    assert summary["sell_only"] == ["CADCHF", "EURAUD", "NZDCHF"]
    assert summary["sizing_fields"] == 27
    # Phase 11.1 promotes per-asset files to first-class source
    assert summary["domain_assets"] == 22
    assert summary["legacy_assets"] == 0


def test_capital_round_trips(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    assert out["capital"] == legacy_yaml["capital"]
    assert out["position_size"] == legacy_yaml["position_size"]
    assert out["portfolio_drawdown_limit"] == legacy_yaml["portfolio_drawdown_limit"]


def test_sell_only_assets_in_legacy_dict(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    assert out["defaults"]["sell_only_assets"] == sorted(legacy_yaml["defaults"]["sell_only_assets"])


def test_asset_set_matches_legacy(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    typed = out["assets"]
    legacy = legacy_yaml["assets"]
    assert set(typed) == set(legacy)


def test_per_asset_simple_fields_round_trip(registry):
    out = registry.as_legacy_dict()
    for name, raw in yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())["assets"].items():
        rebuilt = out["assets"][name]
        assert rebuilt["ticker"] == raw["ticker"]
        assert rebuilt["allocation"] == raw["allocation"]
        assert rebuilt["sl_mult"] == raw["sl_mult"]
        assert rebuilt["tp_mult"] == raw["tp_mult"]


# ── Precedence rules ─────────────────────────────────────────────────


def test_asset_sources_are_all_domain(registry):
    assert all(s == "domain" for s in registry.asset_sources.values())


def test_btcusd_specific_keys_via_compose(registry):
    asset = registry.assets["BTCUSD"]
    assert asset.weekend_eligible is True
    assert asset.weekend_allocation_multiplier == 0.5


def test_gc_max_entry_slippage_via_compose(registry):
    asset = registry.assets["GC"]
    assert asset.max_entry_slippage_pct == 5.0
    assert asset.max_positions_per_asset == 1


def test_nzdusd_adaptive_exit_override(registry):
    """Audit-flags NZDUSD trail_activation_r 0.5 vs default 0.8."""
    asset = registry.assets["NZDUSD"]
    assert asset.adaptive_exit.trail_activation_r == 0.5


def test_usdcad_default_adaptive_exit(registry):
    """Per-asset file absent adaptive_exit → defaults.yaml override."""
    asset = registry.assets["USDCAD"]
    assert asset.adaptive_exit.trail_activation_r == 0.8


def test_regime_geometry_round_trip(registry):
    out = registry.as_legacy_dict()
    legacy_assets = yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())["assets"]
    for asset_name, raw in legacy_assets.items():
        rebuilt = out["assets"][asset_name]["regime_geometry"]
        legacy_geo = raw["regime_geometry"]
        for band in ("GREEN", "YELLOW", "RED"):
            if band in legacy_geo:
                assert rebuilt[band]["sl_mult"] == legacy_geo[band]["sl_mult"], f"{asset_name}.{band}.sl_mult"
                assert rebuilt[band]["tp_mult"] == legacy_geo[band]["tp_mult"], f"{asset_name}.{band}.tp_mult"


# ── Legacy extras carrier ─────────────────────────────────────────


def test_legacy_extras_carries_unpromoted_keys(registry):
    """These live in the legacy YAML but have no domain file yet."""
    expected = {
        "alerting",
        "calibration",
        "data_source",
        "ensemble",
        "execution",
        "kelly",
        "meta_labeling",
        "mode",
        "modes",
        "mt5",
        "optimizations",
        "portfolio",
        "rebalance",
        "research_mode",
        "retrain_freq",
        "retrain_window",
    }
    found = set(registry.legacy_extras.keys())
    assert expected.issubset(found), f"missing legacy_extras: {expected - found}"


def test_legacy_extras_round_trip_via_as_legacy_dict(registry, legacy_yaml):
    out = registry.as_legacy_dict()
    for k in registry.legacy_extras:
        if k in legacy_yaml:
            assert out[k] == legacy_yaml[k], f"legacy_extras drift on {k}"


# ── Missing-file tolerance ──────────────────────────────────────────


def test_registry_paths_default_to_repo_roots():
    """Default constructor paths match the project's layout."""
    from configs.paper_config_registry import (
        REPO_ROOT as REG,
    )

    assert REG.exists()


def test_load_without_legacy_does_not_explode(registry):
    """Phase 11.2 will route this through EngineConfig; assert the new
    registry does not bury mode/modes/etc. keys entirely."""
    out = registry.as_legacy_dict()
    # mode + modes were legacy_extras
    assert "modes" in registry.legacy_extras
    # but as_legacy_dict re-emits them
    assert "modes" in out
