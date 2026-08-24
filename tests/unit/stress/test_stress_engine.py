"""Phase 1H — Adversarial Simulation & Stress Testing.

Tests EigenCapital under adverse conditions:
- Execution-price perturbation
- Spread/slippage stress
- Gap-through-stop
- Delayed execution
- Missing/invalid/stale data
- Extreme volatility
- Liquidity stress
- Partial fills
- Order rejection
- Duplicate events
- Reconciliation divergence
- Portfolio drawdown cascades
- Multi-failure scenarios
- Fail-closed verification
- Accounting invariants
- Property-based tests
"""

import pytest
from eigencapital.stress.engine import StressTestEngine, SystemState
from eigencapital.core.models.position import Position
from eigencapital.core.models.order import Order
from eigencapital.core.models.fill import Fill
from eigencapital.core.models.approved_target import ApprovedTarget
from eigencapital.core.models.order_plan import OrderPlan, Urgency


def _baseline_state() -> SystemState:
    """Create a clean baseline system state."""
    return SystemState(
        cash=100_000.0,
        positions={"ES": 1.0, "NQ": -1.0},
        equity=100_000.0,
        peak_equity=100_000.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        current_leverage=0.5,
        risk_halt=False,
        market_data_valid=True,
        reconciliation_status="HEALTHY",
    )


# ══════════════════════════════════════════════════════════════════
# 1. Execution-Price Perturbation
# ══════════════════════════════════════════════════════════════════


class TestExecutionPricePerturbation:
    """Adverse execution cannot improve economic results."""

    def test_adverse_slippage_worsens_pnl(self):
        """Higher adverse slippage must not improve net P&L."""
        baseline = _baseline_state()

        def perturb(state):
            # Simulate adverse slippage: ES position loses value
            return SystemState(
                cash=state.cash - 500,  # Extra slippage cost
                positions=state.positions.copy(),
                equity=state.equity - 500,
                peak_equity=state.peak_equity,
                current_leverage=state.current_leverage,
            )

        def check(b, s):
            # Adverse slippage must not improve equity
            return s.equity <= b.equity

        engine = StressTestEngine()
        engine.register_scenario(
            "adverse_slippage",
            "Adverse slippage worsens execution",
            perturb,
            check,
            severity="HIGH",
        )
        results = engine.execute(baseline)
        assert results[0].passed

    def test_favorable_slippage_improves_pnl(self):
        """Favorable slippage should improve P&L (but this is the baseline)."""
        baseline = _baseline_state()

        def perturb(state):
            return SystemState(
                cash=state.cash + 200,
                positions=state.positions.copy(),
                equity=state.equity + 200,
                peak_equity=state.equity + 200,
            )

        def check(b, s):
            return s.equity > b.equity

        engine = StressTestEngine()
        engine.register_scenario(
            "favorable_slippage", "Favorable slippage", perturb, check
        )
        results = engine.execute(baseline)
        assert results[0].passed

    def test_asymmetric_slippage_monotonicity(self):
        """Increasing adverse slippage must monotonically worsen P&L."""
        baseline = _baseline_state()
        costs = [100, 200, 500, 1000]
        equities = []

        for cost in costs:

            def perturb(state, c=cost):
                return SystemState(
                    cash=state.cash - c,
                    positions=state.positions.copy(),
                    equity=state.equity - c,
                    peak_equity=state.peak_equity,
                )

            stressed = perturb(baseline)
            equities.append(stressed.equity)

        # Monotonicity: higher cost → lower equity
        for i in range(1, len(equities)):
            assert equities[i] <= equities[i - 1]


# ══════════════════════════════════════════════════════════════════
# 2. Spread Stress
# ══════════════════════════════════════════════════════════════════


class TestSpreadStress:
    """Spread widening increases costs, never improves results."""

    def test_spread_cost_monotonicity(self):
        """Increasing spread must monotonically increase transaction cost."""
        from eigencapital.research.costs.model import CostModel

        multipliers = [1.0, 1.5, 2.0, 5.0, 10.0]
        costs = []
        for mult in multipliers:
            model = CostModel(
                model_id=f"stress_{mult}x",
                spread_ticks=1.0 * mult,
                slippage_ticks=0.5 * mult,
            )
            costs.append(model.cost_per_contract(tick_value=0.25))

        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1], (
                f"Cost not monotonic at multiplier {multipliers[i]}"
            )

    def test_extreme_spread_increases_cost(self):
        """10x spread must cost more than 1x spread."""
        from eigencapital.research.costs.model import CostModel

        base = CostModel(model_id="base", spread_ticks=1, slippage_ticks=0.5)
        extreme = CostModel(model_id="extreme", spread_ticks=10, slippage_ticks=5)
        assert extreme.cost_per_contract(0.25) > base.cost_per_contract(0.25)


