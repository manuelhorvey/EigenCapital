import json
import os
import tempfile

import pandas as pd
import pytest

from paper_trading.state_store import _SKIP_JOURNAL, EngineSnapshot, StateStore, sanitize


class TestEngineSnapshot:
    def test_default_fields(self):
        snap = EngineSnapshot()
        assert snap.schema_version == "1.0.0"
        assert snap.timestamp == ""

    def test_from_dict_roundtrip(self):
        snap = EngineSnapshot(
            timestamp="2026-01-01T00:00:00",
            portfolio={"total_value": 100000},
            assets={"BTC": {"metrics": {}}},
            engine_status={"initialized": True},
        )
        d = snap.__dict__.copy()
        restored = EngineSnapshot.from_dict(d)
        assert restored.schema_version == snap.schema_version
        assert restored.timestamp == snap.timestamp
        assert restored.portfolio == snap.portfolio

    def test_from_dict_missing_schema_version(self):
        restored = EngineSnapshot.from_dict({"timestamp": "2026-01-01"})
        assert restored.schema_version == "0.0.0"


class TestSanitize:
    def test_handles_inf(self):
        assert sanitize(float("inf")) is None

    def test_handles_nan(self):
        assert sanitize(float("nan")) is None

    def test_passes_normal_float(self):
        assert sanitize(42.5) == 42.5

    def test_handles_nested_dict(self):
        result = sanitize({"a": float("nan"), "b": [float("inf"), 1.0]})
        assert result["a"] is None
        assert result["b"][0] is None
        assert result["b"][1] == 1.0


class TestStateStore:
    @pytest.fixture
    def tmp_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            yield store

    def test_creates_directories(self, tmp_store):
        assert os.path.exists(tmp_store.live_dir)
        assert os.path.exists(tmp_store.cache_dir)

    def test_save_and_load_snapshot(self, tmp_store):
        snap = EngineSnapshot(
            timestamp="2026-06-01T12:00:00",
            portfolio={"total_value": 105000.0},
            engine_status={"initialized": True, "last_update": "2026-06-01 12:00:00"},
        )
        tmp_store.save_snapshot(snap)

        loaded = tmp_store.load_snapshot()
        assert loaded is not None
        assert loaded.timestamp == "2026-06-01T12:00:00"
        assert loaded.portfolio["total_value"] == 105000.0

    def test_load_snapshot_no_file(self, tmp_store):
        assert tmp_store.load_snapshot() is None

    def test_load_snapshot_corrupt(self, tmp_store):
        os.makedirs(os.path.dirname(tmp_store.state_path), exist_ok=True)
        with open(tmp_store.state_path, "w") as f:
            f.write("{{corrupt json")
        loaded = tmp_store.load_snapshot()
        assert loaded is None

    def test_snapshot_version_in_file(self, tmp_store):
        snap = EngineSnapshot(timestamp="2026-01-01")
        tmp_store.save_snapshot(snap)
        with open(tmp_store.state_path) as f:
            data = json.load(f)
        assert data["schema_version"] == "1.0.0"

    def test_append_and_read_trades(self, tmp_store):
        trade = {"asset": "BTC", "side": "long", "pnl": 100.0, "exit_date": "2026-06-01"}
        tmp_store.append_trade(trade)
        trades = tmp_store.read_trades(limit=10)
        assert len(trades) == 1
        assert trades[0]["asset"] == "BTC"

    def test_append_multiple_trades(self, tmp_store):
        for i in range(3):
            tmp_store.append_trade({"asset": "BTC", "pnl": i * 50, "exit_date": f"2026-06-0{i+1}"})
        trades = tmp_store.read_trades(limit=10)
        assert len(trades) == 3

    def test_append_and_read_equity_history(self, tmp_store):
        record = {"timestamp": "2026-06-01", "portfolio_value": 100000}
        tmp_store.append_equity_history(record)
        history = tmp_store.read_equity_history()
        assert len(history) == 1

    def test_equity_history_all_entries(self, tmp_store):
        """SQLite stores all entries (no cap)."""
        for i in range(2010):
            tmp_store.append_equity_history({"timestamp": f"2026-06-{i:03d}", "portfolio_value": i})
        history = tmp_store.read_equity_history()
        assert len(history) == 2010

    def test_cache_path(self, tmp_store):
        path = tmp_store.cache_path("BTC-USD")
        assert "BTC_USD" in path
        assert path.endswith(".parquet")

    def test_cache_save_and_load(self, tmp_store):
        df = pd.DataFrame({"close": [100, 101]})
        tmp_store.save_cache("TEST", df)
        loaded = tmp_store.load_cache("TEST")
        assert loaded is not None
        assert len(loaded) == 2

    def test_cache_load_missing(self, tmp_store):
        assert tmp_store.load_cache("NONEXISTENT") is None

    def test_append_confidence_bucket(self, tmp_store):
        bucket = {"asset": "BTC", "date": "2026-06-01", "mean_conf": 0.5}
        tmp_store.append_confidence_bucket(bucket)
        with tmp_store.db._connect() as conn:
            rows = conn.execute("SELECT * FROM confidence_buckets").fetchall()
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"


class TestSkipJournal:
    def test_skip_journal_is_sentinel(self):
        assert _SKIP_JOURNAL is not None
        assert type(_SKIP_JOURNAL).__name__ == "object"
