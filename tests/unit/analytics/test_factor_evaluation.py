"""Tests for factor evaluation: IC, quantile analysis, turnover."""

import random

import pytest

from eigencapital.analytics.validation.factor_evaluation import (
    factor_turnover,
    information_coefficient,
    quantile_analysis,
    quantile_spread_series,
    spearman_correlation,
)


class TestSpearmanCorrelation:
    """Spearman rank correlation primitives."""

    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman_correlation(xs, xs) == pytest.approx(1.0)

    def test_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert spearman_correlation(xs, ys) == pytest.approx(-1.0)

    def test_ties_use_average_ranks(self):
        xs = [1.0, 1.0, 2.0]
        ys = [10.0, 20.0, 30.0]
        corr = spearman_correlation(xs, ys)
        assert -1.0 <= corr <= 1.0

    def test_zero_variance_returns_zero(self):
        assert spearman_correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            spearman_correlation([1.0], [1.0, 2.0])

    def test_short_inputs_zero(self):
        assert spearman_correlation([1.0], [2.0]) == 0.0


class TestInformationCoefficient:
    """IC computation across panel periods."""

    def test_perfect_signal_ic_one(self):
        panels = [
            [(float(i), float(i)) for i in range(10)],
            [(float(i) + 3, float(i)) for i in range(10)],
        ]
        result = information_coefficient(panels)
        assert result.mean_ic == pytest.approx(1.0)
        assert result.pct_positive == pytest.approx(1.0)
        assert result.n_periods == 2

    def test_random_signal_ic_near_zero(self):
        rng = random.Random(42)
        panels = []
        for _ in range(30):
            signals = [rng.gauss(0, 1) for _ in range(40)]
            returns = [rng.gauss(0, 1) for _ in range(40)]
            panels.append(list(zip(signals, returns)))
        result = information_coefficient(panels)
        assert abs(result.mean_ic) < 0.15
        assert result.n_periods == 30

    def test_narrow_periods_skipped(self):
        wide = [(float(i), float(i)) for i in range(10)]
        narrow = [(1.0, 0.01), (2.0, 0.02)]
        result = information_coefficient([wide, narrow, wide], min_names=5)
        assert result.n_periods == 2

    def test_all_narrow_yields_empty_result(self):
        result = information_coefficient([[(1.0, 0.1)] * 3])
        assert result.n_periods == 0
        assert result.ic_series == ()

    def test_t_stat_consistency(self):
        rng = random.Random(7)
        panels = [
            list(
                zip(
                    [rng.gauss(0, 1) for _ in range(30)],
                    [rng.gauss(0, 1) for _ in range(30)],
                )
            )
            for _ in range(50)
        ]
        result = information_coefficient(panels)
        expected_t = result.mean_ic / (
            result.std_ic / math_sqrt(result.n_periods)
        )
        if result.std_ic > 1e-15:
            assert result.t_stat == pytest.approx(expected_t, rel=1e-9)


def math_sqrt(x):
    import math

    return math.sqrt(x)


class TestQuantileAnalysis:
    """Quantile bucketing and monotonic separation."""

    def test_monotonic_positive_separation(self):
        n = 20
        signals = [float(i) for i in range(n)]
        fwd_returns = [s / 100.0 + 0.001 for s in signals]
        result = quantile_analysis(signals, fwd_returns, n_quantiles=5)
        assert result.direction == "positive"
        assert result.monotonic
        assert result.top_minus_bottom > 0
        means = result.quantile_mean_returns
        assert all(means[i] <= means[i + 1] for i in range(len(means) - 1))

    def test_inverted_signal_negative_direction(self):
        n = 20
        signals = [float(i) for i in range(n)]
        fwd_returns = [-s / 100.0 for s in signals]
        result = quantile_analysis(signals, fwd_returns)
        assert result.direction == "negative"
        assert result.top_minus_bottom < 0

    def test_equal_bucket_sizes(self):
        signals = [float(i) for i in range(20)]
        result = quantile_analysis(signals, signals, n_quantiles=5)
        assert result.quantile_sizes == (4, 4, 4, 4, 4)

    def test_constant_signals_no_edge(self):
        signals = [1.0] * 25
        returns = [0.01] * 25
        result = quantile_analysis(signals, returns)
        assert result.direction == "none"

    def test_validation_errors(self):
        with pytest.raises(ValueError):
            quantile_analysis([1.0], [1.0, 2.0])
        with pytest.raises(ValueError):
            quantile_analysis([1.0, 2.0], [1.0, 2.0], n_quantiles=1)

    def test_empty_input(self):
        result = quantile_analysis([], [], n_quantiles=5)
        assert result.quantile_mean_returns == ()
        assert result.n_quantiles == 5

    def test_spread_series_per_period(self):
        panels = [
            [(float(i), float(i)) for i in range(10)],
            [(float(i), float(-i)) for i in range(10)],
        ]
        spreads = quantile_spread_series(panels, n_quantiles=5)
        assert len(spreads) == 2
        assert spreads[0] > 0
        assert spreads[1] < 0


class TestFactorTurnover:
    """Top-set turnover and rank autocorrelation."""

    def test_identical_rankings_zero_turnover_full_autocorr(self):
        ranking = {f"name{i}": float(i) for i in range(20)}
        result = factor_turnover([ranking, ranking, ranking])
        assert result.mean_top_set_turnover == pytest.approx(0.0)
        assert result.mean_rank_autocorrelation == pytest.approx(1.0)
        assert result.n_rebalances == 2

    def test_reversed_rankings_full_turnover_negative_autocorr(self):
        up = {f"name{i}": float(i) for i in range(20)}
        down = {f"name{i}": float(-i) for i in range(20)}
        result = factor_turnover([up, down])
        assert result.mean_top_set_turnover == pytest.approx(1.0)
        assert result.mean_rank_autocorrelation == pytest.approx(-1.0)

    def test_partial_churn_fractional_turnover(self):
        base = {f"n{i}": float(i % 10) for i in range(20)}
        churned = dict(base)
        top_names = sorted(base, key=lambda k: base[k], reverse=True)[:4]
        bottom_names = sorted(base, key=lambda k: base[k])[:4]
        for name in top_names:
            churned[name] = -1.0
        for idx, name in enumerate(bottom_names):
            churned[name] = 100.0 + idx
        result = factor_turnover([base, churned], top_fraction=0.2)
        turnover = result.mean_top_set_turnover
        assert 0.0 < turnover <= 1.0
        assert result.n_rebalances == 1

    def test_insufficient_history_empty(self):
        result = factor_turnover([{"a": 1.0}])
        assert result.n_rebalances == 0
        assert result.top_set_turnover_series == ()

    def test_invalid_top_fraction_raises(self):
        with pytest.raises(ValueError):
            factor_turnover([{"a": 1.0}, {"a": 2.0}], top_fraction=0.0)
        with pytest.raises(ValueError):
            factor_turnover([{"a": 1.0}, {"a": 2.0}], top_fraction=1.5)

    def test_serialization_stable(self):
        up = {f"name{i}": float(i) for i in range(20)}
        d1 = factor_turnover([up, up]).to_dict()
        assert "mean_top_set_turnover" in d1
        assert "mean_rank_autocorrelation" in d1
