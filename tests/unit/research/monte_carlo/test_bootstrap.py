"""Unit tests for R1 Phase B2 — IID bootstrap diagnostic.

Covers the frozen B2 contract:
- the deliberately different invariant vs B1: total P&L is EXPECTED to vary
- sample-size control (default = historical count; explicit override works)
- seeded determinism
- provenance/tamper refusal
- sample-dependent metrics collected alongside path-dependent ones
- historical-vs-simulated labeling
"""

import numpy as np
import pytest

from eigencapital.research.monte_carlo.bootstrap import (
    SAMPLE_DEPENDENT_METRICS,
    run_bootstrap_test,
)
from eigencapital.research.monte_carlo.permutation import run_permutation_test
from tests.unit.research.monte_carlo.test_permutation import _stream_with_pnls


class TestCoreInvariantDifference:
    def test_total_pnl_varies_across_resamples(self):
        """B2 deliberately breaks B1's set invariance: P&L must vary."""
        s = _stream_with_pnls([10.0, -5.0, 20.0, -8.0, 12.0, -3.0, 7.0, -6.0])
        result = run_bootstrap_test(s, n_resamples=300, seed=13)
        assert len(set(result.distributions["total_pnl"])) > 1

    def test_sample_size_equals_historical_count_by_default(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, 1.0])
        result = run_bootstrap_test(s, n_resamples=100, seed=4)
        assert result.sample_size == 4
        # trade_count of every resample equals sample_size
        assert result.historical.metrics.trade_count == 4

    def test_explicit_sample_size_respected(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, 1.0])
        result = run_bootstrap_test(s, n_resamples=100, seed=4, sample_size=10)
        assert result.sample_size == 10

    def test_set_invariance_flag_explicitly_false(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0])
        result = run_bootstrap_test(s, n_resamples=50, seed=4)
        assert result.set_invariance_expected is False
        assert result.to_dict()["set_invariance_expected"] is False

    def test_b2_collects_sample_dependent_metrics_b1_does_not(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, 1.0, -4.0, 3.0])
        b2 = run_bootstrap_test(s, n_resamples=100, seed=9)
        b1 = run_permutation_test(s, n_permutations=100, seed=9)
        assert set(SAMPLE_DEPENDENT_METRICS) <= set(b2.distributions)
        assert not set(SAMPLE_DEPENDENT_METRICS) & set(b1.distributions)

    def test_all_winning_trades_still_shows_pnl_dispersion_via_counts(self):
        """With all-positive trades, P&L still varies: duplicates vs omissions."""
        s = _stream_with_pnls([10.0, 20.0, 5.0, 1.0])
        result = run_bootstrap_test(s, n_resamples=200, seed=21)
        pnls = np.asarray(result.distributions["total_pnl"], dtype=float)
        assert pnls.min() < pnls.max()  # some resamples repeat 20, others draw 1 four times


class TestDistributionBehavior:
    def test_seed_determinism(self):
        s = _stream_with_pnls([10.0, -5.0, 20.0, -8.0, 12.0])
        r1 = run_bootstrap_test(s, n_resamples=100, seed=42)
        r2 = run_bootstrap_test(s, n_resamples=100, seed=42)
        assert r1.distributions == r2.distributions
        assert r1.quantiles == r2.quantiles
        assert r1.historical.percentile == r2.historical.percentile

    def test_extreme_trade_stretches_distribution(self):
        """One outlier dominates IID resamples: wide P&L distribution."""
        s = _stream_with_pnls([1.0, 1.0, 1.0, 500.0])
        result = run_bootstrap_test(s, n_resamples=300, seed=7)
        pnls = np.asarray(result.distributions["total_pnl"], dtype=float)
        # resamples drawing the outlier 0..4 times
        assert pnls.min() <= 4.0 + 1e-9
        assert pnls.max() >= 200.0

    def test_historical_percentiles_within_unit_interval(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0, -4.0])
        result = run_bootstrap_test(s, n_resamples=300, seed=11)
        for metric, pct in result.historical.percentile.items():
            assert 0.0 <= pct <= 1.0, metric

    def test_percentiles_cover_sample_metrics(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0, -4.0])
        result = run_bootstrap_test(s, n_resamples=300, seed=11)
        for metric in SAMPLE_DEPENDENT_METRICS:
            assert metric in result.historical.percentile

    def test_never_recovered_counted_for_recovery_time(self):
        """Resamples with losses ordered last never recover; None is preserved."""
        s = _stream_with_pnls([10.0, -20.0, 5.0, 8.0])
        result = run_bootstrap_test(s, n_resamples=300, seed=19)
        nones = sum(1 for v in result.distributions["recovery_time"] if v is None)
        assert nones > 0
        assert result.quantiles["recovery_time"].get("n_never_recovered", 0) == float(nones)


class TestValidation:
    def test_tampered_stream_refused(self):
        from eigencapital.research.monte_carlo.schema import (
            TradeRecord,
            TradeStream,
            TradeStreamError,
        )

        s = _stream_with_pnls([5.0, -2.0, 8.0])
        tampered = TradeStream(
            stream_id=s.stream_id,
            experiment_id=s.experiment_id,
            strategy_id=s.strategy_id,
            strategy_version=s.strategy_version,
            dataset_id=s.dataset_id,
            dataset_version=s.dataset_version,
            git_commit=s.git_commit,
            cost_model_id=s.cost_model_id,
            cost_model_version=s.cost_model_version,
            trades=tuple(
                TradeRecord(
                    trade_index=t.trade_index,
                    instrument=t.instrument,
                    entry_timestamp=t.entry_timestamp,
                    exit_timestamp=t.exit_timestamp,
                    side=t.side,
                    realized_pnl=t.realized_pnl + 50.0,
                    return_r=t.return_r,
                    costs_paid=t.costs_paid,
                    metadata=t.metadata,
                )
                for t in s.trades
            ),
            provenance_hash=s.provenance_hash,
        )
        with pytest.raises(TradeStreamError, match="provenance"):
            run_bootstrap_test(tampered, n_resamples=10, seed=1)

    def test_invalid_args_rejected(self):
        s = _stream_with_pnls([1.0, 2.0])
        with pytest.raises(Exception, match="n_resamples"):
            run_bootstrap_test(s, n_resamples=0, seed=1)
        with pytest.raises(Exception, match="sample_size"):
            run_bootstrap_test(s, n_resamples=10, seed=1, sample_size=0)
        with pytest.raises(Exception, match="quantiles"):
            run_bootstrap_test(s, n_resamples=10, seed=1, quantiles=(2.0,))


class TestOutputLabeling:
    def test_serialization_labels_historical_vs_simulated(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0])
        result = run_bootstrap_test(s, n_resamples=50, seed=9)
        d = result.to_dict()
        assert "historical" in d and "simulated_distributions" in d
        assert d["method"] == "iid_bootstrap_with_replacement"
        assert "NOT a forecast" in d["methodological_rule"]
        assert "percentile_in_simulated_distribution" in d["historical"]

    def test_seed_recorded(self):
        s = _stream_with_pnls([1.0, -1.0, 2.0])
        result = run_bootstrap_test(s, n_resamples=10, seed=77)
        assert result.seed == 77
        assert result.to_dict()["seed"] == 77
