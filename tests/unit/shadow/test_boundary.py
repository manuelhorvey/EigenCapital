"""Adversarial tests for Phase 1N Shadow Trading & Live Boundary.

Tests cover:
- BrokerAdapter interface
- ShadowBrokerAdapter behavior
- LiveAuthorization validation
- ExecutionBoundary enforcement
- KillSwitch activation/deactivation
- MarketDataSafety checks
- Edge cases: unauthorized live, kill switch, stale data
"""

import pytest

from eigencapital.shadow.contracts import (
    ExecutionMode,
    BrokerOrder,
    BrokerFill,
    BrokerAdapter,
    ShadowBrokerAdapter,
    LiveAuthorization,
    ExecutionBoundary,
    OrderResult,
)
from eigencapital.shadow.safety import (
    KillSwitch,
    KillSwitchStatus,
    MarketDataSafety,
    DataSafetyStatus,
)


# ═══════════════════════════════════════════════
#  BROKER ADAPTER
# ═══════════════════════════════════════════════

class TestBrokerOrder:
    def test_basic_creation(self):
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            limit_price=5000.0,
        )
        assert order.order_id == "ORD-001"
        assert order.side == "BUY"

    def test_serialization(self):
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        d = order.to_dict()
        assert d["order_id"] == "ORD-001"
        assert d["side"] == "BUY"


class TestShadowBrokerAdapter:
    def test_submit_order(self):
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = broker.submit_order(order)
        assert result == OrderResult.ACCEPTED
        assert "recorded" in msg

    def test_recorded_orders(self):
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        broker.submit_order(order)
        orders = broker.get_recorded_orders()
        assert len(orders) == 1
        assert orders[0].order_id == "ORD-001"

    def test_cancel_order(self):
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        broker.submit_order(order)
        result = broker.cancel_order("ORD-001")
        assert result is True

    def test_health_check(self):
        broker = ShadowBrokerAdapter()
        assert broker.health_check() is True

    def test_positions_empty(self):
        broker = ShadowBrokerAdapter()
        assert broker.get_positions() == {}

    def test_account_state(self):
        broker = ShadowBrokerAdapter()
        state = broker.get_account_state()
        assert state["mode"] == "shadow"
        assert state["orders_recorded"] == 0


# ═══════════════════════════════════════════════
#  LIVE AUTHORIZATION
# ═══════════════════════════════════════════════

class TestLiveAuthorization:
    def test_default_disabled(self):
        auth = LiveAuthorization()
        assert auth.live_enabled is False
        assert not auth.is_valid()

    def test_valid_when_enabled(self):
        auth = LiveAuthorization(
            live_enabled=True,
            authorization_token="token123",
            config_fingerprint="abc",
        )
        assert auth.is_valid()

    def test_invalid_without_token(self):
        auth = LiveAuthorization(
            live_enabled=True,
            config_fingerprint="abc",
        )
        assert not auth.is_valid()

    def test_invalid_without_config(self):
        auth = LiveAuthorization(
            live_enabled=True,
            authorization_token="token123",
        )
        assert not auth.is_valid()

    def test_fingerprint_deterministic(self):
        auth = LiveAuthorization(
            live_enabled=True,
            authorization_token="token123",
            config_fingerprint="abc",
        )
        h1 = auth.compute_fingerprint()
        h2 = auth.compute_fingerprint()
        assert h1 == h2
        assert len(h1) == 64

    def test_serialization(self):
        auth = LiveAuthorization(
            live_enabled=True,
            authorization_token="token",
            approver="admin",
        )
        d = auth.to_dict()
        assert d["live_enabled"] is True
        assert d["approver"] == "admin"


# ═══════════════════════════════════════════════
#  EXECUTION BOUNDARY
# ═══════════════════════════════════════════════

