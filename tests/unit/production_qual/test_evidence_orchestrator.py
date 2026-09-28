"""Evidence orchestrator snapshot rate-limiter tests — FINDINGS H-14.

H-14 (HIGH): the snapshot rate limiter dropped throttled requests outright,
so a transient/rare event arriving inside the cooldown window evaporated
without a trace.

Covers:
- An event observed inside the cooldown window is captured (deferred) by the
  first snapshot the interval allows — with its original observation time
- force=True still bypasses the limiter
- Two events inside one cooldown window yield two separate records (nothing
  is collapsed/lost)
- Normal throttling still prevents a burst of snapshots
- Round 2: a mid-flush write failure keeps the failed request and everything
  behind it queued (dequeue-after-success) and surfaces the error
- Round 2: the backlog is capped and reaching the cap triggers an immediate,
  cooldown-bypassing capture instead of dropping requests
- Round 2: generate_report() drains the backlog so the report path (campaign
  end / shutdown) cannot strand pending requests
- Round 2: unchanged-state coalescing cannot swallow an event whose snapshot
  write failed — the limiter and coalescing never both lose one event
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eigencapital.production_qual import evidence_orchestrator as evidence_module
from eigencapital.production_qual.evidence_orchestrator import EvidenceOrchestrator

INTERVAL = 3600.0


# ── Fixtures / helpers ────────────────────────────────────────────


class _Clock:
    """Deterministic stand-in for time.time()."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Patch the module's time source (module-local, not the stdlib)."""
    fake_clock = _Clock(1_000_000.0)
    monkeypatch.setattr(evidence_module, "time", fake_clock)
    return fake_clock


def _make_orchestrator(tmp_path: Path) -> EvidenceOrchestrator:
    return EvidenceOrchestrator(
        campaign_id="TEST-H14",
        evidence_dir=str(tmp_path / "evidence"),
        reports_dir=str(tmp_path / "reports"),
        snapshot_interval_seconds=INTERVAL,
    )


def _snapshot_file(tmp_path: Path) -> Path:
    return tmp_path / "evidence" / "position_snapshots.jsonl"


def _read_snapshots(tmp_path: Path) -> list[dict[str, Any]]:
    path = _snapshot_file(tmp_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _position(ticket: int, *, volume: float = 0.1) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "symbol": "EURUSD",
        "type": 0,
        "volume": volume,
        "price_open": 1.10,
        "magic": 20260825,
    }


@contextmanager
def _failing_snapshot_write(fail_at: int, message: str = "disk full") -> Iterator[dict[str, int]]:
    """Make the `fail_at`-th (1-based) position-snapshot write raise OSError.

    Restores the real writer on exit (including on error), so a test can let
    one write fail, observe the fallout, then continue with healthy writes.
    The failure is raised, never swallowed.
    """
    original = EvidenceOrchestrator._append_jsonl
    stats = {"attempts": 0}

    def patched(orchestrator: EvidenceOrchestrator, filepath: Path, record: dict[str, Any]) -> None:
        if filepath.name == "position_snapshots.jsonl":
            stats["attempts"] += 1
            if stats["attempts"] == fail_at:
                raise OSError(message)
        original(orchestrator, filepath, record)

    EvidenceOrchestrator._append_jsonl = patched
    try:
        yield stats
    finally:
        EvidenceOrchestrator._append_jsonl = original


# ── H-14: transient events survive the cooldown ───────────────────


