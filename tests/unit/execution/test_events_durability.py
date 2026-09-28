"""M-2 durability tests — the execution audit trail must survive a crash.

``AuditLog`` previously kept events only in a plain Python list: a crash lost
the entire trail. These tests pin the durable behaviour: events surviving a
new instance/restart, a torn write from a crash mid-append not zeroing the
history behind it, byte-identical append-only records, the public API the
existing callers rely on, and write failures being surfaced rather than
swallowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from eigencapital.execution.events import AuditEvent, AuditLog, EventType
from eigencapital.live.durable_audit import DurableAudit


def _submitted(log: AuditLog, order_id: str = "ORD-1", **kwargs) -> AuditEvent:
    return log.create_event(
        EventType.ORDER_SUBMITTED,
        timestamp_utc="2025-01-15T10:00:00Z",
        order_id=order_id,
        **kwargs,
    )


# ═══════════════════════════════════════════════
#  RESTART SURVIVAL
# ═══════════════════════════════════════════════


def test_events_survive_new_instance(tmp_path: Path) -> None:
    """A new instance over the same store sees every event the old one emitted."""
    store = tmp_path / "audit.jsonl"
    log = AuditLog(store_path=store)
    first = _submitted(log, instrument_id="ES")
    second = log.create_event(
        EventType.ORDER_FILLED,
        timestamp_utc="2025-01-15T10:01:00Z",
        order_id="ORD-1",
        instrument_id="ES",
        details={"qty": 10},
    )
    assert len(log) == 2

    restarted = AuditLog(store_path=store)
    assert len(restarted) == 2
    assert restarted.get_events() == [first, second]
    assert restarted.get_events(EventType.ORDER_FILLED) == [second]
    assert restarted.get_events(EventType.ORDER_REJECTED) == []
    assert restarted.get_events_for_instrument("ES") == [first, second]
    assert restarted.get_events_for_instrument("NQ") == []
    assert restarted.get_events_for_order("ORD-1") == [first, second]
    assert list(restarted) == [first, second]
    assert restarted.path == store
    # Ids continue instead of restarting, so the trail never repeats itself.
    third = restarted.create_event(EventType.ORDER_CANCELLED)
    assert third.event_id == "EVT-000003"
    assert AuditLog(store_path=store).get_events() == [first, second, third]


# ═══════════════════════════════════════════════
#  TORN WRITE / TORN TAIL
# ═══════════════════════════════════════════════


def test_torn_write_does_not_zero_history(tmp_path: Path) -> None:
    """A crash mid-append leaves a partial tail line: history stays readable."""
    store = tmp_path / "audit.jsonl"
    log = AuditLog(store_path=store)
    keep = _submitted(log)
    # Simulate a crash mid-append: partial record, no trailing newline.
    with open(store, "ab") as handle:
        handle.write(b'{"seq": 99, "payload": {"event": {"event_type": "ord')

    restarted = AuditLog(store_path=store)
    assert len(restarted) == 1
    assert restarted.get_events() == [keep]

    # The next append gets its own line instead of being swallowed by the
    # torn tail, and both records are still there afterwards.
    added = restarted.create_event(
        EventType.ORDER_FILLED,
        timestamp_utc="2025-01-15T10:01:00Z",
        order_id="ORD-1",
    )
    final = AuditLog(store_path=store)
    assert final.get_events() == [keep, added]


def test_zeroed_primary_restored_from_mirror(tmp_path: Path) -> None:
    """A lost/zeroed primary is rebuilt from the atomically written mirror."""
    store = tmp_path / "audit.jsonl"
    mirror = tmp_path / "audit.mirror.jsonl"
    log = AuditLog(store_path=store)
    keep = _submitted(log)
    assert mirror.exists()
    store.write_bytes(b"")  # crash or cleanup destroyed the primary

    restarted = AuditLog(store_path=store)
    assert restarted.get_events() == [keep]
    added = restarted.create_event(EventType.ORDER_FILLED)
    assert AuditLog(store_path=store).get_events() == [keep, added]


# ═══════════════════════════════════════════════
#  APPEND-ONLY
# ═══════════════════════════════════════════════


def test_history_is_append_only(tmp_path: Path) -> None:
    """Existing records are never rewritten, dropped, or renumbered."""
    store = tmp_path / "audit.jsonl"
    log = AuditLog(store_path=store)
    for i in range(3):
        _submitted(log, order_id=f"ORD-{i}")
    first_three = store.read_bytes().splitlines()
    assert len(first_three) == 3

    log.create_event(EventType.ORDER_FILLED, order_id="ORD-3")
    after_fourth = store.read_bytes().splitlines()
    assert len(after_fourth) == 4
    assert after_fourth[:3] == first_three

    # A restart appends on top without touching what came before.
    restarted = AuditLog(store_path=store)
    restarted.create_event(EventType.ORDER_REJECTED, order_id="ORD-4")
    final = store.read_bytes().splitlines()
    assert len(final) == 5
    assert final[:4] == after_fourth
    assert [e.event_id for e in restarted.get_events()] == [
        "EVT-000001",
        "EVT-000002",
        "EVT-000003",
        "EVT-000004",
        "EVT-000005",
    ]


# ═══════════════════════════════════════════════
#  API COMPATIBILITY / DEFAULT STORE
# ═══════════════════════════════════════════════


def test_api_compatible_with_existing_callers() -> None:
    """Exactly the surface the current callers exercise (default store)."""
    log = AuditLog()
    event = _submitted(log, instrument_id="ES")
    assert len(log) == 1
    assert event.event_type == EventType.ORDER_SUBMITTED
    assert event.event_hash != ""
    assert len(event.event_hash) == 64

    log.create_event(EventType.ORDER_FILLED, instrument_id="ES")
    log.create_event(EventType.ORDER_SUBMITTED, instrument_id="NQ")
    assert len(log.get_events(EventType.ORDER_SUBMITTED)) == 2
    assert len(log.get_events_for_instrument("ES")) == 2
    assert len(log.get_events_for_instrument("NQ")) == 1

    serialized = event.to_dict()
    assert serialized["event_id"] == "EVT-000001"
    assert serialized["event_type"] == "order_submitted"
    assert serialized["details"] == {}
    assert len(serialized["event_hash"]) == 64
    assert list(log)[0] == event
    assert log.get_events() == list(log)

    # Direct construction and hashing of an AuditEvent are untouched.
    raw = AuditEvent(event_id="EVT-000009", timestamp_utc="t", event_type=EventType.RISK_APPROVED)
    assert raw.compute_hash() == raw.compute_hash()
    assert len(raw.compute_hash()) == 64

    # Package re-exports still resolve for existing importers.
    from eigencapital.execution import AuditEvent as ExportedAuditEvent
    from eigencapital.execution import AuditLog as ExportedAuditLog

    assert ExportedAuditLog is AuditLog
    assert ExportedAuditEvent is AuditEvent


def test_default_store_path_is_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default reports/ store honours its env override and survives restart."""
    store = tmp_path / "execution_audit.jsonl"
    monkeypatch.setenv("EIGENCAPITAL_EXECUTION_AUDIT_STORE", str(store))

    log = AuditLog()
    assert log.path == store
    event = log.create_event(EventType.SESSION_STARTED, timestamp_utc="2025-01-15T10:00:00Z")
    assert store.exists()
    assert (tmp_path / "execution_audit.mirror.jsonl").exists()

    restarted = AuditLog()
    assert restarted.get_events() == [event]
    assert restarted.get_events(EventType.SESSION_STARTED) == [event]


# ═══════════════════════════════════════════════
#  WRITE FAILURES ARE SURFACED
# ═══════════════════════════════════════════════


def test_write_failure_is_surfaced_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed persist logs at error, raises, and never fakes history."""
    store = tmp_path / "audit.jsonl"
    log = AuditLog(store_path=store)
    real_append = DurableAudit.append

    def _fail(self: DurableAudit, event: str, payload: dict) -> dict:
        raise OSError("disk full")

    monkeypatch.setattr(DurableAudit, "append", _fail)
    with (
        caplog.at_level(logging.ERROR, logger="eigencapital.execution.events"),
        pytest.raises(OSError, match="disk full"),
    ):
        _submitted(log)
    # The live view must never run ahead of the durable trail.
    assert len(log) == 0
    assert log.get_events() == []
    assert not store.exists()
    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert any("disk full" in message and "EVT-000001" in message for message in errors)

    # Once the write path recovers, the log keeps working and stays durable.
    monkeypatch.setattr(DurableAudit, "append", real_append)
    recovered = log.create_event(EventType.ORDER_FILLED, order_id="ORD-2")
    assert [e.event_id for e in log.get_events()] == [recovered.event_id]
    assert AuditLog(store_path=store).get_events() == [recovered]
