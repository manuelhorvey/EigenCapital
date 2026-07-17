"""Tests for Phase 11.2 — EngineConfig.load routes through PaperConfigRegistry."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_load_config_uses_registry():
    """load_config() returns an EngineConfig populated from the registry."""
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = cm.load_config()
    assert cfg.capital == 100000
    assert cfg.position_size == 0.95


def test_load_config_accepts_explicit_path(tmp_path):
    """load_config(path=...) still works when caller supplies a path.

    The path is fed into PaperConfigRegistry as the legacy_path. When
    the explicit YAML carries a key the domain tree has not yet
    promoted (e.g. api_token when not in any domain file), the explicit
    value is surfaced. For keys the domain controls (capital, sizing),
    domain wins — this is the Phase 11.1 precedence contract.
    """
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    test_yaml = tmp_path / "custom.yaml"
    test_yaml.write_text(yaml.safe_dump({"api_token": "override_token_from_test"}))

    cm.reset_config()
    cfg = cm.load_config(str(test_yaml))
    # api_token is unpromoted → legacy_extras; reads from the explicit path
    assert cfg.api_token == "override_token_from_test"


def test_load_config_explicit_path_overrides_domain():
    """Promoted keys (capital, sizing, exit) come from the explicit
    YAML when caller passes a non-default path. The default path keeps
    domain-first precedence; explicit paths are authoritative.
    """
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    # Set mode to a non-existent mode name so no mode override
    # overrides capital back (modes/production.yaml has capital: 100000).
    test_yaml = REPO_ROOT / "_explicit_domain_test.yaml"
    test_yaml.write_text(yaml.safe_dump({"capital": 12345, "mode": "test_no_override"}))
    try:
        cm.reset_config()
        cfg = cm.load_config(str(test_yaml))
        # Explicit path overrides domain when path != DEFAULT_CONFIG_PATH
        assert cfg.capital == 12345
    finally:
        test_yaml.unlink(missing_ok=True)


def test_load_config_preserves_assets_surface():
    """Phase 11.2 must produce an EngineConfig whose .assets dict
    mirrors the legacy YAML, even though loading now flows through the
    registry.
    """
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = cm.load_config()
    assert "USDCAD" in cfg.assets
    assert "BTCUSD" in cfg.assets
    assert "CADCHF" in cfg.assets


def test_load_config_uses_sell_only_assets():
    """Sell-only must surface through the registry → EngineConfig path."""
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = cm.load_config()
    assert cfg.sell_only_assets == frozenset({"CADCHF", "EURAUD", "EURCHF", "GBPCHF", "GBPJPY", "NZDCHF"})


def test_load_config_assets_match_domain_tree():
    """The registry-derived EngineConfig exposes the same 22-asset set
    as the domain tree.
    """
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = cm.load_config()
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    assert set(cfg.assets) == set(reg.assets.keys())


def test_load_config_assets_round_trip_simple_fields():
    """Tickers/allocation/sl/tp preserved through registry → EngineConfig."""
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm
    from configs.paper_config_registry import PaperConfigRegistry

    cm.reset_config()
    cfg = cm.load_config()
    reg = PaperConfigRegistry.load()
    typed = reg.as_legacy_dict()
    for name, rebuilt in typed["assets"].items():
        assert rebuilt["ticker"] == cfg.assets[name]["ticker"], f"ticker drift {name}"
        assert rebuilt["allocation"] == cfg.assets[name]["allocation"], f"allocation drift {name}"


def test_load_config_engine_config_attributes_intact():
    """All EngineConfig surface attributes still readable after registry routing."""
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = cm.load_config()
    # Spot-check several access paths large in the consumer base
    assert cfg.portfolio_drawdown_limit == -0.15
    assert cfg.rebalance in ("daily", "weekly", "monthly", "none")
    assert cfg.data_source in ("yfinance", "mt5")
    assert isinstance(cfg.mt5.bridge_port, int)
    assert 1 <= cfg.mt5.bridge_port <= 65535


def test_load_config_fallback_when_registry_fails(tmp_path, monkeypatch):
    """If the registry raises during load_config, fall back to raw YAML."""
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm
    from configs import paper_config_registry as reg_mod

    # Force PaperConfigRegistry.load to raise
    def _explode(*args, **kwargs):
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(reg_mod.PaperConfigRegistry, "load", _explode)

    cfg_yaml = tmp_path / "fallback.yaml"
    cfg_yaml.write_text(yaml.safe_dump({"capital": 12345}))

    cm.reset_config()
    cfg = cm.load_config(str(cfg_yaml))
    # EngineConfig.from_dict loaded the YAML; capital survives despite
    # the registry failure.
    assert cfg.capital == 12345
