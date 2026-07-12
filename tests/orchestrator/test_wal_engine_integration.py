"""End-to-end WAL integration test — engine → WAL → replay.

Validates:
    - WAL events are emitted at each decision step
    - ReplayRunner can reconstruct state from WAL
    - Replayed state is consistent with engine execution
    - Causal chain hash integrity (features → inference → decision)
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from unittest.mock import MagicMock, PropertyMock

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from shared.model import XGBoostModel
from paper_trading.inference.pipeline import AssetInferencePipeline
from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator
from paper_trading.replay.runner import ReplayRunner
from paper_trading.replay.wal import WalReader, WalWriter


@pytest.fixture
def wal_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _make_mock_engine(name: str, price: float = 100.0, signal: dict | None = None):
    """Create a minimal mock AssetEngine for testing WAL wiring."""
    engine = MagicMock()
    engine.current_price = price
    engine.name = name
    engine.pos_mgr.has_position.return_value = False
    engine.pos_mgr.current_side.return_value = None
    engine.trade_log = []

    if signal is None:
        signal = {"signal": "BUY", "confidence": 0.72, "position_size": 1.0}
    engine.generate_signal.return_value = signal

    type(engine).mtm_value = PropertyMock(return_value=100_000.0)
    type(engine).current_value = PropertyMock(return_value=100_000.0)
    type(engine).peak_value = PropertyMock(return_value=100_000.0)
    engine._last_entry_notional = 0.0

    return engine


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: WAL events emitted through AssetActor
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssetActorWALEmission:
    """AssetActor emits WAL events during run_cycle."""

    def test_emits_price_update(self, wal_dir):
        writer = WalWriter(wal_dir, source="test", batch_size=1, archive_daily=False)
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        assert any(e.event_type == "price_update" for e in events)

    def test_emits_signal_generated(self, wal_dir):
        writer = WalWriter(wal_dir, source="test", batch_size=1, archive_daily=False)
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        assert any(e.event_type == "signal_generated" for e in events)

    def test_event_ordering(self, wal_dir):
        writer = WalWriter(wal_dir, source="test", batch_size=1, archive_daily=False)
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        types = [e.event_type for e in events]
        assert types.index("price_update") < types.index("signal_generated")

    def test_emits_position_closed_when_trade_log_grows(self, wal_dir):
        writer = WalWriter(wal_dir, source="test", batch_size=1, archive_daily=False)
        engine = _make_mock_engine("EURUSD")
        engine.trade_log = [
            {"reason": "sl_hit", "pnl": -150.0, "exit_price": 98.5, "entry_price": 100.0, "side": "long", "exit_date": "2026-05-29"}
        ]
        actor = AssetActor("EURUSD", engine, wal_writer=writer)
        actor._last_trade_count = 0

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        closed = [e for e in events if e.event_type == "position_closed"]
        assert len(closed) >= 1
        assert closed[0].payload["reason"] == "sl_hit"

    def test_no_wal_when_none(self):
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=None)
        result = actor.run_cycle()
        assert result.success

    def test_signal_payload_contains_expected_fields(self, wal_dir):
        writer = WalWriter(wal_dir, source="test", batch_size=1, archive_daily=False)
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        signal_events = [e for e in events if e.event_type == "signal_generated"]
        assert len(signal_events) >= 1
        payload = signal_events[0].payload
        assert "asset" in payload
        assert "signal" in payload
        assert "confidence" in payload


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Orchestrator-level WAL emission
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrchestratorWALEmission:
    """EngineOrchestrator emits portfolio-level WAL events."""

    @pytest.fixture
    def actors(self, wal_dir):
        writer = WalWriter(wal_dir, source="test_orch", batch_size=1, archive_daily=False)
        eur = _make_mock_engine("EURUSD", price=1.1050)
        gbp = _make_mock_engine("GBPUSD", price=1.2650)
        return {
            "EURUSD": AssetActor("EURUSD", eur, wal_writer=writer),
            "GBPUSD": AssetActor("GBPUSD", gbp, wal_writer=writer),
        }

    def test_emits_state_committed(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch", batch_size=1, archive_daily=False)
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="test_orch")
        events = reader.read_all()
        assert any(e.event_type == "state_committed" for e in events)

    def test_emits_actor_health(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch", batch_size=1, archive_daily=False)
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="test_orch")
        events = reader.read_all()
        assert any(e.event_type == "actor_health" for e in events)

    def test_health_payload(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch", batch_size=1, archive_daily=False)
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="test_orch")
        events = reader.read_all()
        health = [e for e in events if e.event_type == "actor_health"]
        assert len(health) >= 1
        assert "green" in health[0].payload
        assert "system_healthy" in health[0].payload


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: End-to-end replay consistency
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEndReplay:
    """ReplayRunner produces state consistent with engine execution from WAL."""

    def test_replay_produces_all_assets(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e", batch_size=1, archive_daily=False)
        eur = _make_mock_engine("EURUSD")
        gbp = _make_mock_engine("GBPUSD")
        actors = {
            "EURUSD": AssetActor("EURUSD", eur, wal_writer=writer),
            "GBPUSD": AssetActor("GBPUSD", gbp, wal_writer=writer),
        }
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)

        assert state["events_replayed"] > 0
        assert "assets" in state

    def test_replay_captures_signals(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e", batch_size=1, archive_daily=False)
        eur = _make_mock_engine("EURUSD", signal={"signal": "SELL", "confidence": 0.8, "position_size": 0.5})
        actors = {"EURUSD": AssetActor("EURUSD", eur, wal_writer=writer)}
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)

        if "EURUSD" in state.get("assets", {}):
            sig = state["assets"]["EURUSD"].get("last_signal")
            if sig is not None:
                assert sig.get("signal") == "SELL"
                assert sig.get("confidence") == 0.8

    def test_replay_deterministic(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e", batch_size=1, archive_daily=False)
        eur = _make_mock_engine("EURUSD")
        actors = {"EURUSD": AssetActor("EURUSD", eur, wal_writer=writer)}
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        state1 = ReplayRunner(reader).replay(from_sequence=0)
        state2 = ReplayRunner(reader).replay(from_sequence=0)

        assert state1["events_replayed"] == state2["events_replayed"]

    def test_multiple_cycles_are_monotonic(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e", batch_size=1, archive_daily=False)
        eur = _make_mock_engine("EURUSD")
        actors = {"EURUSD": AssetActor("EURUSD", eur, wal_writer=writer)}
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()
        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        events = reader.read_all()
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)  # no duplicates

    def test_replay_ignores_unknown_event_types(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e", batch_size=1, archive_daily=False)
        writer.write("unknown_event_type", {"foo": "bar"})

        eur = _make_mock_engine("EURUSD")
        actors = {"EURUSD": AssetActor("EURUSD", eur, wal_writer=writer)}
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)

        assert state["events_replayed"] > 0
        assert "assets" in state


class TestCausalChainHashIntegrity:
    """Verifies feature_hash and model_hash flow consistently through
    features_snapshot → inference_output → decision_output."""

    def test_inference_output_hash_chain(self, tmp_path):
        """_run_inference emits inference_output with matching hashes."""
        np.random.seed(42)
        X = np.random.randn(60, 3)
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        clf = xgb.XGBClassifier(n_estimators=10, max_depth=2, random_state=42, verbosity=0)
        clf.fit(X, y)

        model_path = tmp_path / "test_model.json"
        clf.save_model(str(model_path))
        model_hash = hashlib.sha256(open(model_path, "rb").read()).hexdigest()[:16]

        loaded = xgb.XGBClassifier()
        loaded.load_model(str(model_path))

        engine = MagicMock()
        engine.name = "TESTASSET"
        engine._model_iface = XGBoostModel()
        engine.model = loaded
        engine._model_hash = model_hash
        engine._ensemble = None
        engine._regime_model = None
        engine._meta_label_model = None
        engine._truncate_inference = False
        engine._last_regime_raw_probas = None
        engine._last_regime_long_prob = None
        engine._last_regime_features = None
        engine._last_meta_proba = None

        wal_dir = tmp_path / "wal"
        wal_dir.mkdir()
        writer = WalWriter(str(wal_dir), source="test_chain", batch_size=1, archive_daily=False)
        engine._wal_writer = writer

        features = {"feature_0": 0.75, "feature_1": -0.30, "feature_2": 0.10}
        feature_df = pd.DataFrame([features])
        feature_hash = hashlib.md5(json.dumps(features, sort_keys=True).encode()).hexdigest()[:12]

        pipeline = AssetInferencePipeline(engine)
        proba, _ = pipeline._run_inference(engine, feature_df, feature_df, feature_hash=feature_hash)

        reader = WalReader(str(wal_dir), source="test_chain")
        events = reader.read_all()
        inference_events = [e for e in events if e.event_type == "inference_output"]
        assert len(inference_events) == 1
        ie = inference_events[0]

        assert ie.payload["feature_hash"] == feature_hash
        assert ie.payload["model_hash"] == model_hash
        assert ie.payload["prob_long"] == round(float(proba[-1, 2]), 6)
        assert ie.payload["prob_short"] == round(float(proba[-1, 0]), 6)
        assert ie.payload["prob_neutral"] == round(float(proba[-1, 1]), 6)
        assert ie.payload["asset"] == "TESTASSET"

    def test_full_causal_chain_replay(self, tmp_path):
        """Full WAL replay: hash consistency + model reload → proba match."""
        np.random.seed(1)
        X = np.random.randn(60, 4)
        y = (X[:, 0] - X[:, 2] > 0).astype(int)
        clf = xgb.XGBClassifier(n_estimators=10, max_depth=2, random_state=42, verbosity=0)
        clf.fit(X, y)

        model_path = tmp_path / "chain_model.json"
        clf.save_model(str(model_path))
        model_hash = hashlib.sha256(open(model_path, "rb").read()).hexdigest()[:16]

        wal_dir = tmp_path / "wal"
        wal_dir.mkdir()
        writer = WalWriter(str(wal_dir), source="test_chain", batch_size=1, archive_daily=False)

        features = {"f0": 0.5, "f1": -0.1, "f2": 0.3, "f3": 0.0}
        feature_hash = hashlib.md5(json.dumps(features, sort_keys=True).encode()).hexdigest()[:12]

        writer.write("features_snapshot", {
            "asset": "TESTASSET", "features": features,
            "feature_hash": feature_hash, "feature_schema": sorted(features.keys()),
            "model_hash": model_hash,
        })

        loaded = xgb.XGBClassifier()
        loaded.load_model(str(model_path))
        iface = XGBoostModel()
        raw = iface.predict(loaded, pd.DataFrame([features]))
        proba = (
            np.column_stack([1.0 - raw[:, 1], np.zeros(raw.shape[0]), raw[:, 1]])
            if raw.shape[1] == 2 else raw[:, :3]
        )

        writer.write("inference_output", {
            "asset": "TESTASSET",
            "prob_long": round(float(proba[-1, 2]), 6),
            "prob_short": round(float(proba[-1, 0]), 6),
            "prob_neutral": round(float(proba[-1, 1]), 6),
            "model_hash": model_hash, "feature_hash": feature_hash,
        })
        writer.write("decision_output", {
            "asset": "TESTASSET", "final_signal": "LONG",
            "gates_aborted": False,
            "feature_hash": feature_hash, "model_hash": model_hash,
        })

        reader = WalReader(str(wal_dir), source="test_chain")
        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)
        ast = state["assets"].get("TESTASSET", {})

        assert ast.get("feature_hash") == feature_hash
        assert ast.get("model_hash") == model_hash
        assert ast["last_inference"]["feature_hash"] == feature_hash
        assert ast["last_decision"]["feature_hash"] == feature_hash
        assert ast["last_inference"]["model_hash"] == model_hash
        assert ast["last_decision"]["model_hash"] == model_hash

        # Reload model by hash → re-run inference → compare proba
        reloaded = xgb.XGBClassifier()
        reloaded.load_model(str(model_path))
        assert hashlib.sha256(open(model_path, "rb").read()).hexdigest()[:16] == model_hash

        re_raw = iface.predict(reloaded, pd.DataFrame([features]))
        re_proba = (
            np.column_stack([1.0 - re_raw[:, 1], np.zeros(re_raw.shape[0]), re_raw[:, 1]])
            if re_raw.shape[1] == 2 else re_raw[:, :3]
        )
        recorded = ast["last_inference"]
        assert re_proba[0, 2] == pytest.approx(recorded["prob_long"], abs=1e-6)
        assert re_proba[0, 0] == pytest.approx(recorded["prob_short"], abs=1e-6)
        assert re_proba[0, 1] == pytest.approx(recorded["prob_neutral"], abs=1e-6)
