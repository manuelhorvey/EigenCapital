"""Unit tests for EigenRisk Engine — adversarial risk testing."""

import pytest

from eigencapital.risk.checks.account_checks import (
    AccountState,
    check_daily_loss,
    check_gross_leverage,
    check_kill_switch,
    check_max_drawdown,
    check_min_equity,
    check_position_count,
    check_weekly_loss,
)
from eigencapital.risk.engine import EigenRiskEngine
from eigencapital.risk.policy import CONSERVATIVE, MODERATE, RiskPolicy

# ─── Policy Tests ───────────────────────────────────────────────────────────


class TestRiskPolicy:
    def test_default_policy(self):
        p = RiskPolicy()
        assert p.max_drawdown_pct == 10.0
        assert p.max_gross_leverage == 2.0
        assert p.kill_switch is False

    def test_conservative_policy(self):
        assert CONSERVATIVE.max_drawdown_pct == 5.0
        assert CONSERVATIVE.max_gross_leverage == 1.5

    def test_invalid_drawdown(self):
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            RiskPolicy(max_drawdown_pct=-1)

    def test_to_from_dict(self):
        p = RiskPolicy(max_drawdown_pct=7.5)
        d = p.to_dict()
        assert d["max_drawdown_pct"] == 7.5
        p2 = RiskPolicy.from_dict(d)
        assert p2.max_drawdown_pct == 7.5


# ─── Account Check Tests ────────────────────────────────────────────────────


class TestAccountChecks:
    def test_drawdown_pass(self):
        state = AccountState(equity=95_000, peak_equity=100_000)
        result = check_max_drawdown(state, MODERATE)
        assert result.status == "PASS"

    def test_drawdown_warn(self):
        state = AccountState(equity=94_000, peak_equity=100_000)
        result = check_max_drawdown(state, MODERATE)
        assert result.status == "WARN"

    def test_drawdown_fail(self):
        state = AccountState(equity=89_000, peak_equity=100_000)
        result = check_max_drawdown(state, MODERATE)
        assert result.status == "FAIL"

    def test_drawdown_zero_peak(self):
        state = AccountState(equity=0, peak_equity=0)
        result = check_max_drawdown(state, MODERATE)
        assert result.status == "FAIL"

    def test_daily_loss_pass(self):
        state = AccountState(daily_pnl=-1_000)
        result = check_daily_loss(state, MODERATE)
        assert result.status == "PASS"

    def test_daily_loss_fail(self):
        state = AccountState(daily_pnl=-6_000)
        result = check_daily_loss(state, MODERATE)
        assert result.status == "FAIL"

    def test_weekly_loss_pass(self):
        state = AccountState(weekly_pnl=-10_000)
        result = check_weekly_loss(state, MODERATE)
        assert result.status == "PASS"

    def test_weekly_loss_fail(self):
        state = AccountState(weekly_pnl=-20_000)
        result = check_weekly_loss(state, MODERATE)
        assert result.status == "FAIL"

    def test_gross_leverage_pass(self):
        state = AccountState(equity=100_000, gross_exposure=150_000)
        result = check_gross_leverage(state, MODERATE)
        assert result.status == "PASS"

    def test_gross_leverage_fail(self):
        state = AccountState(equity=100_000, gross_exposure=250_000)
        result = check_gross_leverage(state, MODERATE)
        assert result.status == "FAIL"

    def test_gross_leverage_zero_equity(self):
        state = AccountState(equity=0, gross_exposure=100_000)
        result = check_gross_leverage(state, MODERATE)
        assert result.status == "FAIL"

    def test_min_equity_pass(self):
        state = AccountState(equity=100_000)
        result = check_min_equity(state, MODERATE)
        assert result.status == "PASS"

    def test_min_equity_fail(self):
        state = AccountState(equity=40_000)
        result = check_min_equity(state, MODERATE)
        assert result.status == "FAIL"

    def test_position_count_pass(self):
        state = AccountState(position_count=5)
        result = check_position_count(state, MODERATE)
        assert result.status == "PASS"

    def test_position_count_fail(self):
        state = AccountState(position_count=15)
        result = check_position_count(state, MODERATE)
        assert result.status == "FAIL"

    def test_kill_switch_active(self):
        state = AccountState()
        policy = RiskPolicy(kill_switch=True)
        result = check_kill_switch(state, policy)
        assert result.status == "FAIL"
        assert "Kill switch" in result.message

    def test_kill_switch_inactive(self):
        state = AccountState()
        result = check_kill_switch(state, MODERATE)
        assert result.status == "PASS"


