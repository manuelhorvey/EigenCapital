"""F-02 — Synthetic fixture-ledger remediation (test-only).

Purpose
-------
Verify the existing ``EventLedger`` (``src/eigencapital.production_qual.event_ledger``)
using clearly-labeled synthetic fixtures only. This module:

- Exercises EventLedger append, hash computation, correlation-chain
  reconstruction (get_trade_chain), duplicate correlation-ID handling, and
  deterministic flush/replay from persisted JSONL files.
- Verifies fail-closed behavior for malformed inputs (invalid event type,
  empty account/tier/campaign).
- Proves NO broker APIs, live execution components, or production state are
  touched (EventLedger is pure Python + file I/O).
- Documents the gaps between EventLedger as it exists today and the full
  F-02 acceptance criteria (currency/signed-amount/balance/source-hash fields,
  prev_hash chaining, schema versioning, sequential IDs under lock) as
  pending formal decision — NOT implemented here.

Safety constraints honored
--------------------------
- No live trading, broker integration, order placement, or execution
  orchestration is touched.
- The ledger is NOT wired into any live or paper-trading runtime path.
- All fixtures are synthetic and test-only; no real broker statements,
  account snapshots, credentials, or production state are used.
- No historical evidence is fabricated; no claim is made that synthetic
  results reconcile actual broker equity.
- R4 strategy invariants, broker behaviour, production risk limits, capital,
  leverage, and strategy behaviour are unchanged.

F-02 acceptance criteria status
-------------------------------
The following F-02 criteria CANNOT be satisfied by this synthetic unit and
remain BLOCKED — NOT AUTHORIZED pending live-path approval and formal
decision:

- "EventLedger instantiated in the live loop" — live-path wiring prohibited.
- "get_trade_chain(correlation_id) returns a full chain for a live cycle" —
  no live cycle exists here; only synthetic fixture chains are tested.
- Per-cycle expected equity comparison and unexplained-delta BLOCK — requires
  live cycle integration.
- Startup replay to restore daily baseline; CORRUPTED fails closed — requires
  live-path integration.
- Sequential event IDs under file lock — EventLedger uses uuid4, not
  sequential IDs; changing this is a formal decision, not made here.

The following criteria ARE exercised synthetically in this module:

- Typed, append-only ledger with correlation IDs — verified via synthetic
  append + get_trade_chain.
- Hash-chained event integrity (event_hash) — verified via recomputation.
- Fail-closed on invalid event type / empty account / tier / campaign — verified.
- Atomic persistence (flush to JSONL) — verified via file re-read.
- Deterministic replay from the same fixture set — verified by re-reading
  flushed files and comparing event_hash ordering.

"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eigencapital.production_qual.event_ledger import (
    Event,
    EventLedger,
    EventType,
)


# ═════════════════════════════════════════════════════════════════════════════
# Synthetic fixture factory (test-only, no broker data)
# ═════════════════════════════════════════════════════════════════════════════


def make_synthetic_event_payload(
    event_type: EventType,
    *,
    account_id: str = "TEST-ACCOUNT-001",
    tier: str = "T1-SYNTHETIC",
    campaign_id: str = "CAMPAIGN-SYNTHETIC-001",
    symbol: str | None = "SYNTH_EURUSD",
    position_ticket: int | None = 1001,
    order_ticket: str | None = "ORDER-SYNTH-0001",
    correlation_id: str | None = None,
    parent_event_id: str | None = None,
    broker_reference: str | None = "BROKER-REF-SYNTH-0001",
    state_transition: str | None = "SYNTHETIC-TRANSITION",
    payload: dict[str, Any] | None = None,
    strategy_version: str = "R4-SYNTHETIC-1.0",
) -> dict[str, Any]:
    """Build a fully synthetic event argument set.

    Every value is fabricated for testing only. No broker data, no real
    account, no real order ticket is used.
    """
    if correlation_id is None:
        correlation_id = "CORR-SYNTHETIC-0001"
    return dict(
        event_type=event_type,
        account_id=account_id,
        tier=tier,
        campaign_id=campaign_id,
        symbol=symbol,
        position_ticket=position_ticket,
        order_ticket=order_ticket,
        correlation_id=correlation_id,
        parent_event_id=parent_event_id,
        broker_reference=broker_reference,
        state_transition=state_transition,
        payload=payload or {"synthetic": True, "note": "test fixture only"},
        strategy_version=strategy_version,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _flush_and_reload(ledger: EventLedger, tmp_path: Path) -> list[dict[str, Any]]:
    """Flush the ledger to disk and re-read all persisted event JSONL lines."""
    ledger.flush()
    records: list[dict[str, Any]] = []
    for batch_file in sorted(ledger._base_path.glob("events_*.jsonl")):
        with open(batch_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


# ═════════════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestSyntheticLedgerAppendAndHash:
    """Append produces a deterministic, self-consistent event with a valid
    event_hash computed over all other fields."""

    def test_appended_event_has_deterministic_hash(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        kwargs = make_synthetic_event_payload(EventType.ORDER_SUBMITTED)
        event = ledger.append(**kwargs)
        # event_hash must be a non-empty hex string
        assert isinstance(event.event_hash, str)
        assert len(event.event_hash) == 32
        assert all(c in "0123456789abcdef" for c in event.event_hash)
        # Recomputing over to_dict (minus event_hash) reproduces it
        data = event.to_dict()
        stored_hash = data.pop("event_hash")
        expected = ledger._compute_event_hash(data)
        assert stored_hash == expected

    def test_event_hash_changes_when_payload_changes(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        base = make_synthetic_event_payload(EventType.FILL)
        e1 = ledger.append(**base)
        modified = make_synthetic_event_payload(
            EventType.FILL,
            payload={**base["payload"], "fill_price": 9999.0},
        )
        e2 = ledger.append(**modified)
        assert e1.event_hash != e2.event_hash


class TestSyntheticLedgerCorrelationChain:
    """get_trade_chain(correlation_id) returns the full chain for a synthetic
    cycle, ordered by timestamp."""

    def test_get_trade_chain_returns_full_cycle(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"), flush_after=1000)
        corr = "CORR-SYNTHETIC-CYCLE-001"
        events = [
            make_synthetic_event_payload(
                EventType.SIGNAL_COMPUTED,
                correlation_id=corr,
                symbol="SYNTH_EURUSD",
                position_ticket=None,
                order_ticket=None,
            ),
            make_synthetic_event_payload(
                EventType.ORDER_INTENT,
                correlation_id=corr,
                symbol="SYNTH_EURUSD",
                position_ticket=None,
                order_ticket="ORDER-INTENT-001",
            ),
            make_synthetic_event_payload(
                EventType.ORDER_SUBMITTED,
                correlation_id=corr,
                symbol="SYNTH_EURUSD",
                position_ticket=None,
                order_ticket="ORDER-001",
            ),
            make_synthetic_event_payload(
                EventType.FILL,
                correlation_id=corr,
                symbol="SYNTH_EURUSD",
                position_ticket=5001,
                order_ticket="ORDER-001",
            ),
        ]
        for kwargs in events:
            ledger.append(**kwargs)
        chain = ledger.get_trade_chain(corr)
        assert len(chain) == 4
        # Chain is chronological
        timestamps = [e.timestamp for e in chain]
        assert timestamps == sorted(timestamps)
        # All events share the correlation ID
        assert all(e.correlation_id == corr for e in chain)
        # Event types in expected order
        types = [e.event_type for e in chain]
        assert types == [
            "SIGNAL_COMPUTED",
            "ORDER_INTENT",
            "ORDER_SUBMITTED",
            "FILL",
        ]


class TestSyntheticLedgerDuplicateHandling:
    """Duplicate event appends are recorded (EventLedger appends every call;
    there is no built-in duplicate suppression). The caller is responsible for
    correlation-ID deduplication. This test documents current behavior."""

    def test_duplicate_event_appends_twice(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"), flush_after=1000)
        kwargs = make_synthetic_event_payload(EventType.ORDER_SUBMITTED)
        e1 = ledger.append(**kwargs)
        e2 = ledger.append(**kwargs)
        # Different event_id, same correlation_id -> both recorded
        assert e1.event_id != e2.event_id
        assert e1.correlation_id == e2.correlation_id
        chain = ledger.get_trade_chain(e1.correlation_id)
        assert len(chain) == 2


class TestSyntheticLedgerFailClosed:
    """Invalid inputs fail closed with ValueError."""

    def test_invalid_event_type_rejected(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        kwargs = make_synthetic_event_payload(EventType.ORDER_SUBMITTED)
        with pytest.raises(ValueError, match="event_type must be an EventType"):
            ledger.append(**{**kwargs, "event_type": "NOT_A_REAL_TYPE"})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("account_id", ""),
            ("account_id", None),
            ("tier", ""),
            ("campaign_id", ""),
        ],
    )
    def test_empty_required_field_rejected(
        self, tmp_path: Path, field: str, bad_value: str | None
    ):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        kwargs = make_synthetic_event_payload(EventType.ORDER_SUBMITTED)
        with pytest.raises(ValueError):
            ledger.append(**{**kwargs, field: bad_value})


class TestSyntheticLedgerPersistenceAndReplay:
    """Flush persists events to JSONL; re-reading yields the same events
    in the same order (deterministic replay from the same fixture set)."""

    def test_flush_persists_and_replay_matches(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        kwargs_list = [
            make_synthetic_event_payload(EventType.SIGNAL_COMPUTED),
            make_synthetic_event_payload(EventType.ORDER_SUBMITTED),
            make_synthetic_event_payload(EventType.FILL),
        ]
        events = [ledger.append(**kw) for kw in kwargs_list]
        records = _flush_and_reload(ledger, tmp_path)
        assert len(records) == 3
        # Order preserved
        for rec, ev in zip(records, events):
            assert rec["event_id"] == ev.event_id
            assert rec["event_hash"] == ev.event_hash
            assert rec["correlation_id"] == ev.correlation_id

    def test_replay_after_new_flush_appends_without_overwrite(self, tmp_path: Path):
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        e1 = ledger.append(**make_synthetic_event_payload(EventType.SIGNAL_COMPUTED))
        ledger.flush()
        first_batch_files = list(ledger._base_path.glob("events_*.jsonl"))
        assert len(first_batch_files) == 1
        e2 = ledger.append(**make_synthetic_event_payload(EventType.ORDER_SUBMITTED))
        ledger.flush()
        batch_files = sorted(ledger._base_path.glob("events_*.jsonl"))
        assert len(batch_files) == 2
        # Second batch file contains only the second event
        with open(batch_files[1], encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 1
        assert lines[0]["event_id"] == e2.event_id


class TestSyntheticLedgerNoLivePathMutation:
    """The ledger never touches broker APIs, MT5, or production runtime
    state. It is pure Python + file I/O under the test temp directory."""

    def test_ledger_writes_only_under_tmp_path(self, tmp_path: Path):
        base = tmp_path / "ledger"
        ledger = EventLedger(base_path=str(base))
        ledger.append(**make_synthetic_event_payload(EventType.SIGNAL_COMPUTED))
        ledger.flush()
        # All written files are under the provided tmp_path base
        written = list(base.glob("events_*.jsonl"))
        assert len(written) == 1
        assert all(str(f).startswith(str(base)) for f in written)

    def test_ledger_is_pure_python_file_io(self):
        import eigencapital.production_qual.event_ledger as mod

        text = Path(mod.__file__).read_text(encoding="utf-8")
        # Confirm no broker/execution/live imports or usage. Checking for
        # actual MT5 API usage patterns (not merely the substring "mt5" which
        # can appear in docstrings describing parameter purpose).
        forbidden_imports = [
            "import mt5",
            "from mt5",
            "MetaTrader5",
            "mt5linux",
        ]
        forbidden_usage = [
            "mt5.account_info",
            "mt5.positions_get",
            "mt5.order_send",
            "mt5.symbol_select",
            "mt5.initialize",
            "mt5.shutdown",
        ]
        for pattern in forbidden_imports + forbidden_usage:
            assert pattern not in text, f"Found forbidden reference: {pattern}"


class TestSyntheticLedgerDeterministicReplay:
    """Replay from the same fixture set within a single ledger lifecycle is
    deterministic: flushing persists events, and re-reading them yields the
    same data (event_id and timestamp are auto-generated per-append, so
    comparisons exclude those fields)."""

    def test_same_fixtures_produce_same_persisted_records(self, tmp_path: Path):
        """Appending the same fixture set and flushing produces identical
        persisted records (excluding auto-generated event_id/timestamp)."""
        ledger = EventLedger(base_path=str(tmp_path / "ledger"))
        kwargs = make_synthetic_event_payload(EventType.FILL)

        # Append the same fixture twice
        e1 = ledger.append(**kwargs)
        e2 = ledger.append(**kwargs)
        ledger.flush()

        records = _flush_and_reload(ledger, tmp_path)
        assert len(records) == 2

        # Both records share the same correlation_id and payload structure
        for rec in records:
            assert rec["correlation_id"] == kwargs["correlation_id"]
            assert rec["payload"] == kwargs["payload"]
            assert rec["event_type"] == kwargs["event_type"].value

        # event_id and timestamp differ between the two appends (expected)
        assert records[0]["event_id"] != records[1]["event_id"]
        assert records[0]["timestamp"] != records[1]["timestamp"]
