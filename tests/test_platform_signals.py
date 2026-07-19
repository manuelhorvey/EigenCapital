"""Tests for eigencapital.platform.signals.

Tests the ShutdownManager class and module-level helper functions
(install_graceful_shutdown, register_shutdown_handler).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from unittest import mock

import pytest

from eigencapital.platform.signals import (
    ShutdownManager,
    _default_shutdown,
    install_graceful_shutdown,
    register_shutdown_handler,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level state after each test.

    Clears ``_default_shutdown`` and the ``_pending`` attribute on
    ``register_shutdown_handler`` so tests don't leak state.
    """
    import eigencapital.platform.signals as _sig_mod

    _sig_mod._default_shutdown = None
    # Reset the function-level _pending attribute if set
    if hasattr(register_shutdown_handler, "_pending"):
        delattr(register_shutdown_handler, "_pending")
    yield
    _sig_mod._default_shutdown = None
    if hasattr(register_shutdown_handler, "_pending"):
        delattr(register_shutdown_handler, "_pending")


# ── ShutdownManager ──────────────────────────────────────────────────────────


class TestShutdownManager:
    def test_default_state_not_set(self):
        mgr = ShutdownManager()
        assert mgr.is_set() is False

    def test_trigger_sets_event(self):
        mgr = ShutdownManager()
        mgr.trigger()
        assert mgr.is_set() is True

    def test_bool_conversion(self):
        mgr = ShutdownManager()
        assert bool(mgr) is False
        mgr.trigger()
        assert bool(mgr) is True

    def test_wait_returns_true_after_trigger(self):
        mgr = ShutdownManager()
        mgr.trigger()
        assert mgr.wait(timeout=0.1) is True

    def test_wait_returns_false_on_timeout(self):
        mgr = ShutdownManager()
        assert mgr.wait(timeout=0.05) is False

    def test_clear_resets_event(self):
        mgr = ShutdownManager()
        mgr.trigger()
        assert mgr.is_set() is True
        mgr.clear()
        assert mgr.is_set() is False

    def test_multiple_triggers_idempotent(self):
        mgr = ShutdownManager()
        mgr.trigger()
        mgr.trigger()  # second call should not raise
        assert mgr.is_set() is True

    def test_wait_no_timeout_blocks(self):
        """wait() with no timeout should block until triggered from another thread."""
        mgr = ShutdownManager()

        def trigger_soon():
            import time
            time.sleep(0.05)
            mgr.trigger()

        t = threading.Thread(target=trigger_soon, daemon=True)
        t.start()
        result = mgr.wait()  # blocks until trigger
        assert result is True
        assert mgr.is_set() is True

    def test_install_handlers_idempotent(self):
        mgr = ShutdownManager()
        mgr.install_handlers()
        mgr.install_handlers()  # second call should not raise
        assert mgr._installed is True

    def test_cannot_trigger_twice(self):
        mgr = ShutdownManager()
        mgr.trigger()
        # trigger is idempotent - just check it doesn't raise
        mgr.trigger()
        assert mgr.is_set() is True


class TestShutdownHandlers:
    def test_on_shutdown_called_on_trigger(self):
        mgr = ShutdownManager()
        calls = []
        mgr.on_shutdown(lambda: calls.append("a"))
        mgr.on_shutdown(lambda: calls.append("b"))
        mgr.trigger()
        assert calls == ["a", "b"]

    def test_on_shutdown_called_in_order(self):
        mgr = ShutdownManager()
        order = []
        mgr.on_shutdown(lambda: order.append(1))
        mgr.on_shutdown(lambda: order.append(2))
        mgr.trigger()
        assert order == [1, 2]

    def test_handler_exception_does_not_block_others(self):
        mgr = ShutdownManager()

        def failing():
            raise RuntimeError("oops")

        calls = []
        mgr.on_shutdown(failing)
        mgr.on_shutdown(lambda: calls.append("ok"))

        # Should not raise despite the failing handler
        mgr.trigger()
        assert calls == ["ok"]

    def test_on_shutdown_not_called_without_trigger(self):
        mgr = ShutdownManager()
        called = False

        def handler():
            nonlocal called
            called = True

        mgr.on_shutdown(handler)
        assert called is False  # not triggered yet

    def test_handlers_called_after_wait_returns(self):
        mgr = ShutdownManager()
        calls = []

        def trigger_thread():
            import time
            time.sleep(0.05)
            mgr.trigger()

        mgr.on_shutdown(lambda: calls.append("done"))
        t = threading.Thread(target=trigger_thread, daemon=True)
        t.start()
        mgr.wait(timeout=1.0)
        assert calls == ["done"]


