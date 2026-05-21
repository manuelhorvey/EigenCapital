import numpy as np
import pandas as pd
import pytest

from shared.meta_labeling import (
    MetaModel,
    MetaInferenceResult,
    decision_from_confidence,
    encode_regime,
    compute_vol_zscore,
    build_meta_features_from_trade,
    build_meta_training_data,
    build_inference_features,
    FEATURE_NAMES,
    META_CONFIDENCE_THRESHOLD_FULL,
    META_CONFIDENCE_THRESHOLD_REDUCED,
    MIN_TRADES_FOR_TRAINING,
)


class TestDecisionFromConfidence:
    def test_full_above_threshold(self):
        r = decision_from_confidence(0.70)
        assert r.meta_decision == "FULL"
        assert r.scale_factor == 1.0

    def test_full_at_threshold(self):
        r = decision_from_confidence(META_CONFIDENCE_THRESHOLD_FULL)
        assert r.meta_decision == "FULL"
        assert r.scale_factor == 1.0

    def test_reduced_between_thresholds(self):
        r = decision_from_confidence(0.48)
        assert r.meta_decision == "REDUCED"
        assert r.scale_factor == 0.5

    def test_reduced_at_lower_threshold(self):
        r = decision_from_confidence(META_CONFIDENCE_THRESHOLD_REDUCED)
        assert r.meta_decision == "REDUCED"
        assert r.scale_factor == 0.5

    def test_skip_below_threshold(self):
        r = decision_from_confidence(0.30)
        assert r.meta_decision == "SKIP"
        assert r.scale_factor == 0.0

    def test_confidence_rounded(self):
        r = decision_from_confidence(0.55555)
        # Python's round() uses banker's rounding: 0.55555 → 0.5555
        assert r.meta_confidence == 0.5555


class TestEncodeRegime:
    def test_green(self):
        assert encode_regime("GREEN") == 2

    def test_yellow(self):
        assert encode_regime("YELLOW") == 1

    def test_red(self):
        assert encode_regime("RED") == 0

    def test_case_insensitive(self):
        assert encode_regime("green") == 2

    def test_unknown_falls_to_yellow(self):
        assert encode_regime("CRISIS") == 1


class TestComputeVolZscore:
    def test_basic(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(300) * 0.5))
        z = compute_vol_zscore(close)
        assert isinstance(z, float)

    def test_short_series_returns_zero(self):
        close = pd.Series([100, 101, 102])
        assert compute_vol_zscore(close) == 0.0

    def test_constant_series_returns_zero(self):
        close = pd.Series([100.0] * 300)
        assert compute_vol_zscore(close) == 0.0


