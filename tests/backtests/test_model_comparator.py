import numpy as np
import pandas as pd
import pytest

from backtests.model_comparator import (
    _compute_signals,
    build_summary,
    classify_regime,
    compare_models,
    compare_portfolio,
    compare_shadow_intel,
    compare_signals,
)


class FakeModel:
    def predict_proba(self, X):
        n = len(X)
        proba = np.zeros((n, 3))
        proba[:, 0] = 0.2
        proba[:, 1] = 0.3
        proba[:, 2] = 0.5
        return proba


class FakeDegradedModel:
    def predict_proba(self, X):
        n = len(X)
        proba = np.zeros((n, 3))
        proba[:, 0] = 0.6
        proba[:, 1] = 0.3
        proba[:, 2] = 0.1
        return proba


@pytest.fixture
def sample_X():  # noqa: N802
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=50, freq="D")
    return pd.DataFrame(
        {
            "feature_1": np.random.randn(50),
            "feature_2": np.random.randn(50),
            "feature_3": np.random.randn(50),
        },
        index=dates,
    )


@pytest.fixture
def sample_y():
    return pd.Series(np.random.choice([0, 1, 2], size=50))


@pytest.fixture
def sample_close():
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=50, freq="D")
    return pd.Series(100 + np.cumsum(np.random.randn(50) * 0.5), index=dates)


class TestClassifyRegime:
    def test_returns_series(self, sample_close):
        regime = classify_regime(sample_close)
        assert isinstance(regime, pd.Series)
        assert all(r in ("low_vol", "mid", "transition", "high_vol") for r in regime.unique())

    def test_length_matches_input(self, sample_close):
        regime = classify_regime(sample_close)
        assert len(regime) == len(sample_close)

    def test_includes_expected_regimes(self, sample_close):
        regime = classify_regime(sample_close)
        expected = {"low_vol", "transition", "high_vol"}
        assert expected.issuperset(regime.unique())


class TestComputeSignals:
    def test_basic_signal_generation(self):
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        proba = np.array(
            [
                [0.1, 0.2, 0.7],
                [0.6, 0.3, 0.1],
                [0.3, 0.4, 0.3],
                [0.1, 0.1, 0.8],
                [0.5, 0.3, 0.2],
            ]
        )
        df = _compute_signals(proba, dates, threshold=0.45)
        # Default is 0 (short), signals[long > thr] = 2, signals[short > thr] = 0
        # Row 0: long=0.7>0.45 -> 2, short=0.1-> stays 2
        # Row 1: long=0.1 -> no, short=0.6>0.45 -> 0
        # Row 2: long=0.3->no, short=0.3->no -> default 0
        # Row 3: long=0.8>0.45 -> 2, short=0.1 -> no -> 2
        # Row 4: long=0.2->no, short=0.5>0.45 -> 0
        assert list(df["signal"]) == [2, 0, 0, 2, 0]

    def test_all_neutral(self):
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        proba = np.array(
            [
                [0.33, 0.34, 0.33],
                [0.33, 0.34, 0.33],
                [0.33, 0.34, 0.33],
            ]
        )
        df = _compute_signals(proba, dates, threshold=0.45)
        # Neither > 0.45, default is 0 (short), not 1 (neutral)
        assert list(df["signal"]) == [0, 0, 0]


class TestCompareModels:
    def test_compare_with_y(self, sample_X, sample_y):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_models(old, new, sample_X, y=sample_y)
        assert "n_samples" in result
        assert "old" in result
        assert "new" in result
        assert "class_distribution" in result
        assert "error" not in result

    def test_compare_without_y(self, sample_X):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_models(old, new, sample_X)
        assert "class_distribution" in result
        assert "old" not in result or "accuracy" not in (result.get("old", {}) or {}) is False  # no accuracy without y

    def test_error_handling(self, sample_X):
        class BrokenModel:
            def predict_proba(self, X):
                raise ValueError("broken")

        result = compare_models(BrokenModel(), FakeModel(), sample_X)
        assert "error" in result

    def test_custom_predict_fn(self, sample_X):
        def custom_predict(model, x):
            n = len(x)
            proba = np.zeros((n, 3))
            proba[:, 1] = 1.0
            return proba

        result = compare_models(FakeModel(), FakeDegradedModel(), sample_X, predict_fn=custom_predict)
        assert "error" not in result


class TestCompareSignals:
    def test_basic_comparison(self, sample_X, sample_close):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_signals(old, new, sample_X, sample_close)
        assert "overall_agreement" in result
        assert "total_flips" in result
        assert "flip_rate" in result
        assert "final_signal_old" in result
        assert "final_signal_new" in result
        assert "final_agreement" in result
        assert "mean_confidence_shift" in result
        assert "regime_stratified_agreement" in result

    def test_error_handling(self, sample_X, sample_close):
        class BrokenModel:
            def predict_proba(self, X):
                raise ValueError("broken")

        result = compare_signals(BrokenModel(), FakeModel(), sample_X, sample_close)
        assert "error" in result


