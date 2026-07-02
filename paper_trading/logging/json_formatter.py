"""JSON log formatter — machine-parseable log output for aggregation tools.

Wraps any underlying :class:`logging.LogRecord` into a single-line JSON
object suitable for ingestion by Loki/CloudWatch/Datadog/etc. Includes
correlation ID, level, timestamp, logger name, message, plus any extras
that subscribers attach via ``LoggerAdapter`` or ``extra={"key": ...}``.

Usage::

    import logging
    from paper_trading.logging.json_formatter import JsonFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("eigencapital.engine")
    logger.addHandler(handler)

    logger.info("signal_generated", extra={"asset": "EURUSD", "confidence": 0.72})

Output::

    {"ts":"2026-06-30T12:00:00+00:00","level":"INFO","logger":"eigencapital.engine",
     "msg":"signal_generated","asset":"EURUSD","confidence":0.72,
     "correlation_id":"abc123def456"}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

# LogRecord attributes that should NOT be exposed as top-level JSON keys when
# arbitrary ``extra={"k": v}`` data is attached.  Anything with these names on
# the record is a reserved Python logging attribute.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Format LogRecords as single-line JSON objects.

    The output is deterministic and contains, in this order:
      ts, level, logger, msg, correlation_id, then any ``extra=`` keys.

    Exceptions are encoded via ``exc_info`` and surfaced as ``exc`` key.
    """

    def __init__(
        self,
        *,
        ensure_ascii: bool = False,
        indent: int | None = None,
    ) -> None:
        super().__init__()
        self._ensure_ascii = ensure_ascii
        self._indent = indent

    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        if getattr(record, "correlation_id", None):
            base["correlation_id"] = record.correlation_id

        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)

        if record.stack_info:
            base["stack"] = self.formatStack(record.stack_info)

        # Attach ``extra`` keys (anything not in the reserved attrs).
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in base:
                # Don't clobber built-in keys
                continue
            try:
                json.dumps(value)
                base[key] = value
            except (TypeError, ValueError):
                base[key] = repr(value)

        return json.dumps(base, ensure_ascii=self._ensure_ascii, indent=self._indent)


def install_json_logging(
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    replace: bool = True,
) -> logging.Handler:
    """Attach a JSON :class:`logging.StreamHandler` to *logger*.

    Convenience function for ad-hoc adoption:

        from paper_trading.logging.json_formatter import install_json_logging
        install_json_logging(logging.getLogger("eigencapital"))

    If *replace* is True (default), existing stream handlers are removed
    so the JSON output is not interleaved with human-readable text.
    """
    logger = logger or logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)

    if replace:
        for h in list(logger.handlers):
            if isinstance(h, logging.StreamHandler):
                logger.removeHandler(h)
    logger.addHandler(handler)

    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)

    return handler
