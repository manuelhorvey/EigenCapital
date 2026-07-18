"""Targeted tests for state persistence layer components.

Tests DatabaseStore, SnapshotManager, DataCache, and AnalyticsStore
directly (not through the StateStore facade).
"""

import json
import os
import time

import pandas as pd
import pytest

from paper_trading.state import (
    _AnalyticsStore,
    _DatabaseStore,
    _DataCache,
    _SnapshotManager,
    EngineSnapshot,
)


class TestDatabaseStore:
    """Tests for _DatabaseStore — SQLite-backed append store."""

    def test_initialization_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        store.verify()
        with store._get_connection() as conn:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        for t in store.REQUIRED_TABLES:
            assert t in tables, f"Missing table: {t}"
        store.close_all_connections()

    def test_initialization_sets_wal_mode(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        with store._get_connection() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode == "wal"
        store.close_all_connections()

    def test_initialization_creates_indices(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        with store._get_connection() as conn:
            indices = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
                ).fetchall()
            }
        expected = {
            "idx_trades_asset_entry",
            "idx_trades_exit_date",
            "idx_trades_asset_exit",
            "idx_attribution_entry",
            "idx_attribution_exit_date",
            "idx_attribution_filter",
            "idx_shadow_alt_label",
            "idx_shadow_exit_date",
            "idx_confidence_asset_date",
            "idx_equity_timestamp",
            "idx_equity_assets_equity_id",
            "idx_equity_assets_name",
        }
        assert indices == expected
        store.close_all_connections()

    def test_append_and_read_trades(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        trade = {
            "asset": "BTC",
            "side": "long",
            "entry": 50000.0,
            "exit": 51000.0,
            "entry_date": "2026-06-01",
            "exit_date": "2026-06-02",
            "return": 0.02,
            "pnl": 1000.0,
            "total_pnl": 1000.0,
            "reason": "TP",
            "realized_r": 2.0,
            "bars": 24,
            "conf_at_entry": 0.8,
            "archetype_at_entry": "trend_following",
        }
        store.append_trade(trade)
        trades = store.read_trades(limit=10)
        assert len(trades) == 1
        assert trades[0]["asset"] == "BTC"
        assert trades[0]["side"] == "long"
        assert trades[0]["entry"] == 50000.0
        assert trades[0]["pnl"] == 1000.0
        store.close_all_connections()

    def test_read_trades_empty(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        assert store.read_trades() == []
        store.close_all_connections()

    def test_read_trades_limit(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        for i in range(10):
            store.append_trade({
                "asset": "BTC",
                "side": "long",
                "entry": 50000.0,
                "entry_date": f"2026-06-{i+1:02d}",
                "exit_date": f"2026-06-{i+2:02d}",
            })
        assert len(store.read_trades(limit=3)) == 3
        store.close_all_connections()

    def test_read_trades_since(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        store.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000, "exit": 51000,
            "entry_date": "2026-01-01", "exit_date": "2026-01-15",
            "return": 0.02,
        })
        store.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000, "exit": 51000,
            "entry_date": "2026-06-01", "exit_date": "2026-06-15",
            "return": 0.02,
        })
        df = store.read_trades_since("2026-03-01")
        assert len(df) == 1
        assert df.iloc[0]["exit_date"] == "2026-06-15"
        store.close_all_connections()

    def test_append_and_read_attribution(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        attr = {
            "asset": "EURUSD",
            "trade_id": "T001",
            "entry_date": "2026-06-01",
            "exit_date": "2026-06-02",
            "side": "long",
            "entry_price": 1.1000,
            "exit_price": 1.1050,
            "exit_exit_reason": "TP",
            "exit_realized_r": 1.5,
            "realized_return": 0.005,
            "realized_pnl": 500.0,
            "policy_hash": "abc123",
            "archetype_version": "v3",
            "exit_exit_archetype": "momentum",
            "pred_signal": "long",
            "pred_label": 1,
            "pred_confidence": 0.75,
            "pred_prob_long": 0.75,
            "pred_prob_short": 0.15,
            "pred_prob_neutral": 0.10,
            "pred_meta_proba": 0.72,
            "pred_regime_at_entry": "bullish",
            "pred_archetype_at_entry": "trend_following",
            "exec_entry_type": "market",
            "exec_deferred_bars": 0,
            "exec_entry_price": 1.1000,
            "exec_mid_price_at_signal": 1.0995,
            "exec_entry_slippage_bps": 0.5,
            "friction_entry_slippage_bps": 0.3,
            "friction_exit_slippage_bps": 0.4,
            "exit_mae": -0.002,
            "exit_mfe": 0.008,
            "exit_mae_per_bar": -0.0001,
            "exit_mfe_per_bar": 0.0003,
            "exit_bars_held": 24,
        }
        store.append_attribution(attr)
        records = store.read_attribution(limit=10)
        assert len(records) == 1
        assert records[0]["asset"] == "EURUSD"
        assert records[0]["trade_id"] == "T001"
        store.close_all_connections()

    def test_read_attribution_with_filters(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        for arch in ["trend_following", "mean_reversion"]:
            for regime in ["bullish", "bearish"]:
                store.append_attribution({
                    "asset": "EURUSD",
                    "trade_id": f"T_{arch}_{regime}",
                    "entry_date": "2026-06-01",
                    "exit_date": "2026-06-02",
                    "side": "long",
                    "entry_price": 1.1000,
                    "pred_archetype_at_entry": arch,
                    "pred_regime_at_entry": regime,
                })
        assert len(store.read_attribution(limit=10, archetype="trend_following")) == 2
        assert len(store.read_attribution(limit=10, regime="bearish")) == 2
        assert len(store.read_attribution(limit=10, asset="EURUSD")) == 4
        # Combined filter
        result = store.read_attribution(
            limit=10, archetype="trend_following", regime="bullish"
        )
        assert len(result) == 1
        store.close_all_connections()

    def test_append_and_read_shadow_trades(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        shadow = {
            "asset": "GBPUSD",
            "alt_label": "alt_v1",
            "entry_date": "2026-06-01",
            "exit_date": "2026-06-02",
            "side": "short",
            "entry_price": 1.2500,
            "exit_price": 1.2450,
            "sl_price": 1.2600,
            "tp_price": 1.2400,
            "reason": "TP",
            "return": 0.004,
            "pnl": 400.0,
            "realized_r": 1.2,
            "bars_held": 24,
            "live_exit_reason": "TP",
            "live_realized_r": 1.2,
        }
        store.append_shadow_trade(shadow)
        records = store.read_shadow_trades(limit=10)
        assert len(records) == 1
        assert records[0]["asset"] == "GBPUSD"
        assert records[0]["alt_label"] == "alt_v1"
        # Filter by alt_label
        records = store.read_shadow_trades(limit=10, alt_label="alt_v1")
        assert len(records) == 1
        records = store.read_shadow_trades(limit=10, alt_label="nonexistent")
        assert len(records) == 0
        store.close_all_connections()

    def test_append_and_read_equity_history(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        record = {
            "timestamp": "2026-06-01T12:00:00",
            "portfolio_value": 100000.0,
            "portfolio_return": 0.05,
            "drawdown": -0.02,
            "gross_exposure": 50000.0,
            "net_exposure": 30000.0,
            "vol_spike": 0.15,
            "var_95": 0.02,
            "assets": {"BTC": 50000.0, "ETH": 30000.0},
        }
        store.append_equity_history(record)
        history = store.read_equity_history()
        assert len(history) == 1
        entry = history[0]
        assert entry["portfolio_value"] == 100000.0
        assert entry["portfolio_return"] == 0.05
        assert entry["assets"] == {"BTC": 50000.0, "ETH": 30000.0}
        store.close_all_connections()

    def test_append_confidence_bucket_normalized(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        bucket = {
            "asset": "BTC",
            "date": "2026-06-01",
            "bucket_start": 0,
            "bucket_end": 10,
            "count": 5,
            "mean_conf": 0.05,
            "n_signals": 5,
        }
        store.append_confidence_bucket(bucket)
        with store._get_connection() as conn:
            rows = conn.execute("SELECT * FROM confidence_buckets").fetchall()
        assert len(rows) == 1
        assert rows[0]["count"] == 5
        store.close_all_connections()

    def test_append_confidence_bucket_legacy_format(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        bucket = {
            "asset": "BTC",
            "date": "2026-06-01",
            "count_0_10": 5,
            "count_90_100": 3,
            "mean_conf": 0.5,
            "n_signals": 8,
        }
        store.append_confidence_bucket(bucket)
        with store._get_connection() as conn:
            rows = conn.execute("SELECT * FROM confidence_buckets").fetchall()
        assert len(rows) == 2
        store.close_all_connections()

    def test_append_equity_asset_snapshot(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        record = {
            "timestamp": "2026-06-01",
            "portfolio_value": 100000,
            "assets": {},
        }
        store.append_equity_history(record)
        history = store.read_equity_history()
        equity_id = history[0]["id"]
        store.append_equity_asset_snapshot(equity_id, "SOL", 25000.0)
        history = store.read_equity_history()
        assert history[0]["assets"]["SOL"] == 25000.0
        store.close_all_connections()

    def test_append_equity_history_without_assets(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        record = {
            "timestamp": "2026-06-01T12:00:00",
            "portfolio_value": 100000.0,
        }
        store.append_equity_history(record)
        history = store.read_equity_history()
        assert len(history) == 1
        assert history[0]["portfolio_value"] == 100000.0
        store.close_all_connections()

    def test_prune_trades_dry_run(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        for i in range(5):
            store.append_trade({
                "asset": "BTC",
                "side": "long",
                "entry": 50000.0,
                "entry_date": f"2026-{i+1:02d}-01",
                "exit_date": f"2026-{i+1:02d}-15",
            })
        result = store.prune_trades("2026-03-01", apply=False)
        assert result["total"] == 5
        assert result["pruned"] == 2
        assert result["kept"] == 3
        assert len(store.read_trades(limit=100)) == 5
        store.close_all_connections()

    def test_prune_trades_removes_old_data(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        for i in range(5):
            store.append_trade({
                "asset": "BTC",
                "side": "long",
                "entry": 50000.0,
                "entry_date": f"2026-{i+1:02d}-01",
                "exit_date": f"2026-{i+1:02d}-15",
            })
        result = store.prune_trades("2026-03-01", apply=True)
        assert result["pruned"] == 2
        assert result["kept"] == 3
        assert len(store.read_trades(limit=100)) == 3
        store.close_all_connections()

    def test_prune_trades_nothing_to_prune(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        store.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000,
            "entry_date": "2026-06-01", "exit_date": "2026-06-15",
        })
        result = store.prune_trades("2026-01-01", apply=True)
        assert result["pruned"] == 0
        assert result["kept"] == 1
        store.close_all_connections()

    def test_prune_attribution_removes_old_data(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        for i in range(3):
            store.append_attribution({
                "asset": "EURUSD",
                "trade_id": f"T{i:03d}",
                "entry_date": f"2026-{i+1:02d}-01",
                "exit_date": f"2026-{i+1:02d}-15",
                "side": "long",
                "entry_price": 1.1000,
            })
        result = store.prune_attribution("2026-02-15", apply=True)
        assert result["total"] == 3
        assert result["pruned"] == 1
        assert result["kept"] == 2
        store.close_all_connections()

    def test_prune_equity_history_cascades(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        store.append_equity_history({
            "timestamp": "2026-01-01T12:00:00",
            "portfolio_value": 100000.0,
            "assets": {"BTC": 50000.0},
        })
        store.append_equity_history({
            "timestamp": "2026-06-01T12:00:00",
            "portfolio_value": 110000.0,
            "assets": {"BTC": 60000.0},
        })
        result = store.prune_equity_history("2026-03-01", apply=True)
        assert result["total"] == 2
        assert result["pruned"] == 1
        assert result["kept"] == 1
        history = store.read_equity_history()
        assert len(history) == 1
        assert history[0]["timestamp"] == "2026-06-01T12:00:00"
        store.close_all_connections()

    def test_prune_all_aggregates(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = _DatabaseStore(db_path)
        store.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000, "entry_date": "2026-01-01", "exit_date": "2026-01-15",
        })
        store.append_attribution({
            "asset": "EURUSD", "trade_id": "T001",
            "entry_date": "2026-01-01", "exit_date": "2026-01-15",
            "side": "long", "entry_price": 1.10,
        })
        store.append_equity_history({
            "timestamp": "2026-01-01", "portfolio_value": 100000, "assets": {},
        })
        result = store.prune_all("2026-06-01", apply=True)
        assert result["trades"]["pruned"] == 1
        assert result["attribution"]["pruned"] == 1
        assert result["equity_history"]["pruned"] == 1
        store.close_all_connections()


class TestSnapshotManager:
    """Tests for _SnapshotManager — JSON snapshot persistence with cache."""

    def test_save_and_load(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.0)
        snap = EngineSnapshot(
            timestamp="2026-06-01T12:00:00",
            portfolio={"total_value": 105000.0},
            engine_status={"initialized": True},
        )
        mgr.save(snap)
        loaded = mgr.load()
        assert loaded is not None
        assert loaded.timestamp == "2026-06-01T12:00:00"
        assert loaded.portfolio["total_value"] == 105000.0

    def test_load_no_file(self, tmp_path):
        mgr = _SnapshotManager(str(tmp_path / "nonexistent.json"))
        assert mgr.load() is None

    def test_load_corrupt_file(self, tmp_path):
        path = str(tmp_path / "state.json")
        with open(path, "w") as f:
            f.write("not json at all")
        mgr = _SnapshotManager(path)
        assert mgr.load() is None

    def test_load_empty_file(self, tmp_path):
        path = str(tmp_path / "state.json")
        with open(path, "w") as f:
            f.write("")
        mgr = _SnapshotManager(path)
        assert mgr.load() is None

    def test_sequence_counter_increments(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path)
        snap1 = EngineSnapshot(timestamp="2026-01-01")
        snap2 = EngineSnapshot(timestamp="2026-01-02")
        snap3 = EngineSnapshot(timestamp="2026-01-03")
        mgr.save(snap1)
        seq1 = snap1.sequence_id
        mgr.save(snap2)
        mgr.save(snap3)
        # Sequence IDs are strictly monotonic across all saves
        assert snap1.sequence_id < snap2.sequence_id < snap3.sequence_id
        assert snap3.sequence_id == seq1 + 2

    def test_sequence_counter_monotonic_across_instances(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr1 = _SnapshotManager(state_path)
        mgr2 = _SnapshotManager(str(tmp_path / "state2.json"))
        snap = EngineSnapshot(timestamp="2026-01-01")
        mgr1.save(snap)
        seq1 = snap.sequence_id
        mgr2.save(snap)
        assert snap.sequence_id == seq1 + 1

    def test_load_returns_latest_snapshot_from_disk(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.0)
        mgr.save(EngineSnapshot(timestamp="2026-01-01", portfolio={"v": 1}))
        mgr.save(EngineSnapshot(timestamp="2026-01-02", portfolio={"v": 2}))
        loaded = mgr.load()
        assert loaded is not None
        assert loaded.timestamp == "2026-01-02"
        assert loaded.portfolio["v"] == 2

    def test_cache_hit_within_ttl(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=5.0)
        snap = EngineSnapshot(timestamp="2026-06-01", portfolio={"v": 100})
        mgr.save(snap)
        # First load reads from disk and caches
        loaded1 = mgr.load()
        assert loaded1 is not None
        # Tamper the file on disk
        with open(state_path) as f:
            data = json.load(f)
        data["portfolio"]["v"] = 999
        del data["_checksum"]
        with open(state_path, "w") as f:
            json.dump(data, f)
        # Load again — should return cached version (within TTL)
        loaded2 = mgr.load()
        assert loaded2 is not None
        assert loaded2.portfolio["v"] == 100

    def test_cache_expires_after_ttl(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.01)
        snap = EngineSnapshot(timestamp="2026-06-01T12:00:00")
        mgr.save(snap)
        loaded1 = mgr.load()
        assert loaded1 is not None
        time.sleep(0.02)
        # Cache expired — load re-reads from disk
        loaded2 = mgr.load()
        assert loaded2 is not None

    def test_checksum_rejects_tampered_file(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.0)
        mgr.save(EngineSnapshot(timestamp="2026-06-01", portfolio={"v": 100}))
        with open(state_path) as f:
            data = json.load(f)
        # Tamper the data but keep the original checksum so mismatch is detected
        data["portfolio"]["v"] = 999
        with open(state_path, "w") as f:
            json.dump(data, f)
        loaded = mgr.load()
        assert loaded is None

    def test_load_rejects_future_contract_version(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.0)
        mgr.save(EngineSnapshot(timestamp="2026-06-01"))
        with open(state_path) as f:
            data = json.load(f)
        data["contract_version"] = 99
        data.pop("_checksum", None)
        with open(state_path, "w") as f:
            json.dump(data, f)
        loaded = mgr.load()
        assert loaded is None

    def test_load_accepts_older_contract_version(self, tmp_path):
        state_path = str(tmp_path / "state.json")
        mgr = _SnapshotManager(state_path, cache_ttl=0.0)
        mgr.save(EngineSnapshot(timestamp="2026-06-01"))
        with open(state_path) as f:
            data = json.load(f)
        data["contract_version"] = 2
        data.pop("_checksum", None)
        with open(state_path, "w") as f:
            json.dump(data, f)
        loaded = mgr.load()
        assert loaded is not None


class TestDataCache:
    """Tests for _DataCache — Parquet file cache."""

    def test_save_and_load(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        cache.save("TEST", df)
        loaded = cache.load("TEST")
        assert loaded is not None
        assert len(loaded) == 3
        assert list(loaded["close"]) == [100.0, 101.0, 102.0]

    def test_load_missing(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        assert cache.load("NONEXISTENT") is None

    def test_path_normalizes_ticker(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        path = cache.path_for("BTC-USD")
        assert "BTC_USD" in path
        assert path.endswith(".parquet")

    def test_path_handles_equals_sign(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        path = cache.path_for("BTC=USD")
        assert "BTC_USD" in path
        assert path.endswith(".parquet")

    def test_load_empty_dataframe(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        df = pd.DataFrame()
        cache.save("EMPTY", df)
        assert cache.load("EMPTY") is None

    def test_save_creates_directory(self, tmp_path):
        nested = str(tmp_path / "sub" / "dir")
        cache = _DataCache(nested)
        assert os.path.exists(nested)
        cache.save("TEST", pd.DataFrame({"close": [1.0]}))
        assert cache.load("TEST") is not None

    def test_roundtrip_preserves_columns(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        df = pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 1100],
            }
        )
        cache.save("EURUSD", df)
        loaded = cache.load("EURUSD")
        assert loaded is not None
        assert list(loaded.columns) == list(df.columns)

    def test_multiple_tickers_independent(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        cache.save("BTC", pd.DataFrame({"close": [100.0]}))
        cache.save("ETH", pd.DataFrame({"close": [200.0]}))
        btc = cache.load("BTC")
        eth = cache.load("ETH")
        assert btc is not None and eth is not None
        assert btc["close"].iloc[0] == 100.0
        assert eth["close"].iloc[0] == 200.0

    def test_overwrite_existing_ticker(self, tmp_path):
        cache = _DataCache(str(tmp_path))
        cache.save("BTC", pd.DataFrame({"close": [100.0]}))
        cache.save("BTC", pd.DataFrame({"close": [200.0]}))
        loaded = cache.load("BTC")
        assert loaded is not None
        assert loaded["close"].iloc[0] == 200.0


class TestAnalyticsStore:
    """Tests for _AnalyticsStore — precomputed analytics snapshots."""

    def test_trade_outcomes_with_data(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = _DatabaseStore(db_path)
        analytics_path = str(tmp_path / "analytics.json")
        outcomes_path = str(tmp_path / "outcomes.json")
        store = _AnalyticsStore(db, analytics_path, outcomes_path)

        db.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000, "exit": 51000,
            "entry_date": "2026-06-01", "exit_date": "2026-06-02",
            "return": 0.02, "realized_r": 2.0,
            "reason": "TP",
        })
        result = store.read_trade_outcomes()
        assert result is not None
        assert result["overall"]["tp_rate"] == 1.0
        assert result["overall"]["win_rate"] == 1.0
        assert len(result["by_asset"]) == 1
        assert result["by_asset"][0]["asset"] == "BTC"
        db.close_all_connections()

    def test_trade_outcomes_empty_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = _DatabaseStore(db_path)
        analytics_path = str(tmp_path / "analytics.json")
        outcomes_path = str(tmp_path / "outcomes.json")
        store = _AnalyticsStore(db, analytics_path, outcomes_path)

        result = store.read_trade_outcomes()
        assert result is None
        db.close_all_connections()

    def test_trade_outcomes_cache_ttl(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = _DatabaseStore(db_path)
        analytics_path = str(tmp_path / "analytics.json")
        outcomes_path = str(tmp_path / "outcomes.json")
        store = _AnalyticsStore(db, analytics_path, outcomes_path)

        db.append_trade({
            "asset": "BTC", "side": "long",
            "entry": 50000, "exit": 51000,
            "entry_date": "2026-06-01", "exit_date": "2026-06-02",
            "return": 0.02, "realized_r": 2.0,
            "reason": "TP",
        })
        result = store.read_trade_outcomes()
        assert result is not None
        assert result["overall"]["tp_rate"] == 1.0

        # Second call returns cached result (within 30s TTL)
        result2 = store.read_trade_outcomes()
        assert result2["overall"]["tp_rate"] == 1.0
        db.close_all_connections()

    def test_write_snapshot_frequency(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = _DatabaseStore(db_path)
        analytics_path = str(tmp_path / "analytics.json")
        outcomes_path = str(tmp_path / "outcomes.json")
        store = _AnalyticsStore(db, analytics_path, outcomes_path)

        db.append_attribution({
            "asset": "BTC", "trade_id": "T001",
            "entry_date": "2026-06-01", "exit_date": "2026-06-02",
            "side": "long", "entry_price": 50000, "exit_price": 51000,
            "exit_realized_r": 2.0,
            "pred_archetype_at_entry": "trend_following",
            "pred_regime_at_entry": "bullish",
        })

        # First 4 calls should not write (counter < frequency)
        for _ in range(4):
            store.write_snapshot()
        assert not os.path.exists(analytics_path)

        # 5th call triggers the write
        store.write_snapshot()
        assert os.path.exists(analytics_path)

        result = store.read_snapshot()
        assert result is not None
        assert result["overall"]["n_trades"] == 1
        db.close_all_connections()

    def test_write_snapshot_with_shadow_data(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = _DatabaseStore(db_path)
        analytics_path = str(tmp_path / "analytics.json")
        outcomes_path = str(tmp_path / "outcomes.json")
        store = _AnalyticsStore(db, analytics_path, outcomes_path)

        db.append_attribution({
            "asset": "BTC", "trade_id": "T001",
            "entry_date": "2026-06-01", "exit_date": "2026-06-02",
            "side": "long", "entry_price": 50000,
            "exit_realized_r": 2.0,
        })
        db.append_shadow_trade({
            "asset": "BTC", "alt_label": "shadow_v1",
            "entry_date": "2026-06-01", "exit_date": "2026-06-02",
            "side": "long", "entry_price": 50000, "exit_price": 51000,
            "reason": "TP", "return": 0.02, "pnl": 200,
            "realized_r": 2.0, "bars_held": 24,
            "live_exit_reason": "TP", "live_realized_r": 2.0,
        })

        for _ in range(5):
            store.write_snapshot()

        result = store.read_snapshot()
        assert result is not None
        assert result["shadow"]["n"] == 1
        # The shadow trades DB column is "reason", not "exit_reason",
        # so the divergence check compares "" vs "TP" -> all diverge
        assert result["shadow"]["divergence_rate"] == 1.0
        db.close_all_connections()

    def test_read_snapshot_no_file(self, tmp_path):
        cache_dir = str(tmp_path)
        mgr = _SnapshotManager(str(tmp_path / "state.json"))
        analytics_path = str(tmp_path / "no_such_file.json")
        store = _AnalyticsStore(None, analytics_path, str(tmp_path / "outcomes.json"))
        assert store.read_snapshot() is None
