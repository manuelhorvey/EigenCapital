import pytest
import pandas as pd
import numpy as np
from monitoring.validity_state_machine import ValidityStateMachine, ValidityState, compute_allocation_statistics


class TestValidityStateMachine:
    def test_initial_state_is_yellow(self):
        sm = ValidityStateMachine()
        assert sm.current_state == ValidityState.YELLOW

    def test_transition_to_green_with_high_validity(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            regime_lock_periods=0,
        )
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert result["state"] == "GREEN"

    def test_transition_to_red_with_low_validity(self):
        sm = ValidityStateMachine(
            yellow_exit_threshold=0.40,
            regime_lock_periods=0,
        )
        sm.current_state = ValidityState.YELLOW
        result = sm.transition(0.30, pd.Timestamp("2020-01-01"))
        assert result["state"] == "RED"

    def test_hysteresis_keeps_green_above_exit_threshold(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            green_exit_threshold=0.60,
            regime_lock_periods=0,
        )
        sm.current_state = ValidityState.GREEN
        sm.periods_in_current_state = 5
        result = sm.transition(0.65, pd.Timestamp("2020-01-01"))
        assert result["state"] == "GREEN"

    def test_hysteresis_exits_green_below_exit_threshold(self):
        sm = ValidityStateMachine(
            green_exit_threshold=0.60,
            yellow_entry_threshold=0.45,
            regime_lock_periods=0,
        )
        sm.current_state = ValidityState.GREEN
        result = sm.transition(0.50, pd.Timestamp("2020-01-01"))
        assert result["state"] == "YELLOW"

    def test_regime_lock_blocks_premature_transition(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            regime_lock_periods=5,
        )
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert sm.current_state == ValidityState.YELLOW
        assert result["lock_active"]

    def test_regime_lock_allows_after_sufficient_periods(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            regime_lock_periods=3,
        )
        for i in range(3):
            sm.transition(0.85, pd.Timestamp(f"2020-01-{i+1}"))
        sm.transition(0.85, pd.Timestamp("2020-01-04"), pd.Series([0.85] * 3))
        assert sm.current_state == ValidityState.GREEN

    def test_exposure_mapping(self):
        sm = ValidityStateMachine(
            green_exposure=1.0,
            yellow_exposure=0.5,
            red_exposure=0.0,
            regime_lock_periods=0,
        )
        sm.current_state = ValidityState.GREEN
        r = sm.transition(0.80, pd.Timestamp("2020-01-01"))
        assert r["exposure"] == 1.0

    def test_reset(self):
        sm = ValidityStateMachine()
        sm.transition(0.85, pd.Timestamp("2020-01-01"))
        sm.reset()
        assert sm.current_state == ValidityState.YELLOW
        assert sm.state_history == []
        assert sm.periods_in_current_state == 0

    def test_process_timeline_returns_dataframe(self):
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=50, freq="D")
        validity = np.clip(np.random.randn(50) * 0.2 + 0.6, 0, 1)
        df = pd.DataFrame({"window": dates, "validity": validity})
        sm = ValidityStateMachine(regime_lock_periods=2)
        result = sm.process_timeline(df)
        assert isinstance(result, pd.DataFrame)
        assert "state" in result.columns
        assert "exposure" in result.columns

    def test_get_state_summary(self):
        sm = ValidityStateMachine()
        sm.transition(0.85, pd.Timestamp("2020-01-01"))
        summary = sm.get_state_summary()
        assert "current_state" in summary
        assert "total_transitions" in summary
        assert "transition_history" in summary

    def test_red_to_green_direct_skip(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            red_exit_threshold=0.50,
            regime_lock_periods=0,
        )
        sm.current_state = ValidityState.RED
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert result["state"] == "GREEN"

    def test_volatility_lock_blocks_transition(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            regime_lock_periods=0,
            regime_lock_window=10,
        )
        sm.current_state = ValidityState.YELLOW
        sm.periods_in_current_state = 5
        recent = pd.Series([0.3, 0.8, 0.3, 0.8, 0.3, 0.8, 0.3, 0.8, 0.3, 0.8])
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"), recent_validity=recent)
        assert result["lock_active"]
        assert "volatility" in result["lock_reason"].lower()

    def test_ema_inertia_produces_different_smoothed_values(self):
        sm = ValidityStateMachine(
            inertia_alpha=0.5,
            inertia_beta=0.5,
            regime_lock_periods=0,
        )
        r1 = sm.transition(1.0, pd.Timestamp("2020-01-01"))
        assert r1["smoothed_validity"] == 1.0
        r2 = sm.transition(0.0, pd.Timestamp("2020-01-02"))
        assert r2["smoothed_validity"] == 0.5
        r3 = sm.transition(0.0, pd.Timestamp("2020-01-03"))
        assert r3["smoothed_validity"] == 0.25

    def test_lock_reason_contents(self):
        sm = ValidityStateMachine(regime_lock_periods=3, green_entry_threshold=0.70)
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert result["lock_active"]
        assert "period" in result["lock_reason"]

    def test_consecutive_same_state_increments_periods(self):
        sm = ValidityStateMachine(regime_lock_periods=0)
        result = sm.transition(0.60, pd.Timestamp("2020-01-01"))
        assert result["periods_in_state"] == 1
        result = sm.transition(0.60, pd.Timestamp("2020-01-02"))
        assert result["periods_in_state"] == 2
        result = sm.transition(0.60, pd.Timestamp("2020-01-03"))
        assert result["periods_in_state"] == 3

    def test_transition_without_recent_validity_uses_fallback(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.70,
            regime_lock_periods=0,
        )
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert result["state"] == "GREEN"
        assert result["transition_occurred"]

    def test_custom_parameters(self):
        sm = ValidityStateMachine(
            green_entry_threshold=0.80,
            green_exit_threshold=0.70,
            yellow_entry_threshold=0.50,
            yellow_exit_threshold=0.45,
            red_entry_threshold=0.45,
            red_exit_threshold=0.55,
            inertia_alpha=0.6,
            inertia_beta=0.4,
            regime_lock_periods=0,
            regime_lock_window=8,
            green_exposure=0.9,
            yellow_exposure=0.4,
            red_exposure=0.0,
        )
        result = sm.transition(0.85, pd.Timestamp("2020-01-01"))
        assert result["exposure"] == 0.9
        assert result["state"] == "GREEN"


