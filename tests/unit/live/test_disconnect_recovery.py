from eigencapital.live.risk import DisconnectRecovery, RecoveryState


def _full_resume(rec):
    return rec.request_resume(
        data_fresh=True,
        positions_reconciled=True,
        no_unexpected_orders=True,
        risk_limits_passing=True,
        config_fingerprint_unchanged=True,
    )


class TestDisconnectInvariants:
    def test_reconnect_alone_never_grants_permission(self):
        r = DisconnectRecovery()
        assert r.on_disconnect() == "HALT_NEW_ORDERS"
        assert r.on_reconnect() == "RECONCILIATION_REQUIRED"
        assert r.state == RecoveryState.RECONCILING
        assert _full_resume(r).startswith("INVALID") or r.state != RecoveryState.RESUMED

    def test_only_full_sequence_resumes(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        assert r.submit_reconciliation(True, True, True, True) == "RECONCILED_AWAITING_RESUME_CHECKS"
        assert _full_resume(r) == "TRADING_RESUMED"
        assert r.state == RecoveryState.RESUMED

    def test_stale_data_after_good_reconciliation_halts(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        r.submit_reconciliation(True, True, True, True)
        out = r.request_resume(
            data_fresh=False,
            positions_reconciled=True,
            no_unexpected_orders=True,
            risk_limits_passing=True,
            config_fingerprint_unchanged=True,
        )
        assert out.startswith("HALT:data_fresh")
        assert r.state == RecoveryState.HALTED

    def test_mismatch_never_auto_resumes(self):
        r = DisconnectRecovery()
        r.on_disconnect()
        r.on_reconnect()
        out = r.submit_reconciliation(
            positions_match=False,
            orders_match=True,
            equity_match=True,
            fingerprint_match=True,
            details="ghost position EURUSDm",
        )
        assert out == "HALT_RECONCILE_OR_FLATTEN"
        assert r.state == RecoveryState.HALTED


class TestEscalationAndReset:
    def test_excessive_cycles_freeze(self):
        r = DisconnectRecovery(max_recovery_attempts=2)
        r.on_disconnect()
        r.on_disconnect()
        assert r.on_disconnect() == "FROZEN_EXCESSIVE_DISCONNECTS"
        assert r.state == RecoveryState.FROZEN

    def test_frozen_requires_manual_authorization(self):
        r = DisconnectRecovery(max_recovery_attempts=1)
        r.on_disconnect()
        r.on_disconnect()
        assert r.authorize_reset() == "RESET_TO_HALTED_MANUAL_REVIEW_REQUIRED"
        assert r.state == RecoveryState.HALTED

    def test_invalid_transition_rejected(self):
        r = DisconnectRecovery()
        assert r.on_reconnect().startswith("INVALID")
