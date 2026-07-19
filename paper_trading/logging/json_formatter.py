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
            "msg": self._safe_get_message(record),
        }

        if getattr(record, "correlation_id", None):
            base["correlation_id"] = record.correlation_id  # type: ignore[attr-defined]

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

    @staticmethod
    def _safe_get_message(record: logging.LogRecord) -> str:
        """Return the formatted message, falling back to ``str(record.msg)`` on error.

        ``record.getMessage()`` can raise when the format string + args are
        malformed (e.g. unbalanced ``{`` / ``}`` placeholders for non-format
        messages, or ``args`` of an unexpected type). We never want logging
        itself to crash the caller — see per-file-ignore for this module in
        ``pyproject.toml`` ([tool.ruff.lint.per-file-ignores]).
        """
        try:
            return record.getMessage()
        except BaseException:
            try:
                return str(record.msg)
            except BaseException:
                return "<unrepresentable log message>"


def install_json_logging(
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    replace: bool = False,
) -> logging.Handler:
    """Attach a JSON :class:`logging.StreamHandler` to *logger*.

    Convenience function for ad-hoc adoption:

        from paper_trading.logging.json_formatter import install_json_logging
        install_json_logging(logging.getLogger("eigencapital"))

    If *replace* is True, existing stream handlers whose formatter is NOT
    already a :class:`JsonFormatter` are removed so JSON output is not
    interleaved with human-readable text. Handlers already emitting JSON are
    kept to avoid duplicate log lines. Default behavior is non-replacing
    (handlers are preserved) so this is safe to call multiple times.
    """
    logger = logger or logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)

    if replace:
        for h in list(logger.handlers):
            if not isinstance(h, logging.StreamHandler):
                continue
            if isinstance(h.formatter, JsonFormatter):
                continue
            logger.removeHandler(h)
    logger.addHandler(handler)

    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)

    return handler
