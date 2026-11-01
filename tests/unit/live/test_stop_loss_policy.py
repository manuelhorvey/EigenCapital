"""Stop-loss policy verification (EC-AUDIT-002).

Authoritative policy (verified against code + config, not assumed):

* ``LiveRiskConfig.require_sl_on_positions`` is the policy flag. Production
  sets it to ``false`` (``configs/production/config.toml``): R4 exits are
  signal-driven (rotation / sign-flip / regime-ride). The catastrophic SL
  layer is an asynchronous containment backstop, not a normal exit.
* Gate 6 (``RiskEnforcer._check_position_protection``) is **advisory** when
  enabled: it returns ``CRITICAL`` but does not early-exit the gate pipeline,
  so it is distinguishable from blocking gates.
* The loop halts new entries on any ``BLOCK`` or ``CRITICAL`` result, but the
  Gate 6 critical is recorded and the remaining gates still run.

This module verifies both policy states, the missing/invalid data paths, and
the placement-outcome reporting. It does **not** change production behavior.

Gate 6 now requires a finite, positive stop-loss on the correct side of the
entry: below entry for a long, above entry for a short. Missing, ``None``,
boolean, non-numeric, non-finite, zero, negative, wrong-side, unknown-side,
and unknown-entry values are unprotected. This corrects the validation
semantics only; production still runs with ``require_sl_on_positions=false``
and gate enablement remains a separate operator decision.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from eigencapital.config import load_config
from eigencapital.live.durable_audit import DurableAudit
from eigencapital.live.risk_enforcement import (
    BlockReason,
    GateResult,
    RiskEnforcer,
    RiskEnvelope,
)
from eigencapital.live.watchdog import Watchdog

REPO = Path(__file__).resolve().parents[3]


def _load_supervisor():
    spec = importlib.util.spec_from_file_location(
        "r4_safety_supervisor_sl", REPO / "scripts" / "r4_safety_supervisor.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_safety_supervisor_sl"] = mod
    spec.loader.exec_module(mod)
    return mod


def _position(**overrides):
    pos = {
        "ticket": 1,
        "symbol": "EURUSD",
        "volume": 0.01,
        "type": 0,
        "price_open": 1.1000,
        "sl": 0.0,
        "tp": 0.0,
        "profit": 0.0,
        "magic": 20260825,
        "comment": "R4-Rebalance",
    }
    pos.update(overrides)
    return pos


def _envelope(require_sl: bool) -> RiskEnvelope:
    return RiskEnvelope(
        max_concurrent_positions=19,
        max_position_notional=5_000.0,
        max_order_notional=1_500.0,
        max_per_position_loss_pct=0.10,
        max_account_drawdown_pct=0.10,
        max_daily_loss=250.0,
        min_equity=4_000.0,
        require_sl_on_positions=require_sl,
        t0_equity=5_010.94,
    )


def _protection_gate(results):
    return next(r for r in results if r.gate_name == "position_protection")


class TestAuthoritativePolicy:
    def test_production_policy_is_not_required(self):
        config = load_config("production")
        assert config.live_risk.require_sl_on_positions is False

    def test_envelope_from_config_mirrors_policy(self):
        config = load_config("production")
        envelope = RiskEnvelope.from_config()
        assert envelope.require_sl_on_positions == config.live_risk.require_sl_on_positions

    def test_bare_envelope_default_is_fail_closed(self):
        # A bare RiskEnforcer() (no config) requires SL; production overrides it.
        assert RiskEnvelope().require_sl_on_positions is True


class TestPolicyNotRequired:
    """Production posture: signal-based exits, no mandatory fixed stop."""

    def test_position_without_sl_is_allowed(self):
        enforcer = RiskEnforcer(_envelope(require_sl=False))
        passed, results = enforcer.check_all(
            broker_positions=[_position(sl=0.0)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _protection_gate(results)
        assert gate.result == GateResult.PASS
        assert "disabled" in gate.message.lower()
        assert passed is True

    def test_position_with_valid_sl_is_allowed(self):
        enforcer = RiskEnforcer(_envelope(require_sl=False))
        passed, results = enforcer.check_all(
            broker_positions=[_position(sl=1.0900)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.PASS
        assert passed is True

    def test_missing_sl_key_is_allowed(self):
        pos = _position()
        del pos["sl"]
        enforcer = RiskEnforcer(_envelope(require_sl=False))
        passed, results = enforcer.check_all(
            broker_positions=[pos],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.PASS
        assert passed is True


class TestPolicyRequired:
    def test_valid_sl_passes(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        passed, results = enforcer.check_all(
            broker_positions=[_position(sl=1.0900)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.PASS
        assert passed is True

    def test_valid_short_sl_passes(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        passed, results = enforcer.check_all(
            broker_positions=[_position(type=1, price_open=1.1000, sl=1.1100)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.PASS
        assert passed is True

    def test_long_sl_above_entry_is_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(type=0, price_open=1.1000, sl=1.1100)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_short_sl_below_entry_is_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(type=1, price_open=1.1000, sl=1.0900)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_missing_entry_price_is_unprotected(self):
        pos = _position(sl=1.0900)
        del pos["price_open"]
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[pos],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_unknown_position_side_is_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(type=2, price_open=1.1000, sl=1.0900)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_zero_sl_is_critical(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        passed, results = enforcer.check_all(
            broker_positions=[_position(sl=0.0)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _protection_gate(results)
        assert gate.result == GateResult.CRITICAL
        assert gate.block_reason == BlockReason.NO_SL_PROTECTION
        assert passed is False

    def test_missing_sl_key_is_critical(self):
        pos = _position()
        del pos["sl"]
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        passed, results = enforcer.check_all(
            broker_positions=[pos],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL
        assert passed is False

    def test_multiple_unprotected_lists_symbols(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[
                _position(ticket=1, symbol="EURUSD", sl=0.0),
                _position(ticket=2, symbol="GBPUSD", sl=0.0),
                _position(ticket=3, symbol="USDJPY", sl=1.0),
            ],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        gate = _protection_gate(results)
        assert gate.result == GateResult.CRITICAL
        assert "EURUSD" in gate.message and "GBPUSD" in gate.message
        assert "USDJPY" not in gate.message

    def test_gate6_critical_is_advisory_not_early_exit(self):
        # Later gates (fingerprint) still execute after Gate 6 CRITICAL.
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(sl=0.0)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        names = [r.gate_name for r in results]
        assert "position_protection" in names
        assert "fingerprint" in names
        assert names.index("position_protection") < names.index("fingerprint")


class TestInvalidStopLossData:
    """Invalid SL values must be classified as unprotected when required."""

    def test_none_sl_is_treated_as_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(sl=None)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_negative_sl_is_treated_as_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(sl=-1.0)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    def test_non_numeric_sl_is_treated_as_unprotected(self):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(sl="invalid")],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL

    @pytest.mark.parametrize(
        "bad_value",
        [float("nan"), float("inf"), float("-inf"), True, ""],
    )
    def test_other_invalid_sl_values_are_unprotected(self, bad_value):
        enforcer = RiskEnforcer(_envelope(require_sl=True))
        _, results = enforcer.check_all(
            broker_positions=[_position(sl=bad_value)],
            account_equity=5_000.0,
            account_free_margin=4_900.0,
        )
        assert _protection_gate(results).result == GateResult.CRITICAL


class _FakeBroker:
    """Offline broker double; no network, no credentials."""

    def __init__(self, set_sl_result: bool = True, apply_on_success: bool = True):
        self._positions = [_position(sl=0.0, ticket=1)]
        self._set_sl_result = set_sl_result
        self._apply_on_success = apply_on_success
        self.set_sl_calls: list[tuple[int, float]] = []

    def account(self):
        return {"equity": 5_010.94, "free_margin": 1_000.0}

    def positions(self):
        return [dict(p) for p in self._positions]

    def set_sl(self, ticket: int, sl: float) -> bool:
        self.set_sl_calls.append((ticket, sl))
        if self._set_sl_result and self._apply_on_success:
            for p in self._positions:
                if p["ticket"] == ticket:
                    p["sl"] = sl
        return self._set_sl_result


@pytest.fixture
def supervisor(monkeypatch, tmp_path):
    mod = _load_supervisor()
    monkeypatch.setattr(mod, "_atr14_pct_by_symbol", lambda symbols: {"EURUSD": 0.01})
    monkeypatch.setattr(mod, "_loop_alive", lambda: True)
    monkeypatch.setattr(mod, "trail_age_seconds", lambda path: 0.0)
    audit = DurableAudit(tmp_path / "safety_audit.jsonl")
    wd = Watchdog(stale_after_seconds=60, blind_after_seconds=120, contain_after_seconds=300)
    return mod, audit, wd


class TestPlacementOutcome:
    def test_failed_placement_is_not_reported_as_protected(self, supervisor):
        mod, audit, wd = supervisor
        broker = _FakeBroker(set_sl_result=False)
        record = mod.run_tick(broker, audit, wd, max_concurrent=20, live=True, build_id="test")

        plan = record["protection_plan"]
        assert len(plan) == 1
        assert plan[0]["action"] == "SET_STOP_LOSS"
        assert plan[0]["ok"] is False
        # The position is still unprotected after the failed placement.
        assert broker.positions()[0]["sl"] == 0.0

    def test_successful_placement_then_idempotent(self, supervisor):
        mod, audit, wd = supervisor
        broker = _FakeBroker(set_sl_result=True)
        first = mod.run_tick(broker, audit, wd, max_concurrent=20, live=True, build_id="test")
        assert first["protection_plan"][0]["ok"] is True
        assert broker.positions()[0]["sl"] > 0.0

        second = mod.run_tick(broker, audit, wd, max_concurrent=20, live=True, build_id="test")
        assert second["protection_plan"] == []

    def test_dry_run_never_claims_placement(self, supervisor):
        mod, audit, wd = supervisor
        broker = _FakeBroker(set_sl_result=True)
        record = mod.run_tick(broker, audit, wd, max_concurrent=20, live=False, build_id="test")

        plan = record["protection_plan"]
        assert len(plan) == 1
        assert plan[0]["dry_run"] is True
        assert "ok" not in plan[0]
        assert broker.set_sl_calls == []
