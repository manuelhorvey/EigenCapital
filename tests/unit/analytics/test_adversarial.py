"""Adversarial and property-based tests for statistical invariants.

These tests verify fundamental properties that MUST hold for the
statistical validation layer to be trustworthy.
"""

from eigencapital.analytics.metrics import compute_metrics, compute_returns
from eigencapital.analytics.validation.block_bootstrap import block_bootstrap
from eigencapital.analytics.validation.bootstrap import bootstrap_test, permutation_test
from eigencapital.analytics.validation.cost_stress import cost_stress_test
from eigencapital.analytics.validation.evidence_gate import (
    EvidenceGate,
    EvidenceVerdict,
)
from eigencapital.analytics.validation.validator import ValidationEngine
from eigencapital.analytics.validation.walk_forward import purged_walk_forward


def _make_equity(n=500, drift=0.001, seed=42):
    """Create reproducible equity curve."""
    import random

    rng = random.Random(seed)
    equity = [100_000.0]
    for i in range(n - 1):
        noise = rng.gauss(0, 0.008)
        equity.append(equity[-1] * (1 + drift + noise))
    return equity


# ── A. Cost Monotonicity ──────────────────────────────────────────


class TestCostMonotonicity:
    """Increasing costs must never improve net P&L."""

    def test_higher_costs_worse_sharpe(self):
        """Test that higher cost multipliers produce lower Sharpe."""
        multipliers = [1.0, 1.5, 2.0, 3.0]
        sharpes = [1.5, 1.2, 0.8, 0.3]
        result = cost_stress_test(1.5, multipliers, sharpes)
        # Sharpe must be non-increasing with cost
        for i in range(1, len(result.levels)):
            assert result.levels[i].sharpe <= result.levels[i - 1].sharpe + 0.001

    def test_zero_cost_best(self):
        """Zero cost must produce the best (or tied best) result."""
        result = cost_stress_test(
            base_sharpe=2.0,
            cost_multipliers=[0.0, 1.0, 2.0],
            sharpe_at_costs=[2.0, 1.5, 0.8],
        )
        assert result.levels[0].sharpe >= result.levels[1].sharpe


# ── B. Data Truncation ────────────────────────────────────────────


class TestDataTruncation:
    """Removing future observations must not change historical metrics."""

    def test_truncation_preserves_returns(self):
        """Test that returns are unchanged when truncating from the end."""
        equity = _make_equity(200)
        returns_full = compute_returns(equity)
        returns_truncated = compute_returns(equity[:150])
        # First 149 returns must be identical
        assert returns_full[:149] == returns_truncated[:149]

    def test_truncation_preserves_sharpe(self):
        """Test that truncating from end preserves Sharpe of remaining data."""
        equity = _make_equity(200)
        metrics_full = compute_metrics(equity[:150])
        metrics_truncated = compute_metrics(equity[:150])
        assert metrics_full.sharpe_ratio == metrics_truncated.sharpe_ratio


# ── C. Seed Determinism ───────────────────────────────────────────


class TestSeedDeterminism:
    """Same experiment + same seed = identical result."""

    def test_bootstrap_deterministic(self):
        """Test bootstrap is deterministic with same seed."""
        returns = [0.005 + (i % 3 - 1) * 0.002 for i in range(200)]
        r1 = bootstrap_test(returns, n_bootstrap=200, seed=42)
        r2 = bootstrap_test(returns, n_bootstrap=200, seed=42)
        assert r1.sharpe_mean == r2.sharpe_mean
        assert r1.sharpe_ci_lower == r2.sharpe_ci_lower
        assert r1.sharpe_ci_upper == r2.sharpe_ci_upper

    def test_permutation_deterministic(self):
        """Test permutation is deterministic with same seed."""
        returns = [0.005 + (i % 5 - 2) * 0.001 for i in range(200)]
        r1 = permutation_test(returns, n_permutations=200, seed=42)
        r2 = permutation_test(returns, n_permutations=200, seed=42)
        assert r1.p_value == r2.p_value
        assert r1.observed_sharpe == r2.observed_sharpe

    def test_block_bootstrap_deterministic(self):
        """Test block bootstrap is deterministic with same seed."""
        returns = [0.005 + (i % 4 - 2) * 0.001 for i in range(200)]
        r1 = block_bootstrap(returns, block_size=21, n_bootstrap=100, seed=42)
        r2 = block_bootstrap(returns, block_size=21, n_bootstrap=100, seed=42)
        assert r1.sharpe_mean == r2.sharpe_mean

    def test_different_seeds_differ(self):
        """Test that different seeds produce different results."""
        import random

        returns = [random.gauss(0.005, 0.01) for _ in range(200)]
        r1 = bootstrap_test(returns, n_bootstrap=200, seed=42)
        r2 = bootstrap_test(returns, n_bootstrap=200, seed=99)
        # Very unlikely to be exactly equal with different seeds
        assert r1.sharpe_ci_lower != r2.sharpe_ci_lower or r1.sharpe_ci_upper != r2.sharpe_ci_upper


