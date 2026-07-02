"""Tests for ``paper_trading.logging.correlation`` — correlation ID propagation."""

import logging

import pytest

from paper_trading.logging.correlation import (
    CorrelationIdFilter,
    get_correlation_id,
    set_correlation_id,
)


class TestCorrelationId:
    @pytest.fixture(autouse=True)
    def _reset_cid(self) -> None:
        set_correlation_id("")

    def test_default_is_empty_string(self):
        assert get_correlation_id() == ""

    def test_set_explicit_id(self):
        set_correlation_id("abc123")
        assert get_correlation_id() == "abc123"

    def test_set_auto_generated(self):
        cid = set_correlation_id()
        assert len(cid) == 12
        assert isinstance(cid, str)

    def test_multiple_calls_overwrite(self):
        set_correlation_id("first")
        assert get_correlation_id() == "first"
        set_correlation_id("second")
        assert get_correlation_id() == "second"


class TestCorrelationIdFilter:
    def test_injects_correlation_id(self):
        set_correlation_id("test-cid")
        filt = CorrelationIdFilter()
        record = logging.makeLogRecord({"msg": "test"})
        filt.filter(record)
        assert record.correlation_id == "test-cid"

    def test_uses_dash_when_unset(self):
        set_correlation_id("")  # clear
        filt = CorrelationIdFilter()
        record = logging.makeLogRecord({"msg": "test"})
        filt.filter(record)
        assert record.correlation_id == "-"

    def test_filter_returns_true(self):
        set_correlation_id("x")
        filt = CorrelationIdFilter()
        record = logging.makeLogRecord({"msg": "test"})
        result = filt.filter(record)
        assert result is True
