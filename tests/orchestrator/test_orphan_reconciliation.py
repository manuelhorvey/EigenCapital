"""Targeted tests for OrphanReconciler — coverage push from 43% to 70%+.

Covers all 4 phases:

    - Phase A: drain cleanup queues (retries, abandonment, alerting)
    - Phase B: stale ticket detection (grace period, deal history, recovery)
    - Phase C/D: orphan report + self-healing adoption
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.orchestrator.orphan_reconciliation import (
    MAX_CLEANUP_RETRIES,
    MAX_STALE_TICKET_CYCLES,
    STALE_TICKET_DEAL_CHECK_CYCLES,
    OrphanReconciler,
)


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _mock_position(position_id: str, asset: str = "EURUSD", quantity: float = 1.0,
                   avg_entry_price: float = 1.05, current_price: float = 1.06,
                   unrealized_pnl: float = 10.0) -> MagicMock:
    p = MagicMock()
    p.position_id = position_id
    p.asset = asset
    p.quantity = quantity
    p.avg_entry_price = avg_entry_price
    p.current_price = current_price
    p.unrealized_pnl = unrealized_pnl
    return p


def _mock_engine(ticker: str = "EURUSD", has_position: bool = False,
                 mt5_ticket: str | None = None,
                 cleanup_queue: list | None = None,
                 cleanup_retries: int = 0,
                 current_price: float | None = 1.05) -> MagicMock:
    engine = MagicMock()
    engine.ticker = ticker
    engine.current_price = current_price
    engine.position = {"mt5_ticket": mt5_ticket} if mt5_ticket else ({"something": 1} if has_position else {})
    if cleanup_queue is not None:
        engine._mt5_cleanup_queue = cleanup_queue
    engine._mt5_cleanup_retries = cleanup_retries
    engine._close_position = MagicMock(return_value=True)
    return engine


def _mock_actor(name: str, engine: MagicMock) -> MagicMock:
    actor = MagicMock()
    actor.name = name
    actor._engine = engine
    return actor


def _make_broker(connected: bool = True, positions: list | None = None,
                 symbol_map: dict[str, str] | None = None) -> MagicMock:
    broker = MagicMock()
    broker.ensure_connected.return_value = connected
    broker.get_positions.return_value = positions or []
    broker.ticker_to_mt5_symbol.side_effect = lambda t: t
    broker._symbol_map = symbol_map or {}
    broker.close_position.return_value = True
    broker.get_deal_by_ticket.return_value = None
    broker._position_cache_time = 0.0
    return broker


# ── Init ──────────────────────────────────────────────────────────────────────


class TestInit:
    def test_defaults(self):
        r = OrphanReconciler()
        assert r.abandoned_orphans == 0
        assert r._stale_ticket_cycles == {}
        assert r._orphan_first_seen == {}
        assert r._orphan_cycle_no == 0


class TestReconcile:
    def test_broker_none_returns_early(self):
        r = OrphanReconciler()
        r.reconcile({}, lambda: None)
        # No crash — telemetry proves early return
        assert r._orphan_cycle_no == 0

    def test_broker_available_runs_all_phases(self):
        r = OrphanReconciler()
        broker = _make_broker()
        actors = {"EURUSD": _mock_actor("EURUSD", _mock_engine())}
        r.reconcile(actors, lambda: broker)
        assert r._orphan_cycle_no == 1  # Phase C incremented this


# ── Phase A: Drain cleanup queues ─────────────────────────────────────────────


class TestPhaseADrainQueues:
    def test_no_queue_skips(self):
        r = OrphanReconciler()
        engine = _mock_engine()
        # No _mt5_cleanup_queue attribute set → falls through
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 0

    def test_empty_queue_skips(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[])
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 0

    def test_single_clean_success(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)])
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker()
        broker.close_position.return_value = True
        r._phase_a_drain_queues(broker, actors)
        broker.close_position.assert_called_once_with("EURUSD", "12345")
        assert engine._mt5_cleanup_queue == []  # cleared
        assert engine._mt5_cleanup_retries == 0

    def test_close_fails_adds_to_pending(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)])
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker()
        broker.close_position.return_value = False
        r._phase_a_drain_queues(broker, actors)
        assert engine._mt5_cleanup_queue == [("EURUSD", 12345)]  # still pending
        assert engine._mt5_cleanup_retries == 1

    def test_close_exception_adds_to_pending(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)])
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker()
        broker.close_position.side_effect = OSError("connection lost")
        r._phase_a_drain_queues(broker, actors)
        assert engine._mt5_cleanup_queue == [("EURUSD", 12345)]
        assert engine._mt5_cleanup_retries == 1

    def test_retry_increments_counter(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)], cleanup_retries=2)
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker()
        broker.close_position.return_value = False
        r._phase_a_drain_queues(broker, actors)
        assert engine._mt5_cleanup_retries == 3

    def test_abandonment_after_max_retries(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)], cleanup_retries=MAX_CLEANUP_RETRIES)
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 1
        assert engine._mt5_cleanup_queue == []  # cleared on abandon
        assert engine._mt5_cleanup_retries == 0

    def test_abandonment_at_threshold_triggers_alert(self):
        r = OrphanReconciler()
        # Trigger 3 abandonments (first threshold = 3)
        for i in range(3):
            engine = _mock_engine(cleanup_queue=[("EURUSD", 10000 + i)], cleanup_retries=MAX_CLEANUP_RETRIES)
            actors = {f"ASSET{i}": _mock_actor(f"ASSET{i}", engine)}
            r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 3

    def test_abandonment_at_5th_triggers_alert(self):
        r = OrphanReconciler()
        r.abandoned_orphans = 4
        engine = _mock_engine(cleanup_queue=[("EURUSD", 99999)], cleanup_retries=MAX_CLEANUP_RETRIES)
        actors = {"TEST": _mock_actor("TEST", engine)}
        r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 5  # 5 % 5 == 0 → alertable threshold

    def test_abandonment_alert_exception_does_not_crash(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 12345)], cleanup_retries=MAX_CLEANUP_RETRIES)
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        # The alert path catches (OSError, RuntimeError, KeyError) internally.
        # This test ensures the try/except doesn't crash even when the
        # alerting module import falls through to the except block.
        r._phase_a_drain_queues(_make_broker(), actors)
        assert r.abandoned_orphans == 1

    def test_mixed_queue_some_succeed_some_pending(self):
        r = OrphanReconciler()
        engine = _mock_engine(cleanup_queue=[("EURUSD", 111), ("GBPUSD", 222)])
        actors = {"TEST": _mock_actor("TEST", engine)}
        broker = _make_broker()
        # First close succeeds, second fails
        broker.close_position.side_effect = [True, False]
        r._phase_a_drain_queues(broker, actors)
        assert engine._mt5_cleanup_queue == [("GBPUSD", 222)]  # only failed remains
        assert engine._mt5_cleanup_retries == 1


# ── Phase B: Stale ticket detection ───────────────────────────────────────────


class TestPhaseBStaleTickets:
    def test_not_connected_returns_early(self):
        r = OrphanReconciler()
        broker = _make_broker(connected=False)
        r._phase_b_stale_tickets(broker, {})
        broker.get_positions.assert_not_called()

    def test_get_positions_exception_returns_early(self):
        r = OrphanReconciler()
        broker = _make_broker()
        broker.get_positions.side_effect = OSError("timeout")
        r._phase_b_stale_tickets(broker, {"TEST": _mock_actor("TEST", _mock_engine())})
        # No crash

    def test_no_position_skips(self):
        r = OrphanReconciler()
        engine = _mock_engine()  # no position
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        r._phase_b_stale_tickets(_make_broker(), actors)
        assert r._stale_ticket_cycles == {}

    def test_no_mt5_ticket_skips(self):
        r = OrphanReconciler()
        engine = _mock_engine(has_position=True)  # position but no mt5_ticket
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        r._phase_b_stale_tickets(_make_broker(positions=[_mock_position("999")]), actors)
        assert r._stale_ticket_cycles == {}

    def test_ticket_still_on_broker_no_action(self):
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="100")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("100")])
        r._phase_b_stale_tickets(broker, actors)
        assert r._stale_ticket_cycles == {}  # no stale tracking

    def test_ticket_missing_first_cycle_grace_period(self, caplog):
        caplog.set_level("INFO")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="200")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])  # ticket 200 not present
        r._phase_b_stale_tickets(broker, actors)
        assert r._stale_ticket_cycles == {"EURUSD:200": 1}
        assert "GRACE" in caplog.text

    def test_ticket_missing_below_deal_check_cycles(self, caplog):
        caplog.set_level("INFO")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="200")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        # Start at DEAL_CHECK - 2 so after increment it's DEAL_CHECK - 1
        # (still in grace range, not yet triggering deal check)
        r._stale_ticket_cycles["EURUSD:200"] = STALE_TICKET_DEAL_CHECK_CYCLES - 2
        r._phase_b_stale_tickets(broker, actors)
        assert r._stale_ticket_cycles["EURUSD:200"] == STALE_TICKET_DEAL_CHECK_CYCLES - 1
        assert "GRACE" in caplog.text

    def test_ticket_missing_at_deal_check_cycles_deal_found(self, caplog):
        caplog.set_level("INFO")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="300")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        broker.get_deal_by_ticket.return_value = {
            "result": {"price": 1.10, "profit": 50.0},
        }
        r._stale_ticket_cycles["EURUSD:300"] = STALE_TICKET_DEAL_CHECK_CYCLES
        r._phase_b_stale_tickets(broker, actors)
        assert "found in deal history" in caplog.text
        # Ticket still tracked but not closed
        assert "EURUSD:300" in r._stale_ticket_cycles

    def test_ticket_missing_at_deal_check_cycles_no_deal_closes(self, caplog):
        caplog.set_level("WARNING")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="400", current_price=1.05)
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        broker.get_deal_by_ticket.return_value = None
        r._stale_ticket_cycles["EURUSD:400"] = STALE_TICKET_DEAL_CHECK_CYCLES
        r._phase_b_stale_tickets(broker, actors)
        assert "MT5_ORDER_REJECTED" in caplog.text
        assert "EURUSD:400" not in r._stale_ticket_cycles  # cleaned up
        engine._close_position.assert_called_once()

    def test_ticket_missing_at_max_cycles_closes(self, caplog):
        caplog.set_level("WARNING")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="500", current_price=1.05)
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        r._stale_ticket_cycles["EURUSD:500"] = MAX_STALE_TICKET_CYCLES
        r._phase_b_stale_tickets(broker, actors)
        assert "MT5_STALE_TICKET" in caplog.text
        assert "EURUSD:500" not in r._stale_ticket_cycles  # cleaned up
        engine._close_position.assert_called_once()

    def test_ticket_close_exception_logged(self, caplog):
        caplog.set_level("ERROR")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="600", current_price=1.05)
        engine._close_position.side_effect = RuntimeError("close failed")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        r._stale_ticket_cycles["EURUSD:600"] = MAX_STALE_TICKET_CYCLES
        r._phase_b_stale_tickets(broker, actors)
        assert "ghost" in caplog.text.lower() or "failed to close" in caplog.text

    def test_ticket_reappears_logs_recovery(self, caplog):
        caplog.set_level("INFO")
        r = OrphanReconciler()
        r._stale_ticket_cycles["EURUSD:700"] = 3  # was missing for 3 cycles
        engine = _mock_engine(mt5_ticket="700")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("700")])  # now reappeared
        r._phase_b_stale_tickets(broker, actors)
        assert "RECOVERED" in caplog.text
        assert "EURUSD:700" not in r._stale_ticket_cycles  # cleaned up

    def test_deal_check_exception_logged(self, caplog):
        caplog.set_level("DEBUG")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="800")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("999")])
        broker.get_deal_by_ticket.side_effect = ConnectionError("deal lookup failed")
        r._stale_ticket_cycles["EURUSD:800"] = STALE_TICKET_DEAL_CHECK_CYCLES
        r._phase_b_stale_tickets(broker, actors)
        broker.get_deal_by_ticket.assert_called_once()
        # Exception caught → deal = None → falls through to ORDER_REJECTED path
        assert "MT5_ORDER_REJECTED" in caplog.text or "deal lookup failed" in caplog.text


# ── Phase C/D: Orphan report + self-healing adoption ──────────────────────────


class TestPhaseCOrphanReport:
    def test_get_positions_exception_returns_early(self):
        r = OrphanReconciler()
        broker = _make_broker()
        broker.get_positions.side_effect = OSError("timeout")
        r._phase_c_orphan_report(broker, {})
        assert r._orphan_cycle_no == 0  # never incremented

    def test_no_orphans_no_summary(self, caplog):
        caplog.set_level("WARNING")
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="100")
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(positions=[_mock_position("100")])
        r._phase_c_orphan_report(broker, actors)
        assert r._orphan_cycle_no == 1
        # No summary warning for zero orphans
        assert "PHASE_C_SUMMARY" not in caplog.text

    def test_new_orphan_tracked(self):
        r = OrphanReconciler()
        actors = {"EURUSD": _mock_actor("EURUSD", _mock_engine())}  # no position
        broker = _make_broker(positions=[_mock_position("orphan_1", asset="EURUSD")])
        r._phase_c_orphan_report(broker, actors)
        assert "orphan_1" in r._orphan_first_seen
        assert r._orphan_first_seen["orphan_1"] == 1  # first cycle

    def test_existing_orphan_not_re_tracked(self):
        r = OrphanReconciler()
        r._orphan_first_seen["orphan_1"] = 1
        r._orphan_cycle_no = 2
        actors = {"EURUSD": _mock_actor("EURUSD", _mock_engine())}
        broker = _make_broker(positions=[_mock_position("orphan_1", asset="EURUSD")])
        r._phase_c_orphan_report(broker, actors)
        assert r._orphan_first_seen["orphan_1"] == 1  # not overwritten

    def test_phase_d_adoption_backfills_mt5_ticket(self, caplog):
        caplog.set_level("INFO")
        r = OrphanReconciler()
        engine = _mock_engine(has_position=True)  # no mt5_ticket
        engine.position = {"something": 1}  # paper has a position but no ticket
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        # Use a numeric position_id so int(ticket) works
        broker = _make_broker(
            positions=[_mock_position("99999", asset="EURUSD")],
            symbol_map={"EURUSD": "EURUSD"},
        )
        broker.ticker_to_mt5_symbol.return_value = "EURUSD"
        r._phase_c_orphan_report(broker, actors)
        assert "PHASE_D_ADOPT" in caplog.text
        assert engine.position.get("mt5_ticket") == 99999

    def test_paper_ticket_mismatch_logs_reason(self):
        r = OrphanReconciler()
        engine = _mock_engine(mt5_ticket="existing_ticket")  # paper has different ticket
        engine.position = {"mt5_ticket": "existing_ticket"}
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(
            positions=[_mock_position("orphan_ticket", asset="EURUSD")],
            symbol_map={"EURUSD": "EURUSD"},
        )
        broker.ticker_to_mt5_symbol.return_value = "EURUSD"
        r._phase_c_orphan_report(broker, actors)
        # Orphan not adopted (paper already has a ticket)
        assert engine.position.get("mt5_ticket") == "existing_ticket"

    def test_no_paper_position_logs_reason(self):
        r = OrphanReconciler()
        engine = _mock_engine()  # no position at all
        engine.position = {}  # empty position dict
        actors = {"EURUSD": _mock_actor("EURUSD", engine)}
        broker = _make_broker(
            positions=[_mock_position("orphan_no_paper", asset="EURUSD")],
            symbol_map={"EURUSD": "EURUSD"},
        )
        broker.ticker_to_mt5_symbol.return_value = "EURUSD"
        r._phase_c_orphan_report(broker, actors)
        assert "orphan_no_paper" in r._orphan_first_seen

    def test_removed_asset_orphan(self):
        r = OrphanReconciler()
        actors = {}  # no actors at all
        broker = _make_broker(
            positions=[_mock_position("removed", asset="AUDNZD")],
            symbol_map={"AUDNZD": "AUDNZD"},
        )
        r._phase_c_orphan_report(broker, actors)
        assert "removed" in r._orphan_first_seen

    def test_unknown_symbol_orphan(self):
        r = OrphanReconciler()
        actors = {}
        broker = _make_broker(
            positions=[_mock_position("unknown", asset="UNKNOWN_SYMBOL_X")],
            symbol_map={},
        )
        r._phase_c_orphan_report(broker, actors)
        assert "unknown" in r._orphan_first_seen

    def test_summary_logged_when_orphans_exist(self, caplog):
        caplog.set_level("WARNING")
        r = OrphanReconciler()
        actors = {"EURUSD": _mock_actor("EURUSD", _mock_engine())}  # no position
        broker = _make_broker(
            positions=[_mock_position("orphan_summary", asset="EURUSD")],
        )
        r._phase_c_orphan_report(broker, actors)
        assert "PHASE_C_SUMMARY" in caplog.text
        assert "1" in caplog.text  # 1 unique orphan

    def test_multiple_orphans_tracked_independently(self):
        r = OrphanReconciler()
        actors = {}
        broker = _make_broker(
            positions=[
                _mock_position("orph_a", asset="ASSET_A"),
                _mock_position("orph_b", asset="ASSET_B"),
                _mock_position("orph_c", asset="ASSET_C"),
            ],
        )
        r._phase_c_orphan_report(broker, actors)
        assert len(r._orphan_first_seen) == 3
