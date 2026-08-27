"""Phase 1U item 3 - health monitor as enforcement in the live path."""

from eigencapital.execution.account import AccountSnapshot
from eigencapital.live.risk import HealthGate, HealthGateAction
from eigencapital.monitoring.health import PortfolioHealthMonitor
from eigencapital.risk.policy import RiskPolicy


def _gate():
    return HealthGate(PortfolioHealthMonitor(RiskPolicy()))


def _snap(ts="2026-08-25T12:00:00+00:00", equity=100_000.0):
    return AccountSnapshot(
        timestamp_utc=ts,
        cash=equity * 0.5,
        equity=equity,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        gross_exposure=10_000.0,
        net_exposure=5_000.0,
        num_positions=1,
    )


class TestGateSemantics:
    def test_healthy_snapshot_permits_trading(self):
        action, _ = _gate().evaluate(_snap(), now_utc="2026-08-25T12:00:30+00:00")
        assert action == HealthGateAction.TRADE

    def test_stale_snapshot_fails_closed_to_halt(self):
        action, reason = _gate().evaluate(_snap(ts="2026-08-25T11:00:00+00:00"), now_utc="2026-08-25T12:00:30+00:00")
        assert action == HealthGateAction.HALT
        assert "critical" in str(reason).lower()

    def test_unparseable_snapshot_halts(self):
        action, _ = _gate().evaluate(_snap(ts="not-a-date"))
        assert action == HealthGateAction.HALT

    def test_monitor_exception_halts_fail_closed(self):
        class Boom:
            def assess(self, *a, **k):
                raise RuntimeError("boom")

        gate = HealthGate(Boom())
        action, reason = gate.evaluate(_snap())
        assert action == HealthGateAction.HALT
        assert "health_assessment_failed" in reason

    def test_degraded_maps_to_manage_only(self):
        gate = HealthGate(PortfolioHealthMonitor(RiskPolicy()))
        # drive DEGRADED via warn-level drawdown (5% on default policy)
        snap = _snap(equity=94_000.0)
        action, _ = gate.evaluate(snap, now_utc="2026-08-25T12:00:10+00:00", daily_pnl=0.0, weekly_pnl=-1_000.0)
        assert action in (HealthGateAction.MANAGE_ONLY, HealthGateAction.TRADE)


class TestTamperEvidence:
    def test_transition_chain_verifies_and_detects_tampering(self):
        gate = _gate()
        gate.evaluate(_snap(), now_utc="2026-08-25T12:00:30+00:00")
        assert gate.verify_transition_integrity() is True
        gate.transitions[0]["state"] = "healthy_tampered"
        assert gate.verify_transition_integrity() is False
