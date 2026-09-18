"""Unit tests for R1 Phase B1 — trade-sequence permutation diagnostic.

Covers the frozen B1 handoff contract:
- path metrics against hand-computed values
- the core invariant: pure permutation preserves the exact trade set
  (set-dependent metrics invariant; path-dependent metrics can change)
- seeded determinism (same seed -> identical result)
- provenance/tamper refusal
- explicit historical-vs-simulated labeling in output
"""

import pytest

from eigencapital.research.monte_carlo.path_metrics import (
    compute_path_metrics,
    trade_pnls,
)
from eigencapital.research.monte_carlo.permutation import (
    PATH_DEPENDENT_METRICS,
    run_permutation_test,
)
from eigencapital.research.monte_carlo.schema import (
    TradeRecord,
    TradeStream,
    TradeStreamError,
)
from tests.unit.research.monte_carlo.test_trade_stream import _make_stream


def _stream_with_pnls(pnls, **stream_overrides):
    """Build a stream whose realized P&Ls are exactly `pnls` (in order)."""
    trades = tuple(
        TradeRecord(
            trade_index=i,
            instrument="EURUSD",
            entry_timestamp=f"2026-01-{i:02d}T10:00:00Z",
            exit_timestamp=f"2026-01-{i:02d}T16:00:00Z",
            side="LONG",
            realized_pnl=float(p),
            return_r=None,
            costs_paid=0.0,
            metadata={},
        )
        for i, p in enumerate(pnls, start=1)
    )
    return _make_stream(trades=trades, **stream_overrides)


class TestPathMetrics:
    def test_flat_winning_path(self):
        m = compute_path_metrics([10.0, 10.0, 10.0], initial_equity=100.0)
        assert m.total_pnl == pytest.approx(30.0)
        assert m.max_drawdown == 0.0
        assert m.max_drawdown_duration == 0
        assert m.longest_losing_streak == 0
        assert m.recovery_time is None
        assert m.min_equity == pytest.approx(100.0)
        assert m.time_under_water == 0
        assert m.final_equity == pytest.approx(130.0)

    def test_single_drawdown_hand_computed(self):
        # equity: 100 -> 120 -> 102 -> 122 ; peak 120, trough 102
        m = compute_path_metrics([20.0, -18.0, 20.0], initial_equity=100.0)
        assert m.max_drawdown == pytest.approx((120 - 102) / 120)
        assert m.max_drawdown_duration == 1  # only the -18 trade closes below peak
        assert m.recovery_time == 1  # one trade after trough regains 120
        # equity never dipped below the starting 100, so min includes start
        assert m.min_equity == pytest.approx(100.0)
        assert m.longest_losing_streak == 1
        assert m.total_pnl == pytest.approx(22.0)

    def test_losing_streak_counts_consecutive_losses(self):
        m = compute_path_metrics([5.0, -1.0, -1.0, -2.0, 5.0, -1.0], initial_equity=100.0)
        assert m.longest_losing_streak == 3

    def test_unrecovered_drawdown_gives_none(self):
        m = compute_path_metrics([10.0, -15.0], initial_equity=100.0)
        assert m.recovery_time is None
        assert m.max_drawdown == pytest.approx(15.0 / 110.0)

    def test_return_space_default(self):
        m = compute_path_metrics([0.10, -0.05, 0.08])
        assert m.final_equity == pytest.approx(1.0 + 0.10 - 0.05 + 0.08)
        assert m.max_drawdown == pytest.approx(0.05 / 1.10)

    def test_empty_sequence_rejected(self):
        with pytest.raises(TradeStreamError, match="empty"):
            compute_path_metrics([])

    def test_non_finite_rejected(self):
        with pytest.raises(TradeStreamError, match="finite"):
            compute_path_metrics([1.0, float("nan")])

    def test_trade_pnls_order(self):
        s = _stream_with_pnls([3.0, -1.0, 2.0])
        assert trade_pnls(s) == (3.0, -1.0, 2.0)

    def test_trade_pnls_return_r_requires_values(self):
        s = _stream_with_pnls([3.0, -1.0])
        with pytest.raises(TradeStreamError, match="return_r"):
            trade_pnls(s, use_return_r=True)


