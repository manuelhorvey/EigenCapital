"""Tests for tools/config_migrate — legacy config migration planner."""

import json
import os
import sys
import tempfile

import yaml

from tools.config_migrate import plan_from_legacy, MigrationPlan


_SAMPLE_LEGACY = {
    "capital": 100000,
    "portfolio_drawdown_limit": -0.15,
    "position_size": 0.95,
    "defaults": {
        "max_position_pct_of_equity": 0.15,
        "max_risk_per_trade_pct": 2.0,
        "min_confidence": 55.0,
        "adaptive_exit": {"enabled": True, "be_lock_r": 0.5},
    },
    "assets": {
        "EURUSD": {"ticker": "EURUSD=X", "allocation": 0.05, "sl_mult": 1.0, "tp_mult": 2.0},
        "GBPUSD": {"ticker": "GBPUSD=X", "allocation": 0.05, "sl_mult": 1.0, "tp_mult": 2.0},
    },
    "mt5": {"enabled": False, "bridge_port": 9879},
    "modes": {"paper": {"capital": 100000}},
    "alerting": {"channels": {"pagerduty": {"enabled": False}}},
    "ensemble": {"base_weight": 1.0},
    "calibration": {"enabled": True, "method": "binned"},
    "spread_gate": {"enabled": True},
    "session_gate": {"enabled": True},
    "execution": {
        "governance": {
            "regime_geometry": {"GREEN": {"sl_mult": 1.0, "tp_mult": 1.0}},
            "liquidity_config": {"regime": "normal"},
        }
    },
}


class TestPlanFromLegacy:
    def test_returns_migration_plan(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert isinstance(plan, MigrationPlan)

    def test_capital_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert plan.risk_capital["capital"] == 100000

    def test_sizing_keys_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert plan.risk_sizing["max_position_pct_of_equity"] == 0.15
        assert plan.risk_sizing["max_risk_per_trade_pct"] == 2.0
        assert plan.risk_sizing["min_confidence"] == 55.0

    def test_adaptive_exit_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "default" in plan.risk_exits
        assert plan.risk_exits["default"]["enabled"] is True

    def test_assets_indexed(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "EURUSD" in plan.assets_index
        assert "GBPUSD" in plan.assets_index

    def test_mt5_config_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "mt5" in plan.broker_mt5
        assert plan.broker_mt5["mt5"]["bridge_port"] == 9879

    def test_modes_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "paper" in plan.modes

    def test_summary_contains_all_sections(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        summary = plan.summary()
        assert "risk" in summary
        assert "portfolio" in summary
        assert "ml" in summary
        assert "broker" in summary
        assert "execution" in summary
        assert "governance" in summary
        assert "infrastructure" in summary

    def test_empty_legacy(self):
        plan = plan_from_legacy({})
        assert plan.risk_capital == {}
        assert plan.assets_index == []

    def test_governance_config_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "GREEN" in plan.governance_regime
        assert plan.governance_liquidity["regime"] == "normal"

    def test_alerting_extracted(self):
        plan = plan_from_legacy(_SAMPLE_LEGACY)
        assert "alerting" in plan.infrastructure_alerts
        assert plan.infrastructure_alerts["alerting"]["channels"]["pagerduty"]["enabled"] is False


class TestEndToEnd:
    def test_dry_run_prints_json(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_SAMPLE_LEGACY, f)
            lpath = f.name
        try:
            from tools.config_migrate import main

            sys.argv = ["config_migrate.py", "--dry-run", "--config", lpath]
            rc = main()
            assert rc == 0
            captured = capsys.readouterr()
            result = json.loads(captured.out)
            assert "risk" in result
            assert result["risk"]["capital"] is True
        finally:
            os.unlink(lpath)
