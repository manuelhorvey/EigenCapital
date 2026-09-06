"""Regression tests for the R4 monitor reconnect fix (R4-S 2026-09-06).

The monitor wedge: the monitor held ONE long-lived mt5linux proxy and called
shutdown()+initialize() on the same stale object every cycle. Once that proxy
wedged, re-init failed indefinitely and the monitor spammed CRITICAL
"MT5 DISCONNECTED" alerts every cycle while the bridge itself was healthy
(observed 21:45–21:50 on 2026-09-06). The rebalance loop received the
fresh-session remedy on 2026-09-04; the monitor had not.

Fixed contract, mirrored here:
  _monitor_reconnect() returns a session ONLY after account_info() confirms
  a live account (equity > 0). If the held session cannot be healed it must
  create a fresh session object and verify that one too. It returns None
  only when no session can read live data.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_MODULE = "scripts.r4_monitor"

pytestmark = pytest.mark.skipif(not importlib.util.find_spec("mt5linux"), reason="mt5linux not installed")


def _import_monitor_module():
    if _MODULE in sys.modules:
        return sys.modules[_MODULE]
    return importlib.import_module(_MODULE)


def _live_account(equity: float = 5000.0):
    return SimpleNamespace(equity=equity)


class _FakeSession:
    """Minimal stand-in for the mt5linux MetaTrader5 client surface."""

    def __init__(self, *, initialize_ok=True, account=None, fail_shutdown=False):
        self.initialize_ok = initialize_ok
        self.account = account
        self.fail_shutdown = fail_shutdown
        self.shutdown_calls = 0
        self.initialize_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        if self.fail_shutdown:
            raise RuntimeError("shutdown failed (wedged connection)")

    def initialize(self, *args, **kwargs):
        self.initialize_calls += 1
        return self.initialize_ok

    def account_info(self):
        return self.account

    def last_error(self):
        return (0, "ok")


@pytest.fixture()
def monitor_mod():
    return _import_monitor_module()


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)


# ── _connect_verified_mt5 ──────────────────────────────────────────


def test_connect_verified_returns_live_session(monitor_mod, no_sleep):
    live = _FakeSession(account=_live_account())
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: live):
        result = monitor_mod._connect_verified_mt5()
    assert result is live


def test_connect_verified_rejects_unverified_session(monitor_mod, no_sleep):
    """initialize() True but no account data must NOT count as success."""
    dead = _FakeSession(account=None)
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: dead):
        result = monitor_mod._connect_verified_mt5(max_attempts=1)
    assert result is None
    assert dead.shutdown_calls == 1  # unverified session must be released


def test_connect_verified_survives_connect_exception(monitor_mod, no_sleep):
    def _exploding_factory(**kw):
        raise ConnectionRefusedError("[Errno 111] Connection refused")

    with patch.object(monitor_mod, "MetaTrader5", _exploding_factory):
        result = monitor_mod._connect_verified_mt5()
    assert result is None


# ── _monitor_reconnect ─────────────────────────────────────────────


def test_held_session_heals_is_returned(monitor_mod, no_sleep):
    held = _FakeSession(account=_live_account())
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: _FakeSession(account=_live_account())):
        result = monitor_mod._monitor_reconnect(held)
    assert result is held


def test_wedged_held_session_falls_back_to_fresh(monitor_mod, no_sleep):
    """initialize() True but account_info() None on the held session must NOT
    count as success — a fresh session must be created and verified."""
    held = _FakeSession(account=None)  # the wedge signature
    fresh = _FakeSession(account=_live_account())
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: fresh):
        result = monitor_mod._monitor_reconnect(held)
    assert result is fresh
    assert held.initialize_calls >= 1  # healing was attempted first


def test_wedged_held_and_dead_fresh_returns_none(monitor_mod, no_sleep):
    held = _FakeSession(account=None)
    fresh = _FakeSession(account=None)
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: fresh):
        result = monitor_mod._monitor_reconnect(held)
    assert result is None


def test_shutdown_exception_on_held_is_tolerated(monitor_mod, no_sleep):
    """A wedged held session whose shutdown() raises must not abort recovery."""
    held = _FakeSession(fail_shutdown=True, account=None)
    fresh = _FakeSession(account=_live_account())
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: fresh):
        result = monitor_mod._monitor_reconnect(held)
    assert result is fresh


def test_initialize_exception_on_held_falls_back_to_fresh(monitor_mod, no_sleep):
    held = _FakeSession(account=None)

    class _ExplodingInit(_FakeSession):
        def initialize(self, *a, **k):
            raise RuntimeError("stale rpyc connection")

    held.__class__ = _ExplodingInit  # type: ignore[misc]
    fresh = _FakeSession(account=_live_account())
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: fresh):
        result = monitor_mod._monitor_reconnect(held)
    assert result is fresh


def test_fresh_session_is_verified_not_merely_initialized(monitor_mod, no_sleep):
    """Even the fresh session must pass the account_info() gate."""
    held = _FakeSession(account=None)
    fresh = _FakeSession(account=None)  # init ok, no account
    with patch.object(monitor_mod, "MetaTrader5", lambda **kw: fresh):
        result = monitor_mod._monitor_reconnect(held)
    assert result is None


# ── Main loop wiring ───────────────────────────────────────────────


def test_loop_survives_dead_cycle_and_recovers(monitor_mod, monkeypatch):
    """Cycle 1 reconnect fails → one CRITICAL alert, monitor keeps running;
    cycle 2 reconnect heals → run_check resumes. The loop must NOT exit."""
    mod = monitor_mod
    held = _FakeSession(account=_live_account())
    outcomes = iter([None, held])  # cycle 1: unrecoverable; cycle 2: healed
    alerts, checks = [], []

    def fake_sleep(seconds):
        if seconds == 30:  # disconnect backoff — no cycle count
            return
        fake_sleep.cycles = getattr(fake_sleep, "cycles", 0) + 1
        if fake_sleep.cycles >= 3:
            raise KeyboardInterrupt  # stop the loop from inside

    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    with (
        patch.object(sys, "argv", ["r4_monitor.py", "--loop"]),
        patch.object(mod, "_shutdown", False),
        patch.object(mod, "_connect_verified_mt5", return_value=held),
        patch.object(mod, "_monitor_reconnect", side_effect=lambda m: next(outcomes)),
        patch.object(mod, "alert", side_effect=lambda *a: alerts.append(a)),
        patch.object(mod, "run_check", side_effect=lambda m: checks.append(m)),
        pytest.raises(KeyboardInterrupt),
    ):
        mod.main()

    assert len(alerts) == 1 and alerts[0][0] == "MT5 DISCONNECTED"
    assert len(checks) == 2  # initial check + post-recovery check


def test_loop_recovers_without_false_alert_when_heal_succeeds(monitor_mod, monkeypatch):
    """Healthy bridge + healed session each cycle → zero CRITICAL alerts
    (the false-alarm failure mode observed 21:45–21:50 on 2026-09-06)."""
    mod = monitor_mod
    held = _FakeSession(account=_live_account())
    alerts, checks = [], []

    def fake_sleep(seconds):
        fake_sleep.cycles = getattr(fake_sleep, "cycles", 0) + 1
        if fake_sleep.cycles >= 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    with (
        patch.object(sys, "argv", ["r4_monitor.py", "--loop"]),
        patch.object(mod, "_shutdown", False),
        patch.object(mod, "_connect_verified_mt5", return_value=held),
        patch.object(mod, "_monitor_reconnect", side_effect=lambda m: held),
        patch.object(mod, "alert", side_effect=lambda *a: alerts.append(a)),
        patch.object(mod, "run_check", side_effect=lambda m: checks.append(m)),
        pytest.raises(KeyboardInterrupt),
    ):
        mod.main()

    assert alerts == []
    assert len(checks) == 4  # initial + 3 healthy cycles
