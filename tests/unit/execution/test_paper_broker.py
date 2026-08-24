"""Adversarial tests for Phase 1K Paper-Trading Infrastructure.

Tests cover:
- Paper broker order submission and lifecycle
- Fill generation and invariants
- Position accounting (long, short, reversal)
- Account state and P&L
- Reconciliation
- Audit log
- Edge cases: duplicate orders, partial fills, rejected orders
"""

import pytest

from eigencapital.execution.broker import PaperBroker, OrderLifecycleState, BrokerError
from eigencapital.execution.position_manager import PositionManager
from eigencapital.execution.account import AccountState
from eigencapital.execution.reconciliation import (
    ReconciliationEngine,
    ReconciliationStatus,
)
from eigencapital.execution.events import AuditLog, EventType
from eigencapital.core.models.order import Order


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────


def _make_order(
    instrument_id: str = "ES",
    side: str = "BUY",
    quantity: float = 10.0,
    price: float = 5000.0,
) -> Order:
    return Order(
        order_id=f"ORD-{instrument_id}",
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        timestamp_utc="2025-01-15T10:00:00Z",
        order_type="LIMIT",
        limit_price=price,
        strategy_id="test_strategy",
    )


# ═══════════════════════════════════════════════
#  PAPER BROKER
# ═══════════════════════════════════════════════


class TestPaperBroker:
    def test_submit_order(self):
        broker = PaperBroker()
        order = _make_order()
        order_id = broker.submit_order(order)
        assert order_id == "ES"
        assert broker.get_order_state("ES") == OrderLifecycleState.SUBMITTED

    def test_generate_fill(self):
        broker = PaperBroker()
        order = _make_order(quantity=10, price=5000)
        broker.submit_order(order)
        fill = broker.generate_fill("ES", fill_price=5005)
        assert fill.quantity == 10
        assert broker.get_order_state("ES") == OrderLifecycleState.FILLED

    def test_partial_fill(self):
        broker = PaperBroker()
        order = _make_order(quantity=100, price=5000)
        broker.submit_order(order)
        fill1 = broker.generate_fill("ES", fill_price=5000, fill_quantity=40)
        assert fill1.quantity == 40
        assert broker.get_order_state("ES") == OrderLifecycleState.PARTIALLY_FILLED

        fill2 = broker.generate_fill("ES", fill_price=5001, fill_quantity=60)
        assert fill2.quantity == 60
        assert broker.get_order_state("ES") == OrderLifecycleState.FILLED

    def test_fill_sum_never_exceeds_order(self):
        """Aggregate fills must not exceed order quantity."""
        broker = PaperBroker()
        order = _make_order(quantity=100, price=5000)
        broker.submit_order(order)
        broker.generate_fill("ES", fill_price=5000, fill_quantity=60)
        broker.generate_fill(
            "ES", fill_price=5001, fill_quantity=50
        )  # Only 40 remaining

        # Total fills should be 100, not 110
        fills = broker._fills["ES"]
        total = sum(f.quantity for f in fills)
        assert total <= 100

    def test_reject_order(self):
        broker = PaperBroker()
        order = _make_order()
        broker.submit_order(order)
        result = broker.reject_order("ES", "insufficient margin")
        assert result is True
        assert broker.get_order_state("ES") == OrderLifecycleState.REJECTED

    def test_cancel_order(self):
        broker = PaperBroker()
        order = _make_order()
        broker.submit_order(order)
        result = broker.cancel_order("ES")
        assert result is True
        assert broker.get_order_state("ES") == OrderLifecycleState.CANCELLED

    def test_invalid_quantity_rejected(self):
        PaperBroker()
        # Order model raises ValueError for negative quantity
        with pytest.raises(ValueError, match="quantity must be >= 0"):
            Order(
                order_id="ORD-NEG",
                instrument_id="ES",
                side="BUY",
                quantity=-5,
                timestamp_utc="2025-01-15T10:00:00Z",
                order_type="LIMIT",
                limit_price=5000,
                strategy_id="test",
            )

    def test_duplicate_order_rejected(self):
        broker = PaperBroker()
        order1 = _make_order(quantity=10)
        order2 = _make_order(quantity=20)
        broker.submit_order(order1)
        with pytest.raises(BrokerError, match="already active"):
            broker.submit_order(order2)

    def test_fill_on_nonexistent_order(self):
        broker = PaperBroker()
        with pytest.raises(BrokerError, match="not found"):
            broker.generate_fill("NONEXISTENT", fill_price=5000)

    def test_positions_updated(self):
        broker = PaperBroker()
        order = _make_order(side="BUY", quantity=10, price=5000)
        broker.submit_order(order)
        broker.generate_fill("ES", fill_price=5000)
        positions = broker.get_positions()
        assert positions["ES"] == 10.0

    def test_cash_updated(self):
        broker = PaperBroker(initial_capital=100000)
        order = _make_order(side="BUY", quantity=10, price=5000)
        broker.submit_order(order)
        broker.generate_fill("ES", fill_price=5000)
        # Cash should decrease by 10 * 5000 = 50000
        assert broker.get_cash() < 100000

    def test_account_snapshot(self):
        broker = PaperBroker()
        snapshot = broker.get_account_snapshot()
        assert snapshot["cash"] == 100000
        assert snapshot["num_orders"] == 0

    def test_get_open_orders(self):
        broker = PaperBroker()
        order = _make_order()
        broker.submit_order(order)
        open_orders = broker.get_open_orders()
        assert len(open_orders) == 1

    def test_reset(self):
        broker = PaperBroker()
        order = _make_order()
        broker.submit_order(order)
        broker.generate_fill("ES", fill_price=5000)
        broker.reset()
        assert broker.get_cash() == 100000
        assert len(broker.get_open_orders()) == 0