class TestDeferredSnapshotCapture:
    """A throttled request is deferred, never silently dropped."""

    def test_event_inside_cooldown_captured_on_next_allowed_snapshot(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """Position appearing inside the window shows up at the next capture."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        # Transient position observed deep inside the cooldown window.
        clock.now = base + 100.0
        skipped = orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0)
        assert skipped is None
        # Throttling still holds: nothing written while inside the window.
        assert len(_read_snapshots(tmp_path)) == 1

        # The position has closed again by the time the interval allows a capture.
        clock.now = base + INTERVAL + 1.0
        allowed = orchestrator.capture_cycle_snapshot([], 5005.0, 5005.0, 4500.0)
        assert allowed is not None

        records = _read_snapshots(tmp_path)
        deferred_records = [r for r in records if r["deferred"]]
        assert deferred_records, "throttled request was dropped instead of deferred"
        captured = [r for r in deferred_records if 111 in r["tickets"]]
        assert captured, "transient position 111 missing from deferred snapshot"

        # Deferred record keeps its original observation timestamp.
        observed = datetime.fromisoformat(captured[0]["timestamp"])
        assert observed == datetime.fromtimestamp(base + 100.0, tz=UTC)

        # The entry also reached the qualification dataset.
        correlation_ids = {t.correlation_id for t in orchestrator._dataset.get_all_trades()}
        assert "ticket-111" in correlation_ids

    def test_two_events_inside_one_cooldown_window_not_collapsed(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """Two distinct events in one window produce two separate records."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        clock.now = base + 100.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is None

        clock.now = base + 200.0
        assert orchestrator.capture_cycle_snapshot([_position(222)], 5020.0, 5020.0, 4500.0) is None

        # Both events still inside the window — no record may be written yet.
        assert len(_read_snapshots(tmp_path)) == 1

        clock.now = base + INTERVAL + 1.0
        assert orchestrator.capture_cycle_snapshot([], 5005.0, 5005.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        rec_111 = [r for r in records if 111 in r["tickets"]]
        rec_222 = [r for r in records if 222 in r["tickets"]]
        assert rec_111, "first event lost"
        assert rec_222, "second event lost"
        assert rec_111[0]["cycle_counter"] != rec_222[0]["cycle_counter"]
        assert all(r["deferred"] for r in rec_111 + rec_222)


# ── force=True contract ───────────────────────────────────────────


class TestForceBypass:
    """force=True bypasses the limiter exactly as before."""

    def test_force_bypasses_rate_limiter(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        clock.now = base + 10.0
        forced = orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0, force=True)
        assert forced is not None
        assert 111 in forced["tickets"]

        records = _read_snapshots(tmp_path)
        assert len(records) == 2
        assert records[-1]["deferred"] is False

        # Force does not disable throttling for subsequent ordinary calls.
        clock.now = base + 20.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is None
        assert len(_read_snapshots(tmp_path)) == 2

    def test_generate_report_force_contract_unchanged(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """generate_report(force=...) keeps its public contract."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.generate_report() is not None

        clock.now = base + 60.0
        # Inside the report interval: throttled, but force still bypasses.
        assert orchestrator.generate_report() is None
        assert orchestrator.generate_report(force=True) is not None


# ── Rate limiting still holds ─────────────────────────────────────


class TestThrottlingStillEffective:
    """Steady-state calls inside the window must not produce snapshots."""

    def test_burst_of_calls_produces_no_snapshot_burst(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        for i in range(1, 11):
            clock.now = base + i * 10.0
            assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is None
            assert len(_read_snapshots(tmp_path)) == 1, "throttled call wrote a snapshot"

        # Exactly one capture once the interval elapses — no deferred backlog.
        clock.now = base + INTERVAL + 1.0
        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        assert len(records) == 2
        assert all(r["deferred"] is False for r in records)

    def test_event_write_is_deferred_not_immediate(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """Even a state-changing request waits for the interval to elapse."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        for offset in (100.0, 200.0, 300.0):
            clock.now = base + offset
            assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is None
            assert len(_read_snapshots(tmp_path)) == 1

        # A single deferred record for the (unchanged) event state, not one per call.
        clock.now = base + INTERVAL + 1.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        assert len(records) == 3  # initial + one deferred event + current capture
        assert sum(1 for r in records if r["deferred"]) == 1


# ── Round 2: a mid-flush write failure must not discard the backlog ─


class TestFlushFailureKeepsBacklog:
    """Dequeue-after-success: only written requests leave the backlog."""

    def test_mid_flush_error_keeps_failed_and_remaining_requests(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """A write failing mid-flush surfaces and keeps the rest queued."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        for offset, ticket in ((100.0, 111), (200.0, 222), (300.0, 333)):
            clock.now = base + offset
            assert orchestrator.capture_cycle_snapshot([_position(ticket)], 5010.0, 5010.0, 4500.0) is None
        assert len(orchestrator._deferred_snapshots) == 3

        # Second deferred write fails: 111 committed, 222 (the failed write)
        # and 333 (never attempted) must both survive — nothing is cleared
        # before the loop, and the error is raised to the caller.
        with _failing_snapshot_write(fail_at=2) as stats:
            clock.now = base + INTERVAL + 1.0
            with pytest.raises(OSError, match="disk full"):
                orchestrator.capture_cycle_snapshot([], 5005.0, 5005.0, 4500.0)
            assert stats["attempts"] == 2

        assert [p["ticket"] for r in orchestrator._deferred_snapshots for p in r.positions] == [222, 333]

        records = _read_snapshots(tmp_path)
        assert len(records) == 2  # initial + the single deferred write that succeeded
        assert 111 in records[-1]["tickets"]
        assert records[-1]["deferred"] is True

        # Recovery needs no force and loses nothing.
        clock.now = base + INTERVAL + 10.0
        assert orchestrator.capture_cycle_snapshot([], 5006.0, 5006.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        for ticket in (111, 222, 333):
            assert any(ticket in r["tickets"] for r in records), f"ticket {ticket} lost after flush error"
        assert orchestrator._deferred_snapshots == []


# ── Round 2: bounded backlog ───────────────────────────────────────


class TestBoundedBacklog:
    """The queue is capped; reaching the cap captures immediately, never drops."""

    def test_backlog_cap_triggers_immediate_capture_without_dropping(
        self,
        tmp_path: Path,
        clock: _Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cap = 4
        monkeypatch.setattr(EvidenceOrchestrator, "_max_deferred_snapshots", cap)
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        # Fill the backlog: everything is deferred, nothing written yet.
        for ticket in range(1, cap + 1):
            clock.now = base + ticket * 10.0
            assert orchestrator.capture_cycle_snapshot([_position(ticket)], 5010.0, 5010.0, 4500.0) is None
        assert len(orchestrator._deferred_snapshots) == cap
        assert len(_read_snapshots(tmp_path)) == 1

        # Cap reached: the next distinct event captures immediately, well
        # inside the cooldown, instead of growing the queue or being dropped.
        clock.now = base + 100.0
        captured = orchestrator.capture_cycle_snapshot([_position(cap + 1)], 5010.0, 5010.0, 4500.0)
        assert captured is not None
        assert clock.now - base < INTERVAL, "cap capture must bypass the cooldown"
        assert captured["deferred"] is False
        assert orchestrator._deferred_snapshots == []

        records = _read_snapshots(tmp_path)
        assert len(records) == 1 + cap + 1
        for ticket in range(1, cap + 2):
            assert any(ticket in r["tickets"] for r in records), f"ticket {ticket} dropped at the cap"

        # Write rate stays bounded: the next `cap` distinct events queue up
        # again rather than producing one write each.
        for i in range(1, cap + 1):
            clock.now = base + 100.0 + i * 10.0
            assert orchestrator.capture_cycle_snapshot([_position(100 + i)], 5011.0, 5011.0, 4500.0) is None
        assert len(_read_snapshots(tmp_path)) == 1 + cap + 1
        assert len(orchestrator._deferred_snapshots) == cap

    def test_backlog_never_exceeds_cap(
        self,
        tmp_path: Path,
        clock: _Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cap = 3
        monkeypatch.setattr(EvidenceOrchestrator, "_max_deferred_snapshots", cap)
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        for i in range(1, 20):
            clock.now = base + i * 10.0
            orchestrator.capture_cycle_snapshot([_position(i)], 5010.0, 5010.0, 4500.0)
            assert len(orchestrator._deferred_snapshots) <= cap, "backlog grew past the cap"

        # Whatever is still pending is drained by the report path, and every
        # distinct state seen in the window ends up on disk (nothing dropped
        # when the cap was reached).
        assert orchestrator.generate_report() is not None
        assert orchestrator._deferred_snapshots == []
        records = _read_snapshots(tmp_path)
        for ticket in range(1, 20):
            assert any(ticket in r["tickets"] for r in records), f"ticket {ticket} never captured"


# ── Round 2: backlog survives the report path ──────────────────────


class TestBacklogSurvivesReportGeneration:
    """generate_report() drains pending requests (campaign end / shutdown)."""

    def test_generate_report_drains_pending_requests(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        clock.now = base + 100.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is None
        assert len(orchestrator._deferred_snapshots) == 1

        # Report runs while the snapshot cooldown still holds: the backlog
        # must not be stranded by the report path.
        clock.now = base + 200.0
        assert orchestrator.generate_report() is not None
        assert orchestrator._deferred_snapshots == []

        records = _read_snapshots(tmp_path)
        captured = [r for r in records if 111 in r["tickets"]]
        assert captured, "backlog stranded by generate_report()"
        assert captured[0]["deferred"] is True
        assert datetime.fromisoformat(captured[0]["timestamp"]) == datetime.fromtimestamp(base + 100.0, tz=UTC)

    def test_throttled_report_still_drains_backlog(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        clock.now = base + 100.0
        assert orchestrator.capture_cycle_snapshot([_position(222)], 5010.0, 5010.0, 4500.0) is None
        clock.now = base + 150.0
        assert orchestrator.generate_report() is not None

        clock.now = base + 200.0
        assert orchestrator.capture_cycle_snapshot([_position(333)], 5011.0, 5011.0, 4500.0) is None
        clock.now = base + 250.0
        # Report is inside its own cooldown (returns None) yet still drains.
        assert orchestrator.generate_report() is None
        assert orchestrator._deferred_snapshots == []

        records = _read_snapshots(tmp_path)
        assert any(222 in r["tickets"] for r in records), "first backlog item lost"
        assert any(333 in r["tickets"] for r in records), "second backlog item stranded"


# ── Round 2: coalescing must not eat transients ────────────────────


class TestCoalescingKeepsTransients:
    """The limiter and the state coalescing can never both lose one event."""

    def test_coalesced_repeat_is_still_captured_via_its_queued_twin(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        clock.now = base + 100.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0) is None

        # Same state observed again: coalesced (not queued twice)...
        clock.now = base + 200.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5020.0, 5020.0, 4500.0) is None
        assert len(orchestrator._deferred_snapshots) == 1

        # ...but the transient event it observed is still captured.
        clock.now = base + INTERVAL + 1.0
        assert orchestrator.capture_cycle_snapshot([], 5005.0, 5005.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        assert any(111 in r["tickets"] and r["deferred"] for r in records), "coalescing lost the transient"

    def test_failed_write_does_not_arm_state_coalescing(
        self,
        tmp_path: Path,
        clock: _Clock,
    ) -> None:
        """A state whose snapshot write failed must be re-captured, not coalesced away."""
        orchestrator = _make_orchestrator(tmp_path)
        base = clock.now

        assert orchestrator.capture_cycle_snapshot([], 5000.0, 5000.0, 4500.0) is not None

        with _failing_snapshot_write(fail_at=1, message="torn write"):
            clock.now = base + INTERVAL + 1.0
            with pytest.raises(OSError, match="torn write"):
                orchestrator.capture_cycle_snapshot([_position(111)], 5010.0, 5010.0, 4500.0)
        assert len(_read_snapshots(tmp_path)) == 1

        # Same state again inside the cooldown: it must be deferred, not
        # swallowed by coalescing armed on a write that never landed.
        clock.now = base + INTERVAL + 100.0
        assert orchestrator.capture_cycle_snapshot([_position(111)], 5011.0, 5011.0, 4500.0) is None
        assert len(orchestrator._deferred_snapshots) == 1, "coalescing ate an event whose write failed"

        clock.now = base + 2 * INTERVAL + 1.0
        assert orchestrator.capture_cycle_snapshot([], 5005.0, 5005.0, 4500.0) is not None

        records = _read_snapshots(tmp_path)
        assert any(111 in r["tickets"] and r["deferred"] for r in records), "transient never captured"
        assert orchestrator._deferred_snapshots == []
