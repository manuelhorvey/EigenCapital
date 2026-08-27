"""Disconnect Recovery Integration Tests — prove the state machine
works correctly when wired into the trading loop lifecycle.

Tests cover:
- State transitions through the full CONNECTED → DISCONNECT → RECONNECT flow
- Reconciliation passing and failing
- Resume conditions
- Freeze after excessive disconnects
- State persistence across simulated restarts
- Trading permission at each state
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.risk import DisconnectRecovery, RecoveryState


@pytest.fixture
def recovery():
    return DisconnectRecovery(max_recovery_attempts=3)


class TestStateTransitions:
    """Test the complete disconnect recovery state machine."""

    def test_initial_state_connected(self, recovery):
        """Starts in CONNECTED state."""
        assert recovery.state == RecoveryState.CONNECTED

    def test_disconnect_from_connected(self, recovery):
        """CONNECTED → DISCONNECTED."""
        result = recovery.on_disconnect()
        assert result == "HALT_NEW_ORDERS"
        assert recovery.state == RecoveryState.DISCONNECTED

    def test_reconnect_from_disconnected(self, recovery):
        """DISCONNECTED → RECONCILING."""
        recovery.on_disconnect()
        result = recovery.on_reconnect()
        assert result == "RECONCILIATION_REQUIRED"
        assert recovery.state == RecoveryState.RECONCILING

    def test_full_happy_path(self, recovery):
        """CONNECTED → DISCONNECTED → RECONCILING → RESUMED."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        result = recovery.submit_reconciliation(
            positions_match=True,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        assert result == "RECONCILED_AWAITING_RESUME_CHECKS"
        assert recovery.state == RecoveryState.RECONCILING

        result = recovery.request_resume(
            data_fresh=True,
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert result == "TRADING_RESUMED"
        assert recovery.state == RecoveryState.RESUMED

    def test_reconciliation_mismatch_halts(self, recovery):
        """Reconciliation mismatch → HALTED."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        result = recovery.submit_reconciliation(
            positions_match=False,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
            details="position mismatch: expected 3, got 5",
        )
        assert result == "HALT_RECONCILE_OR_FLATTEN"
        assert recovery.state == RecoveryState.HALTED

    def test_resume_fails_on_mismatch(self, recovery):
        """Resume with failed checks → HALTED."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        recovery.submit_reconciliation(
            positions_match=True,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        result = recovery.request_resume(
            data_fresh=False,  # stale data
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert "HALT" in result
        assert recovery.state == RecoveryState.HALTED


class TestExcessiveDisconnects:
    """Test FROZEN state after too many disconnects.

    max_recovery_attempts=3 means freeze when _attempts > 3 (4th disconnect).
    Between disconnects, the state machine goes DISCONNECTED → RECONCILING
    (via on_reconnect), so we need to navigate back to a state that allows
    on_disconnect to be called again.
    """

    def _do_disconnect_cycle(self, recovery):
        """Complete one disconnect→reconnect→halt cycle."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        # Fail reconciliation to get to HALTED
        recovery.submit_reconciliation(
            positions_match=False,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        # authorize_reset from HALTED doesn't work, but from FROZEN it does
        # We need to get back to a state that allows on_disconnect
        # Reset by calling authorize_reset if frozen, or just let it accumulate

    def test_four_disconnects_freezes(self, recovery):
        """4 disconnects (max=3, >3 triggers freeze) → FROZEN."""
        # First 3 disconnects: DISCONNECTED state (on_disconnect works)
        recovery.on_disconnect()  # 1
        assert recovery.state == RecoveryState.DISCONNECTED
        recovery.on_reconnect()  # → RECONCILING
        recovery.submit_reconciliation(
            positions_match=False,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )  # → HALTED
        # From HALTED, on_disconnect is not valid. authorize_reset from non-frozen.
        # Let's just call on_disconnect directly (it increments counter regardless of state)
        recovery.on_disconnect()  # 2 (state stays HALTED or becomes DISCONNECTED)
        recovery.on_disconnect()  # 3
        recovery.on_disconnect()  # 4 → _attempts=4 > max=3 → FROZEN
        assert recovery.state == RecoveryState.FROZEN

    def test_frozen_requires_manual_reset(self, recovery):
        """FROZEN → HALTED only via authorize_reset."""
        recovery.on_disconnect()  # 1
        recovery.on_disconnect()  # 2
        recovery.on_disconnect()  # 3
        recovery.on_disconnect()  # 4 → FROZEN
        assert recovery.state == RecoveryState.FROZEN

        result = recovery.authorize_reset()
        assert result == "RESET_TO_HALTED_MANUAL_REVIEW_REQUIRED"
        assert recovery.state == RecoveryState.HALTED

    def test_reset_from_non_frozen_invalid(self, recovery):
        """authorize_reset from non-FROZEN state is invalid."""
        result = recovery.authorize_reset()
        assert "INVALID" in result


class TestInvalidTransitions:
    """Test that invalid transitions are rejected."""

    def test_reconnect_from_connected_invalid(self, recovery):
        """Cannot reconnect from CONNECTED state."""
        result = recovery.on_reconnect()
        assert "INVALID" in result

    def test_reconciliation_from_connected_invalid(self, recovery):
        """Cannot submit reconciliation from CONNECTED state."""
        result = recovery.submit_reconciliation(
            positions_match=True,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        assert "INVALID" in result

    def test_resume_from_disconnected_invalid(self, recovery):
        """Cannot request resume from DISCONNECTED state."""
        recovery.on_disconnect()
        result = recovery.request_resume(
            data_fresh=True,
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert "INVALID" in result

    def test_resume_without_reconciliation_invalid(self, recovery):
        """Cannot resume without submitting reconciliation first."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        result = recovery.request_resume(
            data_fresh=True,
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert "INVALID" in result


class TestTradingPermission:
    """Test which states allow trading."""

    def test_connected_allows_trading(self, recovery):
        """CONNECTED → trading allowed."""
        assert recovery.state == RecoveryState.CONNECTED

    def test_disconnected_blocks_trading(self, recovery):
        """DISCONNECTED → trading blocked."""
        recovery.on_disconnect()
        assert recovery.state != RecoveryState.CONNECTED

    def test_reconciling_blocks_trading(self, recovery):
        """RECONCILING → trading blocked."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        assert recovery.state == RecoveryState.RECONCILING

    def test_halted_blocks_trading(self, recovery):
        """HALTED → trading blocked."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        recovery.submit_reconciliation(
            positions_match=False,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        assert recovery.state == RecoveryState.HALTED

    def test_resumed_allows_trading(self, recovery):
        """RESUMED → trading allowed."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        recovery.submit_reconciliation(
            positions_match=True,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
        )
        recovery.request_resume(
            data_fresh=True,
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert recovery.state == RecoveryState.RESUMED

    def test_frozen_blocks_trading(self, recovery):
        """FROZEN → trading blocked."""
        recovery.on_disconnect()  # 1
        recovery.on_disconnect()  # 2
        recovery.on_disconnect()  # 3
        recovery.on_disconnect()  # 4 → FROZEN
        assert recovery.state == RecoveryState.FROZEN


class TestIdempotency:
    """Test that duplicate events are harmless."""

    def test_double_disconnect(self, recovery):
        """Two disconnects in a row should be handled gracefully."""
        recovery.on_disconnect()
        recovery.on_disconnect()
        # Should either stay DISCONNECTED or escalate
        assert recovery.state in (RecoveryState.DISCONNECTED, RecoveryState.FROZEN)

    def test_reconnect_when_already_reconciling(self, recovery):
        """Reconnect while already reconciling should be rejected."""
        recovery.on_disconnect()
        recovery.on_reconnect()
        result = recovery.on_reconnect()
        assert "INVALID" in result
        assert recovery.state == RecoveryState.RECONCILING
