"""Tests for risk/drawdown_controls — drawdown computation, exposure multiplier, and circuit breaker."""

import pytest

from risk.drawdown_controls import (
    compute_drawdown,
    compute_exposure_multiplier,
    check_drawdown_circuit_breaker,
)


class TestComputeDrawdown:
    def test_zero_drawdown_at_peak(self):
        assert compute_drawdown(100.0, 100.0) == 0.0

    def test_positive_drawdown_on_new_high(self):
        assert compute_drawdown(110.0, 100.0) == 0.0

    def test_five_percent_drawdown(self):
        dd = compute_drawdown(95.0, 100.0)
        assert dd == pytest.approx(-0.05)

    def test_twenty_percent_drawdown(self):
        dd = compute_drawdown(80.0, 100.0)
        assert dd == pytest.approx(-0.20)

    def test_zero_peak_returns_zero(self):
        assert compute_drawdown(100.0, 0.0) == 0.0

    def test_negative_peak_returns_zero(self):
        assert compute_drawdown(100.0, -50.0) == 0.0


class TestComputeExposureMultiplier:
    def test_full_exposure_above_soft_limit(self):
        mult, halted = compute_exposure_multiplier(-0.05, -0.15, -0.10)
        assert mult == pytest.approx(1.0)
        assert not halted

    def test_zero_exposure_at_hard_limit(self):
        mult, halted = compute_exposure_multiplier(-0.15, -0.15, -0.10)
        assert mult == pytest.approx(0.0)
        assert halted

    def test_zero_exposure_below_hard_limit(self):
        mult, halted = compute_exposure_multiplier(-0.20, -0.15, -0.10)
        assert mult == pytest.approx(0.0)
        assert halted

    def test_linear_interpolation_between_limits(self):
        # At midpoint between soft(-0.10) and hard(-0.15)
        mult, halted = compute_exposure_multiplier(-0.125, -0.15, -0.10)
        assert mult == pytest.approx(0.5)
        assert not halted

    def test_quarter_interpolation(self):
        mult, halted = compute_exposure_multiplier(-0.1125, -0.15, -0.10)
        assert mult == pytest.approx(0.75)
        assert not halted

    def test_three_quarter_interpolation(self):
        mult, halted = compute_exposure_multiplier(-0.1375, -0.15, -0.10)
        assert mult == pytest.approx(0.25)
        assert not halted

    def test_custom_limits(self):
        mult, halted = compute_exposure_multiplier(-0.05, -0.08, -0.03)
        assert mult == pytest.approx(0.6)
        assert not halted

    def test_exactly_at_soft_limit(self):
        mult, halted = compute_exposure_multiplier(-0.10, -0.15, -0.10)
        assert mult == pytest.approx(1.0)
        assert not halted


class TestCheckDrawdownCircuitBreaker:
    def test_no_breach_returns_safe(self):
        result = check_drawdown_circuit_breaker(95.0, 100.0, -0.15, -0.10)
        assert result["drawdown"] == pytest.approx(-0.05)
        assert result["exposure_multiplier"] == pytest.approx(1.0)
        assert not result["halted"]
        assert not result["breached"]

    def test_breach_at_limit_halted(self):
        result = check_drawdown_circuit_breaker(85.0, 100.0, -0.15, -0.10)
        assert result["drawdown"] == pytest.approx(-0.15)
        assert result["exposure_multiplier"] == pytest.approx(0.0)
        assert result["halted"]
        assert result["breached"]

    def test_breach_without_halt(self):
        result = check_drawdown_circuit_breaker(80.0, 100.0, -0.15, -0.10, halt_on_breach=False)
        assert result["drawdown"] == pytest.approx(-0.20)
        assert result["exposure_multiplier"] == pytest.approx(0.0)
        assert not result["halted"]
        assert result["breached"]

    def test_mid_range_reduced_exposure(self):
        result = check_drawdown_circuit_breaker(88.0, 100.0, -0.20, -0.05)
        assert result["drawdown"] == pytest.approx(-0.12)
        assert result["exposure_multiplier"] == pytest.approx(0.5333, abs=0.001)
        assert not result["halted"]
        assert not result["breached"]

    def test_new_high_no_drawdown(self):
        result = check_drawdown_circuit_breaker(105.0, 100.0)
        assert result["drawdown"] == pytest.approx(0.0)
        assert result["exposure_multiplier"] == pytest.approx(1.0)
        assert not result["halted"]

    def test_custom_limits(self):
        result = check_drawdown_circuit_breaker(92.0, 100.0, -0.05, -0.02)
        assert result["breached"]
        assert result["halted"]
