import os
import tempfile

import pandas as pd
import pytest

from paper_trading.simulation_snapshot import (
    AssetSnapshot,
    SimulationStore,
    build_asset_snapshot,
)

SAMPLE_TIMESTAMP = "2026-06-15T12:00:00"


class TestBuildAssetSnapshot:
    def test_basic(self):
        metrics = {
            "current_value": 10500.0,
            "peak_value": 11000.0,
            "initial_capital": 10000.0,
            "n_trades": 5,
            "n_signals": 12,
            "trade_log": [{"side": "long", "pnl": 100.0}],
            "prob_history": [
                {"signal": "BUY", "confidence": 72, "close_price": 101.5,
                 "prob_long": 0.65, "prob_short": 0.15, "date": "2026-06-15"},
            ],
            "position": {
                "side": "long", "entry": 100.0, "sl": 95.0, "tp": 110.0,
                "entry_date": "2026-06-01", "current_vol": 0.02,
            },
        }
        snap = build_asset_snapshot(
            asset_name="TEST",
            metrics=metrics,
            validity_state="GREEN",
            validity_exposure=1.0,
            meta_inference={"meta_confidence": 0.82, "meta_decision": "FULL"},
            feature_stability={"jaccard_top_10": 0.75, "spearman_rank_corr": 0.8},
            timestamp=SAMPLE_TIMESTAMP,
        )
        assert snap.asset == "TEST"
        assert snap.current_value == 10500.0
        assert snap.peak_value == 11000.0
        assert snap.position_side == "long"
        assert snap.position_entry == 100.0
        assert snap.n_trades == 5
        assert snap.n_signals == 12
        assert snap.last_signal == "BUY"
        assert snap.last_confidence == 72
        assert snap.last_close_price == 101.5
        assert snap.validity_state == "GREEN"
        assert snap.meta_confidence == 0.82
        assert snap.meta_decision == "FULL"
        assert snap.feature_stability_jaccard == 0.75

    def test_no_position(self):
        metrics = {
            "current_value": 10000.0,
            "peak_value": 10000.0,
            "initial_capital": 10000.0,
            "n_trades": 0,
            "n_signals": 10,
            "trade_log": [],
            "prob_history": [],
            "position": None,
        }
        snap = build_asset_snapshot(
            asset_name="NO_POS", metrics=metrics,
            validity_state="YELLOW", validity_exposure=0.5,
            meta_inference=None, feature_stability=None,
            timestamp=SAMPLE_TIMESTAMP,
        )
        assert snap.position_side is None
        assert snap.position_entry is None
        assert snap.last_signal is None

    def test_no_prob_history(self):
        metrics = {
            "current_value": 10000.0, "peak_value": 10000.0,
            "initial_capital": 10000.0, "n_trades": 0, "n_signals": 0,
            "trade_log": [], "prob_history": [], "position": None,
        }
        snap = build_asset_snapshot(
            asset_name="EMPTY", metrics=metrics,
            validity_state="RED", validity_exposure=0.0,
            meta_inference=None, feature_stability=None,
            timestamp=SAMPLE_TIMESTAMP,
        )
        assert snap.last_signal is None
        assert snap.last_confidence is None


class TestSimulationStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield SimulationStore(tmp)

    def _make_snapshot(self, asset: str, ts: str, value: float):
        return AssetSnapshot(
            asset=asset, timestamp=ts,
            current_value=value, peak_value=value, initial_capital=value,
            position_side=None, position_entry=None, position_sl=None,
            position_tp=None, position_entry_date=None, position_vol=None,
            n_trades=0, n_signals=0, trade_log=[], prob_history=[],
        )

    def test_capture_creates_file(self, store):
        snap = self._make_snapshot("TEST", SAMPLE_TIMESTAMP, 10000.0)
        store.capture(
            portfolio_value=100000.0, total_return=0.0,
            cash_buffer=5000.0, satellite_value=0.0,
            asset_snapshots=[snap],
        )
        assert os.path.exists(store.snapshot_path)

    def test_load_snapshot_roundtrip(self, store):
        snap = self._make_snapshot("TEST", SAMPLE_TIMESTAMP, 10500.0)
        store.capture(
            portfolio_value=105000.0, total_return=5.0,
            cash_buffer=5000.0, satellite_value=0.0,
            asset_snapshots=[snap],
        )
        loaded = store.load_snapshot(SAMPLE_TIMESTAMP)
        assert loaded is not None
        assert loaded.timestamp == SAMPLE_TIMESTAMP
        assert loaded.portfolio_value == 105000.0
        assert "TEST" in loaded.assets
        assert loaded.assets["TEST"].current_value == 10500.0

    def test_load_snapshot_multiple_assets(self, store):
        snaps = [
            self._make_snapshot("A", SAMPLE_TIMESTAMP, 100.0),
            self._make_snapshot("B", SAMPLE_TIMESTAMP, 200.0),
        ]
        store.capture(
            portfolio_value=300.0, total_return=0.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=snaps,
        )
        loaded = store.load_snapshot(SAMPLE_TIMESTAMP)
        assert len(loaded.assets) == 2
        assert loaded.assets["A"].current_value == 100.0
        assert loaded.assets["B"].current_value == 200.0

    def test_load_snapshot_by_date(self, store):
        snap = self._make_snapshot("TEST", "2026-06-15T10:00:00", 100.0)
        store.capture(
            portfolio_value=100.0, total_return=0.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=[snap],
        )
        loaded = store.load_snapshot_by_date("2026-06-15")
        assert loaded is not None
        assert loaded.assets["TEST"].current_value == 100.0

    def test_load_snapshot_by_date_no_match(self, store):
        loaded = store.load_snapshot_by_date("2099-01-01")
        assert loaded is None

    def test_list_snapshot_dates(self, store):
        snaps = [
            self._make_snapshot("A", "2026-06-15T10:00:00", 100.0),
            self._make_snapshot("A", "2026-06-16T10:00:00", 101.0),
        ]
        for s in snaps:
            store.capture(
                portfolio_value=100.0, total_return=0.0,
                cash_buffer=0.0, satellite_value=0.0,
                asset_snapshots=[s],
            )
        dates = store.list_snapshot_dates()
        assert "2026-06-15T10:00:00" in dates
        assert "2026-06-16T10:00:00" in dates

    def test_load_snapshot_no_file_returns_none(self, store):
        loaded = store.load_snapshot("2026-06-15T12:00:00")
        assert loaded is None

    def test_capture_with_position(self, store):
        snap = AssetSnapshot(
            asset="POS", timestamp=SAMPLE_TIMESTAMP,
            current_value=11000.0, peak_value=11000.0, initial_capital=10000.0,
            position_side="long", position_entry=100.0,
            position_sl=95.0, position_tp=110.0,
            position_entry_date="2026-06-01", position_vol=0.02,
            n_trades=3, n_signals=15, trade_log=[], prob_history=[],
        )
        store.capture(
            portfolio_value=110000.0, total_return=10.0,
            cash_buffer=2000.0, satellite_value=5000.0,
            asset_snapshots=[snap],
        )
        loaded = store.load_snapshot(SAMPLE_TIMESTAMP)
        assert loaded.assets["POS"].position_side == "long"
        assert loaded.assets["POS"].position_entry == 100.0
        assert loaded.assets["POS"].n_trades == 3

    def test_capture_deduplicates(self, store):
        snap = self._make_snapshot("DUP", SAMPLE_TIMESTAMP, 100.0)
        store.capture(
            portfolio_value=100.0, total_return=0.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=[snap],
        )
        # Capture again with same timestamp — should deduplicate
        store.capture(
            portfolio_value=101.0, total_return=1.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=[snap],
        )
        df = pd.read_parquet(store.snapshot_path)
        matching = df[(df["timestamp"] == SAMPLE_TIMESTAMP) & (df["asset"] == "DUP")]
        assert len(matching) == 1

    def test_empty_asset_list_does_not_write(self, store):
        store.capture(
            portfolio_value=0.0, total_return=0.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=[],
        )
        assert not os.path.exists(store.snapshot_path)

    def test_cold_state_roundtrip(self, store):
        cold = {"model_paths": {"TEST": "models/TEST_model.pkl"}, "schema": "1.0"}
        store.capture(
            portfolio_value=100.0, total_return=0.0,
            cash_buffer=0.0, satellite_value=0.0,
            asset_snapshots=[self._make_snapshot("T", SAMPLE_TIMESTAMP, 100.0)],
            cold_state=cold,
        )
        loaded = store.load_cold_state()
        assert loaded is not None
        assert loaded["model_paths"]["TEST"] == "models/TEST_model.pkl"
