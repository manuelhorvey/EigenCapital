"""Tests for shared/factor_model.py — factor decomposition and constraints."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shared.factor_model import (
    DEFAULT_FACTOR_LIMITS,
    FACTOR_GROUPS,
    compute_factor_exposures,
    compute_factor_returns,
    exposure_violations,
    factor_exposure_penalty,
    list_factors,
    summary,
)


class TestFactorDefinitions:
    def test_factors_defined(self):
        assert len(FACTOR_GROUPS) >= 5
        assert "CHF" in FACTOR_GROUPS
        assert "USD" in FACTOR_GROUPS
        assert "US_EQUITY" in FACTOR_GROUPS

    def test_chf_group_has_pairs(self):
        chf = FACTOR_GROUPS["CHF"]
        assert "EURCHF" in chf
        assert "USDCHF" in chf
        assert "CADCHF" in chf

    def test_equity_group(self):
        eq = FACTOR_GROUPS["US_EQUITY"]
        assert "ES" in eq
        assert "NQ" in eq
        assert "^DJI" in eq

    def test_default_limits_defined(self):
        for factor in FACTOR_GROUPS:
            assert factor in DEFAULT_FACTOR_LIMITS

    def test_limits_are_ranges(self):
        for factor, (lo, hi) in DEFAULT_FACTOR_LIMITS.items():
            assert lo <= 0 <= hi
            assert lo < hi

    def test_list_factors(self):
        factors = list_factors()
        assert isinstance(factors, list)
        assert len(factors) == len(FACTOR_GROUPS)
        assert factors == sorted(factors)


class TestComputeFactorExposures:
    @pytest.fixture
    def sample_weights(self):
        return {
            "EURUSD": 0.05,
            "AUDUSD": 0.03,
            "NZDUSD": 0.02,
            "USDCHF": 0.04,
            "GBPUSD": 0.03,
            "ES": 0.04,
            "NQ": 0.02,
            "^DJI": 0.02,
            "GC": 0.02,
            "EURAUD": 0.03,
        }

    def test_usd_exposure(self, sample_weights):
        exposures = compute_factor_exposures(sample_weights)
        assert "USD" in exposures
        # EURUSD, AUDUSD, NZDUSD, USDCHF, GBPUSD = 0.05+0.03+0.02+0.04+0.03 = 0.17
        assert exposures["USD"] > 0.10

    def test_chf_exposure(self, sample_weights):
        exposures = compute_factor_exposures(sample_weights)
        assert "CHF" in exposures
        # USDCHF only = 0.04
        assert exposures["CHF"] == pytest.approx(0.04)

    def test_equity_exposure(self, sample_weights):
        exposures = compute_factor_exposures(sample_weights)
        assert "US_EQUITY" in exposures
        # ES + NQ + ^DJI = 0.04 + 0.02 + 0.02 = 0.08
        assert exposures["US_EQUITY"] == pytest.approx(0.08)

    def test_commodity_exposure(self, sample_weights):
        exposures = compute_factor_exposures(sample_weights)
        assert "COMMODITY" in exposures
        assert exposures["COMMODITY"] == pytest.approx(0.02)

    def test_empty_weights(self):
        exposures = compute_factor_exposures({})
        for factor in FACTOR_GROUPS:
            assert exposures[factor] == 0.0

    def test_all_weights_zero(self):
        weights = {a: 0.0 for a in ["EURUSD", "AUDUSD", "ES"]}
        exposures = compute_factor_exposures(weights)
        assert all(v == 0.0 for v in exposures.values())

    def test_unknown_asset_ignored(self):
        exposures = compute_factor_exposures({"UNKNOWN": 0.5})
        assert all(v == 0.0 for v in exposures.values())

    def test_custom_factor_groups(self):
        custom = {"MY_FACTOR": frozenset({"EURUSD", "AUDUSD"})}
        exposures = compute_factor_exposures({"EURUSD": 0.1, "AUDUSD": 0.2}, factor_groups=custom)
        assert exposures["MY_FACTOR"] == pytest.approx(0.3)


class TestExposureViolations:
    @pytest.fixture
    def tight_limits(self):
        return {
            "CHF": (-0.05, 0.05),
            "USD": (-0.1, 0.2),
            "US_EQUITY": (0.0, 0.1),
            "COMMODITY": (0.0, 0.03),
        }

    def test_no_violations(self):
        exposures = {"USD": 0.1, "CHF": 0.03, "US_EQUITY": 0.05}
        violations = exposure_violations(exposures)
        for v in violations.values():
            assert v["violation"] is None

    def test_chf_violation(self, tight_limits):
        exposures = {"CHF": 0.15, "USD": 0.1}
        violations = exposure_violations(exposures, limits=tight_limits)
        assert violations["CHF"]["violation"] == "high"

    def test_below_low_violation(self, tight_limits):
        exposures = {"US_EQUITY": -0.05}
        violations = exposure_violations(exposures, limits=tight_limits)
        assert violations["US_EQUITY"]["violation"] == "low"

    def test_violation_details(self, tight_limits):
        exposures = {"CHF": 0.15}
        violations = exposure_violations(exposures, limits=tight_limits)
        v = violations["CHF"]
        assert v["exposure"] == 0.15
        assert v["limit_hi"] == 0.05
        assert v["violation"] == "high"

    def test_empty_exposures(self):
        violations = exposure_violations({})
        assert all(v["violation"] is None for v in violations.values())

    def test_default_limits_used(self):
        exposures = {"COMMODITY": 0.20}
        violations = exposure_violations(exposures)
        assert violations["COMMODITY"]["violation"] == "high"


class TestFactorExposurePenalty:
    def test_no_penalty_within_limits(self):
        weights = {"EURUSD": 0.05, "AUDUSD": 0.03, "GC": 0.02}
        limits = {"USD": (-0.5, 0.5), "CHF": (-0.5, 0.5), "COMMODITY": (0, 0.05)}
        penalty = factor_exposure_penalty(weights, limits)
        assert penalty == 0.0

    def test_positive_penalty_violation(self):
        weights = {"EURUSD": 0.5, "AUDUSD": 0.3, "GC": 0.05}
        limits = {"USD": (-0.2, 0.2), "COMMODITY": (0, 0.05)}
        penalty = factor_exposure_penalty(weights, limits)
        assert penalty > 0

    def test_scaling(self):
        weights = {"EURUSD": 0.5}
        limits = {"USD": (-0.2, 0.2)}
        p1 = factor_exposure_penalty(weights, limits, penalty_scale=1.0)
        p10 = factor_exposure_penalty(weights, limits, penalty_scale=10.0)
        assert p10 == pytest.approx(p1 * 10.0)


class TestComputeFactorReturns:
    @pytest.fixture
    def sample_returns(self):
        rng = np.random.default_rng(42)
        data = {a: rng.normal(0, 0.01, 100) for a in ["EURUSD", "AUDUSD", "USDCHF", "GC", "ES"]}
        return pd.DataFrame(data, index=pd.RangeIndex(100))

    def test_simple_method_shape(self, sample_returns):
        result = compute_factor_returns(sample_returns, method="simple")
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == len(sample_returns)
        assert "USD" in result.columns
        assert "CHF" in result.columns
        assert "COMMODITY" in result.columns

    def test_simple_method_values(self, sample_returns):
        result = compute_factor_returns(sample_returns, method="simple")
        # USD factor: mean of EURUSD, AUDUSD, USDCHF returns
        expected = sample_returns[["EURUSD", "AUDUSD", "USDCHF"]].mean(axis=1)
        expected.name = "USD"
        pd.testing.assert_series_equal(result["USD"], expected)

    def test_simple_method_empty_data(self):
        empty = pd.DataFrame()
        result = compute_factor_returns(empty, method="simple")
        assert isinstance(result, pd.DataFrame)

    def test_regression_method(self, sample_returns):
        # Wrapped in try/except because sklearn may not be installed
        try:
            result = compute_factor_returns(sample_returns, method="regression")
            assert isinstance(result, pd.DataFrame)
        except ImportError:
            pytest.skip("sklearn not available")

    def test_invalid_method(self, sample_returns):
        with pytest.raises(ValueError, match="Unknown method"):
            compute_factor_returns(sample_returns, method="invalid")


class TestSummary:
    def test_summary_structure(self):
        weights = {"EURUSD": 0.05, "AUDUSD": 0.03, "GC": 0.02, "ES": 0.04, "NQ": 0.02}
        s = summary(weights)
        assert "exposures" in s
        assert "violations" in s
        assert "n_violations" in s
        assert "within_limits" in s
        assert isinstance(s["within_limits"], bool)

    def test_n_violations(self):
        weights = {"EURUSD": 0.5, "GC": 0.5}
        s = summary(weights)
        assert s["n_violations"] >= 1
        assert not s["within_limits"]

    def test_no_violations(self):
        weights = {a: 0.05 for a in list(FACTOR_GROUPS["USD"])[:5]}
        s = summary(weights)
        assert isinstance(s["within_limits"], bool)
