"""Tests for paper_trading/writer.py — BackgroundWriter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.writer import BackgroundWriter, WriteCommand, WriteOp


class TestWriteCommand:
    def test_create_wal_event(self):
        cmd = WriteCommand(op=WriteOp.WAL_EVENT, payload={"event_type": "signal", "asset": "EURUSD"})
        assert cmd.op == WriteOp.WAL_EVENT
        assert cmd.payload["event_type"] == "signal"

    def test_create_with_source_and_callback(self):
        called = False

        def cb():
            nonlocal called
            called = True

        cmd = WriteCommand(op=WriteOp.DB_TRADE, payload={}, source="test", callback=cb)
        assert cmd.source == "test"
        cmd.callback()
        assert called


class TestBackgroundWriter:
    def test_enqueue_and_shutdown(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer.enqueue(WriteCommand(op=WriteOp.WAL_EVENT, payload={"event_type": "test"}))
        writer.shutdown(timeout=2.0)
        # No crash = success

    def test_flush(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer.enqueue(WriteCommand(op=WriteOp.WAL_EVENT, payload={"event_type": "test"}))
        ok = writer.flush(timeout=5.0)
        assert ok is True
        writer.shutdown(timeout=2.0)

    def test_execute_wal_event(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.WAL_EVENT, payload={"event_type": "signal", "asset": "EURUSD"}))
        wal.write.assert_called_once_with("signal", {"asset": "EURUSD"})

    def test_execute_db_trade(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.DB_TRADE, payload={"trade_id": "123"}))
        db.append_trade.assert_called_once_with({"trade_id": "123"})

    def test_execute_db_attribution(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.DB_ATTRIBUTION, payload={"trade_id": "123"}))
        db.append_attribution.assert_called_once()

    def test_execute_db_shadow_trade(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.DB_SHADOW_TRADE, payload={}))
        db.append_shadow_trade.assert_called_once()

    def test_execute_db_confidence_bucket(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.DB_CONFIDENCE_BUCKET, payload={}))
        db.append_confidence_bucket.assert_called_once()

    def test_execute_db_equity_history(self):
        wal = MagicMock()
        db = MagicMock()
        writer = BackgroundWriter(wal, db)
        writer._execute(WriteCommand(op=WriteOp.DB_EQUITY_HISTORY, payload={}))
        db.append_equity_history.assert_called_once()
