from __future__ import annotations

import numpy as np
import pandas as pd

from labels.meta_labels import MetaLabelModel


class TestShouldEnter:
    def test_allows_when_proba_above_threshold(self):
        model = MetaLabelModel(threshold=0.55)
        assert model.should_enter(0.70)

    def test_blocks_when_proba_below_threshold(self):
        model = MetaLabelModel(threshold=0.55)
        assert not model.should_enter(0.40)

    def test_allows_at_threshold(self):
        model = MetaLabelModel(threshold=0.55)
        assert model.should_enter(0.55)

    def test_allows_when_proba_is_none(self):
        model = MetaLabelModel()
        assert model.should_enter(None)

    def test_custom_threshold(self):
        strict = MetaLabelModel(threshold=0.80)
        assert not strict.should_enter(0.79)
        assert strict.should_enter(0.80)


class TestPredictProba:
    def test_returns_none_when_untrained(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0]})
        y = np.array([1])
        result = model.predict_proba(X, y)
        assert result is None

    def test_returns_float_when_trained(self):
        model = MetaLabelModel(n_estimators=10, min_train_samples=1)
        np.random.seed(42)
        n = 200
        X = pd.DataFrame(
            {
                "feat_1": np.random.randn(n),
                "feat_2": np.random.randn(n),
                "label": np.random.choice([-1, 1], size=n),
            }
        )
        features = ["feat_1", "feat_2"]
        y_primary = np.random.choice([0, 1, 2], size=n)
        model.train(X, y_primary, features, asset="test_asset", force=True)
        assert model._trained
        proba = model.predict_proba(X, y_primary)
        assert proba is not None
        assert 0.0 <= proba <= 1.0

    def test_returns_none_with_wrong_features(self):
        model = MetaLabelModel(n_estimators=10, min_train_samples=1)
        np.random.seed(42)
        n = 50
        X = pd.DataFrame(
            {
                "feat_1": np.random.randn(n),
                "label": np.random.choice([-1, 1], size=n),
            }
        )
        model.train(X, np.random.choice([0, 1, 2], size=n), ["feat_1"], asset="test_asset2", force=True)
        wrong_X = pd.DataFrame({"feat_wrong": [1.0, 2.0]})
        proba = model.predict_proba(wrong_X, np.array([1, 2]))
        assert proba is None


class TestBuildMetaFeatures:
    def test_adds_primary_prediction(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0, 2.0], "feat_2": [3.0, 4.0], "label": [1, -1]})
        features = ["feat_1", "feat_2"]
        y_primary = np.array([2, 0])
        result = model._build_meta_features(X, features, y_primary)
        assert "meta_primary_pred" in result.columns
        assert "meta_primary_long_prob" in result.columns
        assert "meta_primary_short_prob" in result.columns
        assert "label" not in result.columns
        assert list(result["meta_primary_pred"]) == [2, 0]

    def test_adds_probability_columns(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0], "feat_2": [3.0]})
        features = ["feat_1", "feat_2"]
        y_primary = np.array([[0.1, 0.2, 0.7]])
        result = model._build_meta_features(X, features, y_primary)
        assert "meta_primary_prob_short" in result.columns
        assert "meta_primary_prob_neutral" in result.columns
        assert "meta_primary_prob_long" in result.columns
        assert result["meta_primary_prob_short"][0] == 0.1
        assert result["meta_primary_prob_long"][0] == 0.7

    def test_drops_label_column(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0], "label": [1]})
        result = model._build_meta_features(X, ["feat_1"], np.array([2]))
        assert "label" not in result.columns

    def test_preserves_base_features(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0, 2.0], "feat_2": [3.0, 4.0]})
        result = model._build_meta_features(X, ["feat_1", "feat_2"], np.array([2, 0]))
        assert list(result["feat_1"]) == [1.0, 2.0]
        assert list(result["feat_2"]) == [3.0, 4.0]


class TestTrain:
    def test_skips_when_no_label_column(self):
        model = MetaLabelModel()
        X = pd.DataFrame({"feat_1": [1.0, 2.0]})
        model.train(X, np.array([1, 2]), ["feat_1"], asset="test")
        assert not model._trained

    def test_skips_when_insufficient_samples(self):
        model = MetaLabelModel(min_train_samples=100)
        X = pd.DataFrame(
            {
                "feat_1": [1.0],
                "label": [1],
            }
        )
        model.train(X, np.array([2]), ["feat_1"], asset="test")
        assert not model._trained

    def test_trains_with_sufficient_data(self):
        model = MetaLabelModel(n_estimators=10, min_train_samples=1)
        np.random.seed(42)
        n = 100
        X = pd.DataFrame(
            {
                "feat_1": np.random.randn(n),
                "feat_2": np.random.randn(n),
                "label": np.random.choice([-1, 1], size=n),
            }
        )
        model.train(X, np.random.choice([0, 1, 2], size=n), ["feat_1", "feat_2"], asset="test_train", force=True)
        assert model._trained
        assert model.model is not None


class TestConstructor:
    def test_defaults(self):
        model = MetaLabelModel()
        assert model.n_estimators == 150
        assert model.max_depth == 2
        assert model.learning_rate == 0.03
        assert model.threshold == 0.55
        assert model.min_train_samples == 200
        assert model.retain_meta_on_disk
        assert model.model is None
        assert not model._trained

    def test_custom_values(self):
        model = MetaLabelModel(n_estimators=50, max_depth=3, threshold=0.60, min_train_samples=50)
        assert model.n_estimators == 50
        assert model.max_depth == 3
        assert model.threshold == 0.60
        assert model.min_train_samples == 50

    def test_model_path(self):
        model = MetaLabelModel()
        path = model._model_path("EURUSD")
        assert "EURUSD_meta.json" in str(path)
        assert str(path).endswith(".json")


class TestMetaLabelFeatureSuggestions:
    def test_returns_list_of_strings(self):
        from labels.meta_labels import meta_label_feature_suggestions

        suggestions = meta_label_feature_suggestions()
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0
        assert all(isinstance(s, str) for s in suggestions)
        assert "volatility_regime" in suggestions
        assert "entry_hour" in suggestions
