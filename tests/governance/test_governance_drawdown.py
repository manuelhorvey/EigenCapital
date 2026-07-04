"""Tests for drawdown_controls — pure functions, no mocking needed."""

from __future__ import annotations

from paper_trading.governance.drawdown_controls import (
    check_drawdown_circuit_breaker,
    compute_drawdown,
    compute_exposure_multiplier,
)


class TestComputeDrawdown:
    def test_no_drawdown_when_at_peak(self):
        assert compute_drawdown(100.0, 100.0) == 0.0

    def test_no_drawdown_when_above_peak(self):
        assert compute_drawdown(110.0, 100.0) == 0.0

    def test_drawdown_below_peak(self):
        dd = compute_drawdown(80.0, 100.0)
        assert dd == -0.20

    def test_drawdown_zero_peak_returns_zero(self):
        assert compute_drawdown(100.0, 0.0) == 0.0

    def test_drawdown_negative_peak_returns_zero(self):
        assert compute_drawdown(100.0, -10.0) == 0.0


class TestComputeExposureMultiplier:
    def test_full_exposure_above_soft_limit(self):
        mult, halted = compute_exposure_multiplier(-0.05, drawdown_limit=-0.15, soft_limit=-0.10)
        assert mult == 1.0
        assert not halted

    def test_zero_exposure_at_hard_limit(self):
        mult, halted = compute_exposure_multiplier(-0.15, drawdown_limit=-0.15, soft_limit=-0.10)
        assert mult == 0.0
        assert halted

    def test_partial_exposure_between_limits(self):
        mult, halted = compute_exposure_multiplier(-0.125, drawdown_limit=-0.15, soft_limit=-0.10)
        # t = (-0.125 - -0.10) / (-0.15 - -0.10) = -0.025 / -0.05 = 0.5
        # mult = 1.0 - 0.5 = 0.5
        assert mult == 0.5
        assert not halted

    def test_exactly_at_soft_limit(self):
        mult, halted = compute_exposure_multiplier(-0.10, drawdown_limit=-0.15, soft_limit=-0.10)
        assert mult == 1.0
        assert not halted

    def test_below_hard_limit(self):
        mult, halted = compute_exposure_multiplier(-0.20, drawdown_limit=-0.15, soft_limit=-0.10)
        assert mult == 0.0
        assert halted


class TestCheckDrawdownCircuitBreaker:
    def test_normal_drawdown(self):
        result = check_drawdown_circuit_breaker(95.0, 100.0, drawdown_limit=-0.15, soft_limit=-0.10)
        assert result["drawdown"] == -0.05
        assert result["exposure_multiplier"] == 1.0
        assert not result["halted"]
        assert not result["breached"]

    def test_critical_drawdown_halt(self):
        result = check_drawdown_circuit_breaker(80.0, 100.0, drawdown_limit=-0.15, soft_limit=-0.10)
        assert result["drawdown"] == -0.20
        assert result["exposure_multiplier"] == 0.0
        assert result["halted"]
        assert result["breached"]

    def test_no_halt_when_halt_on_breach_false(self):
        result = check_drawdown_circuit_breaker(
            80.0, 100.0, drawdown_limit=-0.15, soft_limit=-0.10, halt_on_breach=False
        )
        assert result["exposure_multiplier"] == 0.0
        assert not result["halted"]
        assert result["breached"]

    def test_between_limits_not_halted(self):
        result = check_drawdown_circuit_breaker(87.0, 100.0, drawdown_limit=-0.15, soft_limit=-0.10)
        assert result["exposure_multiplier"] == 0.4  # t = 0.6, mult = 0.4
        assert not result["halted"]
        assert not result["breached"]