# ─── EigenRisk Engine Tests ─────────────────────────────────────────────────


class TestEigenRiskEngine:
    def _clear_registries(self):
        from eigencapital.core.models.risk_check_result import RiskCheckResult

        RiskCheckResult._registry.clear()

    def test_all_pass(self):
        self._clear_registries()
        engine = EigenRiskEngine(policy=MODERATE)
        state = AccountState(equity=100_000, peak_equity=100_000)
        result = engine.evaluate(state, requested_quantity=5)
        assert result.decision == "APPROVED"
        assert result.approved_quantity == 5

    def test_drawdown_rejects(self):
        self._clear_registries()
        engine = EigenRiskEngine(policy=MODERATE)
        state = AccountState(equity=89_000, peak_equity=100_000)
        result = engine.evaluate(state, requested_quantity=5)
        assert result.decision == "REJECTED"
        assert result.approved_quantity == 0

    def test_kill_switch_rejects(self):
        self._clear_registries()
        policy = RiskPolicy(kill_switch=True)
        engine = EigenRiskEngine(policy=policy)
        state = AccountState(equity=100_000, peak_equity=100_000)
        result = engine.evaluate(state, requested_quantity=5)
        assert result.decision == "REJECTED"

    def test_multiple_failures(self):
        """Multiple simultaneous breaches all cause REJECTION."""
        self._clear_registries()
        engine = EigenRiskEngine(policy=MODERATE)
        state = AccountState(
            equity=40_000,  # Below min_equity
            peak_equity=100_000,  # 60% drawdown — way over limit
            daily_pnl=-6_000,  # Over daily loss limit
            gross_exposure=250_000,  # 6.25x leverage
            position_count=15,  # Over position limit
        )
        result = engine.evaluate(state)
        assert result.decision == "REJECTED"
        assert result.approved_quantity == 0
        failed = [c for c in result.checks if c.status == "FAIL"]
        assert len(failed) >= 4  # Multiple failures

    def test_checks_are_structured(self):
        self._clear_registries()
        engine = EigenRiskEngine(policy=MODERATE)
        state = AccountState(equity=100_000, peak_equity=100_000)
        result = engine.evaluate(state)
        assert len(result.checks) > 0
        for check in result.checks:
            assert check.check_id != ""
            assert check.status in ("PASS", "WARN", "FAIL")
            assert check.message != ""

    def test_conservative_policy_tighter(self):
        """Conservative policy should reject earlier."""
        state = AccountState(equity=93_000, peak_equity=100_000)

        self._clear_registries()
        engine_moderate = EigenRiskEngine(policy=MODERATE)
        result_moderate = engine_moderate.evaluate(state)

        self._clear_registries()
        engine_conservative = EigenRiskEngine(policy=CONSERVATIVE)
        result_conservative = engine_conservative.evaluate(state)

        # Conservative should reject where moderate warns
        assert result_conservative.decision == "REJECTED"
        assert result_moderate.decision in ("APPROVED", "WARN")

    def test_decision_rejected_implies_zero(self):
        """REJECTED decision must have approved_quantity = 0."""
        self._clear_registries()
        engine = EigenRiskEngine(policy=MODERATE)
        state = AccountState(equity=40_000)
        result = engine.evaluate(state, requested_quantity=10)
        if result.decision == "REJECTED":
            assert result.approved_quantity == 0

    def test_positive_daily_pnl_no_warning(self):
        """Positive daily P&L should not trigger loss check."""
        state = AccountState(daily_pnl=5_000)
        result = check_daily_loss(state, MODERATE)
        assert result.status == "PASS"
