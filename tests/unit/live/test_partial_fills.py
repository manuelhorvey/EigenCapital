"""Phase 1U item 5 - partial-fill policy: the killer scenarios."""

from eigencapital.live.partial_fills import ChaseDecision, PartialFillManager


def _mgr(qty=0.10):
    return PartialFillManager(
        "ORD-1",
        requested_qty=qty,
        max_chase_attempts=1,
        max_age_seconds=60.0,
        max_cumulative_slippage_bps=15.0,
        reference_price=1.1000,
    )


class TestKillerScenario:
    def test_full_lifecycle_ends_at_broker_truth(self):
        m = _mgr()
        assert m.on_fill("f1", 0.06, 1.1002, ts=0) == "REMAINDER_OPEN"
        assert abs(m.remaining - 0.04) < 1e-12
        assert m.decide(now_ts=10, spread_ok=True, risk_and_exposure_ok=True) == ChaseDecision.CHASE
        assert m.chase_attempts == 1
        assert m.on_fill("f2", 0.02, 1.1004, ts=30) == "REMAINDER_OPEN"
        # timeout on the final remainder -> cancel
        assert m.decide(now_ts=120) == ChaseDecision.CANCEL
        rec = m.reconcile_with_broker(broker_position_qty=0.08)
        assert rec["authoritative_qty"] == 0.08
        assert rec["needs_escalation"] is False
        assert abs(rec["local_filled_qty"] - 0.08) < 1e-12

    def test_duplicate_fill_notification_idempotent(self):
        m = _mgr()
        m.on_fill("f1", 0.06, 1.1002, ts=0)
        assert m.on_fill("f1", 0.06, 1.1002, ts=0) == "DUPLICATE_IGNORED"
        assert m.filled_qty == pytest_approx(0.06)

    def test_partial_plus_disconnect_plus_replay(self):
        m = _mgr(0.10)
        m.on_fill("a", 0.04, 1.1001, ts=0)
        m.execute_cancel(5)
        # late replayed/duplicate events after cancel are ignored
        assert m.on_fill("a", 0.04, 1.1001, ts=6) == "DUPLICATE_IGNORED"
        assert m.on_fill("b", 0.02, 1.1003, ts=7) == "FILL_AFTER_CANCEL_IGNORED"
        assert m.filled_qty == pytest_approx(0.04)
        rec = m.reconcile_with_broker(0.05)
        assert rec["authoritative_qty"] == 0.05
        assert rec["needs_escalation"] is True


class TestPolicyGuards:
    def test_max_chase_attempts_exhausted_cancels(self):
        m = _mgr()
        m.max_chase_attempts = 0
        assert m.decide(now_ts=0) == ChaseDecision.CANCEL

    def test_cumulative_slippage_cap_forces_cancel(self):
        m = PartialFillManager("O", 1.0, reference_price=1.1000)
        m.on_fill("f", 0.5, 1.1150, ts=0)  # ~136 bps slippage > 15 cap
        assert m.decide(now_ts=0) == ChaseDecision.CANCEL

    def test_risk_block_keeps_fill_but_no_chase(self):
        m = _mgr()
        m.on_fill("f", 0.06, 1.1002, ts=0)
        d = m.decide(now_ts=10, spread_ok=True, risk_and_exposure_ok=False)
        assert d == ChaseDecision.ACCEPT and m.chase_attempts == 0

    def test_spread_violation_no_chase(self):
        m = _mgr()
        m.on_fill("f", 0.06, 1.1002, ts=0)
        assert m.decide(now_ts=10, spread_ok=False) == ChaseDecision.ACCEPT

    def test_full_fill_done_without_chase(self):
        m = _mgr()
        m.on_fill("only", 0.10, 1.1000, ts=0)
        assert m.decide(now_ts=1) == ChaseDecision.DONE


def pytest_approx(x):
    import pytest

    return pytest.approx(x)
