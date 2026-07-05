"""Tests for environment overlays (Phase 8).

Phase 8 introduces configs/environments/{backtest,live,paper,research,test}.yaml
as overlays to be merged on top of the resolved mode. These tests verify:

1. Each environment file has the expected top-level keys
2. Environments differ from each other in documented ways
3. The mode-resolution logic in paper_trading.config_manager continues
   to handle the per-mode overlay (production, challenge_ftmo_10k, live)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


ENV_DIR = REPO_ROOT / "configs" / "environments"
MODES_DIR = REPO_ROOT / "configs" / "domains" / "modes"


def _load(name: str) -> dict:
    return yaml.safe_load((ENV_DIR / f"{name}.yaml").read_text())


# ── Environment files exist and parse ──────────────────────────────────


def test_environment_files_present():
    for env in ("backtest", "live", "paper", "research", "test"):
        assert (ENV_DIR / f"{env}.yaml").exists(), f"missing env: {env}"


@pytest.mark.parametrize("env", ["backtest", "live", "paper", "research", "test"])
def test_environment_loads(env):
    cfg = _load(env)
    assert isinstance(cfg, dict)


# ── Documented isolation rules ────────────────────────────────────────


def test_backtest_uses_yfinance():
    cfg = _load("backtest")
    assert cfg["data_source"] == "yfinance"
    assert cfg["research_mode"] is True
    assert cfg["rebalance"] == "none"


def test_research_uses_yfinance_and_offline():
    cfg = _load("research")
    assert cfg["data_source"] == "yfinance"
    assert cfg["research_mode"] is True
    assert cfg["rebalance"] == "none"


def test_paper_uses_mt5_daily_rebalance():
    cfg = _load("paper")
    assert cfg["data_source"] == "mt5"
    assert cfg["research_mode"] is False
    assert cfg["rebalance"] == "daily"


def test_live_overrides_mt5_connection_settings():
    cfg = _load("live")
    assert cfg["data_source"] == "mt5"
    assert cfg["mt5"]["enabled"] is True
    assert cfg["mt5"]["bridge_port"] == 9879
    assert cfg["mt5"]["bridge_host"] == "127.0.0.1"


def test_test_environment_disables_broker_and_alerting():
    cfg = _load("test")
    assert cfg["mt5"]["enabled"] is False
    assert cfg["alerting"]["channels"]["pagerduty"]["enabled"] is False
    assert cfg["alerting"]["channels"]["webhook"]["enabled"] is False
    assert cfg["research_mode"] is True


# ── Mode file isolation ────────────────────────────────────────────────


def test_mode_files_separated_by_capital():
    modes = {
        "production": 100000,
        "challenge_ftmo_10k": 10000,
        "live": 100000,
    }
    for mode_name, expected_capital in modes.items():
        cfg = yaml.safe_load((MODES_DIR / f"{mode_name}.yaml").read_text())
        assert cfg["capital"] == expected_capital


def test_modes_have_stricter_factor_limits_than_production():
    """The audit finding: modes override factor_exposure_limits for tighter
    constraints. Verify this is preserved in the per-mode files.
    """
    prod = yaml.safe_load((MODES_DIR / "production.yaml").read_text())
    challenge = yaml.safe_load((MODES_DIR / "challenge_ftmo_10k.yaml").read_text())
    assert prod["defaults"]["factor_exposure_limits"]["CHF"] == 0.20
    assert challenge["defaults"]["factor_exposure_limits"]["CHF"] == 0.15


# ── Mode-resolution (EngineConfig.from_dict) still works ───────────────


def test_engine_config_resolution_still_active():
    """The EngineConfig.from_dict mode-resolution path must still apply
    the per-mode overlay (regression guard for Phase 8)."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry
    from paper_trading.config_manager import EngineConfig

    data = PaperConfigRegistry.load().as_legacy_dict()
    cfg = EngineConfig.from_dict(data)
    assert cfg.mode == "production"
    # Top-level portfolio_drawdown_limit wins; not the mode override
    assert cfg.portfolio_drawdown_limit == -0.15


def test_mode_switch_resolves_correct_capital():
    """Switching mode to challenge_ftmo_10k applies the per-mode capital."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry
    from paper_trading.config_manager import EngineConfig

    data = PaperConfigRegistry.load().as_legacy_dict()
    data["mode"] = "challenge_ftmo_10k"
    cfg = EngineConfig.from_dict(data)
    assert cfg.capital == 10000


def test_mode_switch_resolves_correct_dd_limit():
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry
    from paper_trading.config_manager import EngineConfig

    data = PaperConfigRegistry.load().as_legacy_dict()
    data["mode"] = "live"
    cfg = EngineConfig.from_dict(data)
    # live mode override applies via _merge_mode_overrides:
    # portfolio_drawdown_limit becomes -0.1.
    assert cfg.portfolio_drawdown_limit == -0.1


def test_unknown_mode_falls_back():
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry
    from paper_trading.config_manager import EngineConfig

    data = PaperConfigRegistry.load().as_legacy_dict()
    data["mode"] = "non_existent_mode"
    cfg = EngineConfig.from_dict(data)
    # Falls back to root values; mode name preserved
    assert cfg.mode == "non_existent_mode"
    assert cfg.capital == data["capital"]


# ── Isolated: behavior of environments is deterministic ───────────────


def test_environments_produce_distinct_research_mode_outcomes():
    """Sanity: at least 2 environments produce different research_mode."""
    backtest = _load("backtest")["research_mode"]
    live = _load("live")["research_mode"]
    assert backtest != live


def test_environments_produce_distinct_data_source_outcomes():
    backtest = _load("backtest")["data_source"]
    live = _load("live")["data_source"]
    assert backtest != live


def test_each_environment_has_unique_purpose_key():
    """No two environments carry identical (data_source, research_mode) tuples,
    *OR* when they do (paper vs live both = mt5/non-research) they differ in
    intentional ways (paper keeps alerting default, live enforces MT5).
    """
    backtest = _load("backtest")
    live = _load("live")
    paper = _load("paper")
    live_mt5 = live.get("mt5", {})
    paper_mt5 = paper.get("mt5", {})
    # Live and paper share (mt5, non-research) but live specifies bridge
    # settings explicitly.
    assert live_mt5 != paper_mt5, "live vs paper should differ via mt5 block"
    backtest_key = (backtest["data_source"], backtest["research_mode"])
    paper_key = (paper["data_source"], paper["research_mode"])
    assert backtest_key != paper_key
    research_key = ("yfinance", True)
    for cfg in (backtest, _load("research"), _load("test")):
        assert (cfg["data_source"], cfg["research_mode"]) == research_key
