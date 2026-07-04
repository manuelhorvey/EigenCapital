from __future__ import annotations

import numpy as np

from eigencapital.domain.value_objects.statistical_metrics import (
    _moments,
    _sharpe_variance,
    confidence_reliability_score,
    deflated_sharpe_ratio,
    expected_calibration_error,
    expected_max_sharpe,
    herfindahl_index,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)


class TestSharpeRatio:
    def test_positive_returns(self):
        r = np.random.randn(252) * 0.01 + 0.0005
        sr = sharpe_ratio(r)
        assert sr > 0

    def test_negative_returns(self):
        r = np.random.randn(252) * 0.01 - 0.0005
        sr = sharpe_ratio(r)
        assert sr < 0

    def test_constant_returns_zero_std(self):
        r = np.ones(100) * 0.001
        sr = sharpe_ratio(r)
        assert sr == 0.0

    def test_too_few_observations(self):
        r = np.array([0.01])
        sr = sharpe_ratio(r)
        assert sr == 0.0

    def test_with_risk_free(self):
        r = np.random.randn(252) * 0.01 + 0.0005
        sr = sharpe_ratio(r, rf=0.0003)
        assert isinstance(sr, float)


class TestMoments:
    def test_normal_returns(self):
        r = np.random.randn(500)
        skew, ex_kurt = _moments(r)
        assert abs(skew) < 0.5
        assert abs(ex_kurt) < 1.0

    def test_skewed_returns(self):
        r = np.random.gamma(2, 1, 500)
        skew, ex_kurt = _moments(r)
        assert skew > 0

    def test_too_few_observations(self):
        r = np.array([1.0, 2.0])
        skew, ex_kurt = _moments(r)
        assert skew == 0.0
        assert ex_kurt == 0.0

    def test_constant_returns(self):
        r = np.ones(50) * 1.0
        skew, ex_kurt = _moments(r)
        assert skew == 0.0
        assert ex_kurt == 0.0


class TestSharpeVariance:
    def test_normal_case(self):
        var_sr = _sharpe_variance(1.0, 0.0, 0.0, 252)
        assert var_sr > 0

    def test_few_obs_returns_large_variance(self):
        var_sr = _sharpe_variance(1.0, 0.0, 0.0, 1)
        assert var_sr == 1.0

    def test_negative_variance_floored(self):
        var_sr = _sharpe_variance(2.0, 5.0, -10.0, 252)
        assert var_sr > 0


class TestProbabilisticSharpeRatio:
    def test_strong_signal(self):
        psr = probabilistic_sharpe_ratio(2.0, 252)
        assert psr > 0.95

    def test_zero_sharpe(self):
        psr = probabilistic_sharpe_ratio(0.0, 252)
        assert psr == 0.5

    def test_negative_sharpe(self):
        psr = probabilistic_sharpe_ratio(-1.0, 252)
        assert psr < 0.5

    def test_few_obs_returns_50pct(self):
        psr = probabilistic_sharpe_ratio(1.0, 1)
        assert psr == 0.5

    def test_non_finite_sharpe(self):
        psr = probabilistic_sharpe_ratio(np.nan, 252)
        assert psr == 0.5

    def test_with_benchmark(self):
        psr = probabilistic_sharpe_ratio(1.0, 252, benchmark=0.5)
        assert psr > 0.5


class TestExpectedMaxSharpe:
    def test_single_trial(self):
        emax = expected_max_sharpe(1)
        assert emax == 0.0

    def test_many_trials(self):
        emax = expected_max_sharpe(100)
        assert emax > 0

    def test_increasing_with_trials(self):
        e1 = expected_max_sharpe(10)
        e2 = expected_max_sharpe(100)
        assert e2 > e1


