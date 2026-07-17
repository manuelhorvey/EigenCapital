"""Tests for paper_trading.ops.slack_alerter — SlackAlerter, event processing, drawdown checks."""

from __future__ import annotations

import json
import os
import tempfile
import time as _real_time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from paper_trading.ops.slack_alerter import (
    COOLDOWN_HALT,
    DRAWDOWN_THRESHOLD,
    SlackAlerter,
    _build_blocks,
    _check_drawdown,
    _load_alert_state,
    _save_alert_state,
    _send_slack,
)


# ── _send_slack ────────────────────────────────────────────────────────────


class TestSendSlack:
    def test_returns_true_on_success(self):
        with patch("paper_trading.ops.slack_alerter.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.status = 200
            assert _send_slack("https://hooks.slack.com/foo", {"text": "test"})

    def test_returns_false_on_http_error(self):
        with patch("paper_trading.ops.slack_alerter.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.status = 400
            assert not _send_slack("https://hooks.slack.com/foo", {"text": "test"})

    def test_returns_false_on_exception(self):
        with patch("paper_trading.ops.slack_alerter.urllib.request.urlopen", side_effect=OSError("no network")):
            assert not _send_slack("https://hooks.slack.com/foo", {"text": "test"})


# ── Alert state persistence ────────────────────────────────────────────────


class TestAlertState:
    def test_load_returns_defaults_when_no_file(self):
        with patch.object(Path, "exists", return_value=False):
            state = _load_alert_state()
            assert state["wal_position"] == 0
            assert state["cooldowns"] == {}

    def test_load_returns_content_when_file_exists(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"wal_position": 42, "cooldowns": {}, "last_state_drawdown": None}, f)
            tmppath = f.name
        try:
            with patch("paper_trading.ops.slack_alerter.ALERT_STATE_PATH", Path(tmppath)):
                state = _load_alert_state()
                assert state["wal_position"] == 42
        finally:
            os.unlink(tmppath)

    def test_save_writes_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmppath = f.name
        try:
            with patch("paper_trading.ops.slack_alerter.ALERT_STATE_PATH", Path(tmppath)):
                _save_alert_state({"wal_position": 99})
                with open(tmppath) as f:
                    data = json.load(f)
                assert data["wal_position"] == 99
        finally:
            os.unlink(tmppath)


# ── _check_drawdown ────────────────────────────────────────────────────────


class TestCheckDrawdown:
    def test_returns_none_when_no_state(self):
        with patch.object(Path, "exists", return_value=False):
            assert _check_drawdown() is None

    def test_returns_drawdown(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"portfolio": {"portfolio_value": 90, "peak_value": 100}}, f)
            tmppath = f.name
        try:
            with patch("paper_trading.ops.slack_alerter.STATE_PATH", Path(tmppath)):
                dd = _check_drawdown()
                assert dd == pytest.approx(-0.1)
        finally:
            os.unlink(tmppath)

    def test_returns_none_when_no_peak(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"portfolio": {"portfolio_value": 90}}, f)
            tmppath = f.name
        try:
            with patch("paper_trading.ops.slack_alerter.STATE_PATH", Path(tmppath)):
                assert _check_drawdown() is None
        finally:
            os.unlink(tmppath)


# ── _build_blocks ──────────────────────────────────────────────────────────


class TestBuildBlocks:
    def test_includes_header(self):
        blocks = _build_blocks("Test Alert", "🚨", [])
        assert blocks[0]["type"] == "header"
        assert "Test Alert" in blocks[0]["text"]["text"]

    def test_includes_fields(self):
        fields = [{"type": "mrkdwn", "text": "field1"}]
        blocks = _build_blocks("H", "⚠️", fields)
        assert any(b["type"] == "section" for b in blocks)

    def test_includes_context(self):
        blocks = _build_blocks("H", "⚠️", [], context="custom context")
        ctx = [b for b in blocks if b["type"] == "context"]
        assert len(ctx) == 1
        assert "custom context" in ctx[0]["elements"][0]["text"]


# ── SlackAlerter ───────────────────────────────────────────────────────────