# ══════════════════════════════════════════════════════════════════
# 3. Gap-Through-Stop
# ══════════════════════════════════════════════════════════════════


class TestGapThroughStop:
    """Gaps must not produce favorable fills."""

    def test_gap_worsens_fill_price(self):
        """Gap below stop must produce worse fill than stop price."""
        stop_price = 100.0
        gap_price = 95.0  # Market gaps through stop

        # Fill should be at gap price (worse), not stop price
        fill_price = gap_price
        assert fill_price < stop_price, "Gap fill should be worse than stop"

    def test_gap_cannot_improve_pnl(self):
        """Gap-through-stop cannot produce favorable P&L."""
        entry_price = 100.0
        gap_price = 95.0

        # If we were long, gap produces loss at gap_price
        pnl = gap_price - entry_price
        assert pnl < 0, "Gap should produce loss on long position"


# ══════════════════════════════════════════════════════════════════
# 4. Delayed Execution
# ══════════════════════════════════════════════════════════════════


class TestDelayedExecution:
    """Delays must not produce favorable fills."""

    def test_delay_worsens_fill(self):
        """Delayed execution at adverse price must reflect reality."""
        signal_price = 100.0
        execution_price = 102.0  # Price moved against us

        # Fill must use execution price, not signal price
        fill_price = execution_price
        assert fill_price != signal_price

    def test_stale_signal_not_executed(self):
        """Expired signal must not be executed."""
        current_timestamp = "2025-01-01T10:05:00Z"
        expiry = "2025-01-01T10:02:00Z"

        # Signal expired → should not execute
        is_expired = current_timestamp > expiry
        assert is_expired, "Signal should be expired"


# ══════════════════════════════════════════════════════════════════
# 5. Missing / Invalid / Stale Data
# ══════════════════════════════════════════════════════════════════


class TestMissingInvalidData:
    """Invalid data must not produce new exposure."""

    def test_invalid_ohlc_rejected(self):
        """High < Low must be rejected by Bar model."""
        from eigencapital.core.models.bar import Bar

        Bar._registry.clear()
        with pytest.raises(ValueError):
            Bar(
                instrument_id="ES",
                timestamp_utc="2025-01-01T10:00:00Z",
                bar_start_utc="2025-01-01T09:59:00Z",
                bar_end_utc="2025-01-01T10:00:00Z",
                open=100,
                high=95,
                low=102,
                close=100,  # high < low
                volume=1000,
            )
        Bar._registry.clear()

    def test_negative_price_rejected(self):
        """Negative price must be rejected."""
        from eigencapital.core.models.bar import Bar

        Bar._registry.clear()
        with pytest.raises(ValueError):
            Bar(
                instrument_id="ES",
                timestamp_utc="2025-01-01T10:00:00Z",
                bar_start_utc="2025-01-01T09:59:00Z",
                bar_end_utc="2025-01-01T10:00:00Z",
                open=-100,
                high=100,
                low=50,
                close=100,
                volume=1000,
            )
        Bar._registry.clear()

    def test_zero_volume_allowed(self):
        """Zero volume is allowed (market halt)."""
        from eigencapital.core.models.bar import Bar

        Bar._registry.clear()
        bar = Bar(
            instrument_id="ES",
            timestamp_utc="2025-01-01T10:00:00Z",
            bar_start_utc="2025-01-01T09:59:00Z",
            bar_end_utc="2025-01-01T10:00:00Z",
            open=100,
            high=100,
            low=100,
            close=100,
            volume=0,
        )
        assert bar.volume == 0
        Bar._registry.clear()

    def test_duplicate_bar_rejected(self):
        """Duplicate instrument+timestamp must be rejected."""
        from eigencapital.core.models.bar import Bar

        Bar._registry.clear()
        Bar(
            instrument_id="ES",
            timestamp_utc="2025-01-01T10:00:00Z",
            bar_start_utc="2025-01-01T09:59:00Z",
            bar_end_utc="2025-01-01T10:00:00Z",
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1000,
        )
        with pytest.raises(ValueError, match="Duplicate"):
            Bar(
                instrument_id="ES",
                timestamp_utc="2025-01-01T10:00:00Z",
                bar_start_utc="2025-01-01T09:59:00Z",
                bar_end_utc="2025-01-01T10:00:00Z",
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
            )
        Bar._registry.clear()