# ═══════════════════════════════════════════════
#  POSITION MANAGER
# ═══════════════════════════════════════════════


class TestPositionManager:
    def _make_fill(self, fill_id: str, side: str, quantity: float, price: float):
        from eigencapital.core.models.fill import Fill

        return Fill(
            fill_id=fill_id,
            order_id="O1",
            instrument_id="ES",
            timestamp_utc="2025-01-15T10:00:00Z",
            side=side,
            quantity=quantity,
            fill_price=price,
            strategy_id="test_strategy",
        )

    def test_open_long(self):
        pm = PositionManager()
        fill = self._make_fill("F1", "BUY", 10, 5000)
        pos = pm.update_from_fill(fill)
        assert pos.quantity == 10
        assert pos.is_long
        assert pos.average_entry_price == 5000

    def test_open_short(self):
        pm = PositionManager()
        fill = self._make_fill("F1", "SELL", 10, 5000)
        pos = pm.update_from_fill(fill)
        assert pos.quantity == -10
        assert pos.is_short

    def test_close_position(self):
        pm = PositionManager()
        fill1 = self._make_fill("F1", "BUY", 10, 5000)
        fill2 = self._make_fill("F2", "SELL", 10, 5100)
        pm.update_from_fill(fill1)
        pos = pm.update_from_fill(fill2)
        assert pos.is_flat
        assert pos.realized_pnl == pytest.approx(1000)

    def test_reversal(self):
        pm = PositionManager()
        fill1 = self._make_fill("F1", "BUY", 10, 5000)
        fill2 = self._make_fill("F2", "SELL", 20, 5100)
        pm.update_from_fill(fill1)
        pos = pm.update_from_fill(fill2)
        assert pos.quantity == -10
        assert pos.is_short

    def test_average_entry_price(self):
        pm = PositionManager()
        fill1 = self._make_fill("F1", "BUY", 10, 5000)
        fill2 = self._make_fill("F2", "BUY", 10, 5200)
        pm.update_from_fill(fill1)
        pos = pm.update_from_fill(fill2)
        assert pos.average_entry_price == pytest.approx(5100)
        assert pos.quantity == 20

    def test_unrealized_pnl(self):
        pm = PositionManager()
        fill = self._make_fill("F1", "BUY", 10, 5000)
        pos = pm.update_from_fill(fill, current_price=5100)
        assert pos.unrealized_pnl == pytest.approx(1000)

    def test_total_exposure(self):
        pm = PositionManager()
        fill = self._make_fill("F1", "BUY", 10, 5000)
        pm.update_from_fill(fill)
        assert pm.get_gross_exposure() == pytest.approx(50000)
        assert pm.get_net_exposure() == pytest.approx(50000)

    def test_reset(self):
        pm = PositionManager()
        fill = self._make_fill("F1", "BUY", 10, 5000)
        pm.update_from_fill(fill)
        pm.reset()
        assert len(pm.get_all_positions()) == 0


# ═══════════════════════════════════════════════
#  ACCOUNT STATE
# ═══════════════════════════════════════════════


