"""Tests for statistical validation — hostile testing of research hypotheses.

The validation layer tries to DISPROVE trading edges, not confirm them.
These tests verify that the validation machinery itself is correct.
"""

import math
import pytest
from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult, purged_walk_forward, _compute_sharpe, _compute_returns,
)
from eigencapital.analytics.validation.bootstrap import (
    BootstrapResult, PermutationResult, bootstrap_test, permutation_test,
)
from eigencapital.analytics.validation.sensitivity import (
    SensitivityResult, parameter_sensitivity,
)
from eigencapital.analytics.validation.cost_stress import (
    CostStressResult, cost_stress_test,
)
from eigencapital.analytics.validation.regime import (
    RegimeResult, regime_analysis,
)
from eigencapital.analytics.validation.evidence_gate import (
    EvidenceGate, EvidenceVerdict,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_uptrend_equity(n: int = 1000, daily_drift: float = 0.0005) -> list:
    """Create equity curve with upward drift and realistic noise."""
    import random
    rng = random.Random(42)
    equity = [100_000.0]
    for i in range(n - 1):
        noise = rng.gauss(0, 0.008)
        equity.append(equity[-1] * (1 + daily_drift + noise))
    return equity


def _make_downtrend_equity(n: int = 1000, daily_drift: float = -0.0005) -> list:
    """Create equity curve with downward drift and realistic noise."""
    import random
    rng = random.Random(43)
    equity = [100_000.0]
    for i in range(n - 1):
        noise = rng.gauss(0, 0.008)
        equity.append(equity[-1] * (1 + daily_drift + noise))
    return equity


def _make_random_equity(n: int = 1000, seed: int = 42) -> list:
    """Create equity curve with random walk."""
    import random
    rng = random.Random(seed)
    equity = [100_000.0]
    for i in range(n - 1):
        ret = rng.gauss(0, 0.01)
        equity.append(equity[-1] * (1 + ret))
    return equity


# ── Walk-Forward Tests ───────────────────────────────────────────────────────

class TestWalkForward:
    """Tests for purged walk-forward analysis."""

    def test_insufficient_data(self):
        """Test walk-forward with insufficient data."""
        result = purged_walk_forward(
            equity_curve=[100, 101, 102],
            train_bars=500,
            test_bars=100,
        )
        assert result.total_windows == 0

    def test_uptrend_equity(self):
        """Test walk-forward on uptrend equity curve."""
        equity = _make_uptrend_equity(1000, 0.001)
        result = purged_walk_forward(
            equity_curve=equity,
            train_bars=300,
            test_bars=100,
            purge_bars=10,
        )
        assert result.total_windows > 0
        assert result.mean_oos_sharpe > 0  # Uptrend should have positive OOS Sharpe
        assert result.min_oos_sharpe <= result.mean_oos_sharpe
        assert result.max_oos_sharpe >= result.mean_oos_sharpe

    def test_downtrend_equity(self):
        """Test walk-forward on downtrend equity curve."""
        equity = _make_downtrend_equity(1000, -0.001)
        result = purged_walk_forward(
            equity_curve=equity,
            train_bars=300,
            test_bars=100,
        )
        assert result.total_windows > 0
        # Downtrend should have negative or low OOS Sharpe

    def test_anchored_walk_forward(self):
        """Test anchored (expanding window) walk-forward."""
        equity = _make_uptrend_equity(1000)
        result = purged_walk_forward(
            equity_curve=equity,
            train_bars=300,
            test_bars=100,
            anchored=True,
        )
        assert result.total_windows > 0

    def test_serialization(self):
        """Test deterministic serialization."""
        equity = _make_uptrend_equity(1000)
        result = purged_walk_forward(equity, train_bars=300, test_bars=100)
        d = result.to_dict()
        assert "mean_oos_sharpe" in d
        assert "degradation_ratio" in d
        assert "pct_profitable_windows" in d

    def test_compute_sharpe(self):
        """Test Sharpe ratio computation."""
        # Uniform positive returns → positive Sharpe
        returns = [0.001] * 100
        sharpe = _compute_sharpe(returns)
        assert sharpe > 0

        # Zero returns → zero Sharpe
        returns = [0.0] * 100
        sharpe = _compute_sharpe(returns)
        assert sharpe == 0.0

    def test_compute_returns(self):
        """Test return computation from equity curve."""
        equity = [100, 110, 105, 115]
        returns = _compute_returns(equity)
        assert len(returns) == 3
        assert abs(returns[0] - 0.10) < 0.001
        assert abs(returns[1] - (-5/110)) < 0.001

    def test_degradation_ratio(self):
        """Test degradation ratio computation."""
        equity = _make_uptrend_equity(1000)
        result = purged_walk_forward(equity, train_bars=300, test_bars=100)
        # Degradation should be positive
        assert result.degradation_ratio > 0


# ── Bootstrap Tests ──────────────────────────────────────────────────────────

class TestBootstrap:
    """Tests for bootstrap analysis."""

    def test_bootstrap_insufficient_data(self):
        """Test bootstrap with insufficient data."""
        result = bootstrap_test(returns=[0.01], n_bootstrap=100)
        assert result.n_bootstrap == 0

    def test_bootstrap_positive_returns(self):
        """Test bootstrap on positive returns."""
        returns = [0.001, 0.002, 0.001, 0.003, 0.002] * 20
        result = bootstrap_test(returns, n_bootstrap=500, seed=42)
        assert result.n_bootstrap == 500
        assert result.sharpe_mean > 0
        assert result.pct_positive_sharpe > 50
        assert result.sharpe_ci_lower < result.sharpe_ci_upper

    def test_bootstrap_reproducible(self):
        """Test bootstrap is reproducible with same seed."""
        returns = [0.001, -0.001, 0.002, -0.001, 0.003] * 20
        r1 = bootstrap_test(returns, n_bootstrap=200, seed=42)
        r2 = bootstrap_test(returns, n_bootstrap=200, seed=42)
        assert r1.sharpe_mean == r2.sharpe_mean
        assert r1.sharpe_ci_lower == r2.sharpe_ci_lower

    def test_bootstrap_serialization(self):
        """Test deterministic serialization."""
        returns = [0.001, 0.002, 0.001] * 20
        result = bootstrap_test(returns, n_bootstrap=100)
        d = result.to_dict()
        assert "sharpe_ci_lower" in d
        assert "pct_positive_sharpe" in d

    def test_permutation_insufficient_data(self):
        """Test permutation with insufficient data."""
        result = permutation_test(returns=[0.01], n_permutations=100)
        assert result.n_permutations == 0

    def test_permutation_random_returns(self):
        """Test permutation on random returns (should not be significant)."""
        import random
        rng = random.Random(42)
        returns = [rng.gauss(0, 0.01) for _ in range(200)]
        result = permutation_test(returns, n_permutations=500, seed=42)
        assert result.n_permutations == 500
        # Random returns should have p-value > 0.01 (not significant)
        assert result.p_value > 0.01

    def test_permutation_strong_signal(self):
        """Test permutation on strong signal (should be significant)."""
        # Strong positive signal with enough variance for meaningful Sharpe
        import random
        rng = random.Random(42)
        returns = [0.01 + rng.gauss(0, 0.015) for _ in range(500)]
        result = permutation_test(returns, n_permutations=500, seed=42)
        # With strong positive mean, observed Sharpe should beat most shuffles
        assert result.p_value < 0.05
        assert result.significant_at_5pct

    def test_permutation_serialization(self):
        """Test deterministic serialization."""
        returns = [0.001, -0.001, 0.002] * 20
        result = permutation_test(returns, n_permutations=100)
        d = result.to_dict()
        assert "p_value" in d
        assert "significant_at_5pct" in d


# ── Sensitivity Tests ────────────────────────────────────────────────────────

class TestSensitivity:
    """Tests for parameter sensitivity analysis."""

    def test_robust_parameters(self):
        """Test sensitivity with robust parameters."""
        result = parameter_sensitivity(
            base_sharpe=1.5,
            parameter_results={
                "lookback": [1.4, 1.5, 1.3],
                "threshold": [1.4, 1.5, 1.6],
            },
            degradation_threshold=0.3,
        )
        assert result.overall_robust is True
        assert result.base_sharpe == 1.5

    def test_sensitive_parameter(self):
        """Test sensitivity with one fragile parameter."""
        result = parameter_sensitivity(
            base_sharpe=1.5,
            parameter_results={
                "lookback": [1.4, 1.5, 1.3],  # Robust
                "threshold": [0.2, 1.5, 0.1],  # Fragile
            },
            degradation_threshold=0.3,
        )
        assert result.overall_robust is False
        assert result.worst_case_sharpe == 0.1

    def test_serialization(self):
        """Test deterministic serialization."""
        result = parameter_sensitivity(
            base_sharpe=1.0,
            parameter_results={"p1": [0.8, 1.0, 0.9]},
        )
        d = result.to_dict()
        assert "base_sharpe" in d
        assert "overall_robust" in d


# ── Cost Stress Tests ───────────────────────────────────────────────────────

class TestCostStress:
    """Tests for cost stress analysis."""

    def test_profitable_at_all_costs(self):
        """Test cost stress where strategy is robust."""
        result = cost_stress_test(
            base_sharpe=3.0,
            cost_multipliers=[1.0, 1.5, 2.0, 3.0, 5.0],
            sharpe_at_costs=[3.0, 2.5, 2.0, 1.0, 0.5],
        )
        assert result.survives_1_5x is True
        assert result.survives_2x is True
        assert result.max_survivable_multiplier == 5.0

    def test_unprofitable_at_high_costs(self):
        """Test cost stress where strategy fails at high costs."""
        result = cost_stress_test(
            base_sharpe=1.0,
            cost_multipliers=[1.0, 1.5, 2.0, 3.0],
            sharpe_at_costs=[1.0, 0.5, -0.2, -1.0],
        )
        assert result.survives_1_5x is True
        assert result.survives_2x is False
        assert result.max_survivable_multiplier == 1.5

    def test_breakeven_computation(self):
        """Test breakeven multiplier computation."""
        result = cost_stress_test(
            base_sharpe=1.0,
            cost_multipliers=[1.0, 2.0, 3.0],
            sharpe_at_costs=[1.0, 0.2, -0.5],
        )
        # Breakeven should be between 2.0 and 3.0
        assert 2.0 < result.breakeven_multiplier < 3.0

    def test_serialization(self):
        """Test deterministic serialization."""
        result = cost_stress_test(
            base_sharpe=1.0,
            cost_multipliers=[1.0, 2.0],
            sharpe_at_costs=[1.0, 0.5],
        )
        d = result.to_dict()
        assert "breakeven_multiplier" in d
        assert "levels" in d


# ── Regime Tests ─────────────────────────────────────────────────────────────

class TestRegime:
    """Tests for regime analysis."""

    def test_stable_across_regimes(self):
        """Test regime analysis with stable performance."""
        result = regime_analysis(
            regime_returns={
                "trending": [0.001, 0.002, 0.001, 0.002] * 10,
                "choppy": [0.001, 0.002, 0.001, 0.002] * 10,
                "crisis": [0.001, 0.002, 0.001, 0.002] * 10,
            },
            sharpe_threshold=1.0,
        )
        assert result.regime_dependent is False
        assert len(result.regimes) == 3

    def test_regime_dependent(self):
        """Test regime analysis with regime-dependent performance."""
        result = regime_analysis(
            regime_returns={
                "trending": [0.01, 0.02, 0.01, 0.02] * 10,  # Strong
                "choppy": [-0.01, -0.02, -0.01, -0.02] * 10,  # Weak
            },
            sharpe_threshold=0.5,
        )
        assert result.regime_dependent is True
        assert result.worst_regime == "choppy"
        assert result.best_regime == "trending"

    def test_serialization(self):
        """Test deterministic serialization."""
        result = regime_analysis(
            regime_returns={"up": [0.01] * 20, "down": [-0.01] * 20},
        )
        d = result.to_dict()
        assert "regimes" in d
        assert "worst_regime" in d


# ── Evidence Gate Tests ──────────────────────────────────────────────────────

class TestEvidenceGate:
    """Tests for evidence gate — hypothesis disposition."""

    def test_all_pass_candidate(self):
        """Test evidence gate with all checks passing."""
        import random
        from eigencapital.analytics.validation.universe import UniversePerturbationResult, ConcentrationMetrics
        from eigencapital.analytics.validation.temporal import TemporalStabilityResult
        rng = random.Random(42)
        gate = EvidenceGate()
        # Walk-forward on a strong uptrend
        wf = purged_walk_forward(_make_uptrend_equity(1000, 0.005), train_bars=300, test_bars=100)
        # Bootstrap: strong positive returns with realistic variance
        pos_returns = [0.01 + rng.gauss(0, 0.01) for _ in range(500)]
        boot = bootstrap_test(pos_returns, n_bootstrap=500, seed=42)
        # Permutation: strong signal
        perm_returns = [0.01 + rng.gauss(0, 0.01) for _ in range(500)]
        perm = permutation_test(perm_returns, n_permutations=500, seed=42)
        sens = parameter_sensitivity(1.5, {"p1": [1.4, 1.5, 1.3]})
        cost = cost_stress_test(1.5, [1.0, 1.5, 2.0], [1.5, 1.2, 0.8])
        regime = regime_analysis({"up": [0.01 + rng.gauss(0, 0.015) for _ in range(200)], "down": [0.008 + rng.gauss(0, 0.015) for _ in range(200)]})
        universe = UniversePerturbationResult(
            single_instrument_dependency=False,
            concentration=ConcentrationMetrics(herfindahl_index=0.3),
        )
        temporal = TemporalStabilityResult(window_count=5, performance_decay=False, pct_positive_sharpe=60.0)

        result = gate.evaluate(
            walk_forward=wf,
            bootstrap=boot,
            permutation=perm,
            sensitivity=sens,
            cost_stress=cost,
            regime=regime,
            universe=universe,
            temporal=temporal,
        )
        # Should be CANDIDATE or VALIDATED
        assert result["verdict"] in (EvidenceVerdict.CANDIDATE, EvidenceVerdict.VALIDATED)
        assert result["critical_failures"] == 0

    def test_rejected_on_cost_stress(self):
        """Test evidence gate rejects when cost stress fails."""
        gate = EvidenceGate()
        cost = cost_stress_test(
            base_sharpe=1.0,
            cost_multipliers=[1.0, 1.5, 2.0],
            sharpe_at_costs=[1.0, -0.5, -1.0],  # Fails at 1.5x
        )
        result = gate.evaluate(cost_stress=cost)
        assert result["verdict"] == EvidenceVerdict.REJECTED
        assert result["critical_failures"] > 0

    def test_inconclusive_on_weak_evidence(self):
        """Test evidence gate returns INCONCLUSIVE for weak evidence."""
        gate = EvidenceGate()
        wf = WalkForwardResult(
            total_windows=5,
            mean_oos_sharpe=0.3,
            degradation_ratio=3.0,  # High degradation → fails HIGH check
            pct_profitable_windows=40.0,  # Low → fails HIGH check
        )
        result = gate.evaluate(walk_forward=wf)
        assert result["verdict"] == EvidenceVerdict.INCONCLUSIVE

    def test_no_data_rejected(self):
        """Test evidence gate with no validation data → REJECTED."""
        gate = EvidenceGate()
        result = gate.evaluate()
        assert result["verdict"] == EvidenceVerdict.REJECTED
        assert len(result["missing_evidence"]) > 0

    def test_serialization(self):
        """Test evidence gate result serialization."""
        gate = EvidenceGate()
        result = gate.evaluate()
        assert "verdict" in result
        assert "checks" in result
        assert isinstance(result["checks"], list)
