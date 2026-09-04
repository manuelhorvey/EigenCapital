"""Regression tests for the R4 loop reconnect fix (R4-S 2026-09-04).

The reconnect wedge: the loop held one long-lived mt5linux session whose
account_info() had gone stale, while _reconnect_mt5() reported success on
initialize()==True alone — never verifying the session could actually read
account data. The loop then spun in a false-success reconnect cycle
(17+ cycles on 2026-09-04; 1499 on 2026-09-01).

Fixed contract, mirrored here:
  _reconnect_mt5() returns a session ONLY after account_info() confirms a
  live account (equity > 0). If the held session cannot be healed it must
  create a fresh session object and verify that one too. It returns None
  only when no session can read live data.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_MODULE = "scripts.r4_rebalance_loop"

pytestmark = pytest.mark.skipif(not importlib.util.find_spec("mt5linux"), reason="mt5linux not installed")


def _import_loop_module():
    """Import the script once (module-level code is idempotent-safe here)."""
    if _MODULE in sys.modules:
        return sys.modules[_MODULE]
    mod = importlib.import_module(_MODULE)
    return mod


def _live_account(equity: float = 5000.0):
    return SimpleNamespace(equity=equity)


class _FakeMt5Factory:
    """MetaTrader5 factory substitute; returns a configured fake session."""

    def __init__(self, fresh_session):
        self._fresh = fresh_session
        self.calls = 0

    def __call__(self, host="127.0.0.1", port=8001):
        self.calls += 1
        return self._fresh


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


@pytest.fixture()
def loop_mod():
    return _import_loop_module()


@pytest.fixture()
def no_sleep():
    with patch("time.sleep", return_value=None):
        yield


def test_held_session_heals_is_returned(loop_mod, no_sleep):
    """A held session whose account_info() comes back live is reused as-is."""
    held = _FakeSession(account=_live_account())
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(_FakeSession(account=_live_account()))) as factory:
        result = loop_mod._reconnect_mt5(held)
    assert result is held
    assert factory.calls == 0  # no fresh session created


def test_wedged_held_session_falls_back_to_fresh(loop_mod, no_sleep):
    """initialize() True but account_info() None on the held session must NOT
    count as success — a fresh session must be created and verified."""
    held = _FakeSession(account=None)  # the wedge signature: init ok, reads dead
    fresh = _FakeSession(account=_live_account())
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)) as factory:
        result = loop_mod._reconnect_mt5(held)
    assert result is fresh
    assert factory.calls == 1
    assert held.initialize_calls >= 1  # healing was attempted first


def test_wedged_held_and_dead_fresh_returns_none(loop_mod, no_sleep):
    """No live account data anywhere → None (never a false success)."""
    held = _FakeSession(account=None)
    fresh = _FakeSession(account=None)
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is None


def test_fresh_initialize_failure_returns_none(loop_mod, no_sleep):
    held = _FakeSession(account=None)
    fresh = _FakeSession(initialize_ok=False, account=None)
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is None


def test_fresh_account_zero_equity_returns_none(loop_mod, no_sleep):
    held = _FakeSession(account=None)
    fresh = _FakeSession(account=_live_account(equity=0.0))
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is None


def test_shutdown_exception_on_held_is_tolerated(loop_mod, no_sleep):
    """A wedged held session whose shutdown() raises must not abort recovery."""
    held = _FakeSession(fail_shutdown=True, account=None)
    fresh = _FakeSession(account=_live_account())
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is fresh


def test_initialize_exception_on_held_falls_back_to_fresh(loop_mod, no_sleep):
    held = _FakeSession(account=None)

    class _ExplodingInit(_FakeSession):
        def initialize(self, *a, **k):
            raise RuntimeError("stale rpyc connection")

    held.__class__ = _ExplodingInit  # type: ignore[misc]
    fresh = _FakeSession(account=_live_account())
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is fresh


def test_fresh_session_is_verified_not_merely_initialized(loop_mod, no_sleep):
    """Even the fresh session must pass the account_info() gate — initialize()
    alone must never return a session (the original false-success bug)."""
    held = _FakeSession(account=None)
    fresh = _FakeSession(account=None)  # init ok, no account
    with patch.object(loop_mod, "MetaTrader5", _FakeMt5Factory(fresh)):
        result = loop_mod._reconnect_mt5(held)
    assert result is None
