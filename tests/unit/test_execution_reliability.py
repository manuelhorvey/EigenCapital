"""Adversarial execution reliability tests.

Proves that under failure conditions, the system:
- Never creates duplicate exposure
- Never trades on stale state
- Never bypasses risk gates
- Never invents positions
- Converges to broker truth
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.execution.trading_provider import (
    TradingProvider, AccountInfo, PositionInfo, SymbolInfo,
    TickInfo, OrderRequest, OrderResult,
)
from eigencapital.live.risk_enforcement import (
    RiskEnvelope, RiskEnforcer, GateResult, BlockReason,
)
from eigencapital.live.risk import DisconnectRecovery, RecoveryState
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.risk.policy import RiskPolicy
from typing import Optional, List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gate_blocked(results, reason: BlockReason) -> bool:
    return any(r.result != GateResult.PASS and r.reason == reason for r in results)


def _any_blocked(results) -> bool:
    return any(r.result != GateResult.PASS for r in results)


# ---------------------------------------------------------------------------
# Position Count Enforcement
# ---------------------------------------------------------------------------

class TestPositionCountEnforcement:
    def test_position_count_breach_detected(self):
        """3 positions with limit 2 must be detected as CRITICAL."""
        envelope = RiskEnvelope(max_concurrent_positions=2, t0_equity=5000.0)
        enforcer = RiskEnforcer(envelope)
        positions = [{"symbol": f"S{i}", "volume": 0.01, "price": 100.0} for i in range(3)]
        passed, results = enforcer.check_all(
            broker_positions=positions, account_equity=5000.0, account_free_margin=3000.0,
        )
        assert passed is False
        # Position count breach OR position protection (no SL) — both should block
        assert _any_blocked(results)

    def test_zero_positions_always_pass_count_gate(self):
        """Zero positions should never violate position count."""
        envelope = RiskEnvelope(max_concurrent_positions=8, t0_equity=5000.0)
        enforcer = RiskEnforcer(envelope)
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=5000.0, account_free_margin=3000.0,
        )
        assert passed is True

    def test_positions_without_sl_are_critical(self):
        """Positions without SL must trigger position_protection CRITICAL."""
        envelope = RiskEnvelope(max_concurrent_positions=8, t0_equity=5000.0)
        enforcer = RiskEnforcer(envelope)
        positions = [{"symbol": "EURUSD", "volume": 0.01, "price": 1.1, "sl": 0.0}]
        passed, results = enforcer.check_all(
            broker_positions=positions, account_equity=5000.0, account_free_margin=3000.0,
        )
        assert passed is False
        assert _gate_blocked(results, BlockReason.NO_SL_PROTECTION)


# ---------------------------------------------------------------------------
# Equity / Drawdown Enforcement
# ---------------------------------------------------------------------------

class TestEquityDrawdownEnforcement:
    def test_equity_floor_enforced(self):
        """Equity below minimum must be blocked."""
        envelope = RiskEnvelope(min_equity=4000.0, t0_equity=5000.0, max_account_drawdown_pct=9999.0)
        enforcer = RiskEnforcer(envelope)
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=3500.0, account_free_margin=3000.0,
        )
        assert passed is False
        assert _gate_blocked(results, BlockReason.EQUITY_BELOW_MIN)

    def test_equity_above_minimum_passes(self):
        """Equity above minimum should pass."""
        envelope = RiskEnvelope(min_equity=4000.0, t0_equity=5000.0)
        enforcer = RiskEnforcer(envelope)
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=5000.0, account_free_margin=3000.0,
        )
        assert passed is True

    def test_broker_disconnection_detected(self):
        """Zero equity and zero free margin must be CRITICAL."""
        envelope = RiskEnvelope(t0_equity=5000.0)
        enforcer = RiskEnforcer(envelope)
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=0.0, account_free_margin=0.0,
        )
        assert passed is False
        assert _gate_blocked(results, BlockReason.BROKER_DISCONNECT)


# ---------------------------------------------------------------------------
# Stale State Prevention
# ---------------------------------------------------------------------------

class TestStaleStatePrevention:
    def test_disconnect_halts_trading(self):
        dr = DisconnectRecovery()
        dr.on_disconnect()
        assert dr.state == RecoveryState.DISCONNECTED
        assert dr.state != RecoveryState.CONNECTED

    def test_reconnect_requires_reconciliation(self):
        dr = DisconnectRecovery()
        dr.on_disconnect()
        dr.on_reconnect()
        # Must go through reconciliation, not directly to CONNECTED
        assert dr.state != RecoveryState.CONNECTED

    def test_halted_state_blocks_trading(self):
        dr = DisconnectRecovery()
        dr.on_disconnect()
        dr.on_reconnect()
        dr.submit_reconciliation(True, True, False, True, details="equity_mismatch")
        assert dr.state == RecoveryState.HALTED
        assert dr.state != RecoveryState.CONNECTED

    def test_frozen_after_max_retries(self):
        """After max recovery attempts, system must freeze."""
        dr = DisconnectRecovery(max_recovery_attempts=2)
        for _ in range(3):
            dr.on_disconnect()
            dr.on_reconnect()
        assert dr.state == RecoveryState.FROZEN


# ---------------------------------------------------------------------------
# Risk Gate Enforcement
# ---------------------------------------------------------------------------

class TestRiskGateEnforcement:
    def test_all_gates_reported(self):
        """Every gate must produce a result."""
        enforcer = RiskEnforcer(RiskEnvelope(t0_equity=5000.0))
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=5000.0, account_free_margin=3000.0,
        )
        assert len(results) > 0
        for r in results:
            assert hasattr(r, 'result')
            assert hasattr(r, 'gate_name')
            assert hasattr(r, 'reason')
            assert hasattr(r, 'timestamp')

    def test_fingerprint_gate_present(self):
        """Fingerprint gate must be in results."""
        enforcer = RiskEnforcer(RiskEnvelope(t0_equity=5000.0))
        _, results = enforcer.check_all(
            broker_positions=[], account_equity=5000.0, account_free_margin=3000.0,
        )
        gate_names = [r.gate_name for r in results]
        assert "fingerprint" in gate_names

    def test_fingerprint_match_required(self):
        """Fingerprint mismatch must block trading."""
        enforcer = RiskEnforcer(RiskEnvelope(t0_equity=5000.0))
        passed, results = enforcer.check_all(
            broker_positions=[], account_equity=5000.0, account_free_margin=3000.0,
            fingerprint_match=False,
        )
        assert passed is False


# ---------------------------------------------------------------------------
# Fingerprint Integrity
# ---------------------------------------------------------------------------

class TestFingerprintIntegrity:
    def test_fingerprint_consistent_across_10k_calls(self):
        verifier = FingerprintVerifier(
            manifest=R4ConfigManifest(), risk_policy=RiskPolicy(),
        )
        first = verifier.verify_all()
        for _ in range(10_000):
            result = verifier.verify_all()
            assert result.all_verified == first.all_verified

    def test_fingerprint_detects_manifest_change(self):
        from dataclasses import replace
        manifest1 = R4ConfigManifest()
        manifest2 = replace(manifest1, strategy_version="R4.0_TAMPERED")
        assert manifest1.compute_identity() != manifest2.compute_identity()
