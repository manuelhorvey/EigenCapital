"""PaperConfigRegistry equivalence tests (Phase 11.1).

Verifies that the domain-first PaperConfigRegistry loads successfully
from the domain tree without the legacy paper_trading.yaml file
(which was deleted in Phase 12.7).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def registry():
    mod = importlib.import_module("configs.paper_config_registry")
    return mod.PaperConfigRegistry.load()


# ── Bootstrap shape ───────────────────────────────────────────────────


def test_registry_loads_without_error(registry):
    """Registry loads successfully from domain tree alone (no legacy file)."""
    assert registry is not None


def test_registry_summary_shape(registry):
    summary = registry.summary()
    assert summary["assets"] == 22
    assert summary["sell_only"] == ["CADCHF", "EURAUD", "NZDCHF"]
    assert summary["sizing_fields"] == 29
    assert summary["domain_assets"] == 22
    assert summary["legacy_assets"] == 0


def test_capital_values_from_domain(registry):
    """Capital, position_size, drawdown_limit come from domain files."""
    out = registry.as_legacy_dict()
    assert out["capital"] == 100000.0
    assert out["position_size"] == 0.95
    assert out["portfolio_drawdown_limit"] == -0.15


def test_sell_only_assets_in_legacy_dict(registry):
    out = registry.as_legacy_dict()
    assert out["defaults"]["sell_only_assets"] == ["CADCHF", "EURAUD", "NZDCHF"]


def test_asset_set_expected_size(registry):
    out = registry.as_legacy_dict()
    assert len(out["assets"]) == 22


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


# ── Legacy extras carrier ─────────────────────────────────────────


def test_legacy_extras_empty_without_legacy_file(registry):
    """With paper_trading.yaml deleted (Phase 12.7), legacy_extras
    should be empty — all keys are now promoted to domain files.
    """
    found = set(registry.legacy_extras.keys())
    assert len(found) == 0, f"expected empty legacy_extras, got {found}"
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
    assert out.get("portfolio", {}).get("weight_method") == "factor_constrained_v2"
    assert out.get("execution", {}).get("governance", {}).get("regime_geometry", {}).get("GREEN") is not None
    assert out.get("defaults", {}).get("calibration", {}).get("method") == "binned"
    assert out.get("defaults", {}).get("calibration", {}).get("enabled") is True
    assert out.get("defaults", {}).get("ensemble", {}).get("base_weight") == 1.0
    assert out.get("defaults", {}).get("ensemble", {}).get("regime_feature_window") == 63
    assert out.get("defaults", {}).get("meta_labeling", {}).get("confidence_threshold") == 0.4
    assert out.get("defaults", {}).get("meta_labeling", {}).get("threshold_reduced") == 0.4
    assert hasattr(registry, "label_params")
    assert out.get("alerting", {}).get("channels", {}).get("pagerduty", {}).get("enabled") is False
    assert out.get("execution", {}).get("governance", {}).get("liquidity_config", {}).get("enabled") is True
    assert out.get("execution", {}).get("governance", {}).get("narrative_config", {}).get("enabled") is True
    assert registry.liquidity_config.get("enabled") is True
    assert registry.narrative_config.get("enabled") is True


# ── Missing-file tolerance ──────────────────────────────────────────


def test_registry_paths_default_to_repo_roots():
    """Default constructor paths match the project's layout."""
    from configs.paper_config_registry import (
        REPO_ROOT as REG,
    )

    assert REG.exists()


def test_load_without_legacy_does_not_explode(registry):
    """Registry loads and produces output even without legacy file."""
    out = registry.as_legacy_dict()
    # legacy_extras empty — all keys promoted to domain files
    assert len(registry.legacy_extras) == 0
    # modes still emitted via promoted domain files
    assert "modes" in out
