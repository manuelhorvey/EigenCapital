"""Correlation ID support for structured logging.

Uses ``contextvars`` for thread-safe correlation ID propagation.
Python 3.12+ automatically propagates contextvars through
``ThreadPoolExecutor``, making this seamless with the engine's actor pool.

Usage::

    from paper_trading.logging.correlation import set_correlation_id, get_correlation_id

    cid = set_correlation_id()          # auto-generate
    cid = set_correlation_id("abc123")  # explicit

    current = get_correlation_id()      # read (empty string if unset)

Logging ``CorrelationIdFilter`` adds ``correlation_id`` to every log record.
Add it to a root or per-logger handler::

    root = logging.getLogger("eigencapital")
    root.addFilter(CorrelationIdFilter())
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("_correlation_id", default="")


def set_correlation_id(cid: str | None = None) -> str:
    """Set the correlation ID for the current context.

    If *cid* is ``None``, a 12-hex-char string is generated from ``uuid4``.
    Returns the assigned ID.
    """
    if cid is None:
        cid = uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """Return the current correlation ID (empty string if unset)."""
    return _correlation_id.get()


class CorrelationIdFilter(logging.Filter):
    """Logging filter that injects ``correlation_id`` into every log record.

    The value comes from the ``contextvars`` context of the emitting thread,
    so it propagates correctly through the actor thread pool.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        return True


class CorrelationFormatter(logging.Formatter):
    """Formatter that includes ``correlation_id`` in the format string.

    Default format::

        %(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s
    """

    def __init__(
        self,
        fmt: str = "%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s",
        datefmt: str = "%Y-%m-%d %H:%M:%S",
    ):
        super().__init__(fmt=fmt, datefmt=datefmt)