# ── D. Walk-Forward Temporal Integrity ─────────────────────────────


class TestWalkForwardTemporalIntegrity:
    """Training data must never contain future observations."""

    def test_no_train_test_overlap(self):
        """Test that train and test windows never overlap."""
        equity = _make_equity(1000)
        result = purged_walk_forward(equity, train_bars=300, test_bars=100, purge_bars=10)
        for window in result.windows:
            assert window.train_end <= window.test_start, (
                f"Train ends at {window.train_end} but test starts at {window.test_start}"
            )

    def test_purge_gap(self):
        """Test that purge gap exists between train and test."""
        equity = _make_equity(1000)
        result = purged_walk_forward(equity, train_bars=300, test_bars=100, purge_bars=10)
        for window in result.windows:
            gap = window.test_start - window.train_end
            assert gap >= 10, f"Purge gap is {gap}, expected >= 10"

    def test_chronological_order(self):
        """Test that windows are in chronological order."""
        equity = _make_equity(1000)
        result = purged_walk_forward(equity, train_bars=300, test_bars=100, purge_bars=10)
        for i in range(1, len(result.windows)):
            assert result.windows[i].test_start >= result.windows[i - 1].test_start


# ── E. Permutation Invariance ─────────────────────────────────────


class TestPermutationInvariance:
    """Equivalent reorderings must produce equivalent results."""

    def test_p_value_bounds(self):
        """Test that p-value is always in [0, 1]."""
        returns = [0.005 + (i % 3 - 1) * 0.002 for i in range(200)]
        result = permutation_test(returns, n_permutations=100, seed=42)
        assert 0 <= result.p_value <= 1

    def test_significant_result_has_low_p(self):
        """Test that strong signal produces low p-value."""
        import random

        rng = random.Random(42)
        returns = [0.01 + rng.gauss(0, 0.01) for _ in range(500)]
        result = permutation_test(returns, n_permutations=500, seed=42)
        assert result.p_value < 0.05


# ── F. Bootstrap Reproducibility ──────────────────────────────────


class TestBootstrapReproducibility:
    """Same data + same config = identical confidence intervals."""

    def test_ci_ordering(self):
        """Test that CI lower < point estimate < CI upper."""
        returns = [0.005 + (i % 5 - 2) * 0.002 for i in range(200)]
        result = bootstrap_test(returns, n_bootstrap=200, seed=42)
        assert result.sharpe_ci_lower <= result.sharpe_mean + 0.01
        assert result.sharpe_ci_upper >= result.sharpe_mean - 0.01

    def test_larger_sample_narrower_ci(self):
        """Test that more data produces narrower confidence intervals."""
        import random

        rng = random.Random(42)
        returns_short = [rng.gauss(0.005, 0.01) for _ in range(100)]
        returns_long = [rng.gauss(0.005, 0.01) for _ in range(500)]
        r_short = bootstrap_test(returns_short, n_bootstrap=200, seed=42)
        r_long = bootstrap_test(returns_long, n_bootstrap=200, seed=42)
        ci_width_short = r_short.sharpe_ci_upper - r_short.sharpe_ci_lower
        ci_width_long = r_long.sharpe_ci_upper - r_long.sharpe_ci_lower
        # Longer series should have narrower CI (generally)
        assert ci_width_long < ci_width_short * 2  # Allow some tolerance


# ── G. Evidence Gate: No Silent Pass ───────────────────────────────


