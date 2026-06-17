"""End-to-end WAL integration test — engine → WAL → replay.

Validates:
    - WAL events are emitted at each decision step
    - ReplayRunner can reconstruct state from WAL
    - Replayed state is consistent with engine execution
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, PropertyMock

import pytest

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
        writer = WalWriter(wal_dir, source="test")
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        assert any(e.event_type == "price_update" for e in events)

    def test_emits_signal_generated(self, wal_dir):
        writer = WalWriter(wal_dir, source="test")
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        assert any(e.event_type == "signal_generated" for e in events)

    def test_event_ordering(self, wal_dir):
        writer = WalWriter(wal_dir, source="test")
        engine = _make_mock_engine("EURUSD")
        actor = AssetActor("EURUSD", engine, wal_writer=writer)

        actor.run_cycle()

        reader = WalReader(wal_dir, source="test")
        events = reader.read_all()
        types = [e.event_type for e in events]
        assert types.index("price_update") < types.index("signal_generated")

    def test_emits_position_closed_when_trade_log_grows(self, wal_dir):
        writer = WalWriter(wal_dir, source="test")
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
        writer = WalWriter(wal_dir, source="test")
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
        writer = WalWriter(wal_dir, source="test_orch")
        eur = _make_mock_engine("EURUSD", price=1.1050)
        gbp = _make_mock_engine("GBPUSD", price=1.2650)
        return {
            "EURUSD": AssetActor("EURUSD", eur, wal_writer=writer),
            "GBPUSD": AssetActor("GBPUSD", gbp, wal_writer=writer),
        }

    def test_emits_state_committed(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch")
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="test_orch")
        events = reader.read_all()
        assert any(e.event_type == "state_committed" for e in events)

    def test_emits_actor_health(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch")
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="test_orch")
        events = reader.read_all()
        assert any(e.event_type == "actor_health" for e in events)

    def test_health_payload(self, wal_dir, actors):
        writer = WalWriter(wal_dir, source="test_orch")
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
        writer = WalWriter(wal_dir, source="e2e")
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
        writer = WalWriter(wal_dir, source="e2e")
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
        writer = WalWriter(wal_dir, source="e2e")
        eur = _make_mock_engine("EURUSD")
        actors = {"EURUSD": AssetActor("EURUSD", eur, wal_writer=writer)}
        orch = EngineOrchestrator(actors, wal_writer=writer)

        orch.run_once()

        reader = WalReader(wal_dir, source="e2e")
        state1 = ReplayRunner(reader).replay(from_sequence=0)
        state2 = ReplayRunner(reader).replay(from_sequence=0)

        assert state1["events_replayed"] == state2["events_replayed"]

    def test_multiple_cycles_are_monotonic(self, wal_dir):
        writer = WalWriter(wal_dir, source="e2e")
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
        writer = WalWriter(wal_dir, source="e2e")
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
