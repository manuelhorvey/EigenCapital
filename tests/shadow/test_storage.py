"""Tests for paper_trading/shadow/storage.py — ShadowStorage."""

import tempfile
from pathlib import Path

import pandas as pd

from paper_trading.shadow.storage import ShadowStorage


class TestShadowStorage:
    def test_record_and_flush(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ShadowStorage(base_dir=tmpdir, flush_interval=2)
            store.record("v2", "EURUSD", "BUY", 0.65, 0.60, "BUY", 0.70, 0.68, feature_hash="abc")
            store.record("v2", "EURUSD", "SELL", 0.55, 0.45, "BUY", 0.60, 0.55, feature_hash="def")
            n = store.flush("v2")
            assert n == 2

            # Verify parquet was written
            pq_path = Path(tmpdir) / "v2"
            parquets = list(pq_path.glob("*.parquet"))
            assert len(parquets) == 1
            df = pd.read_parquet(parquets[0])
            assert len(df) == 2
            assert list(df.columns) == [
                "timestamp",
                "feature_hash",
                "model_hash",
                "prod_signal",
                "prod_confidence",
                "prod_p_long",
                "shadow_signal",
                "shadow_confidence",
                "shadow_p_long",
                "inference_time_ms",
                "signal_agreement",
                "confidence_delta",
                "p_long_delta",
            ]

    def test_should_flush(self):
        store = ShadowStorage(flush_interval=3)
        assert not store.should_flush("v2")
        for _ in range(3):
            store.record("v2", "EURUSD", "BUY", 0.6, 0.55, "BUY", 0.65, 0.60)
        assert store.should_flush("v2")

    def test_multiple_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ShadowStorage(base_dir=tmpdir, flush_interval=100)
            store.record("v2", "EURUSD", "BUY", 0.6, 0.55, "HOLD", 0.50, 0.50)
            store.record("v2", "GBPUSD", "SELL", 0.7, 0.30, "SELL", 0.72, 0.28)
            n = store.flush("v2")
            assert n == 2

    def test_aggregate_comparison_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ShadowStorage(base_dir=tmpdir)
            result = store.aggregate_comparison("nonexistent")
            assert result["status"] == "no_data"

    def test_aggregate_comparison_with_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ShadowStorage(base_dir=tmpdir, flush_interval=1)
            store.record("v2", "EURUSD", "BUY", 0.65, 0.60, "BUY", 0.70, 0.68)
            store.flush("v2")
            result = store.aggregate_comparison("v2", lookback_days=365)
            assert result["status"] == "ok"
            assert result["signal_agreement_pct"] == 100.0
            assert result["mean_confidence_delta"] > 0
