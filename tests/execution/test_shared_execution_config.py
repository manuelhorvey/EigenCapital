import numpy as np
import pytest

from shared.execution_config import (
    ExecutionConfig,
    btc_execution_config,
    DEFAULT_EXECUTION_CONFIGS,
    compute_slippage_cost,
    execution_config_from_dict,
    build_execution_configs,
    compute_market_impact,
)


# ── ExecutionConfig ──────────────────────────────────────────────────────────

def test_execution_config_defaults():
    cfg = ExecutionConfig()
    assert cfg.base_spread_bps == 0.5
    assert cfg.spread_max_bps == 50.0
    assert cfg.impact_model == "none"
    assert cfg.min_fill_prob == 0.60


def test_btc_config_different_from_default():
    btc = btc_execution_config()
    default = ExecutionConfig()
    assert btc.base_spread_bps != default.base_spread_bps
    assert btc.spread_max_bps == 150.0
    assert btc.min_fill_prob == 0.30


def test_compute_slippage_cost_zero_vol():
    cfg = ExecutionConfig()
    cost = compute_slippage_cost(np.array([0.0, 0.5, 1.0]), cfg)
    expected_base = (0.5 + 0.5) / 10000  # base_spread_bps + latency_bps
    assert cost[0] == pytest.approx(expected_base)
    assert cost[2] == pytest.approx(expected_base)


def test_compute_slippage_cost_high_vol():
    cfg = ExecutionConfig()
    cost = compute_slippage_cost(np.array([3.0]), cfg)
    expected = (0.5 * (1.0 + 2.0 * 2.0) + 0.5) / 10000  # base + latency
    assert cost[0] == pytest.approx(expected)


def test_compute_slippage_cost_capped():
    cfg = ExecutionConfig(spread_max_bps=10.0, spread_vol_slope=1.0)
    cost = compute_slippage_cost(np.array([50.0]), cfg)
    assert cost[0] == pytest.approx(cfg.spread_max_bps / 10000)


# ── execution_config_from_dict ───────────────────────────────────────────────

def test_from_dict_empty():
    cfg = execution_config_from_dict(None)
    assert isinstance(cfg, ExecutionConfig)
    assert cfg.base_spread_bps == 0.5


def test_from_dict_with_overrides():
    cfg = execution_config_from_dict({"base_spread_bps": 1.5, "spread_max_bps": 100.0})
    assert cfg.base_spread_bps == 1.5
    assert cfg.spread_max_bps == 100.0


def test_from_dict_ignores_invalid_keys():
    cfg = execution_config_from_dict({"invalid": 42, "base_spread_bps": 2.0})
    assert cfg.base_spread_bps == 2.0
    assert not hasattr(cfg, "invalid")


# ── build_execution_configs ──────────────────────────────────────────────────

def test_build_execution_configs_default():
    configs = build_execution_configs({})
    assert "default" in configs
    assert "BTC" in configs


def test_build_execution_configs_asset_override():
    assets = {
        "EURUSD": {"ticker": "EURUSD=X", "execution_config": {"base_spread_bps": 1.0}}
    }
    configs = build_execution_configs(assets)
    cfg = configs["EURUSD=X"]
    assert cfg.base_spread_bps == 1.0


def test_build_execution_configs_defaults_dict():
    configs = build_execution_configs({}, defaults={"base_spread_bps": 2.0})
    assert configs["default"].base_spread_bps == 2.0


# ── compute_market_impact ────────────────────────────────────────────────────

def test_market_impact_none():
    cfg = ExecutionConfig(impact_model="none")
    assert compute_market_impact(1e6, cfg) == 0.0


def test_market_impact_linear():
    cfg = ExecutionConfig(impact_model="linear", impact_coeff=0.1, avg_daily_volume=1e9)
    impact = compute_market_impact(1e7, cfg)
    assert impact > 0.0


def test_market_impact_square_root():
    cfg = ExecutionConfig(impact_model="square_root", impact_coeff=0.1, avg_daily_volume=1e9)
    impact = compute_market_impact(1e7, cfg)
    assert impact > 0.0


def test_market_impact_zero_adv():
    cfg = ExecutionConfig(impact_model="linear", avg_daily_volume=0)
    assert compute_market_impact(1e6, cfg) == 0.0


def test_market_impact_unknown_model():
    cfg = ExecutionConfig(impact_model="cubic")
    assert compute_market_impact(1e6, cfg) == 0.0


# ── DEFAULT_EXECUTION_CONFIGS ────────────────────────────────────────────────

def test_default_execution_configs_has_btc():
    assert "BTC" in DEFAULT_EXECUTION_CONFIGS
    assert "default" in DEFAULT_EXECUTION_CONFIGS
    assert isinstance(DEFAULT_EXECUTION_CONFIGS["BTC"], ExecutionConfig)
