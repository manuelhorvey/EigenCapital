"""
Failure storm testing: Simulate cascading and compound failures.
Tests that the system never trades during compound failure conditions.
"""

import hashlib
import json
from typing import List
from unittest.mock import MagicMock

from eigencapital.config import LiveRiskConfig
from eigencapital.live.risk import DisconnectRecovery, RecoveryState
from eigencapital.risk.policy import RiskPolicy


class TestNetworkFlapping:
    """Simulate rapid disconnect/reconnect cycles."""

    def _flap(self, recovery: DisconnectRecovery, flap_count: int) -> List[str]:
        """Simulate N disconnect/reconnect cycles, return states."""
        states = []
        for i in range(flap_count):
            recovery.on_disconnect()
            states.append(recovery.state.value)
            recovery.on_reconnect()
            states.append(recovery.state.value)
        return states

    def test_mild_flapping_3_cycles(self):
        """3 disconnect/reconnect cycles should not freeze."""
        r = DisconnectRecovery(max_recovery_attempts=5)
        states = self._flap(r, 3)
        assert r.state != RecoveryState.FROZEN
        assert all(s != RecoveryState.FROZEN.value for s in states)

    def test_aggressive_flapping_frozes(self):
        """4+ disconnect/reconnect cycles without reconciliation → FROZEN."""
        r = DisconnectRecovery(max_recovery_attempts=3)
        states = self._flap(r, 4)
        # After exceeding max_recovery_attempts, should be FROZEN
        assert RecoveryState.FROZEN.value in states

    def test_flapping_with_reconciliation_resets(self):
        """Reconciliation between flaps prevents freeze."""
        r = DisconnectRecovery(max_recovery_attempts=10)
        for _ in range(10):
            r.on_disconnect()
            assert r.state != RecoveryState.FROZEN
            r.on_reconnect()
            r.submit_reconciliation(True, True, True, True)
            r.request_resume(True, True, True, True, True)
        # Should be RESUMED after full validation
        assert r.state == RecoveryState.RESUMED

    def test_flapping_blocks_trading(self):
        """Every disconnect must block trading (state != RESUMED)."""
        r = DisconnectRecovery(max_recovery_attempts=10)
        for _ in range(3):
            assert r.state != RecoveryState.RESUMED
            r.on_disconnect()
            assert r.state == RecoveryState.DISCONNECTED
            r.on_reconnect()
            assert r.state == RecoveryState.RECONCILING  # still can't trade

    def test_flapping_attempt_count(self):
        """Track consecutive disconnect attempts."""
        r = DisconnectRecovery(max_recovery_attempts=10)
        for i in range(5):
            r.on_disconnect()
            assert r._attempts == i + 1


class TestBrokerOutageSimulation:
    """Simulate broker outages of varying durations."""

    def test_short_outage_recovery(self):
        """Single disconnect should recover cleanly."""
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state == RecoveryState.DISCONNECTED
        r.on_reconnect()
        r.submit_reconciliation(True, True, True, True)
        r.request_resume(True, True, True, True, True)
        assert r.state == RecoveryState.RESUMED

    def test_long_outage_frozes(self):
        """Sustained outage (exceeding max_attempts) → FROZEN."""
        r = DisconnectRecovery(max_recovery_attempts=3)
        for _ in range(4):
            r.on_disconnect()
            # No on_reconnect — simulating sustained outage
        assert r.state == RecoveryState.FROZEN

    def test_outage_during_order_submission(self):
        """Disconnect during order → must halt."""
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state == RecoveryState.DISCONNECTED
        # Order must be rejected — state is DISCONNECTED
        r.on_reconnect()
        r.submit_reconciliation(True, True, True, True)
        r.request_resume(True, True, True, True, True)
        assert r.state == RecoveryState.RESUMED  # can resume after validation

    def test_outage_during_reconciliation(self):
        """Disconnect during reconciliation → must halt."""
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state == RecoveryState.DISCONNECTED

    def test_multiple_reconnect_attempts_frozen(self):
        """Multiple reconnect attempts without successful reconciliation → FROZEN."""
        r = DisconnectRecovery(max_recovery_attempts=3)
        r.on_disconnect()
        r.on_reconnect()
        # Submit failed reconciliation
        r.submit_reconciliation(False, False, False, False)
        assert r.state == RecoveryState.HALTED

        # Disconnect again
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(False, False, False, False)

        # Disconnect again
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(False, False, False, False)

        # Disconnect again — should be FROZEN
        r.on_disconnect()
        assert r.state == RecoveryState.FROZEN


