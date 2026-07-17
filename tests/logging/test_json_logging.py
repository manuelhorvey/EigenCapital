"""Tests for the JSON log formatter + install_json_logging helper."""

from __future__ import annotations

import io
import json
import logging

import pytest

from paper_trading.logging.correlation import set_correlation_id
from paper_trading.logging.json_formatter import (
    JsonFormatter,
    install_json_logging,
)


@pytest.fixture
def logger_with_stream():
    """Build an isolated logger backed by an in-memory stream."""
    from paper_trading.logging.correlation import CorrelationIdFilter

    logger = logging.getLogger(f"eigencapital.test.json.{id(object())}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationIdFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger, stream


class TestJsonFormatterBasic:
    def test_includes_required_keys(self, logger_with_stream):
        logger, stream = logger_with_stream
        logger.info("hello world")
        line = stream.getvalue().strip()
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["logger"].startswith("eigencapital.test.json")
        assert data["msg"] == "hello world"
        assert "ts" in data

    def test_includes_correlation_id_when_set(self, logger_with_stream):
        logger, stream = logger_with_stream
        cid = set_correlation_id("test-cid-123")
        try:
            logger.info("with cid")
            data = json.loads(stream.getvalue().strip())
            assert data["correlation_id"] == "test-cid-123"
        finally:
            set_correlation_id("")

    def test_no_correlation_id_omits_key(self, logger_with_stream):
        logger, stream = logger_with_stream
        set_correlation_id("")
        logger.info("clean")
        data = json.loads(stream.getvalue().strip())
        # CorrelationIdFilter writes "-" as placeholder when unset
        assert data.get("correlation_id", "-") in ("", "-")

    def test_extra_payload_attached(self, logger_with_stream):
        logger, stream = logger_with_stream
        logger.info(
            "signal_generated",
            extra={"asset": "EURUSD", "confidence": 0.72},
        )
        data = json.loads(stream.getvalue().strip())
        assert data["asset"] == "EURUSD"
        assert data["confidence"] == 0.72

    def test_deterministic_key_order(self, logger_with_stream):
        logger, stream = logger_with_stream
        logger.info("order", extra={"zeta": 1, "alpha": 2})
        data = json.loads(stream.getvalue().strip())
        # Standard keys come first; extras follow.
        keys = list(data.keys())
        assert keys[0] == "ts"
        assert keys[1] == "level"
        assert keys[2] == "logger"
        assert keys[3] == "msg"
        assert "zeta" in keys
        assert "alpha" in keys

    def test_non_json_serializable_extra_repr_encoded(self, logger_with_stream):
        logger, stream = logger_with_stream
        logger.info("bad", extra={"callable_obj": lambda: 1})
        line = stream.getvalue().strip()
        data = json.loads(line)
        # The lambda is represented as a string
        assert isinstance(data["callable_obj"], str)
        assert "lambda" in data["callable_obj"] or "<" in data["callable_obj"]

    def test_exception_serialized(self, logger_with_stream):
        logger, stream = logger_with_stream
        try:
            raise ValueError("internal error")
        except ValueError:
            logger.exception("caught exception")
        data = json.loads(stream.getvalue().strip().splitlines()[-1])
        assert "exc" in data
        assert "ValueError: internal error" in data["exc"]

    def test_each_record_is_single_line(self, logger_with_stream):
        logger, stream = logger_with_stream
        for i in range(50):
            logger.info(f"event_{i}")
        output = stream.getvalue()
        assert output.count("\n") == 50

    def test_unicode_payload_preserved_by_default(self):
        # JsonFormatter default is ensure_ascii=False → UTF-8 inline
        handler = logging.StreamHandler(io.StringIO())
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger(f"test.unic.{id(object())}")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        stream = handler.stream
        logger.info("café 🚀")
        data = json.loads(stream.getvalue().strip())
        assert "café 🚀" in data["msg"]


class TestInstallJsonLogging:
    def test_replaces_stream_handlers(self):
        logger = logging.getLogger(f"test.install.{id(object())}")
        logger.handlers.clear()
        logger.addHandler(logging.StreamHandler())
        install_json_logging(logger, replace=True)
        assert len(logger.handlers) == 1

    def test_preserves_stream_handlers_when_replace_false(self):
        logger = logging.getLogger(f"test.install2.{id(object())}")
        logger.handlers.clear()
        existing = logging.StreamHandler()
        logger.addHandler(existing)
        install_json_logging(logger, replace=False)
        assert existing in logger.handlers
        assert len(logger.handlers) == 2

    def test_sets_log_level(self):
        logger = logging.getLogger(f"test.level.{id(object())}")
        logger.setLevel(logging.WARNING)
        install_json_logging(logger, level=logging.DEBUG, replace=True)
        assert logger.level == logging.DEBUG


class TestJsonFormatterHardening:
    def test_does_not_expose_internal_python_state(self, logger_with_stream):
        logger, stream = logger_with_stream
        logger.info("safe", extra={"user_key": "user_val"})
        data = json.loads(stream.getvalue().strip())
        # Reserved attributes should NOT leak (other than the user-visible 'msg')
        for reserved in (
            "args",
            "pathname",
            "filename",
            "module",
            "msecs",
            "exc_info",
            "exc_text",
            "stack_info",
            "funcName",
            "created",
            "thread",
            "threadName",
            "processName",
            "process",
        ):
            assert reserved not in data, f"Reserved attr {reserved} leaked"
