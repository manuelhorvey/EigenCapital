"""Tests for Deflated Sharpe Ratio (Bailey & López de Prado 2014)."""

import math

import pytest

from eigencapital.analytics.validation.deflated_sharpe import (
    DeflatedSharpeResult,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
    sample_kurtosis,
    sample_skewness,
)


def _normal_returns(seed: int, n: int = 500):
    """Deterministic pseudo-normal returns via Box-Muller."""
    import random

    rng = random.Random(seed)
    out = []
    while len(out) < n:
        u1 = rng.random() or 1e-12
        u2 = rng.random()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        out.append(0.001 + 0.01 * z)
    return out


class TestSampleMoments:
    """Tests for skewness/kurtosis estimators."""

    def test_symmetric_series_zero_skew(self):
        returns = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01]
        assert abs(sample_skewness(returns)) < 1e-12

    def test_right_skew_positive(self):
        returns = [-0.01, 0.01, -0.01, 0.01, 0.10]
        assert sample_skewness(returns) > 0

    def test_normal_kurtosis_near_three(self):
        returns = _normal_returns(seed=7)
        assert abs(sample_kurtosis(returns) - 3.0) < 0.6

    def test_too_few_observations_raise(self):
        with pytest.raises(ValueError):
            sample_skewness([0.01, 0.02, 0.03])
        with pytest.raises(ValueError):
            sample_kurtosis([0.01])

    def test_constant_series_no_crash(self):
        skew = sample_skewness([0.01] * 10)
        kurt = sample_kurtosis([0.01] * 10)
        # Constant series: skewness should be 0, kurtosis should be 3
        assert abs(skew) < 1e-10, f"Constant series skewness should be ~0, got {skew}"
        assert abs(kurt - 3.0) < 1e-10, f"Constant series kurtosis should be ~3, got {kurt}"


class TestExpectedMaximumSharpe:
    """Tests for SR0 under multiple trials."""

    def test_insufficient_trials_raise(self):
        with pytest.raises(ValueError, match="INSUFFICIENT_TRIALS"):
            expected_maximum_sharpe([1.5])
        with pytest.raises(ValueError):
            expected_maximum_sharpe([])

    def test_sr0_increases_with_trials(self):
        trials = [0.2 * i for i in range(20)]
        sr0_small = expected_maximum_sharpe(trials[:5])
        sr0_large = expected_maximum_sharpe(trials)
        assert sr0_large > sr0_small >= 0

    def test_identical_trials_zero_sr0(self):
        assert expected_maximum_sharpe([1.0] * 10) == 0.0


class TestDeflatedSharpeRatio:
    """End-to-end DSR behavior."""

    TRIALS = [round(0.05 * i, 4) for i in range(45)]

    def test_significant_with_low_multiplicity(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=0.15,
            n_trials=5,
            n_periods=1260,
            trial_sharpes=self.TRIALS[:5],
            skewness=0.0,
            kurtosis=3.0,
        )
        assert result.sufficient_trials
        assert result.significant
        assert result.deflated_sharpe >= 0.95
        assert result.expected_max_sharpe < result.observed_sharpe

    def test_high_multiplicity_deflates_edge(self):
        strong = deflated_sharpe_ratio(
            observed_sharpe=0.15,
            n_trials=5,
            n_periods=1260,
            trial_sharpes=self.TRIALS[:5],
            skewness=0.0,
            kurtosis=3.0,
        )
        mined = deflated_sharpe_ratio(
            observed_sharpe=0.15,
            n_trials=200,
            n_periods=1260,
            trial_sharpes=[0.05 * i * 0.1 for i in range(200)],
            skewness=0.0,
            kurtosis=3.0,
        )
        assert mined.deflated_sharpe < strong.deflated_sharpe

    def test_fail_closed_without_trial_dispersion(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=2.0,
            n_trials=50,
            n_periods=1260,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert not result.sufficient_trials
        assert not result.significant
        assert result.deflated_sharpe == 0.0
        assert "INSUFFICIENT_TRIALS" in result.message

    def test_explicit_trial_std_accepted(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=0.15,
            n_trials=10,
            n_periods=1260,
            trial_sr_std=0.05,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert result.sufficient_trials
        assert result.trial_sr_std == 0.05

    def test_negative_trial_std_rejected(self):
        with pytest.raises(ValueError):
            deflated_sharpe_ratio(
                observed_sharpe=0.15,
                n_trials=10,
                n_periods=100,
                trial_sr_std=-0.1,
                skewness=0.0,
                kurtosis=3.0,
            )

    def test_moments_derived_from_returns(self):
        returns = _normal_returns(seed=11)
        derived = deflated_sharpe_ratio(
            observed_sharpe=0.12,
            n_trials=8,
            n_periods=len(returns),
            returns=returns,
            trial_sharpes=self.TRIALS[:8],
        )
        explicit = deflated_sharpe_ratio(
            observed_sharpe=0.12,
            n_trials=8,
            n_periods=len(returns),
            skewness=sample_skewness(returns),
            kurtosis=sample_kurtosis(returns),
            trial_sharpes=self.TRIALS[:8],
        )
        assert derived.n_periods == len(returns)
        assert abs(derived.deflated_sharpe - explicit.deflated_sharpe) < 1e-9

    def test_missing_moments_raises_not_assumes(self):
        with pytest.raises(ValueError):
            deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=5, n_periods=100)

    def test_short_returns_series_fail_closed(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=1.0,
            n_trials=5,
            n_periods=3,
            returns=[0.01, 0.02],
            trial_sharpes=[1.0, 0.5],
        )
        assert not result.sufficient_trials or not result.significant
        assert "INSUFFICIENT_OBSERVATIONS" in result.message

    def test_single_trial_cannot_be_significant(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=3.0,
            n_trials=1,
            n_periods=1260,
            trial_sr_std=0.1,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert not result.significant

    def test_degenerate_moments_reported(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=10.0,
            n_trials=5,
            n_periods=100,
            trial_sharpes=[0.5, 1.0],
            skewness=50.0,
            kurtosis=1.0,
        )
        assert "DEGENERATE_MOMENTS" in result.message
        assert result.deflated_sharpe == 0.0

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            deflated_sharpe_ratio(
                observed_sharpe=1.0,
                n_trials=0,
                n_periods=100,
                skewness=0.0,
                kurtosis=3.0,
            )
        with pytest.raises(ValueError):
            deflated_sharpe_ratio(
                observed_sharpe=1.0,
                n_trials=5,
                n_periods=100,
                skewness=0.0,
                kurtosis=3.0,
                confidence=1.5,
            )


class TestSerialization:
    """Deterministic serialization contract."""

    def test_to_dict_round_stable(self):
        result = deflated_sharpe_ratio(
            observed_sharpe=0.15,
            n_trials=10,
            n_periods=500,
            trial_sharpes=[0.1 * i for i in range(10)],
            skewness=-0.1,
            kurtosis=3.5,
        )
        d1 = result.to_dict()
        d2 = DeflatedSharpeResult(**result.to_dict()).to_dict()
        assert d1 == d2
        for key in (
            "observed_sharpe",
            "expected_max_sharpe",
            "deflated_sharpe",
            "significant",
            "sufficient_trials",
            "n_trials",
        ):
            assert key in d1
