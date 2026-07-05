"""Tests for gate_constants config-driven SELL_ONLY_ASSETS resolution."""

from __future__ import annotations

from typing import Final

import pytest

from paper_trading.config_manager import EngineConfig
from paper_trading.execution.gate_constants import (
    SPREAD_TIER_BPS,
    get_sell_only_assets,
)

_KNOWN_SELL_ONLY: Final[frozenset[str]] = frozenset(
    {
        "CADCHF",
        "NZDCHF",
        "EURAUD",
    }
)


def test_get_sell_only_assets_returns_default_set() -> None:
    """Should return the known 3-asset set from config."""
    import paper_trading.config_manager as cm

    cm.reset_config()
    # Config auto-loads from PaperConfigRegistry (domain tree)
    assets = get_sell_only_assets()
    assert isinstance(assets, frozenset)
    assert assets == _KNOWN_SELL_ONLY
    assert len(assets) == 3
    cm.reset_config()


def test_get_sell_only_assets_includes_known_assets() -> None:
    """Each known asset should be present in the returned set."""
    assets = get_sell_only_assets()
    for asset in _KNOWN_SELL_ONLY:
        assert asset in assets, f"{asset} should be in SELL_ONLY_ASSETS"


def test_get_sell_only_assets_excludes_non_sell_only() -> None:
    """Assets known to have been removed should not be in the set."""
    removed = {"GBPJPY", "USDCHF", "EURCHF", "USDJPY", "^DJI", "AUDUSD", "EURNZD", "NZDUSD"}
    assets = get_sell_only_assets()
    for asset in removed:
        assert asset not in assets, f"{asset} should NOT be in SELL_ONLY_ASSETS"


def test_sell_only_assets_not_empty() -> None:
    """The SELL_ONLY_ASSETS set should never be empty."""
    assets = get_sell_only_assets()
    assert len(assets) > 0


@pytest.mark.parametrize("asset", sorted(_KNOWN_SELL_ONLY))
def test_each_sell_only_asset_individually(asset: str) -> None:
    """Parametrized check that each asset is in the sell-only set."""
    assert asset in get_sell_only_assets()


def test_get_sell_only_assets_respects_config_override() -> None:
    """Should return custom set when config is loaded with sell_only_assets."""
    import paper_trading.config_manager as cm

    cm.reset_config()
    custom = {"CUSTOM1", "CUSTOM2"}
    cfg = EngineConfig()
    cfg.sell_only_assets = frozenset(custom)
    cm._GLOBAL_CONFIG = cfg
    try:
        assets = get_sell_only_assets()
        assert assets == frozenset(custom)
    finally:
        cm.reset_config()


def test_get_sell_only_assets_empty_config_raises() -> None:
    """Should raise RuntimeError when config has empty sell_only_assets."""
    import paper_trading.config_manager as cm

    cm.reset_config()
    cfg = EngineConfig()
    cfg.sell_only_assets = frozenset()
    cm._GLOBAL_CONFIG = cfg
    try:
        with pytest.raises(RuntimeError, match="SELL_ONLY_ASSETS not configured"):
            get_sell_only_assets()
    finally:
        cm.reset_config()


def test_spread_tier_bps_structure() -> None:
    """SPREAD_TIER_BPS should have expected structure and values."""
    assert "fx_major" in SPREAD_TIER_BPS
    assert "fx_cross" in SPREAD_TIER_BPS
    assert "indices" in SPREAD_TIER_BPS
    assert "metals" in SPREAD_TIER_BPS
    assert all(v > 0 for v in SPREAD_TIER_BPS.values())