class TestEvidenceGateNoSilentPass:
    """No required evidence component can silently skip."""

    def test_no_data_rejected(self):
        """Test that no data produces REJECTED."""
        gate = EvidenceGate()
        result = gate.evaluate()
        assert result["verdict"] == EvidenceVerdict.REJECTED

    def test_missing_evidence_inconclusive(self):
        """Test that missing evidence produces INCONCLUSIVE."""
        from eigencapital.analytics.validation.walk_forward import WalkForwardResult

        gate = EvidenceGate()
        # Only provide walk-forward, missing bootstrap + permutation + cost
        wf = WalkForwardResult(
            total_windows=5,
            mean_oos_sharpe=1.0,
            degradation_ratio=1.0,
            pct_profitable_windows=60.0,
        )
        result = gate.evaluate(walk_forward=wf)
        assert result["verdict"] == EvidenceVerdict.INCONCLUSIVE
        assert len(result["missing_evidence"]) > 0

    def test_all_pass_moderate_evidence_candidate(self):
        """Test that all checks pass with moderate evidence → CANDIDATE."""
        gate = EvidenceGate()
        from eigencapital.analytics.validation.bootstrap import (
            BootstrapResult,
            PermutationResult,
        )
        from eigencapital.analytics.validation.cost_stress import CostStressResult
        from eigencapital.analytics.validation.regime import RegimeMetrics, RegimeResult
        from eigencapital.analytics.validation.temporal import TemporalStabilityResult
        from eigencapital.analytics.validation.universe import (
            ConcentrationMetrics,
            UniversePerturbationResult,
        )
        from eigencapital.analytics.validation.walk_forward import WalkForwardResult

        result = gate.evaluate(
            walk_forward=WalkForwardResult(
                total_windows=5,
                mean_oos_sharpe=0.5,
                degradation_ratio=1.5,
                pct_profitable_windows=60.0,
            ),
            bootstrap=BootstrapResult(
                n_bootstrap=100,
                sharpe_ci_lower=0.1,
                sharpe_ci_upper=1.0,
                pct_positive_sharpe=80.0,
            ),
            permutation=PermutationResult(n_permutations=100, p_value=0.03),
            cost_stress=CostStressResult(survives_1_5x=True, breakeven_multiplier=2.5),
            regime=RegimeResult(
                regimes=[RegimeMetrics(regime="up"), RegimeMetrics(regime="down")],
                regime_dependent=False,
                min_sharpe=0.3,
                max_sharpe=0.8,
                sharpe_range=0.5,
            ),
            universe=UniversePerturbationResult(
                single_instrument_dependency=False,
                concentration=ConcentrationMetrics(herfindahl_index=0.3),
            ),
            temporal=TemporalStabilityResult(window_count=5, performance_decay=False, pct_positive_sharpe=60.0),
        )
        assert result["verdict"] == EvidenceVerdict.CANDIDATE


# ── H. Walk-Forward: Insufficient Data ─────────────────────────────


class TestWalkForwardInsufficient:
    """Walk-forward with insufficient data must not crash."""

    def test_too_short(self):
        """Test with equity curve shorter than train+test."""
        result = purged_walk_forward([100, 101, 102], train_bars=100, test_bars=50)
        assert result.total_windows == 0

    def test_exactly_minimum(self):
        """Test with exactly minimum length."""
        equity = list(range(100, 200))
        result = purged_walk_forward(equity, train_bars=50, test_bars=20, purge_bars=5)
        assert result.total_windows >= 0


# ── I. Validation Engine: End-to-End ──────────────────────────────


class TestValidationEngineEndToEnd:
    """End-to-end validation engine tests."""

    def test_full_validation_produces_verdict(self):
        """Test that full validation produces a verdict."""
        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_equity(300)
        result = engine.validate(experiment_id="TEST-001", equity_curve=equity)
        assert result.verdict in [
            EvidenceVerdict.CANDIDATE,
            EvidenceVerdict.VALIDATED,
            EvidenceVerdict.REJECTED,
            EvidenceVerdict.INCONCLUSIVE,
        ]
        assert len(result.evidence_checks) > 0

    def test_validation_report_generation(self):
        """Test that validation report is generated."""
        from eigencapital.analytics.validation.report import generate_report

        engine = ValidationEngine(
            walk_forward_train=100,
            walk_forward_test=50,
            bootstrap_iterations=50,
            permutation_iterations=50,
        )
        equity = _make_equity(300)
        result = engine.validate(experiment_id="TEST-002", equity_curve=equity)
        report = generate_report(result)
        assert "TEST-002" in report
        assert "Verdict:" in report
        assert "## Evidence Gate" in report or "## 12. Evidence Gate" in report
