import numpy as np
import pandas as pd
import pytest

from paper_trading.governance.regime import RegimeClassifier


class TestRegimeClassifier:
    @pytest.fixture
    def classifier(self):
        return RegimeClassifier(confidence_threshold=0.45, smoothing_window=5)

    @pytest.fixture
    def trend_features(self):
        n = 30
        return pd.DataFrame(
            {
                "kaufman_er": np.full(n, 0.7),
                "adx": np.full(n, 35.0),
                "vol_zscore": np.full(n, 0.5),
                "compression": np.full(n, 0.3),
            }
        )

    @pytest.fixture
    def range_features(self):
        n = 30
        return pd.DataFrame(
            {
                "kaufman_er": np.full(n, 0.2),
                "adx": np.full(n, 15.0),
                "vol_zscore": np.full(n, 0.5),
                "compression": np.full(n, 0.8),
            }
        )

    @pytest.fixture
    def volatile_features(self):
        n = 30
        return pd.DataFrame(
            {
                "kaufman_er": np.full(n, 0.3),
                "adx": np.full(n, 20.0),
                "vol_zscore": np.full(n, 2.0),
                "compression": np.full(n, 1.5),
            }
        )

    def test_init_defaults(self):
        c = RegimeClassifier()
        assert c.confidence_threshold == 0.45
        assert c.smoothing_window == 10

    def test_init_custom(self):
        c = RegimeClassifier(confidence_threshold=0.55, smoothing_window=15)
        assert c.confidence_threshold == 0.55
        assert c.smoothing_window == 15

    def test_classify_returns_dataframe(self, classifier, trend_features):
        result = classifier.classify(trend_features)
        assert isinstance(result, pd.DataFrame)

    def test_classify_has_expected_columns(self, classifier, trend_features):
        result = classifier.classify(trend_features)
        expected = {"regime", "P_trend", "P_range", "P_volatile", "regime_confidence", "regime_raw"}
        assert expected.issubset(result.columns)

    def test_trend_features_classify_as_trend(self, classifier, trend_features):
        result = classifier.classify(trend_features)
        assert result["regime"].iloc[-1] == "trend"

    def test_range_features_classify_as_range(self, classifier, range_features):
        result = classifier.classify(range_features)
        assert result["regime"].iloc[-1] == "range"

    def test_volatile_features_classify_as_volatile(self, classifier, volatile_features):
        result = classifier.classify(volatile_features)
        assert result["regime"].iloc[-1] == "volatile"

    def test_low_confidence_classifies_as_neutral(self):
        classifier = RegimeClassifier(confidence_threshold=0.60, smoothing_window=1)
        n = 30
        df = pd.DataFrame(
            {
                "kaufman_er": np.full(n, 0.4),
                "adx": np.full(n, 20.0),
                "vol_zscore": np.full(n, 0.0),
                "compression": np.full(n, 0.5),
            }
        )
        result = classifier.classify(df)
        assert result["regime"].iloc[-1] == "neutral"

    def test_smoothing_adds_persistence(self, classifier):
        n = 50
        kaufman_er = np.concatenate([np.full(15, 0.7), np.full(20, 0.2), np.full(15, 0.7)])
        adx = np.concatenate([np.full(15, 35.0), np.full(20, 15.0), np.full(15, 35.0)])
        df = pd.DataFrame(
            {
                "kaufman_er": kaufman_er,
                "adx": adx,
                "vol_zscore": np.full(n, 0.5),
                "compression": np.full(n, 0.3),
            }
        )
        result = classifier.classify(df)
        smoothed = result["regime"]
        transitions = (smoothed != smoothed.shift(1)).sum()
        raw = result["regime_raw"]
        raw_transitions = (raw != raw.shift(1)).sum()
        assert transitions <= raw_transitions

    def test_probabilities_are_valid(self, classifier, trend_features):
        result = classifier.classify(trend_features)
        assert (result["P_trend"] >= 0).all()
        assert (result["P_trend"] <= 1).all()
        assert (result["P_range"] >= 0).all()
        assert (result["P_range"] <= 1).all()
