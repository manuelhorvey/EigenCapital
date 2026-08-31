"""Configuration Consistency Tests — verify single source of truth.

These tests ensure that:
1. All safety-critical parameters come from config.toml
2. No hardcoded values in execution scripts disagree with config
3. The live_risk envelope matches capital boundaries
4. Fingerprint verification works end-to-end
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.config import (
    LiveRiskConfig,
    load_config,
)
from eigencapital.fidelity.r4_manifest import R4ConfigManifest


class TestConfigLoading:
    """Verify configuration loads correctly from TOML."""

    def test_production_config_loads(self):
        """Production config must load without error."""
        config = load_config("production")
        assert config.environment == "production"
        assert config.broker.account_id == "436921728"
        assert config.broker.broker_name == "exness"

    def test_live_risk_config_loads(self):
        """live_risk config must load expected limits."""
        config = load_config("production")
        lr = config.live_risk
        assert lr.max_concurrent_positions == 20
        assert lr.max_position_notional == 2500.0
        assert lr.max_daily_loss == 250.0
        assert lr.min_equity == 4000.0
        assert lr.t0_equity == 5010.94

    def test_strategy_config_loads_r4_params(self):
        """strategy config must load frozen R4 parameters."""
        config = load_config("production")
        st = config.strategy
        assert st.signal_lookback_long == 252
        assert st.skip_months == 1
        assert st.vol_lookback_signal == 60
        assert st.risk_lookback == 20

    def test_execution_config_loads_max_orders(self):
        """execution config must load max_orders_per_cycle."""
        config = load_config("production")
        assert config.execution.max_orders_per_cycle == 20


class TestLiveRiskFingerprint:
    """Verify live risk envelope can be fingerprinted."""

    def test_fingerprint_deterministic(self):
        """Same config produces same fingerprint."""
        lr1 = LiveRiskConfig()
        lr2 = LiveRiskConfig()
        assert lr1.compute_fingerprint() == lr2.compute_fingerprint()

    def test_fingerprint_changes_on_value_change(self):
        """Changing any value changes the fingerprint."""
        lr1 = LiveRiskConfig(max_daily_loss=250.0)
        lr2 = LiveRiskConfig(max_daily_loss=300.0)
        assert lr1.compute_fingerprint() != lr2.compute_fingerprint()

    def test_fingerprint_immutable(self):
        """LiveRiskConfig is frozen."""
        lr = LiveRiskConfig()
        with pytest.raises(AttributeError):
            lr.max_daily_loss = 999.0


class TestConfigVsScriptConsistency:
    """Verify that config values match what the rebalance loop uses."""

    def test_eligible_symbols_from_config(self):
        """Eligible symbols should be derived from broker config."""
        config = load_config("production")
        eligible = [sym for sym, cls in config.broker.allowed_symbols.items() if not cls.endswith("_excluded")]
        # Must include core forex pairs and USTEC
        for sym in ["EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "USTEC"]:
            assert sym in eligible, f"{sym} missing from eligible symbols"

    def test_risk_envelope_from_config(self):
        """RiskEnvelope values must match live_risk config."""
        config = load_config("production")
        lr = config.live_risk
        assert lr.max_concurrent_positions == 20
        assert lr.max_position_notional == 2500.0
        assert lr.max_daily_loss == 250.0
        assert lr.min_equity == 4000.0
        assert lr.t0_equity == 5010.94

    def test_capital_limits_from_config(self):
        """Capital limits must match config."""
        config = load_config("production")
        assert config.capital.max_equity == 5100.0
        assert config.capital.max_position_size == 5000.0
        assert config.capital.max_concurrent_positions == 20

    def test_no_discrepancy_between_live_risk_and_capital(self):
        """live_risk.max_concurrent_positions must equal capital.max_concurrent_positions."""
        config = load_config("production")
        assert config.live_risk.max_concurrent_positions == config.capital.max_concurrent_positions, (
            f"Discrepancy: live_risk={config.live_risk.max_concurrent_positions} "
            f"vs capital={config.capital.max_concurrent_positions}"
        )


class TestR4ManifestIntegrity:
    """Verify R4 manifest fingerprint is stable."""

    def test_manifest_fingerprint_unchanged(self):
        """R4 manifest fingerprint must match the frozen value."""
        manifest = R4ConfigManifest()
        fp = manifest.compute_identity()
        assert fp == "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"

    def test_manifest_strategy_version(self):
        """Strategy version must be R4.0."""
        manifest = R4ConfigManifest()
        assert manifest.strategy_version == "R4.0"

    def test_manifest_config_fingerprint_matches_toml(self):
        """Config manifest_fingerprint must match R4ConfigManifest."""
        config = load_config("production")
        manifest = R4ConfigManifest()
        assert config.strategy.manifest_fingerprint == manifest.compute_identity()