class TestExecutionBoundary:
    def test_paper_mode_allows(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.PAPER)
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.ACCEPTED

    def test_shadow_mode_allows(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.SHADOW)
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.ACCEPTED

    def test_live_mode_blocked(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.LIVE)
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.UNAUTHORIZED

    def test_live_mode_blocked_even_with_valid_auth(self):
        auth = LiveAuthorization(
            live_enabled=True,
            authorization_token="token123",
            config_fingerprint="abc",
        )
        boundary = ExecutionBoundary(mode=ExecutionMode.LIVE, authorization=auth)
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.UNAUTHORIZED
        assert "Phase 1N" in msg

    def test_kill_switch_blocks(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.PAPER)
        boundary.kill_switch_active = True
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.KILL_SWITCH_ACTIVE

    def test_risk_boundary_blocks(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.PAPER)
        boundary.risk_boundary_healthy = False
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.REJECTED
        assert "Risk" in msg

    def test_stale_data_blocks(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.PAPER)
        boundary.market_data_fresh = False
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.REJECTED
        assert "stale" in msg.lower()

    def test_broker_unavailable_blocks(self):
        boundary = ExecutionBoundary(mode=ExecutionMode.PAPER)
        boundary.broker_healthy = False
        broker = ShadowBrokerAdapter()
        order = BrokerOrder(
            order_id="ORD-001",
            instrument_id="ES",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        result, msg = boundary.authorize_order(order, broker)
        assert result == OrderResult.BROKER_UNAVAILABLE


# ═══════════════════════════════════════════════
#  KILL SWITCH
# ═══════════════════════════════════════════════

class TestKillSwitch:
    def test_default_inactive(self):
        ks = KillSwitch()
        assert not ks.is_active
        assert ks.status == KillSwitchStatus.INACTIVE

    def test_activate(self):
        ks = KillSwitch()
        result = ks.activate("Emergency stop", "2025-01-15T10:00:00Z")
        assert result is True
        assert ks.is_active
        assert ks.activation_count == 1

    def test_deactivate(self):
        ks = KillSwitch()
        ks.activate("test")
        result = ks.deactivate("Issue resolved")
        assert result is True
        assert not ks.is_active

    def test_deactivate_when_inactive(self):
        ks = KillSwitch()
        result = ks.deactivate()
        assert result is False

    def test_activation_count(self):
        ks = KillSwitch()
        ks.activate("reason1")
        ks.deactivate()
        ks.activate("reason2")
        assert ks.activation_count == 2

    def test_serialization(self):
        ks = KillSwitch()
        ks.activate("test reason", "2025-01-15T10:00:00Z")
        d = ks.to_dict()
        assert d["status"] == "active"
        assert d["activation_reason"] == "test reason"


# ═══════════════════════════════════════════════
#  MARKET DATA SAFETY
# ═══════════════════════════════════════════════

class TestMarketDataSafety:
    def test_fresh_data(self):
        safety = MarketDataSafety()
        check = safety.check("ES", "2025-01-15T10:00:00Z", "2025-01-15T10:00:01Z")
        assert check.is_safe

    def test_missing_data(self):
        safety = MarketDataSafety()
        check = safety.check("ES", "", "2025-01-15T10:00:00Z")
        assert not check.is_safe
        assert check.status == DataSafetyStatus.MISSING

    def test_all_instruments_safe(self):
        safety = MarketDataSafety()
        safety.check("ES", "2025-01-15T10:00:00Z", "2025-01-15T10:00:01Z")
        safety.check("NQ", "2025-01-15T10:00:00Z", "2025-01-15T10:00:01Z")
        assert safety.all_instruments_safe()

    def test_not_all_safe(self):
        safety = MarketDataSafety()
        safety.check("ES", "2025-01-15T10:00:00Z", "2025-01-15T10:00:01Z")
        safety.check("NQ", "", "2025-01-15T10:00:00Z")
        assert not safety.all_instruments_safe()

    def test_serialization(self):
        safety = MarketDataSafety()
        check = safety.check("ES", "2025-01-15T10:00:00Z", "2025-01-15T10:00:01Z")
        d = check.to_dict()
        assert d["status"] == "fresh"
        assert d["instrument_id"] == "ES"


# ═══════════════════════════════════════════════
#  ADVERSARIAL — PROPERTIES
# ═══════════════════════════════════════════════

class TestProperties:
    def test_live_always_blocked_in_1n(self):
        """Live execution must always be blocked in Phase 1N."""
        for token in ["", "valid_token"]:
            for config in ["", "valid_config"]:
                auth = LiveAuthorization(
                    live_enabled=True,
                    authorization_token=token,
                    config_fingerprint=config,
                )
                boundary = ExecutionBoundary(mode=ExecutionMode.LIVE, authorization=auth)
                broker = ShadowBrokerAdapter()
                order = BrokerOrder(
                    order_id="ORD-001",
                    instrument_id="ES",
                    side="BUY",
                    quantity=10,
                    order_type="MARKET",
                )
                result, msg = boundary.authorize_order(order, broker)
                assert result == OrderResult.UNAUTHORIZED

    def test_kill_switch_prevents_all_orders(self):
        """Kill switch must prevent all orders regardless of mode."""
        for mode in [ExecutionMode.PAPER, ExecutionMode.SHADOW]:
            boundary = ExecutionBoundary(mode=mode)
            boundary.kill_switch_active = True
            broker = ShadowBrokerAdapter()
            order = BrokerOrder(
                order_id="ORD-001",
                instrument_id="ES",
                side="BUY",
                quantity=10,
                order_type="MARKET",
            )
            result, _ = boundary.authorize_order(order, broker)
            assert result == OrderResult.KILL_SWITCH_ACTIVE

    def test_shadow_records_hypothetical_orders(self):
        """Shadow mode should record what would have been submitted."""
        boundary = ExecutionBoundary(mode=ExecutionMode.SHADOW)
        broker = ShadowBrokerAdapter()
        for i in range(5):
            order = BrokerOrder(
                order_id=f"ORD-{i:03d}",
                instrument_id="ES",
                side="BUY",
                quantity=i + 1,
                order_type="MARKET",
            )
            boundary.authorize_order(order, broker)

        assert len(broker.get_recorded_orders()) == 5