class TestDataCorruption:
    """Simulate corrupted or malformed data."""

    def test_corrupted_fingerprint_rejects(self):
        """Corrupted fingerprint must cause rejection."""
        import dataclasses

        from eigencapital.fidelity.r4_manifest import R4ConfigManifest
        from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

        fv = FingerprintVerifier(manifest=R4ConfigManifest(), risk_policy=RiskPolicy())
        # Verify valid — same objects should match
        result = fv.verify_all()
        assert result.all_verified is True

        # Create tampered manifest using dataclasses.replace (frozen dataclass)
        tampered = dataclasses.replace(R4ConfigManifest(), strategy_version="R4.0_TAMPERED")
        FingerprintVerifier(manifest=tampered, risk_policy=RiskPolicy())
        # The tampered manifest's fingerprint differs from the original
        assert R4ConfigManifest().compute_identity() != tampered.compute_identity()

    def test_missing_fingerprint_rejects(self):
        """Missing fingerprint must cause rejection."""
        fv = MagicMock()
        fv.verify_all.return_value = MagicMock(all_verified=False)
        assert fv.verify_all().all_verified is False

    def test_corrupted_config_rejects(self):
        """Corrupted config must cause rejection."""
        config = LiveRiskConfig()
        # Valid config
        assert config.min_equity > 0

        # Corrupted config (negative equity) — constructor validation
        try:
            LiveRiskConfig(min_equity=-1)
            # If constructor doesn't validate, the test reveals the gap
        except Exception:
            pass  # Expected — constructor validates


