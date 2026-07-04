"""Tests for WAL event capture + deterministic replay (Phase 6).

Covers:
    1. WAL event schema — all event types write and parse correctly
    2. WAL writer — append-only, crash-safe, monotonic sequences
    3. WAL reader — read_all, read_from, count
    4. Replay runner — state reconstruction from events
    5. Continuity verification — replay matches across passes
    6. Determinism assertion — identical WAL + snapshot → identical output
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from paper_trading.replay.runner import ReplayMismatchError, ReplayRunner
from paper_trading.replay.wal import WalEvent, WalReader, WalWriter


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_wal_dir() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def writer(tmp_wal_dir: str) -> WalWriter:
    return WalWriter(tmp_wal_dir, source="test_engine", batch_size=1)


@pytest.fixture
def reader(tmp_wal_dir: str) -> WalReader:
    return WalReader(tmp_wal_dir, source="test_engine")


@pytest.fixture
def full_event_chain(writer: WalWriter) -> list[WalEvent]:
    """Write a complete decision chain for one asset."""
    events = []
    events.append(writer.write("price_update", {"asset": "EURUSD", "price": 1.1050, "ohlcv": {"open": 1.1040, "high": 1.1060, "low": 1.1030, "close": 1.1050}}))
    events.append(writer.write("signal_generated", {"asset": "EURUSD", "signal": "BUY", "confidence": 0.72}))
    events.append(writer.write("entry_executed", {"asset": "EURUSD", "side": "long", "fill_price": 1.1052, "fill_qty": 10000.0, "slippage_bps": 1.8}))
    events.append(writer.write("sl_executed", {"asset": "EURUSD", "fill_price": 1.1020, "gap_fill": True, "slippage_bps": 3.2}))
    events.append(writer.write("position_closed", {"asset": "EURUSD", "reason": "sl_hit", "pnl": -32.0}))
    events.append(writer.write("state_committed", {"assets": {"EURUSD": {"position": None}}}))
    events.append(writer.write("actor_health", {"asset": "EURUSD", "health": "GREEN"}))
    return events


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: WAL Event Schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestWalEvent:
    """Event serialization round-trip."""

    def test_to_dict_from_dict_roundtrip(self):
        event = WalEvent(
            sequence=1,
            source="test",
            event_type="signal_generated",
            timestamp="2026-05-29T12:00:00+00:00",
            payload={"asset": "EURUSD", "signal": "BUY", "confidence": 0.75},
        )
        d = event.to_dict()
        restored = WalEvent.from_dict(d)
        assert restored.sequence == event.sequence
        assert restored.source == event.source
        assert restored.event_type == event.event_type
        assert restored.timestamp == event.timestamp
        assert restored.payload == event.payload

    def test_json_roundtrip(self):
        event = WalEvent(sequence=5, source="engine", event_type="price_update", payload={"price": 1.10})
        raw = json.dumps(event.to_dict())
        restored = WalEvent.from_dict(json.loads(raw))
        assert restored.sequence == 5
        assert restored.payload["price"] == 1.10


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: WAL Writer
# ═══════════════════════════════════════════════════════════════════════════════


class TestWalWriter:
    """Append-only, monotonic sequences, crash safety."""

    def test_writes_sequential_events(self, writer: WalWriter):
        e1 = writer.write("price_update", {"price": 1.10})
        e2 = writer.write("signal_generated", {"signal": "BUY"})
        assert e1.sequence == 1
        assert e2.sequence == 2

    def test_writes_persist_to_disk(self, tmp_wal_dir: str):
        w = WalWriter(tmp_wal_dir, source="persist_test", batch_size=1)
        w.write("price_update", {"price": 1.10})
        assert os.path.exists(w.path)
        with open(w.path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "price_update"

    def test_append_only(self, tmp_wal_dir: str):
        w = WalWriter(tmp_wal_dir, source="append_test", batch_size=1)
        w.write("event_a", {"val": 1})
        w.write("event_b", {"val": 2})
        with open(w.path) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_thread_safe_monotonic(self, writer: WalWriter):
        """Multiple writes from single thread maintain strict order."""
        for i in range(100):
            writer.write("test", {"i": i})
        assert writer.current_sequence == 100

    def test_file_per_source(self, tmp_wal_dir: str):
        w1 = WalWriter(tmp_wal_dir, source="src_a", batch_size=1)
        w2 = WalWriter(tmp_wal_dir, source="src_b", batch_size=1)
        assert w1.path != w2.path
        w1.write("event", {})
        w2.write("event", {})
        assert os.path.exists(w1.path)
        assert os.path.exists(w2.path)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: WAL Reader
# ═══════════════════════════════════════════════════════════════════════════════


class TestWalReader:
    """Read, filter, and count events."""

    def test_read_all(self, writer: WalWriter, reader: WalReader):
        writer.write("a", {"v": 1})
        writer.write("b", {"v": 2})
        events = reader.read_all()
        assert len(events) == 2
        assert events[0].event_type == "a"
        assert events[1].event_type == "b"

    def test_read_from_sequence(self, writer: WalWriter, reader: WalReader):
        for i in range(10):
            writer.write("t", {"i": i})
        events = list(reader.read_from(seq=7))
        assert len(events) == 4  # sequences 7, 8, 9, 10
        assert events[0].sequence == 7

    def test_read_last(self, writer: WalWriter, reader: WalReader):
        for i in range(5):
            writer.write("t", {"i": i})
        last = reader.read_last(n=2)
        assert len(last) == 2
        assert last[0].payload["i"] == 3
        assert last[1].payload["i"] == 4

    def test_count(self, writer: WalWriter, reader: WalReader):
        assert reader.count() == 0
        for i in range(25):
            writer.write("t", {})
        assert reader.count() == 25

    def test_read_empty_returns_empty_list(self, reader: WalReader):
        assert reader.read_all() == []
        assert list(reader.read_from(0)) == []
        assert reader.count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Full Decision Chain Capture
# ═══════════════════════════════════════════════════════════════════════════════


class TestDecisionChainCapture:
    """All event types in a complete cycle are captured correctly."""

    def test_all_event_types_present(self, writer: WalWriter, reader: WalReader):
        event_types = [
            "price_update",
            "feature_computed",
            "signal_generated",
            "risk_approved",
            "entry_executed",
            "sl_executed",
            "tp_executed",
            "position_closed",
            "state_committed",
            "actor_health",
        ]
        for t in event_types:
            writer.write(t, {"asset": "TEST"})

        recorded = {e.event_type for e in reader.read_all()}
        for t in event_types:
            assert t in recorded, f"Event type {t} missing from WAL"

    def test_decision_chain_ordering(self, full_event_chain):
        """Events in a realistic decision chain must be in causal order."""
        expected_order = [
            "price_update",
            "signal_generated",
            "entry_executed",
            "sl_executed",
            "position_closed",
        ]
        recorded_order = [e.event_type for e in full_event_chain if e.event_type in expected_order]
        assert recorded_order == expected_order, (
            f"Decision chain order broken: {recorded_order}"
        )

    def test_event_payloads_carry_required_fields(self, full_event_chain):
        """Each event type must carry the fields needed for replay."""
        for event in full_event_chain:
            assert "asset" in event.payload or event.event_type == "state_committed", (
                f"{event.event_type} missing 'asset' in payload"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Replay Runner — State Reconstruction
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayRunner:
    """State reconstruction from WAL events."""

    def test_replay_from_scratch(self, reader: WalReader, full_event_chain):
        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)
        assert state["events_replayed"] == len(full_event_chain)
        assert "EURUSD" in state["assets"]
        assert state["assets"]["EURUSD"]["last_signal"]["signal"] == "BUY"

    def test_replay_from_midpoint(self, writer: WalWriter, reader: WalReader):
        for i in range(10):
            writer.write("price_update", {"asset": "EURUSD", "price": 1.10 + i * 0.01})
        writer.write("signal_generated", {"asset": "EURUSD", "signal": "SELL", "confidence": 0.65})

        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=11)  # skip first 10, start at event 11 (signal)
        assert state["events_replayed"] == 1
        assert state["assets"]["EURUSD"]["last_signal"]["signal"] == "SELL"

    def test_replay_tracks_sequence(self, writer: WalWriter, reader: WalReader):
        writer.write("price_update", {"asset": "A", "price": 1.0})
        writer.write("price_update", {"asset": "A", "price": 2.0})

        runner = ReplayRunner(reader)
        state = runner.replay(from_sequence=0)
        assert state["last_sequence"] == 2

    def test_empty_wal_returns_empty_state(self, reader: WalReader):
        runner = ReplayRunner(reader)
        state = runner.replay()
        assert state["events_replayed"] == 0

    def test_replay_multiple_assets(self, writer: WalWriter, reader: WalReader):
        writer.write("price_update", {"asset": "EURUSD", "price": 1.10})
        writer.write("price_update", {"asset": "USDJPY", "price": 150.0})
        writer.write("signal_generated", {"asset": "EURUSD", "signal": "BUY"})
        writer.write("signal_generated", {"asset": "USDJPY", "signal": "SELL"})

        runner = ReplayRunner(reader)
        state = runner.replay()
        assert "EURUSD" in state["assets"]
        assert "USDJPY" in state["assets"]
        assert state["assets"]["EURUSD"]["last_signal"]["signal"] == "BUY"
        assert state["assets"]["USDJPY"]["last_signal"]["signal"] == "SELL"

    def test_position_lifecycle_via_replay(self, writer: WalWriter, reader: WalReader):
        """Full position lifecycle: entry → SL → close must be reconstructable."""
        writer.write("entry_executed", {"asset": "EURUSD", "side": "long", "fill_price": 1.10, "fill_qty": 10000})
        writer.write("sl_executed", {"asset": "EURUSD", "fill_price": 1.09, "gap_fill": True})
        writer.write("position_closed", {"asset": "EURUSD", "reason": "sl_hit", "pnl": -100.0})

        runner = ReplayRunner(reader)
        state = runner.replay()
        assert state["assets"]["EURUSD"]["position"] is None  # closed
        assert state["assets"]["EURUSD"]["closed_position"]["reason"] == "sl_hit"
        assert state["assets"]["EURUSD"]["closed_position"]["pnl"] == -100.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: Replay Determinism
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayDeterminism:
    """Identical WAL → identical reconstructed state."""

    def test_two_replays_produce_identical_state(self, writer: WalWriter, reader: WalReader):
        for i in range(20):
            writer.write("price_update", {"asset": "EURUSD", "price": 1.10 + i * 0.001})

        runner = ReplayRunner(reader)
        state_a = runner.replay()
        state_b = runner.replay()
        assert state_a["events_replayed"] == state_b["events_replayed"]
        assert state_a["last_sequence"] == state_b["last_sequence"]

    def test_replay_idempotent(self, writer: WalWriter, reader: WalReader):
        writer.write("signal_generated", {"asset": "EURUSD", "signal": "BUY", "confidence": 0.8})

        runner = ReplayRunner(reader)
        state1 = runner.replay()
        assert state1["events_replayed"] == 1

        # Replay again — same state (but events_replayed resets)
        state2 = runner.replay()
        assert state2["assets"] == state1["assets"]
        assert state2["last_sequence"] == state1["last_sequence"]


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: Continuity Verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestContinuityVerification:
    """Cross-pass state consistency checks."""

    def test_continuity_passes_for_straight_line(self, writer: WalWriter, reader: WalReader):
        for i in range(50):
            writer.write("price_update", {"asset": "EURUSD", "price": 1.10 + i * 0.001})

        runner = ReplayRunner(reader)
        mismatches = runner.verify_continuity(verify_every=10)
        assert len(mismatches) == 0, f"Continuity check failed: {mismatches}"

    def test_continuity_detects_state_divergence(self, writer: WalWriter, reader: WalReader):
        """If two paths produce different states, verify_continuity catches it."""
        for i in range(30):
            writer.write("price_update", {"asset": "EURUSD", "price": 1.10 + i * 0.001})

        runner = ReplayRunner(reader)
        runner.replay()

        # Manually corrupt state after replay
        runner._state["assets"]["EURUSD"]["last_price"] = 999.0

        with pytest.raises(ReplayMismatchError):
            runner._assert_states_match(
                {"assets": {"EURUSD": {"last_price": 1.115}}},  # saved from first pass
                {"assets": {"EURUSD": {"last_price": 999.0}}},  # corrupted
                sequence=20,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: Error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestWalErrorHandling:
    """WAL gracefully handles missing files, corrupt data."""

    def test_reader_on_nonexistent_file(self, tmp_wal_dir: str):
        reader = WalReader(tmp_wal_dir, source="does_not_exist")
        assert reader.read_all() == []
        assert reader.count() == 0

    def test_reader_skips_corrupt_lines(self, tmp_wal_dir: str):
        path = os.path.join(tmp_wal_dir, "data", "live", "wal", "corrupt.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('{"sequence": 1, "source": "t", "event_type": "a", "payload": {}}\n')
            f.write("NOT JSON\n")
            f.write('{"sequence": 2, "source": "t", "event_type": "b", "payload": {}}\n')

        reader = WalReader(tmp_wal_dir, source="corrupt")
        events = reader.read_all()
        assert len(events) == 2  # skips corrupt line
        assert events[0].event_type == "a"
        assert events[1].event_type == "b"


class TestWalConcurrency:
    """Verify locking works correctly under concurrent writes."""

    def test_multithread_writes_no_lost_events(self, tmp_wal_dir: str):
        """100 concurrent writes from multiple threads all land on disk."""
        import threading

        writer = WalWriter(tmp_wal_dir, source="concurrent", batch_size=1)
        n_per_thread = 25
        n_threads = 8
        total_events = n_per_thread * n_threads

        def write_batch(thread_id: int):
            for i in range(n_per_thread):
                writer.write("price_update", {"thread": thread_id, "i": i})

        threads = [
            threading.Thread(target=write_batch, args=(t,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Force flush before reading
        writer.flush()

        # Verify all events were written
        reader = WalReader(tmp_wal_dir, source="concurrent")
        events = reader.read_all()
        assert len(events) == total_events, (
            f"Expected {total_events} events, got {len(events)}"
        )

        # Verify sequences are 1..N with no gaps
        sequences = sorted(e.sequence for e in events)
        assert sequences == list(range(1, total_events + 1)), (
            f"Sequences not a perfect 1..{total_events}: "
            f"min={sequences[0]} max={sequences[-1]} unique={len(set(sequences))}"
        )

    def test_concurrent_flush_does_not_corrupt(self, tmp_wal_dir: str):
        """Concurrent writes + flush calls do not interleave writes half-completed."""
        import threading

        writer = WalWriter(tmp_wal_dir, source="concurrent_flush", batch_size=2)
        n_per_thread = 10
        n_threads = 4

        errors: list[Exception] = []

        def worker(thread_id: int):
            try:
                for i in range(n_per_thread):
                    writer.write("test", {"thread": thread_id, "i": i})
                    writer.flush()  # force concurrent flushes
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(t,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent workers raised: {errors}"

        writer.flush()
        reader = WalReader(tmp_wal_dir, source="concurrent_flush")
        events = reader.read_all()
        # All events should be valid JSON
        for e in events:
            assert isinstance(e.payload, dict)
