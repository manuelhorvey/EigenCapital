import pytest
import pandas as pd
import numpy as np
from models.hybrid_ensemble import HybridRegimeEnsemble


class TestHybridRegimeEnsemble:
    @pytest.fixture
    def ensemble(self):
        return HybridRegimeEnsemble(macro_weight=0.45)

    @pytest.fixture
    def sample_features(self):
        np.random.seed(42)
        n = 500
        dates = pd.date_range("2020-01-01", periods=n, freq="D")
        X = pd.DataFrame({
            "feature_1": np.random.randn(n),
            "feature_2": np.random.randn(n),
            "feature_3": np.random.randn(n),
            "feature_4": np.random.randn(n),
        }, index=dates)
        y = pd.Series(np.random.randint(0, 3, n), index=dates)
        regimes = pd.Series(
            np.random.choice(["trend", "range", "volatile", "neutral"], n),
            index=dates,
        )
        return X, y, regimes

    def test_init_default_weights(self):
        ensemble = HybridRegimeEnsemble()
        assert ensemble.global_weight == 0.4
        assert ensemble.expert_weight == 0.6
        assert ensemble.macro_weight == 0.45

    def test_init_custom_weights(self):
        ensemble = HybridRegimeEnsemble(
            global_weight=0.3, expert_weight=0.7, macro_weight=0.5
        )
        assert ensemble.global_weight == 0.3
        assert ensemble.expert_weight == 0.7
        assert ensemble.macro_weight == 0.5

    def test_train_creates_global_model(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        assert ensemble.global_model is not None
        assert ensemble.feature_names == X.columns.tolist()

    def test_train_creates_expert_heads(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        assert len(ensemble.expert_heads) > 0

    def test_predict_proba_returns_correct_shape(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        probs = ensemble.predict_proba(X.iloc[:10], regimes.iloc[:10])
        assert probs.shape == (10, 3)

    def test_predict_proba_probabilities_sum_to_one(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        probs = ensemble.predict_proba(X.iloc[:10], regimes.iloc[:10])
        assert np.allclose(probs.sum(axis=1), 1.0)

    def test_predict_proba_all_non_negative(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        probs = ensemble.predict_proba(X.iloc[:10], regimes.iloc[:10])
        assert (probs >= 0).all()

    def test_get_sample_weights_recency(self, ensemble):
        weights = ensemble._get_sample_weights(100)
        assert weights[0] < weights[-1]
        assert weights[-1] == 1.0

    def test_get_sample_weights_regime_scaling(self, ensemble):
        trend_w = ensemble._get_sample_weights(100, regime_type="trend")
        neutral_w = ensemble._get_sample_weights(100, regime_type="neutral")
        assert np.all(trend_w > neutral_w)

    def test_fallback_to_global_when_expert_missing(self, ensemble, sample_features):
        X, y, regimes = sample_features
        ensemble.train(X, y, regimes)
        unknown_regimes = pd.Series(["unknown_regime"] * 5, index=X.iloc[:5].index)
        probs = ensemble.predict_proba(X.iloc[:5], unknown_regimes)
        assert probs.shape == (5, 3)
        assert np.allclose(probs.sum(axis=1), 1.0)

    def test_explain_returns_none_for_missing_expert(self, ensemble):
        result = ensemble.explain(pd.DataFrame(), "nonexistent")
        assert result is None

    def test_train_skips_small_expert(self, ensemble, sample_features):
        X, y, regimes = sample_features
        rare_regime = pd.Series(["tiny"] * 10 + ["trend"] * 490, index=X.index)
        ensemble.train(X, y, rare_regime)
        assert "tiny" not in ensemble.expert_heads


class TestDirectionalPrior:
    @pytest.fixture
    def ensemble(self):
        return HybridRegimeEnsemble(directional_prior_weight=0.05,
                                     transition_penalty_weight=0.10)

    def test_directional_prior_boosts_trend_long(self, ensemble):
        n = 5
        X = pd.DataFrame({
            "P_trend": [0.8] * n,
            "P_range": [0.1] * n,
            "P_volatile": [0.1] * n,
        })
        regimes = pd.Series(["trend"] * n)
        probs = np.full((n, 3), 0.33)
        result = ensemble._apply_directional_prior(X, probs, regimes)
        assert result[0, 2] > probs[0, 2]

    def test_directional_prior_damps_volatile(self, ensemble):
        n = 5
        X = pd.DataFrame({
            "P_trend": [0.1] * n,
            "P_range": [0.1] * n,
            "P_volatile": [0.8] * n,
        })
        regimes = pd.Series(["volatile"] * n)
        probs = np.full((n, 3), 0.33)
        result = ensemble._apply_directional_prior(X, probs, regimes)
        assert result[0, 0] < probs[0, 0]
        assert result[0, 2] < probs[0, 2]

    def test_transition_penalty_lowers_exposure(self, ensemble):
        n = 5
        X = pd.DataFrame({
            "P_trend": [0.8] * n,
            "P_range": [0.1] * n,
            "P_volatile": [0.1] * n,
            "transition_risk": [0.9] * n,
        })
        regimes = pd.Series(["trend"] * n)
        probs = np.full((n, 3), 0.33)
        result = ensemble._apply_directional_prior(X, probs, regimes)
        assert result[0, 2] < 0.33 * (1 + 0.05 * 0.8)
