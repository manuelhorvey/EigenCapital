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
    """These live in the legacy YAML but have no domain file yet.

    Phase 12.2c: ``halt`` promoted to configs/domains/risk/halt.yaml.
    Phase 12.3: ``data_source``, ``rebalance``, ``research_mode``,
    ``retrain_freq``, ``retrain_window``, ``api_token`` promoted to
    configs/domains/infrastructure/config.yaml. Phase 12.6:
    ``mt5`` → broker/mt5.yaml, ``execution`` → governance/*.yaml,
    ``optimizations`` → infrastructure/optimizations.yaml. ``alerting``,
    ``ensemble``, ``calibration``, ``kelly``, ``meta_labeling`` pruned
    — they were NEVER consumed through ``EngineConfig`` (no matching
    fields) and are excluded from the carrier.
    """
    expected = {
        "mode",
    }
    pruned = {"kelly"}
    promoted_infra = {"data_source", "rebalance", "research_mode", "retrain_freq", "retrain_window", "api_token"}
    promoted_phase6 = {"mt5", "execution", "optimizations"}
    promoted_ml = {"calibration", "ensemble", "meta_labeling"}
    promoted_gates = {"spread_gate", "session_gate"}
    promoted_governance = {"liquidity_config", "narrative_config"}
    promoted_all = (
        promoted_infra | promoted_phase6 | promoted_ml | promoted_gates | promoted_governance
        | {"portfolio", "halt", "regime_geometry", "alerting", "modes"}
    )
    found = set(registry.legacy_extras.keys())
    assert expected.issubset(found), f"missing legacy_extras: {expected - found}"
    for k in pruned:
        assert k not in found, f"pruned key {k!r} still in legacy_extras"
    for k in promoted_all:
        assert k not in found, f"promoted key {k!r} still in legacy_extras"
    out = registry.as_legacy_dict()
    assert "halt" in out
    assert out["halt"]["drawdown"] == -0.08
    assert out.get("data_source") == "mt5"
    assert out.get("rebalance") == "daily"
    assert out.get("research_mode") is False
    assert out.get("retrain_freq") == "annual"
    assert out.get("retrain_window") == 5
    assert out.get("mt5", {}).get("enabled") is True
    assert out.get("execution", {}).get("governance", {}).get("regime_geometry") is not None
    assert out.get("optimizations", {}).get("batch_http") is True
    # portfolio promoted — must be present in legacy dict output
    assert out.get("portfolio", {}).get("weight_method") == "factor_constrained_v2"
    # regime_geometry promoted — composed into execution.governance (not standalone)
    assert out.get("execution", {}).get("governance", {}).get("regime_geometry", {}).get("GREEN") is not None
    # ML domain files promoted — emitted in defaults block
    assert out.get("defaults", {}).get("calibration", {}).get("method") == "binned"
    assert out.get("defaults", {}).get("calibration", {}).get("enabled") is True
    assert out.get("defaults", {}).get("ensemble", {}).get("base_weight") == 1.0
    assert out.get("defaults", {}).get("ensemble", {}).get("regime_feature_window") == 63
    assert out.get("defaults", {}).get("meta_labeling", {}).get("confidence_threshold") == 0.4
    assert out.get("defaults", {}).get("meta_labeling", {}).get("threshold_reduced") == 0.4
    # label_params stored on registry but NOT emitted in defaults
    assert hasattr(registry, "label_params")
    # alerting promoted — emitted as top-level key
    assert out.get("alerting", {}).get("channels", {}).get("pagerduty", {}).get("enabled") is False
    # governance domain files promoted — composed into execution.governance
    assert out.get("execution", {}).get("governance", {}).get("liquidity_config", {}).get("enabled") is True
    assert out.get("execution", {}).get("governance", {}).get("narrative_config", {}).get("enabled") is True
    # standalone fields on registry
    assert registry.liquidity_config.get("enabled") is True
    assert registry.narrative_config.get("enabled") is True


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
    # mode still in legacy_extras; modes is now promoted
    assert "mode" in registry.legacy_extras
    # as_legacy_dict re-emits them
    assert "modes" in out
