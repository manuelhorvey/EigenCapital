"""Tests for shared/execution_config.py."""

from __future__ import annotations

import numpy as np
import pytest

from shared.execution_config import (
    DEFAULT_EXECUTION_CONFIGS,
    ExecutionConfig,
    btc_execution_config,
    build_execution_configs,
    compute_market_impact,
    compute_slippage_cost,
    execution_config_from_dict,
)


class TestExecutionConfig:
    def test_default_values(self):
        cfg = ExecutionConfig()
        assert cfg.base_spread_bps == 0.5
        assert cfg.spread_vol_slope == 2.0
        assert cfg.spread_max_bps == 50.0
        assert cfg.impact_model == "none"
        assert cfg.vol_window == 21

    def test_btc_config_has_higher_spread(self):
        cfg = btc_execution_config()
        assert cfg.base_spread_bps == 2.0
        assert cfg.spread_max_bps == 150.0
        assert cfg.gap_max_bps == 1000.0
        assert cfg.min_fill_prob == 0.30

    def test_default_configs_contains_btc_and_default(self):
        assert "BTC" in DEFAULT_EXECUTION_CONFIGS
        assert "default" in DEFAULT_EXECUTION_CONFIGS
        assert isinstance(DEFAULT_EXECUTION_CONFIGS["BTC"], ExecutionConfig)

    def test_execution_config_from_dict_empty(self):
        cfg = execution_config_from_dict(None)
        assert cfg.base_spread_bps == 0.5
        assert isinstance(cfg, ExecutionConfig)

    def test_execution_config_from_dict_merges(self):
        cfg = execution_config_from_dict({"base_spread_bps": 2.0, "spread_max_bps": 100.0})
        assert cfg.base_spread_bps == 2.0
        assert cfg.spread_max_bps == 100.0
        assert cfg.vol_window == 21  # unchanged default

    def test_execution_config_from_dict_ignores_invalid_keys(self):
        cfg = execution_config_from_dict({"base_spread_bps": 1.0, "nonexistent": 999})
        assert cfg.base_spread_bps == 1.0
        assert not hasattr(cfg, "nonexistent")


class TestComputeSlippageCost:
    def test_zero_vol_zscore(self):
        cfg = ExecutionConfig()
        vol = np.zeros(5)
        result = compute_slippage_cost(vol, cfg)
        # base_spread_bps + latency_bps = 0.5 + 0.5 = 1.0 bps → /10000
        expected = (cfg.base_spread_bps + cfg.latency_bps) / 10000.0
        assert np.allclose(result, expected)

    def test_high_vol_zscore_expands_spread(self):
        cfg = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=3.0, latency_bps=0.5)
        vol = np.array([3.0])  # excess = 2.0
        result = compute_slippage_cost(vol, cfg)
        # spread = 1.0 * (1 + 3.0 * 2.0) + 0.5 = 7.5 bps
        expected = 7.5 / 10000.0
        assert np.isclose(result[0], expected)

    def test_spread_capped_at_max(self):
        cfg = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=10.0, spread_max_bps=5.0, latency_bps=0.5)
        vol = np.array([5.0])  # excess = 4.0 → spread = 1*(1+40)+0.5 = 41.5 bps → capped at 5.0
        result = compute_slippage_cost(vol, cfg)
        expected = 5.0 / 10000.0
        assert np.isclose(result[0], expected)

    def test_below_threshold_no_excess(self):
        cfg = ExecutionConfig()
        vol = np.array([0.5, 0.8])  # both below 1.0 threshold → excess = 0
        result = compute_slippage_cost(vol, cfg)
        expected = (cfg.base_spread_bps + cfg.latency_bps) / 10000.0
        assert np.allclose(result, expected)


class TestBuildExecutionConfigs:
    def test_empty_assets_returns_default(self):
        configs = build_execution_configs({})
        assert "default" in configs
        assert isinstance(configs["default"], ExecutionConfig)

    def test_btc_always_included(self):
        configs = build_execution_configs({})
        assert "BTC" in configs
        assert "BTC-USD" in configs
        assert configs["BTC"].base_spread_bps == 2.0

    def test_per_asset_override(self):
        configs = build_execution_configs(
            {"EURUSD": {"ticker": "EURUSD=X", "execution_config": {"base_spread_bps": 1.0}}}
        )
        assert configs["EURUSD=X"].base_spread_bps == 1.0
        assert configs["EURUSD"].base_spread_bps == 1.0

    def test_btc_config_not_overwritten_when_present(self):
        configs = build_execution_configs({"BTC": {"ticker": "BTC-USD", "execution_config": {"base_spread_bps": 3.0}}})
        assert "BTC" in configs
        # Should use the override from the asset spec
        assert configs["BTC"].base_spread_bps == 3.0


class TestComputeMarketImpact:
    def test_impact_model_none(self):
        cfg = ExecutionConfig(impact_model="none")
        assert compute_market_impact(1_000_000, cfg) == 0.0

    def test_linear_impact(self):
        cfg = ExecutionConfig(impact_model="linear", impact_coeff=0.1, avg_daily_volume=1e9)
        impact = compute_market_impact(1_000_000, cfg)
        # participation = 1e6 / 1e9 = 0.001, impact = 0.1 * 0.001 * 10000 = 1.0 bps → /10000
        assert impact == pytest.approx(1.0 / 10000.0)

    def test_square_root_impact(self):
        cfg = ExecutionConfig(impact_model="square_root", impact_coeff=0.1, avg_daily_volume=1e9)
        impact = compute_market_impact(1_000_000, cfg)
        # participation = 0.001, impact = 0.1 * sqrt(0.001) * 10000 ≈ 31.62 bps → /10000
        assert impact > 0
        assert impact < 0.01  # less than 1%

    def test_zero_adv_returns_zero(self):
        cfg = ExecutionConfig(impact_model="linear", avg_daily_volume=0)
        assert compute_market_impact(1_000_000, cfg) == 0.0
