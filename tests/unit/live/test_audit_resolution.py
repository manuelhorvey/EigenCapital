"""Focused tests for audit resolution features.

Covers:
1. P1-003: P&L discrepancy check in reconciliation engine
2. P1-010: Multi-factor foreign position detection (magic + symbol allowlist)
3. P2-014: Pending order capacity accounting

These tests validate the specific code changes made to resolve
findings from the 2026-08-28 comprehensive codebase audit.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.position_attribution import (
    capacity_account,
    classify_all,
)
from eigencapital.reconciliation.engine import (
    BrokerState,
    InternalState,
    ReconciliationEngine,
)

# ── Helpers ────────────────────────────────────────────────────────

R4_MAGIC = 20260825
ALLOWED_SYMBOLS = {"EURUSD", "GBPUSD", "BTCUSD", "AUDUSD", "USDCAD"}


def _make_position(
    ticket: int = 1,
    symbol: str = "EURUSD",
    volume: float = 0.1,
    ptype: int = 0,
    magic: int = R4_MAGIC,
    comment: str = "R4",
    profit: float = 0.0,
    sl: float = 0.0,
    tp: float = 0.0,
    price_open: float = 1.1,
) -> dict:
    return {
        "ticket": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": ptype,
        "magic": magic,
        "comment": comment,
        "profit": profit,
        "sl": sl,
        "tp": tp,
        "price_open": price_open,
    }


def _make_broker_state(
    positions: list[dict] | None = None,
    equity: float = 5000.0,
    balance: float = 5000.0,
    free_margin: float = 3000.0,
) -> BrokerState:
    return BrokerState(
        positions=positions or [],
        account_equity=equity,
        account_balance=balance,
        account_free_margin=free_margin,
        orders=[],
        timestamp="2026-08-28T00:00:00Z",
    )


def _make_internal_state(
    positions: dict | None = None,
    last_signal: dict | None = None,
) -> InternalState:
    return InternalState(
        positions=positions or {},
        pending_orders=[],
        last_signal=last_signal or {"weights": {"EURUSD": 0.1}},
        target_weights={"EURUSD": 0.1},
        timestamp="2026-08-28T00:00:00Z",
    )


def _make_engine(**kwargs) -> ReconciliationEngine:
    return ReconciliationEngine(
        r4_magic=R4_MAGIC,
        allowed_symbols=ALLOWED_SYMBOLS,
        **kwargs,
    )


def _get_check(result, check_name):
    """Extract a specific check from reconciliation result."""
    return next(c for c in result.checks if c.check_name == check_name)


# ══════════════════════════════════════════════════════════════════════
# 1. P1-003: P&L Discrepancy Check
# ══════════════════════════════════════════════════════════════════════


class TestPnlDiscrepancyCheck:
    """Tests for the reconciliation engine P&L discrepancy check (P1-003).

    The check compares: |equity - (balance + unrealized_pnl)| vs $10 tolerance.
    """

    def test_balanced_accounts_pass(self):
        """Equity == balance + unrealized P&L → PASS."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=100.0)],
            equity=5100.0,  # balance(5000) + profit(100) = 5100
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "PASS"

    def test_within_tolerance_pass(self):
        """Discrepancy < $10 → PASS (within tolerance)."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=100.0)],
            equity=5105.0,  # balance(5000) + profit(100) = 5100, actual = 5105 → $5 off
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["discrepancy"] == pytest.approx(5.0, abs=0.01)

    def test_discrepancy_exceeds_tolerance_warns(self):
        """Discrepancy > $10 → WARNING."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=100.0)],
            equity=5120.0,  # balance(5000) + profit(100) = 5100, actual = 5120 → $20 off
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "WARNING"
        assert check.details["discrepancy"] == pytest.approx(20.0, abs=0.01)
        assert check.details["tolerance"] == 10.0

    def test_large_loss_discrepancy_warns(self):
        """Large loss creates discrepancy → WARNING."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=-500.0)],
            equity=4600.0,  # balance(5000) + profit(-500) = 4500, actual = 4600 → $100 off
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "WARNING"
        assert check.details["discrepancy"] == pytest.approx(100.0, abs=0.01)

    def test_no_positions_check_skipped(self):
        """When no signal data (last_signal empty), P&L check is skipped."""
        engine = _make_engine()
        broker = _make_broker_state(equity=5000.0, balance=5000.0)
        internal = InternalState(
            positions={},
            pending_orders=[],
            last_signal={},  # empty → no P&L check
            target_weights={},
            timestamp="2026-08-28T00:00:00Z",
        )
        result = engine.reconcile(broker, internal)
        check_names = [c.check_name for c in result.checks]
        assert "pnl_discrepancy" not in check_names

    def test_multiple_positions_summed(self):
        """P&L discrepancy sums all position profits."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, profit=50.0),
                _make_position(ticket=2, symbol="GBPUSD", profit=30.0),
                _make_position(ticket=3, symbol="BTCUSD", profit=-10.0),
            ],
            equity=5075.0,  # balance(5000) + profit(70) = 5070, actual = 5075 → $5 off
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={
                1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC},
                2: {"symbol": "GBPUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC},
                3: {"symbol": "BTCUSD", "volume": 0.01, "side": "buy", "type": 0, "magic": R4_MAGIC},
            }
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["broker_unrealized_pnl"] == pytest.approx(70.0, abs=0.01)

    def test_exact_boundary_at_tolerance(self):
        """Discrepancy exactly at $10 tolerance → PASS (not exceeding)."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=0.0)],
            equity=5010.0,  # balance(5000) + profit(0) = 5000, actual = 5010 → $10
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "PASS"

    def test_just_over_tolerance_warns(self):
        """Discrepancy just over $10 → WARNING."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[_make_position(profit=0.0)],
            equity=5010.01,  # $10.01 off
            balance=5000.0,
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "pnl_discrepancy")
        assert check.status == "WARNING"


