"""Tests for EngineRecoveryService — position restore and orphan handling.

Covers:
    - Normal restore for existing assets
    - Orphan handling for removed/delisted assets:
      - With MT5 ticket + real broker (close attempted)
      - Without MT5 ticket (no close)
      - Paper broker (no close)
      - Real broker close failure (exception logged)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from paper_trading.services.engine_recovery_service import EngineRecoveryService

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.ticker_to_mt5_symbol.return_value = "AUDNZD.fx"
    return broker


@pytest.fixture
def mock_execution_bridge(mock_broker):
    bridge = MagicMock()
    bridge.broker = mock_broker
    bridge._is_real_broker = True
    return bridge


@pytest.fixture
def mock_engine(mock_execution_bridge, mock_broker):
    engine = MagicMock()
    engine.execution_bridge = mock_execution_bridge
    engine.broker = mock_broker
    engine.assets = {"EURUSD": MagicMock()}
    return engine


@pytest.fixture
def service(mock_engine):
    return EngineRecoveryService(mock_engine)


@pytest.fixture
def saved_position():
    return {
        "position": {
            "side": "long",
            "entry": 1.0500,
            "entry_date": "2026-06-17",
            "sl": 1.0400,
            "tp": 1.0700,
            "vol": 0.01,
            "mt5_ticket": 12345,
        },
        "current_value": 100000.0,
        "peak_value": 100500.0,
        "trade_log": [],
        "prob_history": [],
    }


# ── Tests ─────────────────────────────────────────────────────────────────


class TestRestoreExistingAsset:
    def test_restore_existing_calls_inner_method(self, service, saved_position):
        """When asset exists in engine.assets, _restore_saved_position is called."""
        saved = {"EURUSD": saved_position}
        service._restore_saved_position = MagicMock()
        service.restore_positions(saved)
        service._restore_saved_position.assert_called_once_with(
            service.engine.assets["EURUSD"], saved_position
        )

    def test_restore_multiple_mixed(self, service, saved_position):
        """Existing assets restored, orphans only warned (no crash on mixed dict)."""
        existing = {"EURUSD": MagicMock()}
        service.engine.assets = existing
        saved = {
            "EURUSD": saved_position,
            "AUDNZD": saved_position,
        }
        service._restore_saved_position = MagicMock()
        service.restore_positions(saved)
        service._restore_saved_position.assert_called_once_with(
            existing["EURUSD"], saved_position
        )


class TestOrphanDelistedWithMt5Ticket:
    def test_orphan_with_mt5_ticket_and_real_broker(self, service, saved_position, mock_broker, caplog):
        """Delisted asset with MT5 ticket on real broker logs WARNING and closes position."""
        caplog.set_level(logging.INFO)
        saved = {"AUDNZD": saved_position}
        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.ticker_to_mt5_symbol.assert_called_once_with("AUDNZD")
        mock_broker.close_position.assert_called_once_with("AUDNZD.fx", "12345")

        assert "Orphan position for removed/delisted asset 'AUDNZD'" in caplog.text
        assert "side=long" in caplog.text
        assert "entry=1.05000" in caplog.text
        assert "mt5_ticket=12345" in caplog.text
        assert "Closed orphan MT5 position for removed asset 'AUDNZD'" in caplog.text

    def test_orphan_without_mt5_ticket(self, service, saved_position, mock_broker, caplog):
        """Delisted asset without MT5 ticket logs WARNING but does NOT close."""
        pos_no_ticket = dict(saved_position)
        pos_no_ticket["position"] = dict(saved_position["position"])
        pos_no_ticket["position"]["mt5_ticket"] = None
        saved = {"AUDNZD": pos_no_ticket}

        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.close_position.assert_not_called()
        assert "Orphan position for removed/delisted asset 'AUDNZD'" in caplog.text
        assert "mt5_ticket=None" in caplog.text

    def test_orphan_missing_position_key(self, service, mock_broker, caplog):
        """Delisted asset with no 'position' key logs WARNING with defaults."""
        saved = {"AUDNZD": {"current_value": 100000.0}}
        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.close_position.assert_not_called()
        assert "Orphan position for removed/delisted asset 'AUDNZD'" in caplog.text
        assert "side=?" in caplog.text
        assert "entry=0.00000" in caplog.text
        assert "mt5_ticket=None" in caplog.text

    def test_orphan_with_mt5_ticket_paper_broker(self, service, saved_position, mock_broker, caplog):
        """Delisted asset with MT5 ticket on paper broker (is_real=False) does NOT close."""
        service.engine.execution_bridge._is_real_broker = False
        saved = {"AUDNZD": saved_position}

        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.close_position.assert_not_called()
        assert "Orphan position for removed/delisted asset 'AUDNZD'" in caplog.text


class TestOrphanCloseFailure:
    def test_orphan_close_raises_exception(self, service, saved_position, mock_broker, caplog):
        """When close_position raises, the exception is caught and logged as ERROR."""
        caplog.set_level(logging.INFO)
        mock_broker.close_position.side_effect = ConnectionError("bridge down")
        saved = {"AUDNZD": saved_position}

        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.ticker_to_mt5_symbol.assert_called_once_with("AUDNZD")
        mock_broker.close_position.assert_called_once_with("AUDNZD.fx", "12345")
        assert "Failed to close orphan MT5 position for removed asset 'AUDNZD'" in caplog.text

    def test_orphan_ticker_to_mt5_symbol_raises(self, service, saved_position, mock_broker, caplog):
        """When ticker_to_mt5_symbol raises, the exception is caught and logged."""
        caplog.set_level(logging.INFO)
        mock_broker.ticker_to_mt5_symbol.side_effect = KeyError("EURUSD")
        saved = {"AUDNZD": saved_position}

        service.engine.assets = {}
        service.restore_positions(saved)

        mock_broker.close_position.assert_not_called()
        assert "Failed to close orphan MT5 position for removed asset 'AUDNZD'" in caplog.text