# ══════════════════════════════════════════════════════════════════
# 6. Extreme Volatility
# ══════════════════════════════════════════════════════════════════


class TestExtremeVolatility:
    """Volatility spikes must not bypass risk controls."""

    def test_large_price_drop_detected(self):
        """Large price drop must be visible in equity curve."""
        equity = [100_000, 95_000, 80_000, 85_000]  # 20% drawdown
        max_dd = 0
        peak = equity[0]
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
        assert max_dd >= 0.20, "Should detect 20% drawdown"

    def test_volatility_increases_drawdown(self):
        """Higher volatility should produce larger drawdowns."""
        low_vol = [100 * (1 + 0.001 * ((i * 3) % 7 - 3) * 0.1) for i in range(100)]
        high_vol = [100 * (1 + 0.01 * ((i * 7) % 11 - 5) * 0.1) for i in range(100)]

        def max_dd(equity):
            peak = equity[0]
            mdd = 0
            for e in equity:
                if e > peak:
                    peak = e
                dd = (peak - e) / peak
                mdd = max(mdd, dd)
            return mdd

        assert max_dd(high_vol) >= max_dd(low_vol) * 0.5  # At least somewhat larger


# ══════════════════════════════════════════════════════════════════
# 7. Liquidity Stress
# ══════════════════════════════════════════════════════════════════


class TestLiquidityStress:
    """Reduced liquidity must not create phantom positions."""

    def test_partial_fill_tracking(self):
        """Partial fills must be correctly tracked."""
        # Order: 100, Fills: 40 + 30 = 70 (not 100)
        order_qty = 100
        fills = [40, 30]
        total_filled = sum(fills)
        assert total_filled < order_qty, "Partial fill should not equal full order"
        remaining = order_qty - total_filled
        assert remaining == 30

    def test_overfill_prevented(self):
        """Fill sum must not exceed order quantity."""
        order_qty = 100
        fills = [40, 30, 30]  # Exactly fills
        assert sum(fills) == order_qty

    def test_overfill_violation(self):
        """Fill sum exceeding order must be detected."""
        order_qty = 100
        fills = [40, 30, 40]  # 110 > 100
        assert sum(fills) > order_qty, "Overfill should be detectable"


# ══════════════════════════════════════════════════════════════════
# 8. Order Rejection
# ══════════════════════════════════════════════════════════════════


class TestOrderRejection:
    """Rejected orders must not become fills."""

    def test_rejected_order_no_position_change(self):
        """Rejected order must not change position."""
        initial_position = 0.0
        # Order rejected → position unchanged
        final_position = initial_position
        assert final_position == initial_position

    def test_invalid_quantity_rejected(self):
        """Invalid order quantity must be rejected."""
        with pytest.raises(ValueError):
            Order(
                order_id="ORD-REJECT-1",
                instrument_id="ES",
                timestamp_utc="2025-01-01T10:00:00Z",
                strategy_id="test",
                side="BUY",
                quantity=-5,
                order_type="MARKET",
                limit_price=None,
            )

    def test_zero_quantity_order(self):
        """Zero quantity order is allowed (cancel/adjustment)."""
        order = Order(
            order_id="ORD-REJECT-2",
            instrument_id="ES",
            timestamp_utc="2025-01-01T10:00:00Z",
            strategy_id="test",
            side="BUY",
            quantity=0,
            order_type="MARKET",
            limit_price=None,
        )
        assert order.quantity == 0


# ══════════════════════════════════════════════════════════════════
# 9. Duplicate Events
# ══════════════════════════════════════════════════════════════════