# ══════════════════════════════════════════════════════════════════════
# 2. P1-010: Multi-Factor Foreign Position Detection
# ══════════════════════════════════════════════════════════════════════


class TestForeignPositionDetection:
    """Tests for multi-factor foreign position detection (P1-010).

    Primary: magic == R4_MAGIC
    Secondary: symbol in allowed_symbols (if allowlist provided)
    """

    def test_all_r4_positions_pass(self):
        """All positions with R4 magic + allowed symbols → PASS."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GBPUSD"),
                _make_position(ticket=3, symbol="BTCUSD"),
            ]
        )
        internal = _make_internal_state(
            positions={
                1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC},
                2: {"symbol": "GBPUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC},
                3: {"symbol": "BTCUSD", "volume": 0.01, "side": "buy", "type": 0, "magic": R4_MAGIC},
            }
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "PASS"

    def test_foreign_magic_blocks(self):
        """Position with wrong magic → BLOCKING."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="USDJPY", magic=999, comment="manual"),
            ]
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "BLOCKING"
        assert "USDJPY" in check.message

    def test_r4_magic_wrong_symbol_warns(self):
        """R4 magic but symbol not in allowlist → WARNING (suspicious)."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GOLDUSD", magic=R4_MAGIC),  # R4 magic but not in allowlist
            ]
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "WARNING"
        assert "unexpected symbol" in check.message.lower()
        assert len(check.details["suspicious"]) == 1
        assert check.details["suspicious"][0]["symbol"] == "GOLDUSD"

    def test_multiple_foreign_positions(self):
        """Multiple foreign positions all listed in message."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="USDJPY", magic=999),
                _make_position(ticket=3, symbol="GBPJPY", magic=888),
            ]
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "BLOCKING"
        assert "USDJPY" in check.message
        assert "GBPJPY" in check.message
        assert check.details["count"] == 2

    def test_magic_zero_is_foreign(self):
        """Magic=0 (manual trade) → BLOCKING."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="AUDUSD", magic=0),
            ]
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "BLOCKING"

    def test_no_allowlist_skips_secondary_check(self):
        """Without allowlist, only magic is checked (no WARNING for wrong symbol)."""
        engine = ReconciliationEngine(r4_magic=R4_MAGIC)  # no allowed_symbols
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GOLDUSD", magic=R4_MAGIC),  # wrong symbol but no allowlist
            ]
        )
        internal = _make_internal_state(
            positions={1: {"symbol": "EURUSD", "volume": 0.1, "side": "buy", "type": 0, "magic": R4_MAGIC}}
        )
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        # Without allowlist, both pass (magic matches) → no WARNING
        assert check.status == "PASS"

    def test_empty_positions_pass(self):
        """No positions → PASS."""
        engine = _make_engine()
        broker = _make_broker_state(positions=[])
        internal = _make_internal_state(positions={})
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "PASS"

    def test_suspicious_includes_ticket_info(self):
        """WARNING details include ticket, symbol, comment for investigation."""
        engine = _make_engine()
        broker = _make_broker_state(
            positions=[
                _make_position(ticket=42, symbol="XAUUSD", magic=R4_MAGIC, comment="R4-gold"),
            ]
        )
        internal = _make_internal_state(positions={})
        result = engine.reconcile(broker, internal)
        check = _get_check(result, "foreign_positions")
        assert check.status == "WARNING"
        susp = check.details["suspicious"][0]
        assert susp["ticket"] == 42
        assert susp["symbol"] == "XAUUSD"
        assert susp["reason"] == "symbol_not_in_allowlist"


# ══════════════════════════════════════════════════════════════════════
# 3. P2-014: Pending Order Capacity Accounting
# ══════════════════════════════════════════════════════════════════════


class TestPendingOrderCapacity:
    """Tests for pending order capacity accounting (P2-014).

    capacity_account() now accepts pending_orders and counts them
    toward effective capacity to prevent over-ordering.
    """

    def test_no_pending_orders_normal_capacity(self):
        """Without pending orders, capacity is based on open positions only."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GBPUSD"),
            ]
        )
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=[])
        assert verdict.r4_open_count == 2
        assert verdict.pending_order_count == 0
        assert verdict.allow_new_entries is True
        assert "2/5" in verdict.reason

    def test_pending_orders_reduce_capacity(self):
        """Pending orders reduce effective capacity slots."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GBPUSD"),
            ]
        )
        pending = [
            {"ticket": 100, "symbol": "BTCUSD", "magic": R4_MAGIC, "volume": 0.01},
            {"ticket": 101, "symbol": "AUDUSD", "magic": R4_MAGIC, "volume": 0.1},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        assert verdict.r4_open_count == 2
        assert verdict.pending_order_count == 2
        # effective = 2 open + 2 pending = 4 < 5 → still allows entries
        assert verdict.allow_new_entries is True
        assert "+ 2 pending" in verdict.reason

    def test_pending_orders_can_block_entries(self):
        """Pending orders can push effective count to limit, blocking new entries."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GBPUSD"),
                _make_position(ticket=3, symbol="BTCUSD"),
            ]
        )
        pending = [
            {"ticket": 100, "symbol": "AUDUSD", "magic": R4_MAGIC, "volume": 0.1},
            {"ticket": 101, "symbol": "USDCAD", "magic": R4_MAGIC, "volume": 0.1},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        # effective = 3 open + 2 pending = 5 = limit → no new entries
        assert verdict.allow_new_entries is False
        assert verdict.pending_order_count == 2

    def test_pending_orders_can_cause_overflow(self):
        """Pending orders can push effective count above limit."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="GBPUSD"),
                _make_position(ticket=3, symbol="BTCUSD"),
            ]
        )
        pending = [
            {"ticket": 100, "symbol": "AUDUSD", "magic": R4_MAGIC, "volume": 0.1},
            {"ticket": 101, "symbol": "USDCAD", "magic": R4_MAGIC, "volume": 0.1},
            {"ticket": 102, "symbol": "GBPUSD", "magic": R4_MAGIC, "volume": 0.1},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        # effective = 3 + 3 = 6 > 5 → BREACHED
        assert verdict.allow_new_entries is False
        assert "BREACHED" in verdict.reason

    def test_foreign_pending_ignored_for_capacity(self):
        """Foreign pending orders (wrong magic) don't count toward capacity."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
            ]
        )
        pending = [
            {"ticket": 100, "symbol": "USDJPY", "magic": 999, "volume": 0.1},  # foreign
            {"ticket": 101, "symbol": "GBPUSD", "magic": R4_MAGIC, "volume": 0.1},  # R4
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        assert verdict.r4_open_count == 1
        assert verdict.pending_order_count == 1  # only the R4 pending

    def test_contaminated_overrides_pending(self):
        """Foreign positions still quarantine even with pending orders."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
                _make_position(ticket=2, symbol="USDJPY", magic=999),
            ]
        )
        pending = [
            {"ticket": 100, "symbol": "GBPUSD", "magic": R4_MAGIC, "volume": 0.1},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        assert verdict.contaminated is True
        assert verdict.allow_new_entries is False

    def test_no_pending_param_backward_compatible(self):
        """Omitting pending_orders defaults to None → 0 pending."""
        classified = classify_all(
            [
                _make_position(ticket=1, symbol="EURUSD"),
            ]
        )
        verdict = capacity_account(classified, max_concurrent=5)
        assert verdict.pending_order_count == 0
        assert verdict.allow_new_entries is True

    def test_all_pending_no_open(self):
        """All positions pending, none open → capacity based on pending only."""
        classified = classify_all([])
        pending = [
            {"ticket": 100, "symbol": "EURUSD", "magic": R4_MAGIC, "volume": 0.1},
            {"ticket": 101, "symbol": "GBPUSD", "magic": R4_MAGIC, "volume": 0.1},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        assert verdict.r4_open_count == 0
        assert verdict.pending_order_count == 2
        assert verdict.allow_new_entries is True  # 0 + 2 = 2 < 5

    def test_capacity_exact_limit_with_pending(self):
        """Effective count exactly at limit → no new entries."""
        classified = classify_all([_make_position(ticket=i, symbol=f"SYM{i}") for i in range(4)])
        pending = [
            {"ticket": 100, "symbol": "BTCUSD", "magic": R4_MAGIC, "volume": 0.01},
        ]
        verdict = capacity_account(classified, max_concurrent=5, pending_orders=pending)
        # 4 open + 1 pending = 5 = limit
        assert verdict.allow_new_entries is False
        assert verdict.pending_order_count == 1
