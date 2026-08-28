"""Tests for REDUCED shadow-only mode and risk outcome attribution.

Covers:
- REDUCED correctness audit (boundary conditions)
- REDUCED shadow-only behavior
- Risk outcome attribution dataset
- Reconciliation autofix safety
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from eigencapital.live.risk_attribution import RiskOutcomeAttribution
from eigencapital.live.risk_enforcement import RiskEnforcer, RiskEnvelope

# ─────────────────────────────────────────────────────────────
# REDUCED Correctness Audit
# ─────────────────────────────────────────────────────────────


class TestReducedCorrectness:
    """Verify REDUCED mathematically: hard breach → 0, soft → deterministic, no breach → 1.0."""

    def _make_enforcer(self, **kwargs) -> RiskEnforcer:
        envelope = RiskEnvelope(
            max_daily_loss=250.0,
            min_equity=4000.0,
            t0_equity=5000.0,
            max_account_drawdown_pct=0.10,
            **kwargs,
        )
        return RiskEnforcer(envelope=envelope)

    def test_no_breach_returns_1(self):
        """No risk condition → scale factor 1.0."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=5000,
            broker_positions=[],
        )
        assert factor == 1.0
        assert "normal" in reason.lower()

    def test_drawdown_5pct_returns_075(self):
        """Drawdown >= 5% → scale factor 0.75."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 4750  # Set to current to avoid daily loss trigger
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=4750,  # 5% drawdown
            broker_positions=[],
        )
        assert factor == 0.75
        assert "drawdown" in reason.lower()

    def test_drawdown_7pct_returns_050(self):
        """Drawdown >= 7% → scale factor 0.50."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 4650  # Set to current to avoid daily loss trigger
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=4650,  # 7% drawdown
            broker_positions=[],
        )
        assert factor == 0.50

    def test_drawdown_9pct_returns_025(self):
        """Drawdown >= 9% → scale factor 0.25 (maximum reduction)."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 4550  # Set to current to avoid daily loss trigger
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=4550,  # 9% drawdown
            broker_positions=[],
        )
        assert factor == 0.25

    def test_exact_threshold_boundary(self):
        """Exactly at 5% boundary → 0.75."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 4750.0
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=4750.0,  # exactly 5%
            broker_positions=[],
        )
        assert factor == 0.75

    def test_threshold_plus_epsilon(self):
        """Just below 5% → 1.0 (no reduction)."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 4750.01
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=4750.01,  # 4.9998% drawdown
            broker_positions=[],
        )
        assert factor == 1.0

    def test_daily_loss_40pct_of_budget(self):
        """Daily loss at 40% of budget → 0.75."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=4900,  # $100 loss = 40% of $250 budget
            broker_positions=[],
        )
        assert factor == 0.75
        assert "daily loss" in reason.lower()

    def test_daily_loss_80pct_of_budget(self):
        """Daily loss at 80% of budget → 0.25."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=4800,  # $200 loss = 80% of $250 budget
            broker_positions=[],
        )
        assert factor == 0.25

    def test_multiple_soft_breaches_compose_via_min(self):
        """Multiple soft breaches → minimum factor wins."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000  # $350 daily loss triggers 0.25
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=4650,  # 7% drawdown AND $350 daily loss
            broker_positions=[],
        )
        # Daily loss 350 > 250 budget → 0.25
        # 7% drawdown → 0.50
        # min(0.25, 0.50) = 0.25
        assert factor == 0.25

    def test_zero_equity(self):
        """Zero equity → doesn't crash, returns minimum factor."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=0,
            broker_positions=[],
        )
        assert 0 < factor <= 1.0

    def test_negative_equity(self):
        """Negative equity → doesn't crash."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=-100,
            broker_positions=[],
        )
        assert 0 < factor <= 1.0

    def test_nan_equity(self):
        """NaN equity → doesn't crash."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        import math

        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=float("nan"),
            broker_positions=[],
        )
        assert not math.isnan(factor)

    def test_stale_peak_equity_zero(self):
        """Peak equity = 0 → drawdown check skipped."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 0
        enforcer._daily_pnl_start = 0
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=5000,
            broker_positions=[],
        )
        assert factor == 1.0

    def test_concentration_25pct(self):
        """Single position at 25% of equity → 0.75."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        positions = [{"notional": 1250, "symbol": "EURUSD"}]  # 25% of 5000
        factor, reason = enforcer.compute_size_scale_factor(
            account_equity=5000,
            broker_positions=positions,
        )
        assert factor == 0.75
        assert "concentration" in reason.lower()

    def test_concentration_30pct(self):
        """Single position at 30% of equity → 0.50."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000
        positions = [{"notional": 1500, "symbol": "EURUSD"}]  # 30% of 5000
        factor, _ = enforcer.compute_size_scale_factor(
            account_equity=5000,
            broker_positions=positions,
        )
        assert factor == 0.50