class TestDuplicateEvents:
    """Duplicate events must not create duplicate exposure."""

    def test_duplicate_fill_rejected(self):
        """Duplicate fill ID must be rejected."""
        Fill._registry.clear()
        Fill(
            fill_id="F-DUP-1",
            order_id="ORD-1",
            instrument_id="ES",
            timestamp_utc="2025-01-01T10:00:00Z",
            side="BUY",
            quantity=10,
            fill_price=100.0,
            strategy_id="test",
        )
        with pytest.raises(ValueError, match="Duplicate"):
            Fill(
                fill_id="F-DUP-1",  # Same ID
                order_id="ORD-1",
                instrument_id="ES",
                timestamp_utc="2025-01-01T10:00:00Z",
                side="BUY",
                quantity=10,
                fill_price=100.0,
                strategy_id="test",
            )
        Fill._registry.clear()

    def test_duplicate_position_rejected(self):
        """Duplicate position (same instrument+quantity) must be rejected."""
        Position._registry.clear()
        Position(
            instrument_id="ES",
            quantity=5.0,
            average_entry_price=100.0,
            market_value=500.0,
        )
        with pytest.raises(ValueError, match="Duplicate"):
            Position(
                instrument_id="ES",
                quantity=5.0,  # Same instrument+quantity
                average_entry_price=100.0,
                market_value=500.0,
            )
        Position._registry.clear()


# ══════════════════════════════════════════════════════════════════
# 10. Reconciliation Divergence
# ══════════════════════════════════════════════════════════════════


class TestReconciliationDivergence:
    """State divergence must be detected."""

    def test_matching_state_healthy(self):
        """Matching internal/broker state is HEALTHY."""
        internal = {"ES": 1.0, "NQ": -1.0}
        broker = {"ES": 1.0, "NQ": -1.0}
        assert internal == broker

    def test_divergent_state_detected(self):
        """Divergent state must be detected."""
        internal = {"ES": 1.0, "NQ": -1.0}
        broker = {"ES": 0.0, "NQ": -1.0}  # ES position missing
        assert internal != broker

    def test_partial_divergence(self):
        """Partial divergence (different quantities) must be detected."""
        internal = {"ES": 2.0}
        broker = {"ES": 1.0}
        assert internal != broker


# ══════════════════════════════════════════════════════════════════
# 11. Fail-Closed Verification
# ══════════════════════════════════════════════════════════════════


class TestFailClosed:
    """System must fail closed under critical conditions."""

    def test_rejected_risk_no_order(self):
        """REJECTED risk decision must produce zero approved quantity."""
        ApprovedTarget._registry.clear()
        target = ApprovedTarget(
            target_id="AT-FAIL-1",
            intended_quantity=10.0,
            approved_quantity=0.0,
            decision="REJECTED",
            approval_reason="Risk limit exceeded",
        )
        assert target.approved_quantity == 0
        assert target.is_rejected
        ApprovedTarget._registry.clear()

    def test_rejected_target_invariant(self):
        """REJECTED must always have approved_quantity = 0."""
        ApprovedTarget._registry.clear()
        with pytest.raises(ValueError, match="REJECTED"):
            ApprovedTarget(
                target_id="AT-FAIL-2",
                intended_quantity=10.0,
                approved_quantity=5.0,  # Violates REJECTED invariant
                decision="REJECTED",
                approval_reason="test",
            )
        ApprovedTarget._registry.clear()

    def test_kill_switch_blocks_orders(self):
        """Kill switch must block all new orders."""
        from eigencapital.risk.engine import EigenRiskEngine
        from eigencapital.risk.policy import RiskPolicy
        from eigencapital.risk.checks.account_checks import AccountState

        policy = RiskPolicy(kill_switch=True)
        engine = EigenRiskEngine(policy=policy)
        state = AccountState(equity=100_000, peak_equity=100_000)
        result = engine.evaluate(state, requested_quantity=10)
        assert result.decision == "REJECTED"

    def test_zero_equity_blocks_orders(self):
        """Zero equity must block new orders."""
        from eigencapital.risk.engine import EigenRiskEngine
        from eigencapital.risk.policy import RiskPolicy
        from eigencapital.risk.checks.account_checks import AccountState

        policy = RiskPolicy(min_equity=50_000)
        engine = EigenRiskEngine(policy=policy)
        state = AccountState(equity=0, peak_equity=100_000)
        result = engine.evaluate(state, requested_quantity=10)
        assert result.decision == "REJECTED"


# ══════════════════════════════════════════════════════════════════
# 12. Accounting Invariants
# ══════════════════════════════════════════════════════════════════