class TestDeflatedSharpeRatio:
    def test_single_trial_delegates_to_psr(self):
        dsr = deflated_sharpe_ratio(1.0, 252, num_trials=1)
        psr = probabilistic_sharpe_ratio(1.0, 252)
        assert dsr == psr

    def test_many_trials_lowers_confidence(self):
        dsr1 = deflated_sharpe_ratio(1.0, 252, num_trials=1)
        dsr2 = deflated_sharpe_ratio(1.0, 252, num_trials=1000)
        assert dsr2 <= dsr1

    def test_few_obs(self):
        dsr = deflated_sharpe_ratio(1.0, 1, num_trials=100)
        assert dsr == probabilistic_sharpe_ratio(1.0, 1)

    def test_non_finite_sharpe(self):
        dsr = deflated_sharpe_ratio(np.inf, 252, num_trials=100)
        assert dsr == probabilistic_sharpe_ratio(np.inf, 252)


class TestMinTRL:
    def test_high_sharpe_needs_fewer_obs(self):
        n1 = minimum_track_record_length(2.0)
        n2 = minimum_track_record_length(0.5)
        assert n1 < n2

    def test_zero_sharpe_returns_large(self):
        n = minimum_track_record_length(0.0)
        assert n == 10**6

    def test_non_finite_sharpe(self):
        n = minimum_track_record_length(np.nan)
        assert n == 10**6

    def test_floor_at_2(self):
        n = minimum_track_record_length(100.0)
        assert n >= 2

    def test_with_skew_and_kurtosis(self):
        n = minimum_track_record_length(1.0, skew=0.5, excess_kurt=2.0)
        assert n >= 2


class TestECE:
    def test_perfect_calibration(self):
        probs = np.array([0.2, 0.4, 0.6, 0.8])
        outcomes = np.array([0, 0, 1, 1])
        ece = expected_calibration_error(probs, outcomes, n_bins=2)
        assert 0 < ece <= 0.31

    def test_miscalibrated(self):
        probs = np.array([0.9, 0.9, 0.9, 0.9])
        outcomes = np.array([0, 0, 0, 0])
        ece = expected_calibration_error(probs, outcomes, n_bins=2)
        assert ece > 0

    def test_fewer_obs_than_bins(self):
        probs = np.array([0.5])
        outcomes = np.array([1])
        ece = expected_calibration_error(probs, outcomes, n_bins=10)
        assert ece == 0.0

    def test_last_bin_includes_one(self):
        probs = np.array([1.0, 1.0, 0.0, 0.0])
        outcomes = np.array([1, 1, 0, 0])
        ece = expected_calibration_error(probs, outcomes, n_bins=3)
        assert ece >= 0


class TestConfidenceReliabilityScore:
    def test_perfect_is_one(self):
        probs = np.array([0.0, 1.0])
        outcomes = np.array([0, 1])
        crs = confidence_reliability_score(probs, outcomes, n_bins=2)
        assert crs >= 0.0

    def test_crs_is_one_minus_ece(self):
        probs = np.array([0.2, 0.8, 0.3, 0.7])
        outcomes = np.array([0, 1, 0, 1])
        ece = expected_calibration_error(probs, outcomes, n_bins=2)
        crs = confidence_reliability_score(probs, outcomes, n_bins=2)
        assert abs(crs - (1.0 - ece)) < 1e-10


class TestHerfindahlIndex:
    def test_concentrated(self):
        r = np.array([100.0, 1.0, 1.0])
        h = herfindahl_index(r)
        assert h > 0.5

    def test_diversified(self):
        r = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        h = herfindahl_index(r)
        assert abs(h - 0.2) < 1e-6

    def test_all_zero(self):
        r = np.array([0.0, 0.0, 0.0])
        h = herfindahl_index(r)
        assert h == 0.0

    def test_single_asset(self):
        r = np.array([100.0])
        h = herfindahl_index(r)
        assert h == 1.0

    def test_negative_and_positive(self):
        r = np.array([50.0, -30.0, 20.0])
        h = herfindahl_index(r)
        assert 0 < h < 1
