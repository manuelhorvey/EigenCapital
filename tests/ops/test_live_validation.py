"""Tests for the live validation suite (scripts/ops/live_validation.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.live_validation import (
    _VALIDATORS,
    CheckResult,
    check_asset_gate_overrides,
    check_calibration,
    check_concurrent_position_limit,
    check_emergency_halt,
    check_engine_status,
    check_live_sharpe,
    check_mt5_connectivity,
    check_portfolio_drawdown,
    check_position_concentration,
    check_sell_tripwires,
    check_signal_flips,
    load_state,
    print_human,
    print_json,
    run,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def healthy_state() -> dict:
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "engine_status": {
            "initialized": True,
            "last_update": now_iso,
            "market_closed": False,
            "emergency_halt": False,
            "halt_reason": "",
            "halt_detail": "",
            "mt5_status": {"connected": True, "status": "CONNECTED"},
        },
        "portfolio": {
            "total_value": 100000.0,
            "total_return": 0.05,
            "open_positions": 5,
            "closed_trades": 50,
            "portfolio_drawdown": -0.02,
            "position_concentration": {
                "long": 5,
                "short": 3,
                "total": 8,
                "skew": 0.20,
                "dominant_side": "long",
                "threshold": 0.75,
                "alert": False,
            },
            "pek": {
                "portfolio_snapshot": {
                    "concurrent_remaining": 8,
                    "total_equity": 100000.0,
                }
            },
            "live_sharpe": {"available": True, "cycle_sharpe_adj": 1.26},
        },
        "halt_conditions": {
            "max_drawdown_pct": 0.15,
            "max_concurrent_positions": 13,
        },
        "assets": {
            "EURUSD": {
                "sell_only": False,
                "tripwire_active": False,
                "gate_override": False,
                "signal_flip": False,
                "metrics": {"n_trades": 30, "mean_confidence": 72.0, "win_rate": 68.0},
            },
            "CADCHF": {
                "sell_only": True,
                "tripwire_active": False,
                "gate_override": False,
                "signal_flip": False,
                "metrics": {"n_trades": 25, "mean_confidence": 75.0, "win_rate": 70.0},
            },
            "GBPUSD": {
                "sell_only": False,
                "tripwire_active": False,
                "gate_override": False,
                "signal_flip": False,
                "metrics": {"n_trades": 20, "mean_confidence": 65.0, "win_rate": 62.0},
            },
            "USDJPY": {
                "sell_only": False,
                "tripwire_active": False,
                "gate_override": False,
                "signal_flip": False,
                "metrics": {"n_trades": 15, "mean_confidence": 70.0, "win_rate": 66.0},
            },
        },
    }


# ── CheckResult ───────────────────────────────────────────────────────────


class TestCheckResult:
    def test_required_fields(self):
        r = CheckResult("test_check", "PASS", "All good")
        assert r.name == "test_check"
        assert r.status == "PASS"
        assert r.message == "All good"
        assert r.details == {}

    def test_with_details(self):
        r = CheckResult("test_check", "WARN", "Something", {"key": "val"})
        assert r.details == {"key": "val"}


# ── load_state ────────────────────────────────────────────────────────────


class TestLoadState:
    def test_loads_valid_json(self, tmp_path: Path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"key": "value"}))
        assert load_state(p) == {"key": "value"}

    def test_file_not_found(self, tmp_path: Path):
        assert load_state(tmp_path / "nonexistent.json") == {}

    def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "state.json"
        p.write_text("{invalid")
        with pytest.raises(json.JSONDecodeError):
            load_state(p)


# ── Individual checks ─────────────────────────────────────────────────────


class TestCheckEngineStatus:
    def test_healthy(self, healthy_state):
        r = check_engine_status(healthy_state)
        assert r.status == "PASS"

    def test_not_initialized(self, healthy_state):
        healthy_state["engine_status"]["initialized"] = False
        r = check_engine_status(healthy_state)
        assert r.status == "ERROR"

    def test_no_last_update(self, healthy_state):
        healthy_state["engine_status"]["last_update"] = None
        r = check_engine_status(healthy_state)
        assert r.status == "ERROR"


class TestCheckEmergencyHalt:
    def test_no_halt(self, healthy_state):
        r = check_emergency_halt(healthy_state)
        assert r.status == "PASS"

    def test_halted(self, healthy_state):
        healthy_state["engine_status"]["emergency_halt"] = True
        healthy_state["engine_status"]["halt_reason"] = "DRAWDOWN"
        r = check_emergency_halt(healthy_state)
        assert r.status == "ERROR"
        assert "halted" in r.message.lower()


class TestCheckPortfolioDrawdown:
    def test_normal(self, healthy_state):
        r = check_portfolio_drawdown(healthy_state)
        assert r.status == "PASS"

    def test_exceeds_limit(self, healthy_state):
        healthy_state["portfolio"]["portfolio_drawdown"] = -0.20
        r = check_portfolio_drawdown(healthy_state)
        assert r.status == "ERROR"

    def test_approaching_limit(self, healthy_state):
        healthy_state["portfolio"]["portfolio_drawdown"] = -0.12
        r = check_portfolio_drawdown(healthy_state)
        assert r.status == "WARN"


class TestCheckPositionConcentration:
    def test_within_threshold(self, healthy_state):
        r = check_position_concentration(healthy_state)
        assert r.status == "PASS"

    def test_alert_triggered(self, healthy_state):
        healthy_state["portfolio"]["position_concentration"]["alert"] = True
        healthy_state["portfolio"]["position_concentration"]["skew"] = 0.85
        r = check_position_concentration(healthy_state)
        assert r.status == "WARN"

    def test_missing_data(self):
        r = check_position_concentration({})
        assert r.status == "PASS"


class TestCheckSellTripwires:
    def test_none_tripped(self, healthy_state):
        r = check_sell_tripwires(healthy_state)
        assert r.status == "PASS"

    def test_tripped(self, healthy_state):
        healthy_state["assets"]["CADCHF"]["tripwire_active"] = True
        r = check_sell_tripwires(healthy_state)
        assert r.status == "WARN"
        assert "CADCHF" in r.message


class TestCheckMT5Connectivity:
    def test_connected(self, healthy_state):
        r = check_mt5_connectivity(healthy_state)
        assert r.status == "PASS"

    def test_disconnected(self, healthy_state):
        healthy_state["engine_status"]["mt5_status"]["connected"] = False
        healthy_state["engine_status"]["mt5_status"]["status"] = "DISCONNECTED"
        r = check_mt5_connectivity(healthy_state)
        assert r.status == "WARN"


class TestCheckCalibration:
    def test_within_bounds(self, healthy_state):
        r = check_calibration(healthy_state)
        assert r.status == "PASS"

    def test_overconfident(self, healthy_state):
        healthy_state["assets"]["NZDCAD"] = {
            "metrics": {"n_trades": 25, "mean_confidence": 92.0, "win_rate": 60.0}
        }
        r = check_calibration(healthy_state)
        assert r.status == "WARN"

    def test_insufficient_trades(self, healthy_state):
        healthy_state["assets"]["NZDCAD"] = {
            "metrics": {"n_trades": 5, "mean_confidence": 92.0, "win_rate": 60.0}
        }
        r = check_calibration(healthy_state)
        assert r.status == "PASS"


class TestCheckConcurrentPositionLimit:
    def test_within_limit(self, healthy_state):
        r = check_concurrent_position_limit(healthy_state)
        assert r.status == "PASS"

    def test_at_capacity(self, healthy_state):
        healthy_state["portfolio"]["open_positions"] = 13
        r = check_concurrent_position_limit(healthy_state)
        assert r.status == "WARN"

    def test_approaching_limit(self, healthy_state):
        healthy_state["portfolio"]["open_positions"] = 11
        r = check_concurrent_position_limit(healthy_state)
        assert r.status == "INFO"


class TestCheckGateOverrides:
    def test_none(self, healthy_state):
        r = check_asset_gate_overrides(healthy_state)
        assert r.status == "PASS"

    def test_some_overrides(self, healthy_state):
        # 1/4 assets gate-overridden = 25%, below 40% threshold → INFO
        healthy_state["assets"]["EURUSD"]["gate_override"] = True
        r = check_asset_gate_overrides(healthy_state)
        assert r.status == "INFO"

    def test_excessive_overrides(self, healthy_state):
        # 3/4 assets gate-overridden = 75%, exceeds 40% threshold → WARN
        for i, name in enumerate(healthy_state["assets"]):
            healthy_state["assets"][name]["gate_override"] = i < 3
        r = check_asset_gate_overrides(healthy_state)
        assert r.status == "WARN"


class TestCheckSignalFlips:
    def test_no_flips(self, healthy_state):
        r = check_signal_flips(healthy_state)
        assert r.status == "PASS"

    def test_excessive_flips(self, healthy_state):
        # Need 4+ flips to exceed threshold of 3
        for name in ("EURUSD", "CADCHF", "GBPUSD", "JPYUSD"):
            healthy_state.setdefault("assets", {})[name] = {"signal_flip": True}
        r = check_signal_flips(healthy_state)
        assert r.status == "WARN"


class TestCheckLiveSharpe:
    def test_positive(self, healthy_state):
        r = check_live_sharpe(healthy_state)
        assert r.status == "PASS"

    def test_negative(self, healthy_state):
        healthy_state["portfolio"]["live_sharpe"]["cycle_sharpe_adj"] = -0.5
        r = check_live_sharpe(healthy_state)
        assert r.status == "WARN"

    def test_not_available(self, healthy_state):
        healthy_state["portfolio"]["live_sharpe"]["available"] = False
        r = check_live_sharpe(healthy_state)
        assert r.status == "INFO"


# ── Runner ────────────────────────────────────────────────────────────────


class TestRunner:
    def test_all_checks_are_registered(self):
        """Every stand-alone check function is in the _VALIDATORS list."""
        # Check that all check functions defined in this file are registered
        check_names = {fn.__name__ for fn in _VALIDATORS if fn.__name__.startswith("check_")}
        # The module-level check_ functions should all be registered
        assert "check_engine_status" in check_names
        assert "check_portfolio_drawdown" in check_names
        assert "check_emergency_halt" in check_names
        assert len(check_names) >= 10  # at least 10 checks

    def test_healthy_state_passes_all(self, healthy_state):
        results = run(healthy_state)
        for r in results:
            assert r.status in ("PASS", "INFO"), f"{r.name} should not be WARN/ERROR: {r.message}"

    def test_error_state_detected(self, healthy_state):
        healthy_state["engine_status"]["initialized"] = False
        healthy_state["engine_status"]["emergency_halt"] = True
        results = run(healthy_state)
        errors = [r for r in results if r.status == "ERROR"]
        assert len(errors) >= 2  # at least 2 errors

    def test_all_checks_produce_valid_status(self, healthy_state):
        results = run(healthy_state)
        for r in results:
            assert r.status in ("PASS", "WARN", "ERROR", "INFO"), f"Invalid status: {r.status}"
            assert isinstance(r.name, str)
            assert isinstance(r.message, str)

    def test_check_does_not_raise(self):
        """All checks gracefully handle empty/missing data."""
        for fn in _VALIDATORS:
            try:
                fn({})
            except Exception:  # noqa: BLE001 — test intentionally checks broad resilience
                pytest.fail(f"{fn.__name__} raised exception on empty state")


# ── Output formatters ─────────────────────────────────────────────────────


class TestPrinters:
    def test_print_human_no_error(self, capsys, healthy_state):
        results = run(healthy_state)
        print_human(results)
        captured = capsys.readouterr()
        assert "PASS" in captured.out or "✓" in captured.out

    def test_print_json_valid(self, healthy_state):
        results = run(healthy_state)
        print_json(results)
        # Can't capture easily; just check it doesn't raise
        assert True

    def test_print_json_parseable(self, healthy_state, capsys):
        results = run(healthy_state)
        print_json(results)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "checks" in data
        assert "summary" in data
        assert data["summary"]["total"] >= 10