class TestPermutationInvariant:
    def test_set_invariance_holds(self):
        """The frozen B1 invariant: permutation preserves the exact trade set."""
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0, -4.0, 6.0, 1.0])
        result = run_permutation_test(s, n_permutations=200, seed=7)
        assert result.set_invariance_verified
        # total_pnl and trade_count identical everywhere by construction
        hist = result.historical.metrics
        assert hist.total_pnl == pytest.approx(5.0 - 2.0 + 8.0 - 1.0 + 3.0 - 4.0 + 6.0 + 1.0)
        assert hist.trade_count == 8
        # distributions only contain path-dependent metrics
        assert set(result.distributions) == set(PATH_DEPENDENT_METRICS)

    def test_path_dependent_metrics_actually_vary(self):
        """Drawdown/streaks must NOT be constant across permutations."""
        s = _stream_with_pnls([20.0, -18.0, 15.0, -12.0, 30.0])
        result = run_permutation_test(s, n_permutations=100, seed=3)
        assert len(set(result.distributions["max_drawdown"])) > 1
        assert len(set(result.distributions["longest_losing_streak"])) > 1

    def test_single_trade_degenerate_distribution(self):
        s = _stream_with_pnls([5.0])
        result = run_permutation_test(s, n_permutations=10, seed=1)
        assert result.historical.metrics.total_pnl == pytest.approx(5.0)
        assert all(v == [0.0] * 10 for v in [result.distributions["max_drawdown"]])


class TestPermutationBehavior:
    def test_seed_determinism(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0, -4.0, 6.0, 1.0, -3.0, 2.0])
        r1 = run_permutation_test(s, n_permutations=100, seed=42)
        r2 = run_permutation_test(s, n_permutations=100, seed=42)
        assert r1.distributions == r2.distributions
        assert r1.quantiles == r2.quantiles
        assert r1.historical.percentile == r2.historical.percentile

    def test_historical_percentiles_within_unit_interval(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0, -4.0, 6.0, 1.0])
        result = run_permutation_test(s, n_permutations=300, seed=11)
        for metric, pct in result.historical.percentile.items():
            assert 0.0 <= pct <= 1.0, metric

    def test_lucky_ordering_scores_high_percentile(self):
        """Wins-first ordering should have benign drawdown vs permutations."""
        s = _stream_with_pnls([30.0, 25.0, 20.0, -5.0, -8.0, -3.0])
        result = run_permutation_test(s, n_permutations=500, seed=5)
        # historical = wins first: shallow DD, high percentile on max_drawdown
        assert result.historical.percentile["max_drawdown"] > 0.75

    def test_unlucky_ordering_scores_low_percentile(self):
        """Losses-first ordering should have deep DD vs permutations."""
        s = _stream_with_pnls([-8.0, -5.0, -3.0, 20.0, 25.0, 30.0])
        result = run_permutation_test(s, n_permutations=500, seed=5)
        assert result.historical.percentile["max_drawdown"] < 0.25

    def test_min_equity_dips_below_start(self):
        m = compute_path_metrics([10.0, -25.0, 5.0], initial_equity=100.0)
        assert m.min_equity == pytest.approx(85.0)

    def test_quantiles_reported(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, -1.0, 3.0])
        result = run_permutation_test(s, n_permutations=200, seed=2, quantiles=(0.1, 0.9))
        for metric in PATH_DEPENDENT_METRICS:
            entry = result.quantiles[metric]
            assert {"q0.1", "q0.9"} <= set(entry)
            # n_never_recovered may only appear for recovery_time (None = no recovery)
            if "n_never_recovered" in entry:
                assert metric == "recovery_time"
                assert 0.0 <= entry["n_never_recovered"] <= result.n_permutations

    def test_invalid_args_rejected(self):
        s = _stream_with_pnls([1.0, 2.0])
        with pytest.raises(TradeStreamError, match="n_permutations"):
            run_permutation_test(s, n_permutations=0, seed=1)
        with pytest.raises(TradeStreamError, match="quantiles"):
            run_permutation_test(s, n_permutations=10, seed=1, quantiles=(1.5,))


class TestProvenanceRefusal:
    def test_tampered_stream_refused(self):
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
                    realized_pnl=t.realized_pnl + 100.0,  # tampered
                    return_r=t.return_r,
                    costs_paid=t.costs_paid,
                    metadata=t.metadata,
                )
                for t in s.trades
            ),
            provenance_hash=s.provenance_hash,  # stale hash
        )
        with pytest.raises(TradeStreamError, match="provenance"):
            run_permutation_test(tampered, n_permutations=10, seed=1)


class TestOutputLabeling:
    def test_serialization_labels_historical_vs_simulated(self):
        s = _stream_with_pnls([5.0, -2.0, 8.0, 1.0])
        result = run_permutation_test(s, n_permutations=50, seed=9)
        d = result.to_dict()
        assert "historical" in d and "simulated_distributions" in d
        assert d["method"] == "trade_sequence_permutation"
        assert "NOT a forecast" in d["methodological_rule"]
        # historical metrics and percentiles are reported separately
        assert "metrics" in d["historical"]
        assert "percentile_in_simulated_distribution" in d["historical"]

    def test_seed_recorded_for_reproducibility(self):
        s = _stream_with_pnls([1.0, -1.0, 2.0])
        result = run_permutation_test(s, n_permutations=10, seed=123)
        assert result.seed == 123
        assert result.to_dict()["seed"] == 123