class TestSlackAlerterInit:
    def test_initializes_default_state(self):
        with patch.object(Path, "exists", return_value=False):
            alerter = SlackAlerter("https://hooks.slack.com/foo")
            assert alerter.webhook_url == "https://hooks.slack.com/foo"
            assert alerter.state["wal_position"] == 0

    def test_stores_last_wal_event_time_on_poll(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"event_type": "state_committed", "payload": {"actors": {}, "emergency_halt": false}}\n')
            wal_path = f.name
        try:
            alerter = SlackAlerter.__new__(SlackAlerter)
            alerter.webhook_url = "https://hooks.slack.com/foo"
            alerter.wal_path = Path(wal_path)
            alerter.state = {"wal_position": 0, "cooldowns": {}}
            alerter._last_wal_event_time = 0.0
            alerter._engine_down_sent = False
            alerter._send_asset_halted = MagicMock()
            alerter._send_emergency_halt = MagicMock()
            alerter._send_concentration_alert = MagicMock()
            before = _real_time.time()
            alerter._poll_wal()
            assert alerter._last_wal_event_time >= before
        finally:
            os.unlink(wal_path)


class TestSlackAlerterPoll:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._send_asset_halted = MagicMock()
            a._send_emergency_halt = MagicMock()
            a._send_concentration_alert = MagicMock()
            return a

    def test_poll_noop_when_wal_missing(self, alerter):
        with patch.object(Path, "exists", return_value=False):
            alerter._poll_wal()

    def test_poll_reads_new_events(self, alerter):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(
                json.dumps(
                    {
                        "event_type": "position_concentration",
                        "payload": {"skew": 0.8, "threshold": 0.75, "alert": True, "dominant_side": "short"},
                    }
                )
                + "\n"
            )
            wal_path = f.name
        try:
            alerter.wal_path = Path(wal_path)
            alerter.state["wal_position"] = 0
            alerter._poll_wal()
            alerter._send_concentration_alert.assert_called_once()
        finally:
            os.unlink(wal_path)


class TestProcessEvent:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._handle_state_committed = MagicMock()
            a._handle_concentration = MagicMock()
            return a

    def test_routes_state_committed(self, alerter):
        alerter._process_event({"event_type": "state_committed", "payload": {"actors": {}}})
        alerter._handle_state_committed.assert_called_once()

    def test_routes_concentration(self, alerter):
        alerter._process_event({"event_type": "position_concentration", "payload": {"skew": 0.8}})
        alerter._handle_concentration.assert_called_once()

    def test_ignores_unknown(self, alerter):
        alerter._process_event({"event_type": "unknown"})
        alerter._handle_state_committed.assert_not_called()
        alerter._handle_concentration.assert_not_called()


class TestHandleStateCommitted:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._send_asset_halted = MagicMock()
            a._send_emergency_halt = MagicMock()
            return a

    def test_sends_halt_alert_for_halted_asset(self, alerter):
        payload = {
            "actors": {"EURUSD": {"health": "HALTED", "cycle_id": 5, "consecutive_failures": 3}},
            "emergency_halt": False,
        }
        alerter._handle_state_committed(payload)
        alerter._send_asset_halted.assert_called_once()

    def test_sends_emergency_halt_when_flagged(self, alerter):
        payload = {"actors": {}, "emergency_halt": True}
        alerter._handle_state_committed(payload)
        alerter._send_emergency_halt.assert_called_once()

    def test_respects_halt_cooldown(self, alerter):
        import time

        alerter.state["cooldowns"]["halt:EURUSD"] = time.time()
        payload = {"actors": {"EURUSD": {"health": "HALTED"}}, "emergency_halt": False}
        alerter._handle_state_committed(payload)
        alerter._send_asset_halted.assert_not_called()

    def test_sends_after_cooldown_expires(self, alerter):
        import time

        alerter.state["cooldowns"]["halt:EURUSD"] = time.time() - COOLDOWN_HALT - 10
        payload = {
            "actors": {"EURUSD": {"health": "HALTED", "cycle_id": 1, "consecutive_failures": 1}},
            "emergency_halt": False,
        }
        alerter._handle_state_committed(payload)
        alerter._send_asset_halted.assert_called_once()


