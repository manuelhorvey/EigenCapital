"""Tests for shared/metrics_snapshot.py."""

from __future__ import annotations

import pytest

from shared.metrics_snapshot import MetricsSnapshot


class TestMetricsSnapshotDataclass:
    def test_default_values(self):
        snap = MetricsSnapshot()
        assert snap.asset == ""
        assert snap.current_value == 0.0
        assert snap.n_trades == 0
        assert snap.n_signals == 0

    def test_to_dict_roundtrip(self):
        snap = MetricsSnapshot(
            asset="EURUSD",
            current_value=100500.0,
            total_return=0.5,
            n_trades=10,
            n_signals=100,
            win_rate=60.0,
            profit_factor=1.5,
            signal_distribution={"BUY": 40, "SELL": 60, "FLAT": 0},
            sharpe_ratio=0.85,
        )
        d = snap.to_dict()
        assert d["asset"] == "EURUSD"
        assert d["n_trades"] == 10
        assert d["sharpe_ratio"] == 0.85

    def test_from_dict_roundtrip(self):
        snap = MetricsSnapshot.from_dict(
            {
                "asset": "GBPUSD",
                "current_value": 99000.0,
                "n_trades": 5,
                "win_rate": 40.0,
                "nonexistent_key": "ignored",
            }
        )
        assert snap.asset == "GBPUSD"
        assert snap.n_trades == 5
        assert snap.current_value == 99000.0
        assert not hasattr(snap, "nonexistent_key")

    def test_get_method(self):
        snap = MetricsSnapshot(asset="BTCUSD")
        assert snap.get("asset") == "BTCUSD"
        assert snap.get("nonexistent", "fallback") == "fallback"
        assert snap.get("asset", "fallback") == "BTCUSD"

    def test_getitem_method(self):
        snap = MetricsSnapshot(asset="NZDUSD", n_trades=3)
        assert snap["asset"] == "NZDUSD"
        assert snap["n_trades"] == 3

    def test_optional_fields_default_to_none(self):
        snap = MetricsSnapshot()
        assert snap.profit_factor is None
        assert snap.monthly_pf is None
        assert snap.position is None
        assert snap.meta_inference is None
        assert snap.scale_out_tiers is None

    def test_sharpe_fields_default_to_none(self):
        snap = MetricsSnapshot()
        assert snap.sharpe_ratio is None
        assert snap.psr_gt_0 is None
        assert snap.psr_gt_1 is None
        assert snap.min_trl is None
        assert snap.crs is None
        assert snap.hhi is None

    def test_exit_reasons_default_empty(self):
        snap = MetricsSnapshot()
        assert snap.exit_reasons == {}
        assert snap.archetype_stats == {}

    def test_signal_distribution_default(self):
        snap = MetricsSnapshot()
        assert snap.signal_distribution == {"BUY": 0, "SELL": 0, "FLAT": 0}