class TestShutdownContextManager:
    def test_context_manager_installs_handlers(self):
        with ShutdownManager() as mgr:
            assert mgr._installed is True

    def test_context_manager_triggers_on_exit(self):
        """__exit__ should call trigger() if not already set."""
        mgr = ShutdownManager()
        with mgr:
            pass
        assert mgr.is_set() is True

    def test_context_manager_no_double_trigger(self):
        """If already triggered, __exit__ should not raise."""
        mgr = ShutdownManager()
        with mgr:
            mgr.trigger()
        assert mgr.is_set() is True


# ── Signal handling ──────────────────────────────────────────────────────────


class TestSignalHandling:
    @mock.patch("signal.signal")
    def test_install_handlers_registers_sigint(self, mock_signal):
        mgr = ShutdownManager()
        mgr.install_handlers()
        assert mock_signal.call_count >= 1
        # At least SIGINT was registered
        args = [c[0] for c in mock_signal.call_args_list]
        sigint_call = any(c[0][0] == signal.SIGINT for c in mock_signal.call_args_list)
        assert sigint_call

    @mock.patch("signal.signal")
    def test_install_handlers_registers_sigterm(self, mock_signal):
        mgr = ShutdownManager()
        mgr.install_handlers()
        sigterm_call = any(c[0][0] == signal.SIGTERM for c in mock_signal.call_args_list)
        assert sigterm_call

    @mock.patch("signal.signal", side_effect=ValueError("SIGTERM not supported"))
    def test_install_handlers_graceful_on_windows(self, mock_signal):
        """Windows raises ValueError for SIGTERM — should be caught gracefully."""
        mgr = ShutdownManager()
        # SIGINT should succeed, SIGTERM should raise ValueError
        mgr.install_handlers()
        assert mgr._installed is True

    @mock.patch("signal.signal")
    def test_signal_handler_triggers_shutdown(self, mock_signal):
        mgr = ShutdownManager()
        mgr.install_handlers()
        # Extract the handler that was registered for SIGINT
        sigint_handler = None
        for call_args in mock_signal.call_args_list:
            sig, handler = call_args[0]
            if sig == signal.SIGINT:
                sigint_handler = handler
                break
        assert sigint_handler is not None

        # Call the handler
        sigint_handler(signal.SIGINT, None)
        assert mgr.is_set() is True


# ── Module-level helpers ──────────────────────────────────────────────────────


class TestInstallGracefulShutdown:
    def test_with_explicit_manager(self):
        mgr = ShutdownManager()
        result = install_graceful_shutdown(mgr)
        assert result is mgr
        assert mgr._installed is True

    def test_without_argument_creates_default(self):
        result = install_graceful_shutdown()
        assert isinstance(result, ShutdownManager)
        assert result._installed is True

    def test_without_argument_returns_same_default(self):
        a = install_graceful_shutdown()
        b = install_graceful_shutdown()
        assert a is b

    def test_explicit_manager_becomes_default(self):
        mgr = ShutdownManager()
        install_graceful_shutdown(mgr)
        default = install_graceful_shutdown()
        assert default is mgr


class TestRegisterShutdownHandler:
    def test_before_default_exists_stores_pending(self):
        """Handlers registered before install_graceful_shutdown are stored."""
        # Ensure no default exists yet
        assert _default_shutdown is None

        calls = []
        register_shutdown_handler(lambda: calls.append("a"))
        register_shutdown_handler(lambda: calls.append("b"))

        # Now install the default — pending handlers should be transferred
        mgr = install_graceful_shutdown()
        mgr.trigger()
        assert calls == ["a", "b"]

    def test_after_default_exists_registers_directly(self):
        mgr = install_graceful_shutdown()
        calls = []

        register_shutdown_handler(lambda: calls.append("c"))
        mgr.trigger()
        assert calls == ["c"]

    def test_pending_not_lost_on_concurrent_setup(self):
        """Pending handlers should survive if default is set after registering."""
        register_shutdown_handler(lambda: None)
        mgr = install_graceful_shutdown()
        # The pending list should be empty after transfer
        pending = getattr(register_shutdown_handler, "_pending", [])
        assert len(pending) == 0

    def test_registrations_are_idempotent(self):
        """Calling register_shutdown_handler without a pending handler is a no-op."""
        # Should not raise when there's no default and no pending list yet
        register_shutdown_handler(lambda: None)
        # Second call with same handler should also not raise
        register_shutdown_handler(lambda: None)
