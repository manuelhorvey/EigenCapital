"""Tests for the Phase 3 typed domain models — read-side mirror parity.

Goal: assert that the typed ``RiskConfig`` / per-asset
``AssetConfig`` models rebuild the legacy ``EngineConfig`` surface
losslessly when round-tripped through the new typed layer.

These tests guard the Phase 4 write-mode split: legacy consumers can
continue to read the legacy dict shape until they migrate, because
the typed model can re-emit a byte-identical copy of the legacy YAML.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import fields
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

risk_mod = importlib.import_module("configs.domain_models.risk")
assets_mod = importlib.import_module("configs.domain_models.assets")


@pytest.fixture(scope="module")
def legacy_yaml() -> dict:
    path = REPO_ROOT / "configs" / "paper_trading.yaml"
    return yaml.safe_load(path.read_text())


# ── RiskConfig ────────────────────────────────────────────────────────


def test_risk_config_exposes_all_legacy_keys(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assert rc.capital.initial == legacy_yaml["capital"]
    assert rc.capital.position_size == legacy_yaml["position_size"]
    assert rc.capital.portfolio_drawdown_limit == legacy_yaml["portfolio_drawdown_limit"]

    # Halt defaults fill the legacy defaults shape
    assert rc.halt.drawdown == -0.08
    assert rc.halt.monthly_pf == 0.70
    assert rc.halt.signal_drought == 30
    assert rc.halt.prob_drift == 0.25
    assert rc.halt.prob_drift_min_samples == 10

    defaults = legacy_yaml["defaults"]
    assert rc.sizing.rolling_window_bars == defaults["rolling_window_bars"]
    assert rc.sizing.max_risk_per_trade_pct == defaults["max_risk_per_trade_pct"]
    assert rc.sizing.net_short_concentration_threshold == defaults["net_short_concentration_threshold"]
    assert rc.sizing.size_taper_min == defaults["size_taper_min"]
    assert rc.sizing.mt5_enable_max_risk_per_trade_pct == defaults["mt5_enable_max_risk_per_trade_pct"]


def test_risk_config_exhausts_legacy_defaults_keys(legacy_yaml):
    """Every key in legacy defaults.* must have a typed counterpart
    or be in a known-exclusion list. Prevents drift where a new key
    is added to YAML without propagating to the typed model.
    """
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    sizing_field_names = {f.name for f in fields(risk_mod.SizingConfig)}

    legacy_keys = set((legacy_yaml.get("defaults") or {}).keys())
    # Adapter fields not yet in SizingConfig:
    known_excluded = {
        "adaptive_exit",
        "stacking",
        "sell_only_assets",  # promoted to SellOnlyConfig
        "spread_gate",
        "session_gate",
        "adx_entry_gate",
        "entry_optimization",
        # Phase 11.3: these flatten up to top-level in the legacy mirror
        # (they were misplaced nested under defaults in pre-Phase-11 YAML)
        "data_source",
        "rebalance",
        "research_mode",
        "retrain_freq",
        "retrain_window",
    }
    legacy_keys.difference_update(known_excluded)
    missing = legacy_keys - sizing_field_names
    assert not missing, f"Legacy defaults keys not present in SizingConfig: {sorted(missing)}"


def test_sell_only_assets_resolves_to_frozenset(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    expected = frozenset({"CADCHF", "NZDCHF", "EURAUD"})
    assert rc.sell_only.assets == expected


def test_exit_with_overrides_rejects_unknown_keys():
    base = risk_mod.ExitConfig()
    with pytest.raises(TypeError):
        base.with_overrides(nonexistent=1.0)


def test_exit_with_overrides_applies_changes():
    base = risk_mod.ExitConfig()
    out = base.with_overrides(be_lock_r=0.7)
    assert out.be_lock_r == 0.7
    assert out.trail_activation_r == base.trail_activation_r


# ── AssetConfig ───────────────────────────────────────────────────────


def test_assets_map_round_trips(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assets = assets_mod.assets_from_legacy(legacy_yaml["assets"], rc.exits_default)
    assert set(assets) == set(legacy_yaml["assets"])

    for name, raw in legacy_yaml["assets"].items():
        rebuilt = assets[name].to_legacy_dict()
        # Compare on the *shape* of the typed surface — the extras dict
        # carries keys not yet promoted.
        assert rebuilt["ticker"] == raw["ticker"]
        assert rebuilt["allocation"] == raw["allocation"]
        assert rebuilt["sl_mult"] == raw["sl_mult"]
        assert rebuilt["tp_mult"] == raw["tp_mult"]
        if "spread_tier" in raw:
            assert rebuilt["spread_tier"] == raw["spread_tier"]


def test_asset_regime_geometry_round_trips(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assets = assets_mod.assets_from_legacy(legacy_yaml["assets"], rc.exits_default)

    for name, raw in legacy_yaml["assets"].items():
        rebuilt = assets[name].to_legacy_dict()
        legacy_geom = raw.get("regime_geometry") or {}
        for band in ("GREEN", "YELLOW", "RED"):
            if band in legacy_geom:
                assert rebuilt["regime_geometry"][band]["sl_mult"] == legacy_geom[band]["sl_mult"]
                assert rebuilt["regime_geometry"][band]["tp_mult"] == legacy_geom[band]["tp_mult"]


def test_asset_adaptive_exit_overlay_applies(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assets = assets_mod.assets_from_legacy(legacy_yaml["assets"], rc.exits_default)

    # USDCAD has the default trail_activation_r 0.8; NZDUSD has 0.5
    assert assets["USDCAD"].adaptive_exit.trail_activation_r == 0.8
    assert assets["NZDUSD"].adaptive_exit.trail_activation_r == 0.5


def test_asset_adaptive_exit_inherits_defaults_when_missing():
    raw = {"ticker": "DEMO=X", "allocation": 0.05, "sl_mult": 1.0, "tp_mult": 1.5}
    base_exit = risk_mod.ExitConfig()
    asset = assets_mod.AssetConfig.from_dict("DEMO", raw, base_exit)
    assert asset.adaptive_exit.be_lock_r == base_exit.be_lock_r
    assert asset.adaptive_exit.trail_retrace_pct == base_exit.trail_retrace_pct


def test_btc_weekend_eligibility_preserved(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assets = assets_mod.assets_from_legacy(legacy_yaml["assets"], rc.exits_default)
    assert assets["BTCUSD"].weekend_eligible is True
    assert assets["BTCUSD"].weekend_allocation_multiplier == 0.5
    rebuilt = assets["BTCUSD"].to_legacy_dict()
    assert rebuilt["weekend_eligible"] is True


def test_gc_max_entry_slippage_preserved(legacy_yaml):
    rc = risk_mod.RiskConfig.from_legacy(legacy_yaml)
    assets = assets_mod.assets_from_legacy(legacy_yaml["assets"], rc.exits_default)
    assert assets["GC"].max_entry_slippage_pct == 5.0
    assert assets["GC"].max_positions_per_asset == 1
