"""Phase 1T Tests — Micro-Live Qualification."""

import pytest

from eigencapital.micro_live.campaign import (
    KillReason,
    MicroLiveAuthorization,
    MicroLiveCampaign,
    MicroLiveEnvelope,
    MicroLiveStatus,
    MicroLiveVerdict,
)
from eigencapital.micro_live.qualification import (
    MicroLiveEvaluator,
)

# ============================================================
# MICRO-LIVE ENVELOPE TESTS
# ============================================================


class TestMicroLiveEnvelope:
    """Test micro-live risk envelope."""

    def test_envelope_creation(self):
        env = MicroLiveEnvelope()
        assert env.max_account_equity == 1000.0
        assert env.max_position_size == 100.0
        assert env.max_order_notional == 50.0
        assert env.max_concurrent_positions == 5
        assert env.max_daily_loss == 50.0
        assert env.max_total_drawdown == 200.0
        assert env.max_drawdown_pct == 0.20

    def test_envelope_identity_deterministic(self):
        e1 = MicroLiveEnvelope()
        e2 = MicroLiveEnvelope()
        assert e1.compute_identity() == e2.compute_identity()

    def test_envelope_identity_changes(self):
        e1 = MicroLiveEnvelope(max_account_equity=1000)
        e2 = MicroLiveEnvelope(max_account_equity=2000)
        assert e1.compute_identity() != e2.compute_identity()

    def test_envelope_stricter_than_production(self):
        """Micro-live limits must be stricter than normal production."""
        env = MicroLiveEnvelope()
        assert env.max_account_equity <= 10000  # much less than production
        assert env.max_position_size <= 1000
        assert env.max_daily_loss <= 500


# ============================================================
# MICRO-LIVE AUTHORIZATION TESTS
# ============================================================


class TestMicroLiveAuthorization:
    """Test micro-live authorization."""

    def test_authorization_creation(self):
        auth = MicroLiveAuthorization(
            authorization_id="AUTH-001",
            campaign_id="CAMP-001",
            strategy_fingerprint="abc123",
            risk_envelope_hash="def456",
            broker_identity="exness",
            account_identity="168966110",
            operator_identity="manuel",
            max_capital=1000.0,
            max_duration_hours=168,
            created_timestamp="2026-08-24T00:00:00",
            expiry_timestamp="2026-08-31T00:00:00",
        )
        assert auth.is_active
        assert auth.max_capital == 1000.0

    def test_authorization_expiry(self):
        auth = MicroLiveAuthorization(
            authorization_id="AUTH-001",
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            risk_envelope_hash="def",
            broker_identity="exness",
            account_identity="123",
            operator_identity="manuel",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="2026-08-24",
            expiry_timestamp="2026-08-25",
        )
        assert not auth.is_expired("2026-08-24")
        assert auth.is_expired("2026-08-26")

    def test_authorization_to_dict(self):
        auth = MicroLiveAuthorization(
            authorization_id="AUTH-001",
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            risk_envelope_hash="def",
            broker_identity="exness",
            account_identity="123",
            operator_identity="manuel",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="2026-08-24",
            expiry_timestamp="2026-08-31",
        )
        d = auth.to_dict()
        assert "authorization_id" in d
        assert d["max_capital"] == 1000


# ============================================================
# MICRO-LIVE CAMPAIGN TESTS
# ============================================================


