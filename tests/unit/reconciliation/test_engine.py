"""Unit tests for ReconciliationEngine (H-7).

Covers:
- Matched broker/internal state -> RECONCILED
- Price-only P&L drift beyond tolerance -> WARNING
- Swap/commission-inclusive P&L reconciliation (H-4)
- Missing / extra positions -> BLOCKING
- Disconnected (zeroed) broker feed -> BLOCKING

Regression H-4: a position with zero price change but accrued swap/commission
must NOT register as P&L drift.
"""

from __future__ import annotations

import pytest

from eigencapital.reconciliation.engine import (
    BrokerState,
    InternalState,
    ReconciliationEngine,
)

R4_MAGIC = 20260825
TIMESTAMP = "2026-09-28T00:00:00+00:00"


def _position(
    ticket: int = 1,
    symbol: str = "EURUSD",
    volume: float = 0.1,
    ptype: int = 0,
    magic: int = R4_MAGIC,
    profit: float | None = 0.0,
    swap: float | None = None,
    commission: float | None = None,
) -> dict:
    pos = {
        "ticket": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": ptype,
        "magic": magic,
        "comment": "R4",
        "profit": profit,
    }
    if swap is not None:
        pos["swap"] = swap
    if commission is not None:
        pos["commission"] = commission
    return pos


def _internal_position(
    ticket: int = 1,
    symbol: str = "EURUSD",
    volume: float = 0.1,
    side: str = "buy",
    magic: int = R4_MAGIC,
) -> dict:
    return {
        "ticket": ticket,
        "symbol": symbol,
        "volume": volume,
        "side": side,
        "magic": magic,
    }


def _broker(
    positions: list[dict] | None = None,
    equity: float = 5000.0,
    balance: float = 5000.0,
    free_margin: float = 3000.0,
    orders: list[dict] | None = None,
) -> BrokerState:
    return BrokerState(
        positions=positions if positions is not None else [],
        account_equity=equity,
        account_balance=balance,
        account_free_margin=free_margin,
        orders=orders if orders is not None else [],
        timestamp=TIMESTAMP,
    )


def _internal(
    positions: dict | None = None,
    last_signal: dict | None = None,
) -> InternalState:
    return InternalState(
        positions=positions if positions is not None else {},
        pending_orders=[],
        last_signal=last_signal if last_signal is not None else {"weights": {"EURUSD": 0.1}},
        target_weights={"EURUSD": 0.1},
        timestamp=TIMESTAMP,
    )


def _engine() -> ReconciliationEngine:
    return ReconciliationEngine(r4_magic=R4_MAGIC)


def _check(result, check_name: str):
    return next(c for c in result.checks if c.check_name == check_name)


class TestMatchedState:
    def test_identical_state_reconciles(self):
        result = _engine().reconcile(
            _broker(positions=[_position(profit=42.0)], equity=5042.0),
            _internal(positions={1: _internal_position()}),
        )
        assert result.status == "RECONCILED"
        assert result.action_required == "NONE"
        assert result.mismatches == []
        assert all(c.status == "PASS" for c in result.checks)

    def test_serialization_round_trips(self):
        result = _engine().reconcile(_broker(), _internal())
        payload = result.to_dict()
        assert payload["status"] == "RECONCILED"
        assert isinstance(payload["checks"], list)
        assert payload["broker_state_hash"]


