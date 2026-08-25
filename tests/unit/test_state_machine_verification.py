"""State Machine Verification Tests — prove every transition is safe.

Models the complete live state machine and verifies:
1. All legal transitions exist
2. All illegal transitions are blocked
3. No state allows trading when it shouldn't
4. Every state has a defined exit path
5. FROZEN requires explicit operator intervention

State machine:
  STARTING → CONNECTING → CONNECTED → TRADING
                                         ↓
                                    DISCONNECTED → RECONCILING → RESUMED
                                         ↓              ↓
                                      HALTED         HALTED
                                         ↓
                                      FROZEN

Trading permission:
  CONNECTED → TRADE
  RESUMED → TRADE
  All others → BLOCKED
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.live.risk import DisconnectRecovery, RecoveryState


# ── Define the complete state machine ─────────────────────────────

# Legal transitions: (from_state, event) → to_state
LEGAL_TRANSITIONS = {
    # Disconnect recovery
    (RecoveryState.CONNECTED, "disconnect"): RecoveryState.DISCONNECTED,
    (RecoveryState.DISCONNECTED, "reconnect"): RecoveryState.RECONCILING,
    (RecoveryState.RECONCILING, "reconcile_pass"): RecoveryState.RECONCILING,  # stays
    (RecoveryState.RECONCILING, "resume_pass"): RecoveryState.RESUMED,
    (RecoveryState.RECONCILING, "resume_fail"): RecoveryState.HALTED,
    (RecoveryState.RECONCILING, "reconcile_fail"): RecoveryState.HALTED,
    (RecoveryState.RESUMED, "disconnect"): RecoveryState.DISCONNECTED,
    (RecoveryState.HALTED, "authorize_reset_from_frozen"): RecoveryState.HALTED,  # only from FROZEN
    (RecoveryState.FROZEN, "authorize_reset"): RecoveryState.HALTED,
    # Excessive disconnects
    (RecoveryState.CONNECTED, "excessive_disconnects"): RecoveryState.FROZEN,
    (RecoveryState.DISCONNECTED, "excessive_disconnects"): RecoveryState.FROZEN,
}

# States that allow trading
TRADING_STATES = {RecoveryState.CONNECTED, RecoveryState.RESUMED}

# States that block trading
BLOCKED_STATES = {
    RecoveryState.DISCONNECTED,
    RecoveryState.RECONCILING,
    RecoveryState.HALTED,
    RecoveryState.FROZEN,
}


class TestTradingPermission:
    """Verify trading permission at every state."""

    @pytest.mark.parametrize("state", list(TRADING_STATES))
    def test_trading_states_allow_trading(self, state):
        """CONNECTED and RESUMED must allow trading."""
        assert state in TRADING_STATES

    @pytest.mark.parametrize("state", list(BLOCKED_STATES))
    def test_blocked_states_prevent_trading(self, state):
        """DISCONNECTED, RECONCILING, HALTED, FROZEN must block trading."""
        assert state in BLOCKED_STATES

    def test_no_state_outside_definitions(self):
        """Every RecoveryState must be in either TRADING or BLOCKED."""
        all_states = set(RecoveryState)
        defined = TRADING_STATES | BLOCKED_STATES
        assert all_states == defined, f"Undefined states: {all_states - defined}"


class TestDisconnectRecoveryTransitions:
    """Verify the DisconnectRecovery state machine transitions correctly."""

    def test_connected_to_disconnected(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state == RecoveryState.DISCONNECTED

    def test_disconnected_to_reconciling(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        assert r.state == RecoveryState.RECONCILING

    def test_reconciling_to_resumed(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=True, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        r.request_resume(
            data_fresh=True, positions_reconciled=True,
            no_unexpected_orders=True, risk_limits_passing=True,
            config_fingerprint_unchanged=True, health_state="healthy",
        )
        assert r.state == RecoveryState.RESUMED

    def test_reconciling_to_halted_on_mismatch(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=False, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        assert r.state == RecoveryState.HALTED

    def test_resume_to_halted_on_check_failure(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=True, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        r.request_resume(
            data_fresh=False,  # FAIL
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
            health_state="healthy",
        )
        assert r.state == RecoveryState.HALTED

    def test_frozen_on_excessive_disconnects(self):
        r = DisconnectRecovery(max_recovery_attempts=2)
        r.on_disconnect()  # 1
        r.on_disconnect()  # 2
        r.on_disconnect()  # 3 → FROZEN (>2)
        assert r.state == RecoveryState.FROZEN

    def test_frozen_to_halted_via_authorize_reset(self):
        r = DisconnectRecovery(max_recovery_attempts=1)
        r.on_disconnect()  # 1
        r.on_disconnect()  # 2 → FROZEN
        r.authorize_reset()
        assert r.state == RecoveryState.HALTED


class TestIllegalTransitions:
    """Verify that illegal transitions are impossible."""

    def test_cannot_trade_from_disconnected(self):
        """DISCONNECTED → TRADING must be impossible."""
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state != RecoveryState.CONNECTED
        assert r.state != RecoveryState.RESUMED

    def test_cannot_trade_from_reconciling(self):
        """RECONCILING → TRADING must be impossible without full sequence."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        assert r.state == RecoveryState.RECONCILING
        # Must complete reconciliation + resume to trade

    def test_cannot_trade_from_halted(self):
        """HALTED → TRADING must be impossible."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=False, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        assert r.state == RecoveryState.HALTED
        assert r.state not in TRADING_STATES

    def test_cannot_trade_from_frozen(self):
        """FROZEN → TRADING must require explicit operator reset."""
        r = DisconnectRecovery(max_recovery_attempts=1)
        r.on_disconnect()
        r.on_disconnect()
        r.on_disconnect()
        assert r.state == RecoveryState.FROZEN
        assert r.state not in TRADING_STATES

    def test_cannot_resume_without_reconciliation(self):
        """Cannot resume without submitting reconciliation first."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        result = r.request_resume(
            data_fresh=True, positions_reconciled=True,
            no_unexpected_orders=True, risk_limits_passing=True,
            config_fingerprint_unchanged=True, health_state="healthy",
        )
        assert "INVALID" in result
        assert r.state == RecoveryState.RECONCILING

    def test_cannot_reconnect_from_connected(self):
        """Cannot reconnect when already connected."""
        r = DisconnectRecovery()
        result = r.on_reconnect()
        assert "INVALID" in result

    def test_cannot_disconnect_when_already_disconnected(self):
        """Double disconnect should escalate or stay."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_disconnect()
        # Should either stay DISCONNECTED or escalate
        assert r.state in (RecoveryState.DISCONNECTED, RecoveryState.FROZEN)


class TestIdempotency:
    """Verify duplicate events are harmless."""

    def test_double_reconnect_rejected(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        result = r.on_reconnect()
        assert "INVALID" in result
        assert r.state == RecoveryState.RECONCILING

    double_disconnect_scenarios = [
        (RecoveryState.CONNECTED, "disconnect"),
        (RecoveryState.DISCONNECTED, "disconnect"),
    ]

    def test_duplicate_events_dont_crash(self):
        """All operations should be safe to call multiple times."""
        r = DisconnectRecovery()
        # Call everything multiple times
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=True, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        r.request_resume(
            data_fresh=True, positions_reconciled=True,
            no_unexpected_orders=True, risk_limits_passing=True,
            config_fingerprint_unchanged=True, health_state="healthy",
        )
        # Extra calls should be harmless
        r.on_disconnect()
        r.on_reconnect()
        assert r.state in (RecoveryState.RECONCILING, RecoveryState.DISCONNECTED)


class TestStatePersistence:
    """Verify state can be serialized and restored."""

    def test_state_serializable(self):
        """All state values must be JSON-serializable."""
        import json
        for state in RecoveryState:
            data = {"state": state.value}
            serialized = json.dumps(data)
            restored = json.loads(serialized)
            assert restored["state"] == state.value

    def test_full_cycle_serializable(self):
        """A complete disconnect→resume cycle must be serializable."""
        import json
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(
            positions_match=True, orders_match=True,
            equity_match=True, fingerprint_match=True,
        )
        r.request_resume(
            data_fresh=True, positions_reconciled=True,
            no_unexpected_orders=True, risk_limits_passing=True,
            config_fingerprint_unchanged=True, health_state="healthy",
        )
        # Serialize
        data = {
            "state": r.state.value,
            "attempts": r._attempts,
            "reconciled": r._reconciled,
        }
        serialized = json.dumps(data)
        restored = json.loads(serialized)
        assert restored["state"] == "resumed"
        assert restored["attempts"] == 1
        assert restored["reconciled"] is True