class TestAccountState:
    def test_initial_state(self):
        account = AccountState(initial_capital=100000)
        assert account.cash == 100000
        assert account.equity == 100000
        assert account.realized_pnl == 0

    def test_update_from_buy_fill(self):
        account = AccountState(initial_capital=100000)
        account.update_from_fill("buy", 10, 5000)
        assert account.cash == 50000  # 100000 - 10*5000

    def test_update_from_sell_fill(self):
        account = AccountState(initial_capital=100000)
        account.update_from_fill("sell", 10, 5000)
        assert account.cash == 150000  # 100000 + 10*5000

    def test_equity_includes_unrealized(self):
        account = AccountState(initial_capital=100000)
        account.update_from_fill("buy", 10, 5000)
        account.update_positions(
            gross_exposure=50000,
            net_exposure=50000,
            num_positions=1,
            unrealized_pnl=1000,
        )
        assert account.equity == 51000  # 50000 cash + 1000 unrealized

    def test_snapshot(self):
        account = AccountState(initial_capital=100000)
        snap = account.snapshot("2025-01-15T10:00:00Z")
        assert snap.cash == 100000
        assert snap.equity == 100000
        assert snap.provenance_hash != ""

    def test_snapshot_deterministic(self):
        account = AccountState(initial_capital=100000)
        s1 = account.snapshot()
        s2 = account.snapshot()
        assert s1.provenance_hash == s2.provenance_hash

    def test_reset(self):
        account = AccountState(initial_capital=100000)
        account.update_from_fill("buy", 10, 5000)
        account.reset()
        assert account.cash == 100000


# ═══════════════════════════════════════════════
#  RECONCILIATION
# ═══════════════════════════════════════════════


class TestReconciliation:
    def test_reconciled(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={"ES": 10.0},
            broker_positions={"ES": 10.0},
            expected_cash=50000,
            broker_cash=50000,
            expected_fills=1,
            broker_fills=1,
        )
        assert result.status == ReconciliationStatus.RECONCILED

    def test_position_mismatch(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={"ES": 10.0},
            broker_positions={"ES": 9.0},
            expected_cash=50000,
            broker_cash=50000,
            expected_fills=1,
            broker_fills=1,
        )
        assert result.status == ReconciliationStatus.MISMATCH

    def test_cash_mismatch(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={"ES": 10.0},
            broker_positions={"ES": 10.0},
            expected_cash=50000,
            broker_cash=49000,
            expected_fills=1,
            broker_fills=1,
        )
        assert result.status == ReconciliationStatus.WARNING

    def test_fill_count_mismatch(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={"ES": 10.0},
            broker_positions={"ES": 10.0},
            expected_cash=50000,
            broker_cash=50000,
            expected_fills=2,
            broker_fills=1,
        )
        assert result.status == ReconciliationStatus.WARNING

    def test_tolerance(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={"ES": 10.0},
            broker_positions={"ES": 10.0000001},
            expected_cash=50000,
            broker_cash=50000,
            expected_fills=1,
            broker_fills=1,
            tolerance=1e-5,
        )
        assert result.status == ReconciliationStatus.RECONCILED

    def test_serialization(self):
        engine = ReconciliationEngine()
        result = engine.reconcile(
            expected_positions={},
            broker_positions={},
            expected_cash=100000,
            broker_cash=100000,
            expected_fills=0,
            broker_fills=0,
        )
        d = result.to_dict()
        assert d["status"] == "reconciled"


# ═══════════════════════════════════════════════
#  AUDIT LOG
# ═══════════════════════════════════════════════


class TestAuditLog:
    def test_append_event(self):
        log = AuditLog()
        event = log.create_event(
            EventType.ORDER_SUBMITTED,
            timestamp_utc="2025-01-15T10:00:00Z",
            instrument_id="ES",
        )
        assert len(log) == 1
        assert event.event_type == EventType.ORDER_SUBMITTED

    def test_event_hash_deterministic(self):
        log = AuditLog()
        event = log.create_event(
            EventType.ORDER_FILLED,
            timestamp_utc="2025-01-15T10:00:00Z",
        )
        assert event.event_hash != ""
        assert len(event.event_hash) == 64

    def test_filter_by_type(self):
        log = AuditLog()
        log.create_event(EventType.ORDER_SUBMITTED)
        log.create_event(EventType.ORDER_FILLED)
        log.create_event(EventType.ORDER_SUBMITTED)

        submitted = log.get_events(EventType.ORDER_SUBMITTED)
        assert len(submitted) == 2

    def test_filter_by_instrument(self):
        log = AuditLog()
        log.create_event(EventType.ORDER_SUBMITTED, instrument_id="ES")
        log.create_event(EventType.ORDER_SUBMITTED, instrument_id="NQ")

        es_events = log.get_events_for_instrument("ES")
        assert len(es_events) == 1

    def test_event_serialization(self):
        log = AuditLog()
        event = log.create_event(
            EventType.POSITION_CHANGED,
            timestamp_utc="2025-01-15T10:00:00Z",
            instrument_id="ES",
            details={"quantity": 10},
        )
        d = event.to_dict()
        assert d["event_type"] == "position_changed"
        assert d["details"]["quantity"] == 10
