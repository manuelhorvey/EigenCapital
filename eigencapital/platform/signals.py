"""Cross-platform shutdown and signal handling.

On Linux, SIGTERM can be caught to perform graceful shutdown.
On Windows, SIGTERM immediately kills the process (cannot be caught).

This module provides a ``ShutdownManager`` that uses ``threading.Event``
for cooperative shutdown, which works identically on all platforms.

Usage::

    from eigencapital.platform import ShutdownManager, install_graceful_shutdown

    shutdown = ShutdownManager()
    install_graceful_shutdown(shutdown)

    while not shutdown.is_set():
        # do work
        shutdown.wait(timeout=1.0)

    # Cleanup runs here regardless of platform
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Callable

logger = logging.getLogger("eigencapital.platform.signals")


class ShutdownManager:
    """Cooperative shutdown manager.

    Wraps a ``threading.Event`` and provides both signal-based and
    programmatic shutdown triggering.  Works identically on Linux
    and Windows because SIGTERM can be caught on Linux but not on
    Windows — on Windows the signal handler is simply never invoked,
    and shutdown is triggered via the Event directly.

    Usage::

        shutdown = ShutdownManager()

        def worker():
            while not shutdown.is_set():
                # ...

        # Signal-based shutdown (Linux only; no-op on Windows)
        shutdown.install_handlers()

        # Or programmatic shutdown from another thread:
        # shutdown.trigger()
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._handlers: list[Callable[[], None]] = []
        self._installed = False

    # ── Event interface ────────────────────────────────────────────────

    def is_set(self) -> bool:
        """Return True if shutdown has been requested."""
        return self._event.is_set()

    def __bool__(self) -> bool:
        """Allow ``if shutdown:`` shorthand."""
        return self._event.is_set()

    def trigger(self) -> None:
        """Request graceful shutdown. Callable from any thread."""
        self._event.set()
        for handler in self._handlers:
            try:
                handler()
            except Exception:  # noqa: BLE001
                logger.exception("Shutdown handler failed")

    def wait(self, timeout: float | None = None) -> bool:
        """Block until shutdown is requested or timeout elapses.

        Args:
            timeout: Maximum time to wait in seconds (or None for indefinite).

        Returns:
            True if shutdown was requested, False if timeout elapsed.
        """
        return self._event.wait(timeout)

    def clear(self) -> None:
        """Reset the shutdown flag (for testing)."""
        self._event.clear()

    # ── Signal handlers ────────────────────────────────────────────────

    def install_handlers(self) -> None:
        """Install signal handlers for SIGINT and SIGTERM.

        On Windows, SIGTERM cannot be caught (the process is killed),
        but SIGINT (Ctrl+C) works.  This is safe: on Windows the signal
        handler is registered but never invoked for SIGTERM.
        """
        if self._installed:
            return

        def _handler(signum: int, frame: object) -> None:
            logger.info("Received signal %d — initiating graceful shutdown", signum)
            self.trigger()

        try:
            signal.signal(signal.SIGINT, _handler)
        except (ValueError, OSError):
            pass

        try:
            signal.signal(signal.SIGTERM, _handler)
        except (ValueError, OSError):
            # Windows: SIGTERM cannot be caught, this raises ValueError
            pass

        self._installed = True

    # ── Shutdown handlers ──────────────────────────────────────────────

    def on_shutdown(self, handler: Callable[[], None]) -> None:
        """Register a callback invoked when shutdown is triggered.

        Handlers are called in registration order when ``trigger()`` is called.
        """
        self._handlers.append(handler)

    # ── Context manager ────────────────────────────────────────────────

    def __enter__(self) -> ShutdownManager:
        self.install_handlers()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        if not self._event.is_set():
            self.trigger()


# ── Module-level shortcuts ──────────────────────────────────────────────────

_default_shutdown: ShutdownManager | None = None
_default_shutdown_lock = threading.Lock()


def install_graceful_shutdown(shutdown: ShutdownManager | None = None) -> ShutdownManager:
    """Install signal handlers for graceful shutdown.

    Returns the ShutdownManager instance (creates a default if not provided).
    Also transfers any pending handlers registered via
    ``register_shutdown_handler()`` before the default was set.

    Usage::

        from eigencapital.platform import install_graceful_shutdown

        shutdown = install_graceful_shutdown()
        shutdown.wait()
        # Cleanup runs here
    """
    global _default_shutdown
    if shutdown is not None:
        shutdown.install_handlers()
        with _default_shutdown_lock:
            _default_shutdown = shutdown
            _transfer_pending()
        return shutdown

    if _default_shutdown is None:
        with _default_shutdown_lock:
            if _default_shutdown is None:
                _default_shutdown = ShutdownManager()
                _default_shutdown.install_handlers()
                _transfer_pending()
    return _default_shutdown


def _transfer_pending() -> None:
    """Transfer any pending shutdown handlers to ``_default_shutdown``.

    Must be called while holding ``_default_shutdown_lock``.
    """
    if _default_shutdown is not None:
        for h in getattr(register_shutdown_handler, "_pending", []):
            _default_shutdown.on_shutdown(h)
        register_shutdown_handler._pending = []  # type: ignore[attr-defined]


def register_shutdown_handler(handler: Callable[[], None]) -> None:
    """Register a callback on the default ShutdownManager.

    Safe to call before ``install_graceful_shutdown()`` — the handler
    is stored and registered once the manager exists.
    """
    global _default_shutdown
    if _default_shutdown is not None:
        _default_shutdown.on_shutdown(handler)
    else:
        # Store for later registration
        if not hasattr(register_shutdown_handler, "_pending"):
            register_shutdown_handler._pending = []  # type: ignore[attr-defined]
        register_shutdown_handler._pending.append(handler)  # type: ignore[attr-defined]

    # Also register on the default ShutdownManager if it already exists
    with _default_shutdown_lock:
        if _default_shutdown is not None:
            for h in getattr(register_shutdown_handler, "_pending", []):
                _default_shutdown.on_shutdown(h)
            register_shutdown_handler._pending = []  # type: ignore[attr-defined]