class TestPriceOnlyDrift:
    def test_price_only_drift_warns(self):
        """Equity off from balance + unrealized beyond $10 -> WARNING."""
        result = _engine().reconcile(
            _broker(positions=[_position(profit=100.0)], equity=5150.0),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "WARNING"
        assert check.details["discrepancy"] == pytest.approx(50.0, abs=0.01)
        assert result.status == "WARNING"
        assert result.action_required == "REVIEW"

    def test_small_drift_within_tolerance_passes(self):
        result = _engine().reconcile(
            _broker(positions=[_position(profit=100.0)], equity=5105.0),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["discrepancy"] == pytest.approx(5.0, abs=0.01)


class TestSwapCommissionInclusivePnl:
    def test_equity_includes_swap_and_commission(self):
        """equity = balance + profit + swap + commission -> PASS."""
        result = _engine().reconcile(
            _broker(
                positions=[_position(profit=100.0, swap=-12.5, commission=-5.0)],
                equity=5082.5,
            ),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["broker_swap"] == pytest.approx(-12.5)
        assert check.details["broker_commission"] == pytest.approx(-5.0)
        assert result.status == "RECONCILED"

    def test_swap_and_commission_reported_on_warning(self):
        result = _engine().reconcile(
            _broker(
                positions=[_position(profit=100.0, swap=-12.5, commission=-5.0)],
                equity=5200.0,
            ),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "WARNING"
        assert check.details["broker_swap"] == pytest.approx(-12.5)
        assert check.details["broker_commission"] == pytest.approx(-5.0)
        assert check.details["expected_equity"] == pytest.approx(5082.5)

    def test_none_feed_values_treated_as_zero(self):
        """Broker feed may report None for profit/swap/commission."""
        pos = _position(profit=None)
        pos["swap"] = None
        pos["commission"] = None
        result = _engine().reconcile(
            _broker(positions=[pos], equity=5000.0),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["broker_swap"] == pytest.approx(0.0)


class TestH4Regression:
    def test_zero_price_change_with_swap_is_not_drift(self):
        """H-4: accrued swap with flat price must not register as drift."""
        result = _engine().reconcile(
            _broker(
                positions=[_position(profit=0.0, swap=-25.0, commission=-7.5)],
                equity=4967.5,
            ),
            _internal(positions={1: _internal_position()}),
        )
        check = _check(result, "pnl_discrepancy")
        assert check.status == "PASS"
        assert check.details["discrepancy"] == pytest.approx(0.0, abs=0.01)
        assert check.details["broker_swap"] == pytest.approx(-25.0)
        assert check.details["broker_commission"] == pytest.approx(-7.5)
        assert result.status == "RECONCILED"

    def test_swap_only_position_is_not_drift(self):
        result = _engine().reconcile(
            _broker(
                positions=[_position(profit=0.0, swap=-33.0)],
                equity=4967.0,
            ),
            _internal(positions={1: _internal_position()}),
        )
        assert _check(result, "pnl_discrepancy").status == "PASS"
        assert result.status == "RECONCILED"


class TestMissingAndExtraPositions:
    def test_missing_broker_position_blocks(self):
        result = _engine().reconcile(
            _broker(positions=[], equity=5000.0),
            _internal(positions={1: _internal_position()}),
        )
        assert _check(result, "position_count").status == "CRITICAL"
        assert _check(result, "position_1_exists").status == "BLOCKING"
        assert result.status == "BLOCKING"
        assert result.action_required == "HALT"

    def test_extra_broker_position_blocks(self):
        result = _engine().reconcile(
            _broker(positions=[_position(ticket=7)], equity=5000.0),
            _internal(positions={}),
        )
        assert _check(result, "position_count").status == "CRITICAL"
        assert _check(result, "position_7_unexpected").status == "BLOCKING"
        assert result.status == "BLOCKING"
        assert result.action_required == "HALT"

    def test_quantity_mismatch_halts(self):
        result = _engine().reconcile(
            _broker(positions=[_position(volume=0.2)], equity=5000.0),
            _internal(positions={1: _internal_position(volume=0.1)}),
        )
        assert _check(result, "position_1_quantity").status == "CRITICAL"
        assert result.action_required == "HALT"

    def test_side_mismatch_halts(self):
        result = _engine().reconcile(
            _broker(positions=[_position(ptype=1)], equity=5000.0),
            _internal(positions={1: _internal_position(side="buy")}),
        )
        assert _check(result, "position_1_side").status == "CRITICAL"
        assert result.action_required == "HALT"


class TestDisconnectedBroker:
    def test_zeroed_feed_blocks_trading(self):
        """A dead/disconnected feed reports zeroed equity -> BLOCKING/HALT."""
        result = _engine().reconcile(
            _broker(positions=[], equity=0.0, balance=0.0, free_margin=0.0),
            _internal(positions={}, last_signal={}),
        )
        check = _check(result, "account_equity")
        assert check.status == "BLOCKING"
        assert check.action == "HALT"
        assert result.status == "BLOCKING"
        assert result.action_required == "HALT"

    def test_negative_free_margin_halts(self):
        result = _engine().reconcile(
            _broker(positions=[], equity=5000.0, free_margin=-100.0),
            _internal(positions={}, last_signal={}),
        )
        assert _check(result, "account_free_margin").status == "CRITICAL"
        assert result.action_required == "HALT"
