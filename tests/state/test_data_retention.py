"""Tests for SQLite data retention pruning (trades, attribution, equity_history)."""

from __future__ import annotations

import os
import tempfile

import pytest

from paper_trading.state_store import StateStore


class TestPruneTrades:
    def test_prune_no_data(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            result = store.db.prune_trades("2026-01-01", apply=True)
            assert result["total"] == 0
            assert result["pruned"] == 0

    def test_prune_keeps_recent(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_trade({
                "asset": "EURUSD",
                "side": "long",
                "entry": 1.05,
                "exit": 1.06,
                "entry_date": "2026-01-01",
                "exit_date": "2026-07-01",
            })
            result = store.db.prune_trades("2026-06-01", apply=True)
            assert result["total"] == 1
            assert result["pruned"] == 0
            assert result["kept"] == 1

    def test_prune_removes_old(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_trade({
                "asset": "EURUSD",
                "side": "long",
                "entry": 1.05,
                "exit": 1.06,
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
            })
            result = store.db.prune_trades("2026-01-01", apply=True)
            assert result["total"] == 1
            assert result["pruned"] == 1
            assert result["kept"] == 0

    def test_prune_keeps_mixed(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_trade({
                "asset": "EURUSD",
                "side": "long",
                "entry": 1.05,
                "exit": 1.06,
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
            })
            store.append_trade({
                "asset": "GBPUSD",
                "side": "short",
                "entry": 1.25,
                "exit": 1.24,
                "entry_date": "2026-01-01",
                "exit_date": "2026-07-01",
            })
            result = store.db.prune_trades("2026-01-01", apply=True)
            assert result["total"] == 2
            assert result["pruned"] == 1
            assert result["kept"] == 1


class TestPruneAttribution:
    def test_prune_removes_old(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_attribution({
                "asset": "EURUSD",
                "trade_id": "t1",
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
                "side": "long",
                "exit_realized_r": 2.0,
            })
            result = store.db.prune_attribution("2026-01-01", apply=True)
            assert result["total"] == 1
            assert result["pruned"] == 1

    def test_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_attribution({
                "asset": "EURUSD",
                "trade_id": "t1",
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
                "side": "long",
                "exit_realized_r": 2.0,
            })
            result = store.db.prune_attribution("2026-01-01", apply=False)
            assert result["total"] == 1
            assert result["pruned"] == 1
            # Verify data still exists (dry-run)
            remaining = store.read_attribution(limit=100)
            assert len(remaining) == 1


class TestPruneEquityHistory:
    def test_prune_removes_old(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_equity_history({
                "timestamp": "2025-01-01T00:00:00",
                "portfolio_value": 100000,
                "assets": {},
            })
            result = store.db.prune_equity_history("2026-01-01", apply=True)
            assert result["total"] == 1
            assert result["pruned"] == 1

    def test_cascade_deletes_asset_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_equity_history({
                "timestamp": "2025-01-01T00:00:00",
                "portfolio_value": 100000,
                "assets": {"BTC": 50000, "ETH": 20000},
            })
            # Verify snapshots exist before prune
            history = store.read_equity_history()
            assert len(history) == 1
            assert len(history[0].get("assets", {})) == 2

            store.db.prune_equity_history("2026-01-01", apply=True)
            after = store.read_equity_history()
            assert len(after) == 0


class TestPruneAll:
    def test_prune_all_aggregates(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_trade({
                "asset": "EURUSD",
                "side": "long",
                "entry": 1.05,
                "exit": 1.06,
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
            })
            store.append_attribution({
                "asset": "EURUSD",
                "trade_id": "t1",
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
                "side": "long",
                "exit_realized_r": 2.0,
            })
            store.append_equity_history({
                "timestamp": "2025-01-01T00:00:00",
                "portfolio_value": 100000,
                "assets": {},
            })
            result = store.db.prune_all("2026-01-01", apply=True)
            assert result["trades"]["pruned"] == 1
            assert result["attribution"]["pruned"] == 1
            assert result["equity_history"]["pruned"] == 1

    def test_prune_all_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.append_trade({
                "asset": "EURUSD",
                "side": "long",
                "entry": 1.05,
                "exit": 1.06,
                "entry_date": "2025-01-01",
                "exit_date": "2025-06-01",
            })
            result = store.db.prune_all("2026-01-01", apply=False)
            assert result["trades"]["pruned"] == 1
            # Data still exists after dry-run
            trades = store.read_trades(limit=10)
            assert len(trades) == 1