class TestComputeAllocationStatistics:
    def test_empty_dataframe(self):
        result = compute_allocation_statistics(pd.DataFrame())
        assert result == {}

    def test_state_distribution(self):
        df = pd.DataFrame({
            "state": ["GREEN", "GREEN", "YELLOW", "RED"],
            "exposure": [1.0, 1.0, 0.5, 0.0],
            "transition_occurred": [True, False, True, False],
            "lock_active": [False, False, True, False],
            "periods_in_state": [3, 4, 2, 1],
        })
        result = compute_allocation_statistics(df)
        assert result["state_distribution"]["GREEN"] == 0.5
        assert result["state_distribution"]["YELLOW"] == 0.25
        assert result["state_distribution"]["RED"] == 0.25


class TestValidityStateEnum:
    def test_has_correct_values(self):
        assert ValidityState.GREEN.value == "GREEN"
        assert ValidityState.YELLOW.value == "YELLOW"
        assert ValidityState.RED.value == "RED"


class TestCircuitBreaker:
    def test_no_trip_on_normal_conditions(self):
        from paper_trading.orchestrator.health import CircuitBreaker

        cb = CircuitBreaker(max_drawdown_pct=0.25, vol_spike_threshold=3.0, max_consecutive_losses=15)
        result = cb.check(portfolio_value=100.0)
        assert not result.trip
        assert result.severity == "info"

    def test_trip_on_vol_spike(self):
        from paper_trading.orchestrator.health import CircuitBreaker

        cb = CircuitBreaker(max_drawdown_pct=0.25, vol_spike_threshold=3.0)
        result = cb.check(portfolio_value=100.0, portfolio_vol=3.5, baseline_vol=1.0)
        assert result.trip
        assert "vol_spike" in result.reason

    def test_trip_on_consecutive_losses(self):
        from paper_trading.orchestrator.health import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=5)
        for _ in range(5):
            cb.check(portfolio_value=100.0)
            cb.record_daily_pnl(-1.0)
        result = cb.check(portfolio_value=99.0)
        assert result.trip
        assert "consecutive_loss" in result.reason

    def test_no_trip_on_consecutive_gains(self):
        from paper_trading.orchestrator.health import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=5)
        for i in range(6):
            cb.check(portfolio_value=100.0 + i)
            cb.record_daily_pnl(1.0)
        result = cb.check(portfolio_value=106.0)
        assert not result.trip
