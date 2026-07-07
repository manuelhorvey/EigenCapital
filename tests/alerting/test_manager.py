"""Tests for paper_trading/alerting/manager.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.alerting.channel import Alert, Channel, Severity
from paper_trading.alerting.manager import (
    AlertManager,
    _reset_alert_manager,
    _severity_ge,
    global_alert_manager,
    setup_alerting_from_config,
)


class TestSeverityGe:
    def test_info_ge_info(self):
        assert _severity_ge(Severity.INFO, Severity.INFO)

    def test_warning_ge_info(self):
        assert _severity_ge(Severity.WARNING, Severity.INFO)

    def test_critical_ge_warning(self):
        assert _severity_ge(Severity.CRITICAL, Severity.WARNING)

    def test_info_not_ge_warning(self):
        assert not _severity_ge(Severity.INFO, Severity.WARNING)


class TestAlertManager:
    def test_empty_alert_returns_empty_list(self):
        mgr = AlertManager()
        results = mgr.alert(Severity.WARNING, "test", "message")
        assert results == []

    def test_add_channel_and_alert(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        channel.send.return_value = True
        mgr.add_channel(channel)
        results = mgr.alert(Severity.WARNING, "test", "message")
        assert results == [True]
        channel.send.assert_called_once()

    def test_channel_not_called_below_threshold(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        mgr.add_channel(channel, min_severity=Severity.CRITICAL)
        results = mgr.alert(Severity.INFO, "test", "message")
        assert results == []
        channel.send.assert_not_called()

    def test_channel_failure_returns_false(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        channel.send.side_effect = RuntimeError("connection failed")
        mgr.add_channel(channel)
        results = mgr.alert(Severity.WARNING, "test", "message")
        assert results == [False]

    def test_critical_convenience_method(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        channel.send.return_value = True
        mgr.add_channel(channel)
        results = mgr.critical("title", "msg")
        assert results == [True]

    def test_warning_convenience_method(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        channel.send.return_value = True
        mgr.add_channel(channel)
        results = mgr.warning("title", "msg")
        assert results == [True]

    def test_info_convenience_method(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        channel.send.return_value = True
        mgr.add_channel(channel, min_severity=Severity.INFO)
        results = mgr.info("title", "msg")
        assert results == [True]

    def test_remove_channel(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        mgr.add_channel(channel)
        assert mgr.channel_count == 1
        mgr.remove_channel(channel)
        assert mgr.channel_count == 0

    def test_multiple_channels(self):
        mgr = AlertManager()
        ch1 = MagicMock(spec=Channel)
        ch2 = MagicMock(spec=Channel)
        ch1.send.return_value = True
        ch2.send.return_value = True
        mgr.add_channel(ch1, min_severity=Severity.INFO)
        mgr.add_channel(ch2, min_severity=Severity.INFO)
        results = mgr.alert(Severity.INFO, "test", "msg")
        assert len(results) == 2

    def test_alert_includes_details(self):
        mgr = AlertManager()
        channel = MagicMock(spec=Channel)
        mgr.add_channel(channel)
        mgr.alert(Severity.WARNING, "test", "msg", details={"key": "val"}, asset="EURUSD")
        call_args = channel.send.call_args[0][0]
        assert isinstance(call_args, Alert)
        assert call_args.severity == Severity.WARNING
        assert call_args.title == "test"
        assert call_args.details == {"key": "val"}
        assert call_args.asset == "EURUSD"


class TestGlobalAlertManager:
    def test_default_singleton(self):
        _reset_alert_manager()
        mgr1 = global_alert_manager()
        mgr2 = global_alert_manager()
        assert mgr1 is mgr2

    def test_override(self):
        mgr = AlertManager()
        result = global_alert_manager(override=mgr)
        assert result is mgr


class TestSetupAlertingFromConfig:
    def test_no_config_no_crash(self):
        _reset_alert_manager()
        mgr = setup_alerting_from_config(config={})
        assert isinstance(mgr, AlertManager)

    def test_with_alerting_config_disabled(self):
        _reset_alert_manager()
        config = {"alerting": {"channels": {}}}
        mgr = setup_alerting_from_config(config)
        assert mgr.channel_count == 0
