"""Tests for shared/validation_gates.py — model deployment validation gates."""

import numpy as np

from shared.validation_gates import (
    gate_sharpe_improvement,
    gate_ece_not_worse,
    gate_ic_positive,
    gate_statistical_significance,
    gate_drawdown_not_worse,
    run_validation_gates,
)


class TestGateSharpeImprovement:
    def test_passes_when_sharpe_improves(self):
        r = gate_sharpe_improvement(0.5, 1.0)
        assert r.passed is True
        assert r.metric_value == 0.5

    def test_passes_when_sharpe_degradation_within_tolerance(self):
        r = gate_sharpe_improvement(1.0, 0.85, max_degradation=0.2)
        assert r.passed is True

    def test_fails_when_sharpe_degradation_exceeds_tolerance(self):
        r = gate_sharpe_improvement(1.0, 0.5, max_degradation=0.2)
        assert r.passed is False


class TestGateECENotWorse:
    def test_passes_when_ece_improves(self):
        r = gate_ece_not_worse(0.25, 0.10)
        assert r.passed is True

    def test_passes_when_degradation_within_tolerance(self):
        r = gate_ece_not_worse(0.25, 0.28, max_degradation=0.05)
        assert r.passed is True

    def test_fails_when_degradation_exceeds_tolerance(self):
        r = gate_ece_not_worse(0.25, 0.35, max_degradation=0.05)
        assert r.passed is False

    def test_defers_when_data_unavailable(self):
        r = gate_ece_not_worse(None, 0.10)
        assert r.passed is True
        assert "unavailable" in r.message


class TestGateICPositive:
    def test_passes_when_ic_positive(self):
        r = gate_ic_positive(0.05)
        assert r.passed is True

    def test_fails_when_ic_negative(self):
        r = gate_ic_positive(-0.02, min_ic=0.0)
        assert r.passed is False

    def test_defers_when_data_unavailable(self):
        r = gate_ic_positive(None)
        assert r.passed is True


class TestGateStatisticalSignificance:
    def test_passes_when_candidate_significantly_better(self):
        rng = np.random.default_rng(42)
        incumbent = rng.normal(0, 1, 100)
        candidate = incumbent + 0.5  # systematically better
        r = gate_statistical_significance(incumbent, candidate, p_threshold=0.10)
        assert r.passed is True

    def test_fails_when_not_significant_with_strict_threshold(self):
        rng = np.random.default_rng(42)
        # Near-identical distributions — p will be >> 0.001
        incumbent = rng.normal(0, 1, 1000)
        candidate = incumbent + rng.normal(0, 0.5, 1000) * 0.01
        r = gate_statistical_significance(incumbent, candidate, p_threshold=0.001)
        assert r.passed is False

    def test_defers_when_insufficient_data(self):
        r = gate_statistical_significance(
            np.array([0.1, 0.2]),
            np.array([0.3, 0.4]),
        )
        assert r.passed is True
        assert "Insufficient" in r.message


class TestGateDrawdownNotWorse:
    def test_passes_when_dd_improves(self):
        r = gate_drawdown_not_worse(-0.30, -0.20)
        assert r.passed is True

    def test_passes_when_degradation_within_tolerance(self):
        r = gate_drawdown_not_worse(-0.20, -0.30, max_degradation=0.20)
        assert r.passed is True

    def test_fails_when_degradation_exceeds_tolerance(self):
        r = gate_drawdown_not_worse(-0.10, -0.40, max_degradation=0.20)
        assert r.passed is False


class TestRunValidationGates:
    def test_all_gates_pass_with_good_candidate(self):
        incumbent = {"oos_sharpe": 0.5, "ece": 0.25, "oos_ic": 0.03, "oos_max_dd": -0.20}
        candidate = {"oos_sharpe": 1.0, "ece": 0.10, "oos_ic": 0.06, "oos_max_dd": -0.15}
        rng = np.random.default_rng(42)
        inc_ret = rng.normal(0.1, 1, 100)
        cand_ret = inc_ret + 0.3
        results = run_validation_gates("TEST", incumbent, candidate, inc_ret, cand_ret)
        assert all(r.passed for r in results)
        assert len(results) == 5

    def test_missing_data_defers_gates(self):
        results = run_validation_gates("TEST")
        assert all(r.passed for r in results)
        assert len(results) == 5
