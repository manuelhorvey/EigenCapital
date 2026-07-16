"""PaperConfigRegistry round-trip and summary tests.

The Phase 4 ``ConfigRegistry`` (``configs/domain_loader.py``) was deleted
in Phase 12.7 — ``PaperConfigRegistry`` (``configs/paper_config_registry.py``)
is the sole typed configuration loader. These tests validate its
``load()``, ``as_legacy_dict()``, and ``summary()`` methods.

The legacy ``paper_trading.yaml`` was deleted in Phase 12.7 — all config
keys are promoted to domain files under ``configs/domains/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from configs.paper_config_registry import PaperConfigRegistry  # noqa: E402


def _load_reg() -> PaperConfigRegistry:
    return PaperConfigRegistry.load()


def _legacy_dict() -> dict:
    return _load_reg().as_legacy_dict()


def test_registry_loads_without_error() -> None:
    reg = _load_reg()
    assert reg is not None


def test_registry_summary_shape() -> None:
    summary = _load_reg().summary()
    assert summary["assets"] == 22
    assert summary["sell_only"] == ["CADCHF", "EURAUD", "EURCHF", "GBPCHF", "GBPJPY", "NZDCHF"]
    assert summary["sizing_fields"] == 31
    assert summary["legacy_extras"] == []  # all keys promoted


def test_as_legacy_dict_contains_required_top_level_keys() -> None:
    out = _legacy_dict()
    for k in ("capital", "position_size", "portfolio_drawdown_limit", "defaults", "assets"):
        assert k in out, f"missing top-level key: {k}"


def test_as_legacy_dict_capital_values() -> None:
    out = _legacy_dict()
    assert out["capital"] == 100000
    assert out["position_size"] == 0.95
    assert out["portfolio_drawdown_limit"] == -0.15


def test_as_legacy_dict_defaults_contains_sizing_fields() -> None:
    out = _legacy_dict()
    defaults = out["defaults"]
    for k in (
        "rolling_window_bars",
        "max_risk_per_trade_pct",
        "net_short_concentration_threshold",
        "size_taper_min",
        "mt5_enable_max_risk_per_trade_pct",
        "min_confidence",
    ):
        assert k in defaults, f"missing sizing field: {k}"


def test_as_legacy_dict_sell_only() -> None:
    out = _legacy_dict()
    sell_only = out["defaults"]["sell_only_assets"]
    assert isinstance(sell_only, list)
    assert "CADCHF" in sell_only
    assert "EURAUD" in sell_only
    assert "NZDCHF" in sell_only
    assert len(sell_only) == 6


def test_as_legacy_dict_adaptive_exit() -> None:
    out = _legacy_dict()
    ae = out["defaults"]["adaptive_exit"]
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
        assert k in ae, f"missing adaptive_exit key: {k}"


def test_as_legacy_dict_assets_round_trip() -> None:
    out = _legacy_dict()
    assets = out["assets"]
    assert len(assets) == 22
    # Spot-check a few assets
    for name in ("USDCAD", "BTCUSD", "GC", "CADCHF"):
        assert name in assets, f"missing asset: {name}"
        a = assets[name]
        assert "ticker" in a
        assert "allocation" in a
        assert "sl_mult" in a
        assert "tp_mult" in a
        assert "config" in a


def test_as_legacy_dict_assets_have_adaptive_exit_config() -> None:
    """Each asset should have adaptive_exit inside the config block."""
    out = _legacy_dict()
    for name, a in out["assets"].items():
        cfg = a.get("config", {})
        assert "adaptive_exit" in cfg, f"{name} missing adaptive_exit in config"
        ae = cfg["adaptive_exit"]
        assert "trail_activation_r" in ae


def test_as_legacy_dict_halt() -> None:
    out = _legacy_dict()
    halt = out.get("halt", {})
    assert halt.get("drawdown") == -0.08
    assert halt.get("monthly_pf") == 0.70
    assert halt.get("signal_drought") == 30
    assert halt.get("prob_drift") == 0.25


def test_as_legacy_dict_mt5() -> None:
    out = _legacy_dict()
    mt5 = out.get("mt5", {})
    assert mt5.get("enabled") is True
    assert mt5.get("bridge_port") == 9879
    assert mt5.get("bridge_host") == "127.0.0.1"


def test_as_legacy_dict_execution_governance() -> None:
    out = _legacy_dict()
    execution = out.get("execution", {})
    governance = execution.get("governance", {})
    # regime_geometry
    assert "regime_geometry" in governance
    rg = governance["regime_geometry"]
    for band in ("GREEN", "YELLOW", "RED"):
        assert band in rg
    # liquidity_config
    assert "liquidity_config" in governance
    liq = governance["liquidity_config"]
    assert liq.get("enabled") is True
    # narrative_config
    assert "narrative_config" in governance
    nar = governance["narrative_config"]
    assert "fxstreet_url" in nar


def test_as_legacy_dict_modes() -> None:
    out = _legacy_dict()
    modes = out.get("modes", {})
    assert "production" in modes
    assert "challenge_ftmo_10k" in modes
    assert "live" in modes
    assert modes["production"]["capital"] == 100000
    assert modes["challenge_ftmo_10k"]["capital"] == 10000


def test_as_legacy_dict_round_trips_to_valid_yaml() -> None:
    """The legacy dict should be YAML-serializable (no non-serializable types)."""
    out = _legacy_dict()
    yaml_text = yaml.safe_dump(out, sort_keys=False)
    reloaded = yaml.safe_load(yaml_text)
    assert reloaded == out


def test_registry_summary_is_json_serializable() -> None:
    summary = _load_reg().summary()
    json.dumps(summary)


def test_registry_has_no_legacy_extras() -> None:
    """All keys should be promoted — legacy_extras should be empty."""
    reg = _load_reg()
    assert len(reg.legacy_extras) == 0


def test_registry_asset_sources_all_domain() -> None:
    """All 22 assets should come from domain files, not legacy."""
    reg = _load_reg()
    for source in reg.asset_sources.values():
        assert source == "domain", f"asset {source} sourced from legacy"
    assert len(reg.asset_sources) == 22


def test_registry_alerting_promoted() -> None:
    reg = _load_reg()
    assert "channels" in reg.alerting
    assert "pagerduty" in reg.alerting["channels"]
    assert "webhook" in reg.alerting["channels"]


def test_registry_calibration_promoted() -> None:
    reg = _load_reg()
    assert reg.calibration.get("enabled") is True
    assert reg.calibration.get("method") == "platt"


def test_registry_ensemble_promoted() -> None:
    reg = _load_reg()
    assert reg.ensemble.get("base_weight") == 1.0


def test_registry_spread_gate_promoted() -> None:
    reg = _load_reg()
    assert reg.spread_gate.get("enabled") is True
    assert "fx_major" in reg.spread_gate.get("tiers", {})


def test_registry_session_gate_promoted() -> None:
    reg = _load_reg()
    assert reg.session_gate.get("enabled") is True
    assert "crypto" in reg.session_gate.get("tiers", {})


# ── Environment overlays ──────────────────────────────────────────────


def test_registry_environments_loaded() -> None:
    """All 5 environment files should be loaded by Step 1r."""
    reg = _load_reg()
    expected = {"backtest", "live", "paper", "research", "test"}
    assert set(reg.environments.keys()) == expected


def test_registry_environment_name_default() -> None:
    """Default environment name is 'paper'."""
    reg = _load_reg()
    assert reg.environment_name == "paper"


def test_environment_overlay_applied_in_as_legacy_dict() -> None:
    """The 'paper' environment overlays data_source, rebalance, research_mode.
    These match the domain defaults, so the overlay is a no-op for paper."""
    out = _legacy_dict()
    assert out.get("data_source") == "mt5"
    assert out.get("rebalance") == "daily"
    assert out.get("research_mode") is False


def test_environment_test_overrides_mt5_and_alerting() -> None:
    """The 'test' environment disables MT5 and alerting."""
    reg = _load_reg()
    reg.environment_name = "test"
    out = reg.as_legacy_dict()
    assert out.get("data_source") == "yfinance"
    assert out.get("research_mode") is True
    assert out.get("rebalance") == "none"
    mt5 = out.get("mt5", {})
    assert mt5.get("enabled") is False
    alerting = out.get("alerting", {})
    channels = alerting.get("channels", {})
    assert channels.get("pagerduty", {}).get("enabled") is False
    assert channels.get("webhook", {}).get("enabled") is False


def test_environment_live_overrides_mt5() -> None:
    """The 'live' environment enables MT5 with specific bridge settings."""
    reg = _load_reg()
    reg.environment_name = "live"
    out = reg.as_legacy_dict()
    mt5 = out.get("mt5", {})
    assert mt5.get("enabled") is True
    assert mt5.get("bridge_port") == 9879
    assert mt5.get("bridge_host") == "127.0.0.1"


def test_environment_backtest_overrides() -> None:
    """The 'backtest' environment uses yfinance and disables rebalance."""
    reg = _load_reg()
    reg.environment_name = "backtest"
    out = reg.as_legacy_dict()
    assert out.get("data_source") == "yfinance"
    assert out.get("research_mode") is True
    assert out.get("rebalance") == "none"


def test_summary_includes_environments() -> None:
    """summary() should report environment info."""
    summary = _load_reg().summary()
    assert "environments" in summary
    assert len(summary["environments"]) == 5
    assert summary["environment_name"] == "paper"
