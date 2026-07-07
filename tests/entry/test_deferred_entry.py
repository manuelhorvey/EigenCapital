"""Tests for paper_trading/entry/deferred_entry.py."""

from __future__ import annotations

from paper_trading.entry.decision import SignalType, TradeDecision  # noqa: F401
from paper_trading.entry.deferred_entry import DeferredEntry, DeferredEntryStatus


class _FakeDecision:
    """Minimal TradeDecision stand-in for testing DeferredEntry."""

    def __init__(self, asset="EURUSD", signal="BUY", timestamp="2026-07-07T12:00:00"):
        self.asset = asset
        self.signal = signal
        self.timestamp = timestamp


class TestDeferredEntry:
    def test_from_decision_creates_pending(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        assert entry.status == DeferredEntryStatus.PENDING
        assert entry.entry_id is not None
        assert len(entry.entry_id) == 12

    def test_update_increments_bars(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        assert entry.bars_elapsed == 0
        entry.update()
        assert entry.bars_elapsed == 1

    def test_update_expires_after_max_bars(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec, max_bars=3)
        for _ in range(4):
            entry.update()
        assert entry.status == DeferredEntryStatus.EXPIRED

    def test_trigger_transitions_to_triggered(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        entry.trigger(fill_price=1.1050)
        assert entry.status == DeferredEntryStatus.TRIGGERED
        assert entry.trigger_price == 1.1050

    def test_cancel_transitions_to_cancelled(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        entry.cancel(reason="Manual")
        assert entry.status == DeferredEntryStatus.CANCELLED

    def test_close_transitions_to_closed(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        entry.close()
        assert entry.status == DeferredEntryStatus.CLOSED

    def test_is_active_when_pending(self):
        dec = _FakeDecision()
        entry = DeferredEntry.from_decision(dec)
        assert entry.is_active is True
        entry.cancel()
        assert entry.is_active is False

    def test_idempotent_entry_id(self):
        dec1 = _FakeDecision(asset="EURUSD")
        dec2 = _FakeDecision(asset="EURUSD")
        entry1 = DeferredEntry.from_decision(dec1)
        entry2 = DeferredEntry.from_decision(dec2)
        assert entry1.entry_id == entry2.entry_id

    def test_different_assets_different_ids(self):
        dec1 = _FakeDecision(asset="EURUSD")
        dec2 = _FakeDecision(asset="GBPUSD")
        entry1 = DeferredEntry.from_decision(dec1)
        entry2 = DeferredEntry.from_decision(dec2)
        assert entry1.entry_id != entry2.entry_id