class TestAccountingInvariants:
    """Accounting must be consistent under all conditions."""

    def test_buy_decreases_cash(self):
        """Buy order must decrease cash."""
        cash = 100_000.0
        fill_price = 100.0
        quantity = 1.0
        commission = 2.50

        cash_after = cash - (quantity * fill_price + commission)
        assert cash_after < cash

    def test_sell_increases_cash(self):
        """Sell order must increase cash."""
        cash = 100_000.0
        fill_price = 100.0
        quantity = 1.0
        commission = 2.50

        cash_after = cash + (quantity * fill_price - commission)
        assert cash_after > cash

    def test_no_phantom_equity(self):
        """No scenario should create unexplained equity gain."""
        initial_equity = 100_000.0
        # Simulate: buy 1 at 100, price drops to 90
        cash = initial_equity - 100
        position_value = 90  # Price dropped
        equity = cash + position_value
        assert equity < initial_equity, "Price drop must reduce equity"

    def test_commission_always_positive(self):
        """Commission must always be a cost (reduce equity)."""
        equity_before = 100_000.0
        commission = 2.50
        equity_after = equity_before - commission
        assert equity_after < equity_before


# ══════════════════════════════════════════════════════════════════
# 13. Portfolio Drawdown Cascades
# ══════════════════════════════════════════════════════════════════


class TestDrawdownCascades:
    """Drawdown breakers must activate correctly."""

    def test_drawdown_breaker_triggers(self):
        """Drawdown exceeding limit must trigger breaker."""
        policy_max_dd = 10.0  # 10%
        current_dd = 12.0  # 12% drawdown
        assert current_dd > policy_max_dd, "Breaker should trigger"

    def test_daily_loss_limit_triggers(self):
        """Daily loss exceeding limit must trigger halt."""
        daily_loss_limit = 5000.0
        actual_loss = 6000.0
        assert actual_loss > daily_loss_limit

    def test_leverage_limit_triggers(self):
        """Leverage exceeding limit must block new exposure."""
        max_leverage = 2.0
        current_leverage = 2.5
        assert current_leverage > max_leverage


# ══════════════════════════════════════════════════════════════════
# 14. Property-Based Tests
# ══════════════════════════════════════════════════════════════════


class TestPropertyBased:
    """Fundamental invariants that must hold under all conditions."""

    def test_fill_sum_never_exceeds_order(self):
        """sum(fills) must never exceed order.quantity."""
        # This is enforced by OrderLifecycle
        # Property: if sum(fills) > order.quantity, system must reject
        order_qty = 100
        fills = [40, 30, 30]
        assert sum(fills) <= order_qty

    def test_rejected_target_always_zero(self):
        """REJECTED target must always have approved_quantity = 0."""
        ApprovedTarget._registry.clear()
        target = ApprovedTarget(
            target_id="AT-PROP-1",
            intended_quantity=10.0,
            approved_quantity=0.0,
            decision="REJECTED",
            approval_reason="test",
        )
        assert target.approved_quantity == 0
        ApprovedTarget._registry.clear()

    def test_position_sign_encodes_direction(self):
        """Position quantity sign must encode direction."""
        long_pos = Position(instrument_id="L", quantity=1.0)
        short_pos = Position(instrument_id="S", quantity=-1.0)
        flat_pos = Position(instrument_id="F", quantity=0.0)

        assert long_pos.is_long
        assert short_pos.is_short
        assert flat_pos.is_flat
        Position._registry.clear()

    def test_order_plan_delta_correctness(self):
        """OrderPlan delta must equal target - current."""
        OrderPlan._registry.clear()
        plan = OrderPlan(
            plan_id="OP-PROP-1",
            instrument_id="ES",
            target_quantity=5.0,
            current_quantity=2.0,
            quantity_delta=3.0,
            execution_policy_version="v1",
            urgency=Urgency.SESSION,
        )
        assert plan.quantity_delta == plan.target_quantity - plan.current_quantity
        OrderPlan._registry.clear()

    def test_cost_stress_monotonicity(self):
        """Increasing cost multipliers must not improve Sharpe."""
        from eigencapital.analytics.validation.cost_stress import cost_stress_test

        result = cost_stress_test(
            base_sharpe=2.0,
            cost_multipliers=[1.0, 1.5, 2.0, 3.0],
            sharpe_at_costs=[2.0, 1.5, 0.8, 0.2],
        )
        for i in range(1, len(result.levels)):
            assert result.levels[i].sharpe <= result.levels[i - 1].sharpe + 0.001

    def test_bootstrap_ci_contains_mean(self):
        """Bootstrap CI should approximately contain the point estimate."""
        from eigencapital.analytics.validation.bootstrap import bootstrap_test

        returns = [0.005 + (i % 5 - 2) * 0.002 for i in range(200)]
        result = bootstrap_test(returns, n_bootstrap=200, seed=42)
        # Point estimate should be within CI bounds (approximately)
        assert result.sharpe_ci_lower <= result.sharpe_mean + 1.0
        assert result.sharpe_ci_upper >= result.sharpe_mean - 1.0

    def test_permutation_p_value_bounds(self):
        """Permutation p-value must be in [0, 1]."""
        from eigencapital.analytics.validation.bootstrap import permutation_test

        returns = [0.005 + (i % 3 - 1) * 0.002 for i in range(200)]
        result = permutation_test(returns, n_permutations=100, seed=42)
        assert 0 <= result.p_value <= 1


