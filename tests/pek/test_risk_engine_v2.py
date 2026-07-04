"""Tests for RiskEngineV2 adaptive risk budgeting."""
import pytest

from eigencapital.domain.time import utc_now
from paper_trading.pek.contracts.performance_state import PerformanceState, RegimeVelocity
from paper_trading.pek.contracts.portfolio_state import PortfolioStateSnapshot
from paper_trading.pek.engine_v2 import RiskEngineV2


def _snapshot(**overrides) -> PortfolioStateSnapshot:
    kwargs = dict(
        version=1,
        generated_at=utc_now(),
        mode="production",
        total_equity=100_000.0,
        peak_value=100_000.0,
        drawdown_pct=0.0,
        positions=(),
        total_long_notional=50_000.0,
        total_short_notional=0.0,
        gross_exposure=50_000.0,
        net_exposure=50_000.0,
        open_position_count=1,
        daily_pnl=0.0,
        daily_loss_remaining=1000.0,
        max_daily_loss=2000.0,
        drawdown_remaining=15_000.0,
        leverage_remaining=150_000.0,
        max_leverage=2.0,
        concurrent_remaining=20,
        max_concurrent=21,
        factor_exposures=(),
        factor_limits=(),
        factor_headroom=(),
        clusters=(),
        asset_gates=(),
        max_risk_per_trade_pct=1.0,
        min_risk_per_trade_pct=0.10,
        position_ranking_enabled=False,
    )
    kwargs.update(overrides)
    return PortfolioStateSnapshot(**kwargs)


def _perf(velocity_scalar=1.0, **overrides) -> PerformanceState:
    kwargs = dict(
        version=1,
        generated_at=utc_now(),
        outcome_scalar=1.0,
        degradation_scalar=1.0,
        market_scalar=1.0,
        execution_scalar=1.0,
        velocity=RegimeVelocity(
            pnl_velocity=0.0, pnl_acceleration=0.0,
            vol_velocity=0.0, degradation_velocity=0.0, execution_velocity=0.0,
        ),
        velocity_scalar=velocity_scalar,
        composite_scalar=1.0,
        win_rate_20=0.5,
        consecutive_losses=0,
        r_cumulative_20=0.0,
        calibration_ece=0.0,
        atr_ratio=1.0,
        regime_label="RANGE",
        slippage_p90=0.0,
    )
    kwargs.update(overrides)
    return PerformanceState(**kwargs)


class TestRiskEngineV2:
    def test_normal_conditions_returns_base_risk(self):
        engine = RiskEngineV2({"max_risk_per_trade_pct": 1.0, "min_risk_per_trade_pct": 0.10})
        budget = engine.compute_budget(_snapshot(), _perf())
        assert budget.max_risk_per_trade_pct == 1.0

    def test_at_drawdown_limit_effective_zero(self):
        engine = RiskEngineV2({"max_risk_per_trade_pct": 1.0, "min_risk_per_trade_pct": 0.10, "max_drawdown_pct": -0.15})
        budget = engine.compute_budget(_snapshot(drawdown_pct=-0.15), _perf())
        assert budget.max_risk_per_trade_pct == 0.0

    def test_min_risk_floor_applied_not_at_limit(self):
        engine = RiskEngineV2({"max_risk_per_trade_pct": 1.0, "min_risk_per_trade_pct": 0.10, "max_drawdown_pct": -0.15})
        # Perf scalar 0.3 should push below min_risk floor
        budget = engine.compute_budget(_snapshot(drawdown_pct=-0.05), _perf(composite_scalar=0.3, velocity_scalar=0.3))
        assert budget.max_risk_per_trade_pct >= 0.10

    def test_heat_cap_computed_correctly(self):
        engine = RiskEngineV2({"max_leverage": 2.0})
        # Gross exposure is 50K on 100K equity = 0.5 heat, well under 90% of 2.0
        budget = engine.compute_budget(_snapshot(), _perf())
        assert budget.max_portfolio_heat == 2.0

    def test_scalars_in_budget(self):
        engine = RiskEngineV2({})
        budget = engine.compute_budget(_snapshot(), _perf())
        assert 0.0 < budget.drawdown_scalar <= 1.0
        assert 0.0 < budget.performance_scalar <= 1.0

    def test_velocity_scalar_from_perf_state(self):
        engine = RiskEngineV2({})
        budget = engine.compute_budget(_snapshot(), _perf(velocity_scalar=0.8))
        assert budget.velocity_scalar == 0.8