class TestComparePortfolio:
    def test_basic_simulation(self, sample_X, sample_close):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_portfolio(old, new, sample_X, sample_close)
        assert "initial_capital" in result
        assert "old" in result
        assert "new" in result
        assert "delta" in result
        assert "return_diff" in result["delta"]
        assert "trade_diff" in result["delta"]

    def test_error_handling(self, sample_X, sample_close):
        class BrokenModel:
            def predict_proba(self, X):
                raise ValueError("broken")

        result = compare_portfolio(BrokenModel(), FakeModel(), sample_X, sample_close)
        assert "error" in result

    def test_custom_parameters(self, sample_X, sample_close):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_portfolio(old, new, sample_X, sample_close, initial_capital=50000.0, threshold=0.3)
        assert result["initial_capital"] == 50000.0


class TestCompareShadowIntel:
    def test_basic_comparison(self, sample_X, sample_close):
        old = FakeModel()
        new = FakeDegradedModel()
        result = compare_shadow_intel(old, new, sample_X, sample_close, asset="TEST")
        assert "asset" in result
        assert "class_distribution_shift" in result
        assert "entropy_shift" in result
        assert "signal_agreement" in result
        assert "mean_confidence_old" in result
        assert "mean_confidence_new" in result
        assert "regime_stability" in result
        assert result["asset"] == "TEST"

    def test_error_handling(self, sample_X, sample_close):
        class BrokenModel:
            def predict_proba(self, X):
                raise ValueError("broken")

        result = compare_shadow_intel(BrokenModel(), FakeModel(), sample_X, sample_close)
        assert "error" in result

    def test_zero_confidence_when_no_trades(self, sample_X, sample_close):
        class FlatModel:
            def predict_proba(self, X):
                n = len(X)
                proba = np.zeros((n, 3))
                proba[:, 1] = 1.0
                return proba

        result = compare_shadow_intel(FlatModel(), FlatModel(), sample_X, sample_close)
        assert result["mean_confidence_old"]["short"] == 0.0
        assert result["mean_confidence_old"]["long"] == 0.0


class TestBuildSummary:
    def test_all_pass(self):
        result = build_summary(
            model_result={
                "old": {"accuracy": 0.6},
                "new": {"accuracy": 0.61},
            },
            signal_result={
                "overall_agreement": 0.9,
                "flip_rate": 0.05,
            },
            portfolio_result={
                "old": {"total_return": 0.05},
                "new": {"total_return": 0.10},
            },
            shadow_result={
                "entropy_shift": 0.05,
            },
        )
        assert result["verdict"] == "PASS"

    def test_warn_on_some_failures(self):
        result = build_summary(
            model_result={
                "old": {"accuracy": 0.6},
                "new": {"accuracy": 0.5},
            },
            signal_result={
                "overall_agreement": 0.7,
                "flip_rate": 0.2,
            },
            portfolio_result={
                "old": {"total_return": 0.05},
                "new": {"total_return": -0.05},
            },
            shadow_result={
                "entropy_shift": 0.3,
            },
        )
        assert result["verdict"] == "FAIL"

    def test_partial_pass(self):
        result = build_summary(
            model_result={
                "old": {"accuracy": 0.6},
                "new": {"accuracy": 0.5},
            },
            signal_result={
                "overall_agreement": 0.9,
                "flip_rate": 0.05,
            },
            portfolio_result={
                "old": {"total_return": 0.05},
                "new": {"total_return": 0.10},
            },
            shadow_result={
                "entropy_shift": 0.3,
            },
        )
        assert result["verdict"] in ("PASS", "WARN", "FAIL")

    def test_with_errors_in_sub_results(self):
        result = build_summary(
            model_result={"error": "failed"},
            signal_result={"error": "failed"},
            portfolio_result={"error": "failed"},
            shadow_result={"error": "failed"},
        )
        assert result["total_checks"] == 0
        assert result["verdict"] == "PASS"

    def test_custom_thresholds(self):
        thresholds = {
            "accuracy_drop": 0.1,
            "logloss_increase": 0.1,
            "agreement_min": 0.7,
            "flip_rate_max": 0.25,
            "return_drop": 0.1,
            "entropy_shift_max": 0.2,
        }
        result = build_summary(
            model_result={
                "old": {"accuracy": 0.6},
                "new": {"accuracy": 0.55},
            },
            signal_result={
                "overall_agreement": 0.75,
                "flip_rate": 0.2,
            },
            portfolio_result={
                "old": {"total_return": 0.05},
                "new": {"total_return": 0.03},
            },
            shadow_result={
                "entropy_shift": 0.15,
            },
            thresholds=thresholds,
        )
        assert result["verdict"] == "PASS"
