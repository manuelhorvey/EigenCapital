import numpy as np
import pandas as pd
import pytest

from backtests.adversarial_manifold import (
    PERTURBATIONS,
    _clip01,
    _compute_regime_score,
    _entropy,
    _perturb_correlation,
    _perturb_noise,
    _perturb_trend,
    _perturb_volatility,
    _safe,
    evaluate_adversarial_manifold,
)


class TestSafe:
    def test_returns_value(self):
        assert _safe(5.0) == 5.0
        assert _safe(None) == 0.0
        assert _safe(None, 1.0) == 1.0


class TestClip01:
    def test_clips(self):
        assert _clip01(-0.5) == 0.0
        assert _clip01(1.5) == 1.0
        assert _clip01(0.5) == 0.5


class TestEntropy:
    def test_entropy_computation(self):
        np.random.seed(42)
        proba = np.array([[0.8, 0.1, 0.1], [0.1, 0.8, 0.1]])
        h = _entropy(proba)
        assert h > 0

    def test_certain_distribution(self):
        proba = np.array([[1.0, 0.0, 0.0]])
        h = _entropy(proba)
        assert h == pytest.approx(0.0, abs=1e-6)


class TestPerturbations:
    @pytest.fixture
    def sample_X(self):  # noqa: N802
        np.random.seed(42)
        return pd.DataFrame(np.random.randn(50, 5), columns=[f"f{i}" for i in range(5)])

    def test_perturb_volatility_shock(self, sample_X):
        result = _perturb_volatility(sample_X, "shock")
        assert result.shape == sample_X.shape
        assert list(result.columns) == list(sample_X.columns)

    def test_perturb_volatility_compression(self, sample_X):
        result = _perturb_volatility(sample_X, "compression")
        assert result.shape == sample_X.shape

    def test_perturb_volatility_noise(self, sample_X):
        result = _perturb_volatility(sample_X, "noise")
        assert result.shape == sample_X.shape

    def test_perturb_correlation_decouple(self, sample_X):
        result = _perturb_correlation(sample_X, "decouple")
        assert result.shape == sample_X.shape

    def test_perturb_correlation_inversion(self, sample_X):
        result = _perturb_correlation(sample_X, "inversion")
        assert result.shape == sample_X.shape

    def test_perturb_correlation_break_default(self, sample_X):
        result = _perturb_correlation(sample_X, "break")
        assert result.shape == sample_X.shape

    def test_perturb_trend_flip(self, sample_X):
        result = _perturb_trend(sample_X, "flip")
        assert result.shape == sample_X.shape

    def test_perturb_trend_burst(self, sample_X):
        X_with_mom = sample_X.copy()
        X_with_mom["mom_10"] = np.random.randn(50)
        X_with_mom["vs_spy"] = np.random.randn(50)
        result = _perturb_trend(X_with_mom, "burst")
        assert result.shape == X_with_mom.shape

    def test_perturb_trend_decay(self, sample_X):
        result = _perturb_trend(sample_X, "decay")
        assert result.shape == sample_X.shape

    def test_perturb_noise_inject(self, sample_X):
        result = _perturb_noise(sample_X, "inject")
        assert result.shape == sample_X.shape

    def test_perturb_noise_spike(self, sample_X):
        result = _perturb_noise(sample_X, "spike")
        assert result.shape == sample_X.shape

    def test_perturb_noise_dropout(self, sample_X):
        result = _perturb_noise(sample_X, "dropout")
        assert result.shape == sample_X.shape

    def test_perturb_volatility_single_row(self):
        X = pd.DataFrame(np.random.randn(1, 3), columns=["a", "b", "c"])
        # Should handle single row gracefully
        result = _perturb_volatility(X, "shock")
        assert result.shape == (1, 3)


class FakeModel:
    def predict_proba(self, X):
        n = len(X)
        proba = np.zeros((n, 3))
        proba[:, 0] = 0.2
        proba[:, 1] = 0.3
        proba[:, 2] = 0.5
        return proba


class TestComputeRegimeScore:
    def test_basic_score(self):
        np.random.seed(42)
        n = 20
        X_orig = pd.DataFrame(np.random.randn(n, 3), columns=["a", "b", "c"])
        X_pert = X_orig.copy() * 1.1
        close = pd.Series(np.ones(n) * 100)
        baseline_proba = FakeModel().predict_proba(X_orig)

        score = _compute_regime_score(FakeModel(), X_orig, X_pert, close, baseline_proba)
        assert 0 <= score <= 1

    def test_identical_inputs_score_high(self):
        np.random.seed(42)
        n = 20
        X = pd.DataFrame(np.random.randn(n, 3), columns=["a", "b", "c"])
        close = pd.Series(np.ones(n) * 100)
        baseline_proba = FakeModel().predict_proba(X)

        score = _compute_regime_score(FakeModel(), X, X, close, baseline_proba)
        assert score > 0.5


class TestEvaluateAdversarialManifold:
    def test_basic_evaluation(self):
        np.random.seed(42)
        n = 30
        X = pd.DataFrame(np.random.randn(n, 3), columns=["a", "b", "c"])
        close = pd.Series(np.ones(n) * 100)

        result = evaluate_adversarial_manifold(
            asset="TEST",
            model=FakeModel(),
            X=X,
            close=close,
            threshold=0.45,
        )
        assert "asset" in result
        assert "cmss" in result
        assert "max_regime_drop" in result
        assert "attractor_drift" in result
        assert "stability_class" in result
        assert "regime_scores" in result
        assert "normal_score" in result
        assert result["asset"] == "TEST"
        assert result["stability_class"] in ("ROBUST", "MODERATE", "BRITTLE")

    def test_all_perturbations_in_scores(self):
        np.random.seed(42)
        n = 40
        X = pd.DataFrame(np.random.randn(n, 3), columns=["a", "b", "c"])
        close = pd.Series(np.ones(n) * 100)

        result = evaluate_adversarial_manifold("TEST", FakeModel(), X, close)
        assert set(result["regime_scores"].keys()) == set(PERTURBATIONS.keys())

    def test_custom_predict_fn(self):
        np.random.seed(42)
        n = 20
        X = pd.DataFrame(np.random.randn(n, 3), columns=["a", "b", "c"])
        close = pd.Series(np.ones(n) * 100)

        def my_predict(model, x):
            n = len(x)
            proba = np.zeros((n, 3))
            proba[:, 1] = 1.0
            return proba

        result = evaluate_adversarial_manifold("TEST", FakeModel(), X, close, predict_fn=my_predict)
        assert "cmss" in result
