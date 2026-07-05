import os
import sys
import tempfile
from pathlib import Path

import yaml

from tools.check_config_schema import validate

_SAMPLE_VALID_CONFIG = {
    "capital": 100000,
    "position_size": 0.95,
    "rebalance": "daily",
    "data_source": "yfinance",
    "portfolio_drawdown_limit": -0.15,
    "mt5": {
        "enabled": False,
        "bridge_host": "127.0.0.1",
        "bridge_port": 9879,
        "min_lot": 0.05,
    },
    "assets": {
        "EURUSD": {
            "ticker": "EURUSD=X",
            "allocation": 0.05,
            "sl_mult": 1.0,
            "tp_mult": 2.0,
            "spread_tier": "fx_major",
        },
        "GC": {
            "ticker": "GC=F",
            "allocation": 0.07,
            "sl_mult": 1.0,
            "tp_mult": 4.0,
            "spread_tier": "metals",
            "max_entry_slippage_pct": 5.0,
        },
    },
    "defaults": {
        "min_confidence": 55.0,
        "max_position_pct_of_equity": 0.15,
        "max_risk_per_trade_pct": 2.0,
        "portfolio_max_leverage": 2.0,
        "sell_only_assets": ["CADCHF", "ES"],
        "spread_gate": {"enabled": True, "tiers": {"fx_major": 10}},
    },
    "ensemble": {"base_weight": 1.0, "threshold": 0.15},
    "calibration": {"enabled": True, "method": "binned"},
    "portfolio": {"weight_method": "factor_constrained_v2"},
    "alerting": {"channels": {"pagerduty": {"enabled": False}}},
}


def _write_config(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f)
    return path


class TestConfigSchema:
    def test_valid_config_passes(self):
        path = _write_config(_SAMPLE_VALID_CONFIG)
        assert validate(path) == 0
        os.unlink(path)

    def test_invalid_rebalance_fails(self):
        cfg = dict(_SAMPLE_VALID_CONFIG, rebalance="hourly")
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_invalid_data_source_fails(self):
        cfg = dict(_SAMPLE_VALID_CONFIG, data_source="bloomberg")
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_negative_capital_fails_validation(self):
        cfg = dict(_SAMPLE_VALID_CONFIG, capital=-1000)
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_bad_mt5_port_fails(self):
        cfg = dict(_SAMPLE_VALID_CONFIG)
        cfg["mt5"] = {"bridge_port": 99999}
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_empty_assets_passes(self):
        cfg = dict(_SAMPLE_VALID_CONFIG, assets={})
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    def test_asset_missing_ticker_fails(self):
        cfg = dict(_SAMPLE_VALID_CONFIG)
        cfg["assets"] = {"EURUSD": {"allocation": 0.05}}
        path = _write_config(cfg)
        # Missing ticker -> fails type check (None is not str)
        assert validate(path) == 1
        os.unlink(path)

    def test_config_file_not_found(self):
        assert validate("/nonexistent/path.yaml") == 1

    def test_invalid_yaml_syntax(self):
        path = tempfile.mktemp(suffix=".yaml")
        with open(path, "w") as f:
            f.write(": broken yaml: [\n")
        assert validate(path) == 1
        os.unlink(path)

    def test_non_dict_root_fails(self):
        path = tempfile.mktemp(suffix=".yaml")
        with open(path, "w") as f:
            f.write("[1, 2, 3]\n")
        assert validate(path) == 1
        os.unlink(path)

    def test_real_config_passes(self):
        """Validate against the PaperConfigRegistry output."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from configs.paper_config_registry import PaperConfigRegistry

        reg = PaperConfigRegistry.load()
        data = reg.as_legacy_dict()
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f)
        try:
            assert validate(path) == 0
        finally:
            os.unlink(path)

    def test_optional_execution_section(self):
        cfg = dict(_SAMPLE_VALID_CONFIG)
        cfg.pop("execution", None)
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    # ── Phase 12.2 cross-field invariant tests ─────────────────────────

    def _build(self, **overrides) -> dict:
        base = dict(_SAMPLE_VALID_CONFIG)
        base["defaults"] = dict(base.get("defaults", {}))
        for k, v in overrides.items():
            if k == "defaults":
                base["defaults"].update(v)
            else:
                base[k] = v
        return base

    def test_mt5_max_risk_eq_max_risk_passes(self):
        cfg = self._build(defaults={"max_risk_per_trade_pct": 2.0, "mt5_max_risk_per_trade_pct": 2.0})
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    def test_mt5_max_risk_below_max_risk_passes(self):
        cfg = self._build(defaults={"max_risk_per_trade_pct": 2.0, "mt5_max_risk_per_trade_pct": 1.5})
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    def test_mt5_max_risk_above_enabled_fails(self):
        cfg = self._build(
            defaults={
                "max_risk_per_trade_pct": 2.0,
                "mt5_max_risk_per_trade_pct": 10.0,
                "mt5_enable_max_risk_per_trade_pct": True,
            }
        )
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_mt5_max_risk_above_disabled_warns(self):
        cfg = self._build(
            defaults={
                "max_risk_per_trade_pct": 2.0,
                "mt5_max_risk_per_trade_pct": 10.0,
                "mt5_enable_max_risk_per_trade_pct": False,
            }
        )
        path = _write_config(cfg)
        assert validate(path) == 0  # warning only, still passes
        os.unlink(path)

    def test_profit_lock_threshold_zero_passes(self):
        cfg = self._build(defaults={"profit_lock_threshold_pct": 0})
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    def test_profit_lock_threshold_100_passes(self):
        cfg = self._build(defaults={"profit_lock_threshold_pct": 100})
        path = _write_config(cfg)
        assert validate(path) == 0
        os.unlink(path)

    def test_profit_lock_threshold_negative_fails(self):
        cfg = self._build(defaults={"profit_lock_threshold_pct": -5})
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_profit_lock_threshold_over_100_fails(self):
        cfg = self._build(defaults={"profit_lock_threshold_pct": 150})
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_factor_exposure_limit_too_high_fails(self):
        cfg = self._build(
            defaults={
                "factor_exposure_limits": {
                    "CHF": 0.2,
                    "AUD": 1.5,  # > 1.0
                }
            }
        )
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_factor_exposure_limit_negative_fails(self):
        cfg = self._build(
            defaults={
                "factor_exposure_limits": {
                    "CHF": -0.1,  # < 0
                }
            }
        )
        path = _write_config(cfg)
        assert validate(path) == 1
        os.unlink(path)

    def test_factor_exposure_limit_sum_over_1_warns_only(self):
        cfg = self._build(
            defaults={
                "factor_exposure_limits": {
                    "CHF": 0.2,
                    "AUD": 0.25,
                    "NZD": 0.25,
                    "JPY": 0.25,
                    "USD": 0.4,
                }
            }
        )
        path = _write_config(cfg)
        # sum = 1.35 > 1.0, but this is a warning — still passes
        assert validate(path) == 0
        os.unlink(path)