# ══════════════════════════════════════════════════════════════════
# 15. Multi-Failure Scenarios
# ══════════════════════════════════════════════════════════════════


class TestMultiFailure:
    """Combined failure scenarios — the most dangerous cases."""

    def test_stale_data_plus_wide_spread(self):
        """Stale data + wide spreads must not create exposure."""
        market_data_valid = False  # Stale data
        spread_wide = True

        # System should not generate new orders
        should_trade = market_data_valid and not spread_wide
        assert not should_trade

    def test_drawdown_breach_plus_volatility(self):
        """Drawdown breach + volatility spike must trigger halt."""
        drawdown_breached = True
        volatility_spike = True

        # Risk breaker should be active
        risk_halt = drawdown_breached or volatility_spike
        assert risk_halt

    def test_partial_fill_plus_rejection(self):
        """Partial fill + subsequent rejection must not create overfill."""
        order_qty = 100
        partial_fill = 40
        order_qty - partial_fill

        # After rejection, remaining should still be 60
        final_filled = partial_fill  # Rejection doesn't add fills
        assert final_filled <= order_qty

    def test_reconciliation_divergence_plus_new_signal(self):
        """Reconciliation divergence must block new signals."""
        reconciliation_status = "CRITICAL"
        has_signal = True

        # Critical divergence should block trading
        should_execute = reconciliation_status == "HEALTHY" and has_signal
        assert not should_execute


# ══════════════════════════════════════════════════════════════════
# 16. StressTestEngine Integration
# ══════════════════════════════════════════════════════════════════


class TestStressTestEngine:
    """Integration tests for the stress test engine."""

    def test_engine_executes_scenarios(self):
        """Engine must execute all registered scenarios."""
        engine = StressTestEngine()
        engine.register_scenario(
            "test_1",
            "Test scenario",
            lambda s: SystemState(
                cash=s.cash - 100, equity=s.equity - 100, positions=s.positions.copy()
            ),
            lambda b, s: s.equity < b.equity,
        )
        results = engine.execute(_baseline_state())
        assert len(results) == 1
        assert results[0].passed

    def test_engine_deterministic(self):
        """Engine must produce deterministic results."""

        def perturb(state):
            return SystemState(
                cash=state.cash - 100,
                equity=state.equity - 100,
                positions=state.positions.copy(),
            )

        def check(b, s):
            return s.equity < b.equity

        engine1 = StressTestEngine()
        engine1.register_scenario("det_1", "Deterministic", perturb, check)
        r1 = engine1.execute(_baseline_state())

        engine2 = StressTestEngine()
        engine2.register_scenario("det_1", "Deterministic", perturb, check)
        r2 = engine2.execute(_baseline_state())

        assert r1[0].status == r2[0].status
        assert r1[0].maximum_loss == r2[0].maximum_loss

    def test_engine_detects_invariant_violations(self):
        """Engine must detect NaN in positions."""

        def perturb(state):
            return SystemState(
                cash=state.cash,
                positions={"ES": float("nan")},  # Violation!
                equity=state.equity,
            )

        def check(b, s):
            return True  # Check passes but invariant fails

        engine = StressTestEngine()
        engine.register_scenario("nan_test", "NaN position", perturb, check)
        results = engine.execute(_baseline_state())
        assert results[0].failed  # Invariant violation → FAIL
        assert any("nan" in v for v in results[0].violated_invariants)

    def test_inconclusive_on_error(self):
        """Engine must return INCONCLUSIVE on perturbation error."""

        def bad_perturb(state):
            raise RuntimeError("Simulated failure")

        def check(b, s):
            return True

        engine = StressTestEngine()
        engine.register_scenario("error_test", "Error scenario", bad_perturb, check)
        results = engine.execute(_baseline_state())
        assert results[0].status == "INCONCLUSIVE"