class TestHandleConcentration:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._send_concentration_alert = MagicMock()
            return a

    def test_sends_onset_alert_on_transition(self, alerter):
        alerter._handle_concentration({"skew": 0.8, "threshold": 0.75, "alert": True, "dominant_side": "short"})
        alerter._send_concentration_alert.assert_called_once_with(0.8, 0.75, "short", alert_type="onset")

    def test_sends_clear_alert_on_recovery(self, alerter):
        alerter.state["concentration_state"] = "above_threshold"
        alerter._handle_concentration({"skew": 0.5, "threshold": 0.75, "alert": False, "dominant_side": "long"})
        alerter._send_concentration_alert.assert_called_once_with(0.5, 0.75, "long", alert_type="clear")

    def test_sends_heartbeat_when_sustained(self, alerter):
        import time

        alerter.state["concentration_state"] = "above_threshold"
        alerter.state["concentration_heartbeat_due"] = time.time() - 1
        alerter._handle_concentration({"skew": 0.85, "threshold": 0.75, "alert": True, "dominant_side": "short"})
        alerter._send_concentration_alert.assert_called_once_with(0.85, 0.75, "short", alert_type="heartbeat")

    def test_no_alert_when_below_threshold_and_no_change(self, alerter):
        alerter.state["concentration_state"] = "below_threshold"
        alerter._handle_concentration({"skew": 0.5, "threshold": 0.75, "alert": False, "dominant_side": "none"})
        alerter._send_concentration_alert.assert_not_called()


class TestCheckEngineStale:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._send_engine_stale = MagicMock()
            return a

    def test_sends_alert_when_stale(self, alerter):
        import time

        alerter._last_wal_event_time = time.time() - 200
        alerter._check_engine_stale()
        alerter._send_engine_stale.assert_called_once()

    def test_sends_only_once(self, alerter):
        import time

        alerter._engine_down_sent = True
        alerter._last_wal_event_time = time.time() - 200
        alerter._check_engine_stale()
        alerter._send_engine_stale.assert_not_called()

    def test_clears_flag_when_engine_recovers(self, alerter):
        import time

        alerter._engine_down_sent = True
        alerter._last_wal_event_time = time.time()
        alerter._check_engine_stale()
        assert not alerter._engine_down_sent


class TestDrawdownAlert:
    @pytest.fixture
    def alerter(self):
        with patch.object(Path, "exists", return_value=False):
            a = SlackAlerter("https://hooks.slack.com/foo")
            a._send_drawdown_alert = MagicMock()
            return a

    def test_sends_when_below_threshold_and_new_low(self, alerter):
        with patch("paper_trading.ops.slack_alerter._check_drawdown", return_value=DRAWDOWN_THRESHOLD - 0.01):
            alerter._check_state_if_due()
            alerter._send_drawdown_alert.assert_called_once()

    def test_skips_when_above_threshold(self, alerter):
        with patch("paper_trading.ops.slack_alerter._check_drawdown", return_value=-0.05):
            alerter._check_state_if_due()
            alerter._send_drawdown_alert.assert_not_called()

    def test_resets_on_recovery(self, alerter):
        alerter.state["last_state_drawdown"] = -0.12
        with patch("paper_trading.ops.slack_alerter._check_drawdown", return_value=-0.05):
            alerter._check_state_if_due()
            assert alerter.state["last_state_drawdown"] is None


class TestMain:
    def test_main_noop_without_webhook(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("paper_trading.ops.slack_alerter.logger") as mock_log:
                from paper_trading.ops.slack_alerter import main

                main()
                mock_log.warning.assert_called_once()

    def test_main_creates_alerter_with_webhook(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/foo"}, clear=True):
            with patch("paper_trading.ops.slack_alerter.SlackAlerter.run") as mock_run:
                with patch.object(Path, "exists", return_value=False):
                    from paper_trading.ops.slack_alerter import main

                    main()
                    mock_run.assert_called_once()