class TestMetaModel:
    def test_initial_state(self):
        mm = MetaModel()
        assert not mm.is_trained
        assert mm.get_state()["trained"] is False
        assert mm.get_state()["n_trades"] == 0

    def test_untrained_predict_returns_full(self):
        mm = MetaModel()
        r = mm.predict({f: 0.5 for f in FEATURE_NAMES})
        assert r.meta_decision == "FULL"
        assert r.meta_confidence == 0.5
        assert r.scale_factor == 1.0

    def test_train_skipped_below_minimum(self):
        mm = MetaModel()
        n = MIN_TRADES_FOR_TRAINING - 10
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        assert not mm.is_trained

    def test_train_succeeds_with_enough_data(self):
        mm = MetaModel()
        n = MIN_TRADES_FOR_TRAINING + 10
        np.random.seed(42)
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        assert mm.is_trained
        assert mm.get_state()["n_trades"] == n

    def test_predict_after_training(self):
        mm = MetaModel()
        n = 100
        np.random.seed(42)
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        r = mm.predict({f: 0.0 for f in FEATURE_NAMES})
        assert 0.0 <= r.meta_confidence <= 1.0
        assert r.meta_decision in ("FULL", "REDUCED", "SKIP")

    def test_predict_missing_features(self):
        mm = MetaModel()
        n = 100
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        r = mm.predict({"primary_confidence": 0.5})
        assert r.meta_decision == "FULL"

    def test_class_imbalance_does_not_crash(self):
        mm = MetaModel()
        n = 100
        np.random.seed(42)
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series([1] * 90 + [0] * 10)  # 90/10 imbalance
        mm.train(X, y)
        assert mm.is_trained

    def test_constant_features_skip_training(self):
        mm = MetaModel()
        n = 100
        X = pd.DataFrame({f: np.zeros(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        assert not mm.is_trained


class TestBuildFeaturesFromTrade:
    @pytest.fixture
    def trade(self):
        return {
            "asset": "TEST",
            "side": "long",
            "entry": 100.0,
            "exit": 105.0,
            "entry_date": "2026-06-15",
            "exit_date": "2026-06-20",
            "return": 0.05,
            "pnl": 50.0,
            "reason": "tp",
        }

    @pytest.fixture
    def prob_history(self):
        return [
            {"date": "2026-06-10", "confidence": 65, "signal": "BUY"},
            {"date": "2026-06-15", "confidence": 72, "signal": "BUY"},
            {"date": "2026-06-18", "confidence": 60, "signal": "FLAT"},
        ]

    @pytest.fixture
    def close(self):
        np.random.seed(42)
        return pd.Series(100 + np.cumsum(np.random.randn(300) * 0.5),
                         index=pd.date_range("2024-01-01", periods=300, freq="D"))

    def test_basic_feature_building(self, trade, prob_history, close):
        features = build_meta_features_from_trade(
            trade, prob_history, [],
            feature_stability_penalty=-0.10,
            close=close,
        )
        assert features is not None
        assert features["primary_confidence"] == pytest.approx(0.72)
        assert features["feature_stability_penalty"] == -0.10
        assert all(f in features for f in FEATURE_NAMES)

    def test_no_matching_signal_returns_none(self, close):
        trade = {"entry_date": "2025-01-01", "pnl": 10.0}
        features = build_meta_features_from_trade(
            trade, [], [],
            feature_stability_penalty=0.0, close=close,
        )
        assert features is None

    def test_matches_closest_signal(self, trade, close):
        prob_history = [
            {"date": "2026-06-14", "confidence": 30, "signal": "SELL"},
            {"date": "2026-06-16", "confidence": 80, "signal": "BUY"},
        ]
        features = build_meta_features_from_trade(
            trade, prob_history, [],
            feature_stability_penalty=0.0, close=close,
        )
        # 2026-06-15 should match 2026-06-14 (closest <= entry_date)
        assert features["primary_confidence"] == pytest.approx(0.30)

    def test_validity_history_included(self, trade, prob_history, close):
        validity = [
            {"timestamp": "2026-06-01", "state": "GREEN", "periods_in_state": 10},
            {"timestamp": "2026-06-10", "state": "YELLOW", "periods_in_state": 5},
        ]
        features = build_meta_features_from_trade(
            trade, prob_history, validity,
            feature_stability_penalty=0.0, close=close,
        )
        assert features["regime_state_encoded"] == encode_regime("YELLOW")


class TestBuildTrainingData:
    def test_basic(self):
        n = 60
        trade_log = [
            {"entry_date": f"2026-06-{i+1:02d}", "pnl": 10.0 if i % 2 == 0 else -5.0}
            for i in range(n)
        ]
        prob_history = [
            {"date": f"2026-06-{i+1:02d}", "confidence": 60 + i % 20}
            for i in range(n)
        ]
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(300) * 0.5))
        X, y = build_meta_training_data(
            trade_log, prob_history, [],
            feature_stability_penalty=0.0, close=close,
        )
        assert X is not None
        assert y is not None
        assert len(X) == n
        assert len(y) == n
        assert list(X.columns) == FEATURE_NAMES

    def test_below_minimum_returns_none(self):
        trade_log = [{"entry_date": "2026-06-01", "pnl": 10.0}]
        prob_history = [{"date": "2026-06-01", "confidence": 60}]
        close = pd.Series([100.0] * 300)
        X, y = build_meta_training_data(
            trade_log, prob_history, [],
            feature_stability_penalty=0.0, close=close,
        )
        assert X is None
        assert y is None

    def test_skips_trades_without_pnl(self):
        n = 120
        trade_log = [
            {"entry_date": f"2026-06-{i+1:02d}", "pnl": 10.0 if i % 2 == 0 else None}
            for i in range(n)
        ]
        prob_history = [
            {"date": f"2026-06-{i+1:02d}", "confidence": 60}
            for i in range(n)
        ]
        close = pd.Series([100.0] * 300)
        X, y = build_meta_training_data(
            trade_log, prob_history, [],
            feature_stability_penalty=0.0, close=close,
        )
        assert X is not None
        assert len(X) == n // 2  # only the ones with pnl set


class TestBuildInferenceFeatures:
    def test_basic(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(300) * 0.5))
        features = build_inference_features(
            primary_confidence=0.75,
            regime_state="GREEN",
            periods_in_state=12,
            feature_stability_penalty=-0.10,
            close=close,
        )
        assert features["primary_confidence"] == 0.75
        assert features["regime_state_encoded"] == 2
        assert features["feature_stability_penalty"] == -0.10
        assert features["days_since_regime_change"] == 12.0
        assert all(f in features for f in FEATURE_NAMES)

    def test_red_regime(self):
        close = pd.Series([100.0] * 300)
        features = build_inference_features(
            primary_confidence=0.5, regime_state="RED",
            periods_in_state=3, feature_stability_penalty=0.0, close=close,
        )
        assert features["regime_state_encoded"] == 0
        assert features["days_since_regime_change"] == 3.0