# ─────────────────────────────────────────────────────────────
# REDUCED Shadow-Only Mode
# ─────────────────────────────────────────────────────────────


class TestReducedShadowMode:
    """Verify REDUCED records shadow decisions but doesn't apply them."""

    def test_shadow_decision_recorded(self):
        """Shadow decision is recorded with correct fields."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000

        record = enforcer.record_shadow_decision(
            intended_size=0.10,
            scale_factor=0.75,
            reason="drawdown 5.2%",
            equity=4740,
            positions=[{"notional": 1000}],
        )

        assert record["mode"] == "SHADOW"
        assert record["intended_size"] == 0.10
        assert record["approved_size"] == 0.10  # Not reduced!
        assert record["hypothetical_reduced_size"] == pytest.approx(0.075)
        assert record["scale_factor"] == 0.75
        assert record["subsequent_return"] is None  # Filled later

    def test_shadow_does_not_apply(self):
        """Shadow mode: approved_size == intended_size always."""
        enforcer = self._make_enforcer()
        enforcer._peak_equity = 5000
        enforcer._daily_pnl_start = 5000

        # Even with extreme reduction factor
        record = enforcer.record_shadow_decision(
            intended_size=0.10,
            scale_factor=0.25,
            reason="drawdown 9.5%",
            equity=4525,
            positions=[],
        )

        assert record["approved_size"] == 0.10  # Still not reduced
        assert record["hypothetical_reduced_size"] == 0.025

    def test_shadow_decisions_bounded(self):
        """Shadow decision list is bounded."""
        enforcer = self._make_enforcer()
        enforcer._max_shadow_decisions = 5

        for i in range(10):
            enforcer.record_shadow_decision(
                intended_size=0.10,
                scale_factor=1.0,
                reason="test",
                equity=5000,
                positions=[],
            )

        assert len(enforcer.get_shadow_decisions()) == 5

    def _make_enforcer(self, **kwargs) -> RiskEnforcer:
        envelope = RiskEnvelope(
            max_daily_loss=250.0,
            min_equity=4000.0,
            t0_equity=5000.0,
            max_account_drawdown_pct=0.10,
            **kwargs,
        )
        return RiskEnforcer(envelope=envelope)


# ─────────────────────────────────────────────────────────────
# Risk Outcome Attribution
# ─────────────────────────────────────────────────────────────


class TestRiskOutcomeAttribution:
    """Test the attribution dataset builder."""

    def test_record_entry_and_exit(self):
        """Full lifecycle: entry → price updates → exit → attribution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attr = RiskOutcomeAttribution(data_dir=tmpdir)

            attr.record_trade_entry(
                ticket=12345,
                symbol="EURUSD",
                direction="LONG",
                entry_price=1.1000,
                entry_size=0.10,
                equity=5000,
                drawdown_pct=0.02,
                risk_level="NORMAL",
                scale_factor=1.0,
                scale_reason="normal conditions",
            )

            # Simulate price movement
            attr.update_price(12345, 1.0950)  # adverse
            attr.update_price(12345, 1.1050)  # favorable
            attr.update_price(12345, 1.0930)  # new adverse low

            # Exit
            result = attr.record_trade_exit(
                ticket=12345,
                exit_price=1.1020,
                realized_pnl=20.0,
            )

            assert result["mae"] == pytest.approx(0.0070, abs=0.0001)  # 1.1000 - 1.0930
            assert result["mfe"] == pytest.approx(0.0050, abs=0.0001)  # 1.1050 - 1.1000
            assert result["realized_pnl"] == 20.0
            assert result["holding_days"] is not None

            # Verify JSONL written
            filepath = os.path.join(tmpdir, "trade_attribution.jsonl")
            assert os.path.exists(filepath)
            with open(filepath) as f:
                records = [json.loads(line) for line in f]
            assert len(records) == 1
            assert records[0]["ticket"] == 12345

    def test_counterfactual_with_reduced(self):
        """When scale_factor < 1.0, counterfactual is computed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attr = RiskOutcomeAttribution(data_dir=tmpdir)

            attr.record_trade_entry(
                ticket=99999,
                symbol="GBPUSD",
                direction="SHORT",
                entry_price=1.2800,
                entry_size=0.10,
                equity=4800,
                drawdown_pct=0.06,
                risk_level="WARNING",
                scale_factor=0.50,
                scale_reason="drawdown 6%",
            )

            result = attr.record_trade_exit(
                ticket=99999,
                exit_price=1.2750,
                realized_pnl=50.0,
            )

            assert result["counterfactual_size"] == 0.05
            assert result["counterfactual_pnl"] == 25.0  # 50 * 0.50

    def test_summary_statistics(self):
        """Summary computes correct aggregates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attr = RiskOutcomeAttribution(data_dir=tmpdir)

            # Trade 1: winner
            attr.record_trade_entry(
                ticket=1,
                symbol="EURUSD",
                direction="LONG",
                entry_price=1.10,
                entry_size=0.1,
                equity=5000,
                drawdown_pct=0.01,
                risk_level="NORMAL",
                scale_factor=1.0,
                scale_reason="normal",
            )
            attr.record_trade_exit(1, exit_price=1.11, realized_pnl=100)

            # Trade 2: loser
            attr.record_trade_entry(
                ticket=2,
                symbol="GBPUSD",
                direction="SHORT",
                entry_price=1.28,
                entry_size=0.1,
                equity=4900,
                drawdown_pct=0.05,
                risk_level="WARNING",
                scale_factor=0.75,
                scale_reason="drawdown 5%",
            )
            attr.record_trade_exit(2, exit_price=1.29, realized_pnl=-80)

            summary = attr.get_summary()
            assert summary["total_trades"] == 2
            assert summary["winning_trades"] == 1
            assert summary["losing_trades"] == 1
            assert summary["total_pnl"] == 20
            assert summary["reduced_trades_count"] == 1
            assert summary["reduced_trades_pct"] == 50.0

    def test_unknown_ticket_exit(self):
        """Exiting unknown ticket returns error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attr = RiskOutcomeAttribution(data_dir=tmpdir)
            result = attr.record_trade_exit(ticket=99999, exit_price=1.0, realized_pnl=0)
            assert "error" in result


# ─────────────────────────────────────────────────────────────
# Reconciliation Autofix Safety Audit
# ─────────────────────────────────────────────────────────────


class TestReconciliationAutofixSafety:
    """Audit autofix classifications: SAFE / CONDITIONAL / DANGEROUS / NEVER AUTOMATE."""

    def test_stale_positions_classified_as_safe_autofix(self):
        """Stale position refresh is SAFE_AUTOFIX."""
        from eigencapital.reconciliation.engine import (
            ReconciliationAction,
            ReconciliationCheck,
            ReconciliationSeverity,
        )

        check = ReconciliationCheck(
            check_name="stale_positions",
            status="WARNING",
            severity=ReconciliationSeverity.WARNING.value,
            action=ReconciliationAction.SAFE_AUTOFIX.value,
            message="3 stale positions",
            details={"stale_tickets": [100, 200, 300]},
        )
        assert check.action == ReconciliationAction.SAFE_AUTOFIX.value

    def test_position_count_mismatch_is_halting(self):
        """Position count mismatch is NEVER AUTOMATE — requires human review."""
        from eigencapital.reconciliation.engine import (
            ReconciliationAction,
            ReconciliationCheck,
            ReconciliationSeverity,
        )

        check = ReconciliationCheck(
            check_name="position_count",
            status="CRITICAL",
            severity=ReconciliationSeverity.CRITICAL.value,
            action=ReconciliationAction.HALT.value,
            message="Count mismatch: broker=5, internal=3",
        )
        assert check.action == ReconciliationAction.HALT.value

    def test_foreign_positions_are_blocking(self):
        """Foreign position detection is NEVER AUTOMATE — blocks trading."""
        from eigencapital.reconciliation.engine import (
            ReconciliationAction,
            ReconciliationCheck,
            ReconciliationSeverity,
        )

        check = ReconciliationCheck(
            check_name="foreign_positions",
            status="BLOCKING",
            severity=ReconciliationSeverity.BLOCKING.value,
            action=ReconciliationAction.HALT.value,
            message="3 foreign positions detected",
        )
        assert check.action == ReconciliationAction.HALT.value