class TestMicroLiveCampaign:
    """Test micro-live campaign lifecycle."""

    def _make_campaign(self):
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="AUTH-001",
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            risk_envelope_hash=env.compute_identity(),
            broker_identity="exness",
            account_identity="123",
            operator_identity="manuel",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="2026-08-24",
            expiry_timestamp="2026-08-31",
        )
        return MicroLiveCampaign("CAMP-001", env, auth)

    def test_lifecycle(self):
        camp = self._make_campaign()
        assert camp.state.status == MicroLiveStatus.PLANNED

        # Preflight
        result = camp.preflight()
        assert result["all_pass"]
        assert camp.state.status == MicroLiveStatus.PREFLIGHT

        # Activate
        assert camp.activate()
        assert camp.state.status == MicroLiveStatus.ACTIVE
        assert camp.is_active

    def test_fill_recording(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        fill = camp.record_fill(
            instrument_id="EURUSDm",
            side="BUY",
            quantity=100,
            fill_price=1.1020,
            spread=0.0002,
            slippage=0.0001,
        )
        assert fill["instrument_id"] == "EURUSDm"
        assert camp.state.orders_filled == 1

    def test_slippage_kill(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        camp.record_fill(
            instrument_id="EURUSDm",
            side="BUY",
            quantity=100,
            fill_price=1.1020,
            spread=0.0002,
            slippage=0.0050,  # exceeds max_slippage
        )
        assert camp.was_killed
        assert len(camp._kill_log) == 1

    def test_reconciliation_kill(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        matched = camp.record_reconciliation(
            internal_position={"EURUSDm": 100.0},
            broker_position={"EURUSDm": 95.0},  # mismatch
        )
        assert not matched
        assert camp.was_killed

    def test_drawdown_kill(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        camp._state.peak_equity = 1000.0
        reason = camp.check_kill_conditions(current_equity=750.0)
        assert reason == KillReason.DRAWDOWN_LIMIT

    def test_daily_loss_kill(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        camp._state.daily_pnl = -60.0  # exceeds max_daily_loss
        reason = camp.check_kill_conditions()
        assert reason == KillReason.DAILY_LOSS_LIMIT

    def test_no_kill_when_safe(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()

        camp._state.peak_equity = 1000.0
        reason = camp.check_kill_conditions(current_equity=990.0)
        assert reason is None

    def test_cannot_activate_without_preflight(self):
        camp = self._make_campaign()
        assert not camp.activate()

    def test_get_result(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()
        result = camp.get_result()
        assert "campaign_id" in result
        assert "state" in result
        assert "authorization" in result


# ============================================================
# QUALIFICATION TESTS
# ============================================================


class TestQualification:
    """Test micro-live qualification evaluation."""

    def _make_qualified_campaign(self):
        camp = self._make_campaign()
        camp.preflight()
        camp.activate()
        # Record some successful fills
        for i in range(5):
            camp.record_fill(
                instrument_id=f"SYM{i}",
                side="BUY",
                quantity=10,
                fill_price=100.0,
                spread=0.0002,
                slippage=0.0001,
            )
        return camp

    def _make_campaign(self):
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="AUTH-001",
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            risk_envelope_hash=env.compute_identity(),
            broker_identity="exness",
            account_identity="123",
            operator_identity="manuel",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="2026-08-24",
            expiry_timestamp="2026-08-31",
        )
        return MicroLiveCampaign("CAMP-001", env, auth)

    def test_qualification_qualified(self):
        camp = self._make_qualified_campaign()
        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        assert report.verdict == MicroLiveVerdict.QUALIFIED
        assert report.failed_checks == 0

    def test_qualification_blocked_on_kill(self):
        camp = self._make_qualified_campaign()
        camp.execute_kill(KillReason.RISK_LIMIT_BREACH, "test")
        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        assert report.verdict == MicroLiveVerdict.BLOCKED

    def test_qualification_blocked_on_reconciliation(self):
        camp = self._make_qualified_campaign()
        camp.record_reconciliation(
            internal_position={"X": 100},
            broker_position={"X": 50},
        )
        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        assert report.verdict == MicroLiveVerdict.BLOCKED

    def test_report_markdown(self):
        camp = self._make_qualified_campaign()
        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        md = report.to_markdown()
        assert "Micro-Live Qualification Report" in md
        assert "QUALIFIED" in md

    def test_report_to_dict(self):
        camp = self._make_qualified_campaign()
        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        d = report.to_dict()
        assert "verdict" in d
        assert "checks" in d
        assert len(d["checks"]) == 7

    def test_report_hash_deterministic(self):
        camp = self._make_qualified_campaign()
        evaluator = MicroLiveEvaluator()
        r1 = evaluator.evaluate(camp)
        r2 = evaluator.evaluate(camp)
        assert r1.report_hash == r2.report_hash


# ============================================================
# ADVERSARIAL TESTS
# ============================================================


class TestAdversarialMicroLive:
    """Adversarial tests for micro-live."""

    def test_envelope_immutable(self):
        env = MicroLiveEnvelope()
        with pytest.raises(AttributeError):
            env.max_account_equity = 999999  # type: ignore

    def test_authorization_immutable(self):
        auth = MicroLiveAuthorization(
            authorization_id="A",
            campaign_id="C",
            strategy_fingerprint="s",
            risk_envelope_hash="r",
            broker_identity="b",
            account_identity="a",
            operator_identity="o",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="t",
            expiry_timestamp="e",
        )
        with pytest.raises(AttributeError):
            auth.is_active = False  # type: ignore

    def test_kill_is_instant(self):
        """Kill must stop all activity immediately."""
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="A",
            campaign_id="C",
            strategy_fingerprint="s",
            risk_envelope_hash="r",
            broker_identity="b",
            account_identity="a",
            operator_identity="o",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="t",
            expiry_timestamp="e",
        )
        camp = MicroLiveCampaign("C", env, auth)
        camp.preflight()
        camp.activate()

        # Kill
        camp.execute_kill(KillReason.MANUAL_KILL, "emergency")
        assert camp.was_killed
        assert not camp.is_active

    def test_reconciliation_failure_is_fatal(self):
        """Reconciliation mismatch must be fatal — no recovery without human review."""
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="A",
            campaign_id="C",
            strategy_fingerprint="s",
            risk_envelope_hash="r",
            broker_identity="b",
            account_identity="a",
            operator_identity="o",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="t",
            expiry_timestamp="e",
        )
        camp = MicroLiveCampaign("C", env, auth)
        camp.preflight()
        camp.activate()

        # Reconciliation fails
        camp.record_reconciliation(
            internal_position={"X": 100},
            broker_position={"X": 50},
        )
        assert camp.was_killed
        # Cannot resume without explicit human action
        assert camp.state.status == MicroLiveStatus.KILLED

    def test_slippage_violation_is_fatal(self):
        """Excessive slippage must trigger immediate kill."""
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="A",
            campaign_id="C",
            strategy_fingerprint="s",
            risk_envelope_hash="r",
            broker_identity="b",
            account_identity="a",
            operator_identity="o",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="t",
            expiry_timestamp="e",
        )
        camp = MicroLiveCampaign("C", env, auth)
        camp.preflight()
        camp.activate()

        camp.record_fill(
            instrument_id="X",
            side="BUY",
            quantity=10,
            fill_price=100,
            spread=0.001,
            slippage=0.01,
        )
        assert camp.was_killed

    def test_profit_not_required_for_qualification(self):
        """A loss-making campaign can still qualify if behavior is correct."""
        env = MicroLiveEnvelope()
        auth = MicroLiveAuthorization(
            authorization_id="A",
            campaign_id="C",
            strategy_fingerprint="s",
            risk_envelope_hash="r",
            broker_identity="b",
            account_identity="a",
            operator_identity="o",
            max_capital=1000,
            max_duration_hours=168,
            created_timestamp="t",
            expiry_timestamp="e",
        )
        camp = MicroLiveCampaign("C", env, auth)
        camp.preflight()
        camp.activate()

        # Record loss-making fills
        for i in range(5):
            camp.record_fill(
                instrument_id=f"SYM{i}",
                side="BUY",
                quantity=10,
                fill_price=100,
                spread=0.0002,
                slippage=0.0001,
            )
        camp._state.total_pnl = -50.0  # losing money

        evaluator = MicroLiveEvaluator()
        report = evaluator.evaluate(camp)
        # Should still qualify — behavior is correct even though losing
        assert report.verdict in (MicroLiveVerdict.QUALIFIED, MicroLiveVerdict.QUALIFIED_WITH_RESTRICTIONS)