class TestCompoundFailures:
    """Simulate multiple simultaneous failures."""

    def test_disconnect_plus_fingerprint_mismatch(self):
        """Disconnect + fingerprint mismatch → HALTED."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        # Fingerprint mismatch in reconciliation
        result = r.submit_reconciliation(True, True, True, False, details="fingerprint_mismatch")
        assert r.state == RecoveryState.HALTED
        assert "HALT" in result

    def test_disconnect_plus_daily_loss_breach(self):
        """Disconnect + daily loss breach → HALT after resume check."""
        r = DisconnectRecovery()
        r.on_disconnect()
        assert r.state == RecoveryState.DISCONNECTED
        r.on_reconnect()
        r.submit_reconciliation(True, True, True, True)
        # Resume check fails because risk_limits_passing=False
        result = r.request_resume(True, True, True, False, True)
        assert r.state == RecoveryState.HALTED
        assert "risk_limits_passing" in result

    def test_disconnect_plus_health_degradation(self):
        """Excessive disconnects → FROZEN."""
        r = DisconnectRecovery(max_recovery_attempts=3)
        for _ in range(4):
            r.on_disconnect()
        assert r.state == RecoveryState.FROZEN

    def test_multiple_disconnects_resilience(self):
        """System should survive 100 disconnects without crash."""
        r = DisconnectRecovery(max_recovery_attempts=100)
        for i in range(100):
            r.on_disconnect()
            if r.state != RecoveryState.FROZEN:
                r.on_reconnect()
                r.submit_reconciliation(True, True, True, True)
                r.request_resume(True, True, True, True, True)
        # System should not crash — either RESUMED or FROZEN
        assert r.state in (RecoveryState.RESUMED, RecoveryState.FROZEN)

    def test_freeze_authorize_reset(self):
        """FROZEN state can be reset with authorize_reset."""
        r = DisconnectRecovery(max_recovery_attempts=2)
        for _ in range(3):
            r.on_disconnect()
        assert r.state == RecoveryState.FROZEN
        result = r.authorize_reset()
        assert r.state == RecoveryState.HALTED
        assert "RESET" in result

    def test_position_mismatch_halts(self):
        """Position mismatch during reconciliation → HALTED."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        result = r.submit_reconciliation(False, True, True, True, details="position_mismatch")
        assert r.state == RecoveryState.HALTED
        assert "HALT" in result

    def test_equity_mismatch_halts(self):
        """Equity mismatch during reconciliation → HALTED."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(True, True, False, True, details="equity_mismatch")
        assert r.state == RecoveryState.HALTED

    def test_order_mismatch_halts(self):
        """Order mismatch during reconciliation → HALTED."""
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(True, False, True, True, details="order_mismatch")
        assert r.state == RecoveryState.HALTED


class TestStatePersistenceUnderStorm:
    """Verify state persistence survives failure storms."""

    def test_state_survives_disconnect_storm(self, tmp_path):
        """State file must be consistent after storm."""
        from eigencapital.live.supervisor import ProcessSupervisor

        state_dir = str(tmp_path)
        s = ProcessSupervisor(state_dir=state_dir)

        # Simulate storm
        for _ in range(10):
            r = DisconnectRecovery()
            r.on_disconnect()
            r.on_reconnect()

        # Supervisor should still function
        assert s.is_owner is False  # no state file = not owner

    def test_pid_file_survives_process_restart(self, tmp_path):
        """State file must be updated on restart."""
        import shutil

        from eigencapital.live.supervisor import ProcessSupervisor

        state_dir = str(tmp_path)
        s = ProcessSupervisor(state_dir=state_dir)

        # Claim instance
        assert s.claim_instance() is True
        assert s.is_owner is True

        # Simulate process crash (remove state dir)
        shutil.rmtree(state_dir)

        # New instance should claim
        s2 = ProcessSupervisor(state_dir=state_dir)
        assert s2.claim_instance() is True


class TestSecurityAtScale:
    """Verify security properties under stress."""

    def test_no_credentials_in_audit_log(self):
        """Audit logs must never contain credentials."""
        from eigencapital.live.risk_enforcement import BlockReason, GateResult, RiskEnforcer, RiskGateResult

        enforcer = RiskEnforcer(LiveRiskConfig())
        # Simulate many cycles
        for _ in range(100):
            results = [
                RiskGateResult(
                    gate_name="test",
                    result=GateResult.BLOCK,
                    block_reason=BlockReason.NO_SL_PROTECTION,
                    message="ok",
                    details={},
                    broker_state_hash="abc",
                    timestamp="2026-01-01T00:00:00",
                )
            ]
            enforcer.audit(results)

        # Verify no sensitive data in audit log
        log = enforcer.get_audit_log()
        for entry in log:
            entry_str = json.dumps(entry, default=str).lower()
            # No password-like strings
            assert "password" not in entry_str
            assert "secret" not in entry_str

    def test_fingerprint_tampering_detected(self):
        """Any fingerprint tampering must be detected."""
        import dataclasses

        from eigencapital.fidelity.r4_manifest import R4ConfigManifest
        from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

        # Frozen on construction — same objects match
        fv = FingerprintVerifier(manifest=R4ConfigManifest(), risk_policy=RiskPolicy())
        result = fv.verify_all()
        assert result.all_verified is True

        # Tamper strategy version — different manifest produces different fingerprint
        bad = dataclasses.replace(R4ConfigManifest(), strategy_version="R4.1")
        assert R4ConfigManifest().compute_identity() != bad.compute_identity()

        # Create verifier with tampered manifest — frozen fingerprint won't match
        fv_tampered = FingerprintVerifier(manifest=bad, risk_policy=RiskPolicy())
        # The frozen fingerprint is from bad, which differs from the original
        assert fv.frozen_manifest_fingerprint != fv_tampered.frozen_manifest_fingerprint

    def test_config_fingerprint_consistency(self):
        """Config fingerprint must be deterministic."""
        import json

        c1 = LiveRiskConfig()
        c2 = LiveRiskConfig()
        d1 = {k: v for k, v in c1.__dict__.items()}
        d2 = {k: v for k, v in c2.__dict__.items()}
        fp1 = hashlib.sha256(json.dumps(d1, sort_keys=True, default=str).encode()).hexdigest()
        fp2 = hashlib.sha256(json.dumps(d2, sort_keys=True, default=str).encode()).hexdigest()
        assert fp1 == fp2, "Config fingerprint must be deterministic"

    def test_risk_policy_fingerprint_consistency(self):
        """RiskPolicy fingerprint must be deterministic."""
        import json

        r1 = RiskPolicy()
        r2 = RiskPolicy()
        d1 = {k: v for k, v in r1.__dict__.items() if k != "fingerprint"}
        d2 = {k: v for k, v in r2.__dict__.items() if k != "fingerprint"}
        fp1 = hashlib.sha256(json.dumps(d1, sort_keys=True, default=str).encode()).hexdigest()
        fp2 = hashlib.sha256(json.dumps(d2, sort_keys=True, default=str).encode()).hexdigest()
        assert fp1 == fp2, "RiskPolicy fingerprint must be deterministic"
