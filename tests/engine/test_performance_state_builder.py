"""Tests for PerformanceStateBuilder and its sub-trackers."""

import pytest

from paper_trading.pek.contracts.performance_state import PerformanceState
from paper_trading.pek.perf.performance_state_builder import (
    DegradationMonitor,
    ExecutionQualityTracker,
    MarketStateReader,
    PerformanceStateBuilder,
    VelocityProcessor,
)


class TestMarketStateReader:
    def test_default_scalar_is_range(self):
        reader = MarketStateReader()
        assert reader.scalar() == 1.0

    def test_trend_regime_returns_08(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=1.0, regime="TREND", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.scalar() == 0.8

    def test_range_returns_10(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=1.0, regime="RANGE", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.scalar() == 1.0

    def test_stressed_liquidity_returns_04(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=1.0, regime="TREND", spread_regime="NORMAL", liquidity_regime="STRESSED")
        assert reader.scalar() == 0.4

    def test_wide_spread_returns_06(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=1.0, regime="TREND", spread_regime="WIDE", liquidity_regime="NORMAL")
        assert reader.scalar() == 0.6

    def test_volatile_high_atr_returns_05(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=2.0, regime="VOLATILE", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.scalar() == 0.5

    def test_volatile_low_atr_returns_fallback(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=1.0, regime="VOLATILE", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.scalar() == 0.8

    def test_atr_ratio_velocity_zero_with_few_samples(self):
        reader = MarketStateReader()
        assert reader.atr_ratio_velocity() == 0.0
        reader.update(atr_ratio=1.0, regime="RANGE", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.atr_ratio_velocity() == 0.0

    def test_atr_ratio_velocity_computed_with_5_samples(self):
        reader = MarketStateReader()
        for i in range(5):
            reader.update(atr_ratio=float(i), regime="RANGE", spread_regime="NORMAL", liquidity_regime="NORMAL")
        vel = reader.atr_ratio_velocity()
        assert vel != 0.0

    def test_atr_ratio_default(self):
        reader = MarketStateReader()
        assert reader.atr_ratio() == 1.0

    def test_atr_ratio_after_update(self):
        reader = MarketStateReader()
        reader.update(atr_ratio=2.5, regime="TREND", spread_regime="NORMAL", liquidity_regime="NORMAL")
        assert reader.atr_ratio() == 2.5


class TestDegradationMonitor:
    def test_scalar_default_is_10(self):
        dm = DegradationMonitor()
        assert dm.scalar() == 1.0

    def test_low_ece_good_stability_returns_10(self):
        dm = DegradationMonitor()
        dm.update(ece=0.05, feature_stability=0.90)
        assert dm.scalar() == 1.0

    def test_moderate_ece_or_stability_returns_06(self):
        dm = DegradationMonitor()
        dm.update(ece=0.12, feature_stability=0.80)
        assert dm.scalar() == 0.6

    def test_high_ece_low_stability_returns_04(self):
        dm = DegradationMonitor()
        dm.update(ece=0.20, feature_stability=0.50)
        assert dm.scalar() == 0.4

    def test_ece_velocity_zero_with_few_samples(self):
        dm = DegradationMonitor()
        assert dm.ece_velocity() == 0.0
        for _ in range(4):
            dm.update(ece=0.1, feature_stability=0.8)
        assert dm.ece_velocity() == 0.0

    def test_ece_velocity_computed_after_5_samples(self):
        dm = DegradationMonitor()
        for i in range(5):
            dm.update(ece=0.1 + i * 0.02, feature_stability=0.8)
        vel = dm.ece_velocity()
        assert vel != 0.0


class TestExecutionQualityTracker:
    def test_scalar_default_is_10(self):
        eq = ExecutionQualityTracker()
        assert eq.scalar() == 1.0

    def test_slippage_p90_zero_with_few_samples(self):
        eq = ExecutionQualityTracker()
        assert eq.slippage_p90() == 0.0

    def test_slippage_p90_computed(self):
        eq = ExecutionQualityTracker()
        for i in range(10):
            eq.record_slippage(0.01 * (i + 1))
        p90 = eq.slippage_p90()
        assert 0.09 <= p90 <= 0.11

    def test_partial_fill_rate_zero_initially(self):
        eq = ExecutionQualityTracker()
        assert eq.partial_fill_rate() == 0.0

    def test_partial_fill_rate_after_trades(self):
        eq = ExecutionQualityTracker()
        eq.record_fill(was_partial=True)
        eq.record_fill(was_partial=False)
        eq.record_fill(was_partial=True)
        assert eq.partial_fill_rate() == pytest.approx(2.0 / 3.0)

    def test_scalar_low_with_high_partial_fill_rate(self):
        eq = ExecutionQualityTracker()
        for _ in range(5):
            eq.record_fill(was_partial=True)
        assert eq.scalar() == 0.5

    def test_scalar_low_with_high_slippage(self):
        eq = ExecutionQualityTracker()
        for _ in range(10):
            eq.record_slippage(3.5)
        assert eq.slippage_p90() > 3.0
        assert eq.scalar() == 0.6

    def test_record_trade_calls_outcome_tracker(self):
        eq = ExecutionQualityTracker()
        eq.record_trade(asset="EURUSD", exit_reason="TP", r_multiple=2.0, mae_pct=0.5, mfe_pct=3.0)
        assert eq._total_trades == 0

    def test_slippage_velocity_zero_with_few_samples(self):
        eq = ExecutionQualityTracker()
        assert eq.slippage_velocity() == 0.0
        for _ in range(9):
            eq.record_slippage(0.01)
        assert eq.slippage_velocity() == 0.0

    def test_slippage_velocity_computed(self):
        eq = ExecutionQualityTracker()
        for _ in range(10):
            eq.record_slippage(0.01)
        vel = eq.slippage_velocity()
        assert vel == pytest.approx(0.0)


class TestVelocityProcessor:
    def test_compute_defaults(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(pnl_velocity=0.0, vol_velocity=0.0, degradation_velocity=0.0, execution_velocity=0.0)
        assert scalar == 1.0

    def test_crash_detected(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(
            pnl_velocity=-0.03, vol_velocity=0.12, degradation_velocity=0.0, execution_velocity=0.0
        )
        assert 0.5 < scalar < 1.0

    def test_recovery_detected(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(
            pnl_velocity=0.03, vol_velocity=-0.10, degradation_velocity=0.0, execution_velocity=0.0
        )
        assert scalar > 1.0

    def test_shock_from_execution(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(pnl_velocity=0.0, vol_velocity=0.0, degradation_velocity=0.0, execution_velocity=0.15)
        assert 0.5 <= scalar < 1.0

    def test_high_degradation_velocity(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(pnl_velocity=0.0, vol_velocity=0.0, degradation_velocity=0.10, execution_velocity=0.0)
        assert 0.5 <= scalar < 1.0

    def test_scalar_clamped(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(
            pnl_velocity=0.03, vol_velocity=-0.10, degradation_velocity=0.0, execution_velocity=0.0
        )
        assert 1.0 <= scalar <= 1.5

    def test_return_velocity_object(self):
        vp = VelocityProcessor()
        vp.update_portfolio_value(100.0)
        vel, scalar = vp.compute(
            pnl_velocity=0.01, vol_velocity=0.02, degradation_velocity=0.01, execution_velocity=0.01
        )
        assert vel.pnl_velocity == 0.01
        assert vel.vol_velocity == 0.02


class TestPerformanceStateBuilder:
    def test_build_returns_performance_state(self):
        builder = PerformanceStateBuilder()
        state = builder.build(portfolio_value=100_000)
        assert isinstance(state, PerformanceState)
        assert state.version == 1

    def test_build_increments_version(self):
        builder = PerformanceStateBuilder()
        builder.build(100_000)
        s2 = builder.build(100_100)
        assert s2.version == 2

    def test_composite_in_range(self):
        builder = PerformanceStateBuilder()
        state = builder.build(100_000)
        assert 0.02 <= state.composite_scalar <= 1.2

    def test_ece_warning_logged_once(self, caplog):
        import logging

        caplog.set_level(logging.WARNING)
        builder = PerformanceStateBuilder()
        builder.build(100_000)
        builder.build(100_100)
        warnings = [r for r in caplog.records if "ECETracker was never connected" in r.message]
        assert len(warnings) == 1

    def test_ece_returns_zero(self):
        builder = PerformanceStateBuilder()
        state = builder.build(100_000)
        assert state.calibration_ece == 0.0

    def test_regime_label_default(self):
        builder = PerformanceStateBuilder()
        state = builder.build(100_000)
        assert state.regime_label == "RANGE"

    def test_atr_ratio_default(self):
        builder = PerformanceStateBuilder()
        state = builder.build(100_000)
        assert state.atr_ratio == 1.0

    def test_build_twice_same_version_increments(self):
        builder = PerformanceStateBuilder()
        state1 = builder.build(100_000)
        state2 = builder.build(100_000)
        assert state2.version == state1.version + 1

    def test_slippage_p90_default(self):
        builder = PerformanceStateBuilder()
        state = builder.build(100_000)
        assert state.slippage_p90 == 0.0

    def test_save_load_roundtrip(self):
        builder = PerformanceStateBuilder()
        builder.record_trade("EURUSD", "TP", 2.0, 0.1, 0.5)
        builder.record_trade("GBPUSD", "SL", -1.0, 0.3, 0.2)
        saved = builder.save_state()
        assert "outcomes" in saved
        assert len(saved["outcomes"]) == 2
        assert saved["outcomes"][0]["exit_reason"] == "TP"
        assert saved["consecutive_losses"] == 1

        builder2 = PerformanceStateBuilder()
        builder2.load_state(saved)
        restored = builder2.save_state()
        assert restored["outcomes"] == saved["outcomes"]
        assert restored["consecutive_losses"] == saved["consecutive_losses"]
        assert restored["r_sum"] == saved["r_sum"]
        assert restored["portfolio_value_history"] == saved["portfolio_value_history"]

    def test_load_state_with_none_does_not_raise(self):
        builder = PerformanceStateBuilder()
        builder.load_state(None)
        assert builder.save_state()["outcomes"] == []

    def test_load_state_with_empty_dict_does_not_raise(self):
        builder = PerformanceStateBuilder()
        builder.load_state({})
        assert builder.save_state()["outcomes"] == []
