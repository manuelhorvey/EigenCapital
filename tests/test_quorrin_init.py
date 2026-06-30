from __future__ import annotations

import logging
import os
import tempfile

import quorrin


class TestVersion:
    def test_version_is_string(self):
        assert isinstance(quorrin.__version__, str)
        assert quorrin.__version__ == "1.5.0"


class TestSetupLogging:
    def test_default_stream_handler(self):
        quorrin.setup_logging(level=logging.DEBUG)
        root = logging.getLogger("quorrin")
        assert root.level == logging.DEBUG
        handlers = root.handlers
        assert len(handlers) >= 1
        has_stream = any(isinstance(h, logging.StreamHandler) for h in handlers)
        assert has_stream

    def test_with_file_handler(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_path = f.name
        try:
            quorrin.setup_logging(level=logging.INFO, log_file=log_path)
            logger = logging.getLogger("quorrin.test_file")
            logger.info("test message")
            assert os.path.exists(log_path)
            with open(log_path) as f:
                content = f.read()
            assert "test message" in content
        finally:
            if os.path.exists(log_path):
                os.unlink(log_path)

    def test_setup_logging_adds_correlation_filter(self):
        quorrin.setup_logging(level=logging.WARNING)
        root = logging.getLogger("quorrin")
        for handler in root.handlers:
            filters = handler.filters
            has_corr = any(type(f).__name__ == "CorrelationIdFilter" for f in filters)
            if has_corr:
                break
        assert has_corr, "No handler has CorrelationIdFilter"

    def test_logger_propagates(self):
        child = logging.getLogger("quorrin.test_child")
        assert child.propagate is True
