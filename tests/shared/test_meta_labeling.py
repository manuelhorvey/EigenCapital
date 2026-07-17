"""Tests for shared/meta_labeling.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shared.meta_labeling import (
    FEATURE_NAMES,
    MIN_TRADES_FOR_TRAINING,
    MetaInferenceResult,
    MetaModel,
    build_inference_features,
    build_meta_features_from_trade,
    build_meta_training_data,
    compute_vol_zscore,
    decision_from_confidence,
    encode_regime,
)


class TestEncodeRegime:
    def test_green(self):
        assert encode_regime("GREEN") == 2

    def test_yellow(self):
        assert encode_regime("YELLOW") == 1

    def test_red(self):
        assert encode_regime("RED") == 0

    def test_case_insensitive(self):
        assert encode_regime("green") == 2
        assert encode_regime("Yellow") == 1

    def test_unknown_returns_yellow(self):
        assert encode_regime("UNKNOWN") == 1


class TestComputeVolZscore:
    def test_flat_returns_zero(self):
        close = pd.Series(np.full(300, 100.0))
        z = compute_vol_zscore(close)
        assert z == pytest.approx(0.0, abs=0.01)

    def test_insufficient_data_returns_zero(self):
        close = pd.Series(np.full(10, 100.0))
        z = compute_vol_zscore(close, window=21)
        assert z == 0.0

    def test_increasing_vol_positive_zscore(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(300) * 0.3))
        z = compute_vol_zscore(close)
        assert isinstance(z, float)
        assert np.isfinite(z)


class TestDecisionFromConfidence:
    def test_full_above_threshold(self):
        result = decision_from_confidence(0.70)
        assert result.meta_decision == "FULL"
        assert result.scale_factor == 1.0
        assert result.sl_adjust == 1.0
        assert result.tp_adjust == 1.0

    def test_reduced_between_thresholds(self):
        result = decision_from_confidence(0.45)
        assert result.meta_decision == "REDUCED"
        assert result.scale_factor == 0.5
        assert result.sl_adjust == 0.80
        assert result.tp_adjust == 0.80

    def test_skip_below_threshold(self):
        result = decision_from_confidence(0.30)
        assert result.meta_decision == "SKIP"
        assert result.scale_factor == 0.0

    def test_custom_thresholds(self):
        result = decision_from_confidence(0.50, full_threshold=0.60, reduced_threshold=0.40)
        assert result.meta_decision == "REDUCED"

    def test_at_exact_threshold_full(self):
        result = decision_from_confidence(0.55)
        assert result.meta_decision == "FULL"

    def test_edge_case_at_reduced_threshold(self):
        result = decision_from_confidence(0.40)
        assert result.meta_decision == "REDUCED"
        result = decision_from_confidence(0.3999)
        assert result.meta_decision == "SKIP"


class TestMetaModel:
    def test_default_not_trained(self):
        model = MetaModel()
        assert not model.is_trained
        assert model.get_state()["trained"] is False

    def test_train_skipped_with_few_trades(self):
        model = MetaModel()
        features = pd.DataFrame({k: np.random.randn(10) for k in FEATURE_NAMES})
        labels = pd.Series(np.random.randint(0, 2, size=10))
        model.train(features, labels)
        assert not model.is_trained
        assert model.get_state()["n_trades"] == 10

    def test_train_succeeds_with_sufficient_trades(self):
        model = MetaModel()
        n = MIN_TRADES_FOR_TRAINING + 10
        np.random.seed(42)
        features = pd.DataFrame({k: np.random.randn(n) for k in FEATURE_NAMES})
        labels = pd.Series(np.random.randint(0, 2, size=n))
        model.train(features, labels)
        assert model.is_trained

    def test_train_missing_features(self):
        model = MetaModel()
        n = MIN_TRADES_FOR_TRAINING + 10
        features = pd.DataFrame({"primary_confidence": np.random.randn(n), "regime_state_encoded": np.random.randn(n)})
        labels = pd.Series(np.random.randint(0, 2, size=n))
        model.train(features, labels)
        assert not model.is_trained

    def test_predict_before_training_returns_full(self):
        model = MetaModel()
        result = model.predict({"primary_confidence": 0.7, "regime_state_encoded": 2})
        assert result.meta_decision == "FULL"
        assert result.scale_factor == 1.0

    def test_predict_after_training_returns_result(self):
        model = MetaModel()
        np.random.seed(42)
        n = MIN_TRADES_FOR_TRAINING + 10
        features = pd.DataFrame({k: np.random.randn(n) for k in FEATURE_NAMES})
        labels = pd.Series(np.random.randint(0, 2, size=n))
        model.train(features, labels)
        result = model.predict({k: 0.5 for k in FEATURE_NAMES})
        assert isinstance(result, MetaInferenceResult)
        assert result.meta_decision in ("FULL", "REDUCED", "SKIP")

    def test_predict_missing_features_falls_back(self):
        model = MetaModel()
        model._trained = True
        result = model.predict({"primary_confidence": 0.7})
        assert result.meta_decision == "FULL"
        assert result.scale_factor == 1.0


class TestBuildMetaFeaturesFromTrade:
    def test_no_entry_date_returns_none(self):
        result = build_meta_features_from_trade({"pnl": 100}, [], [], 0.0, pd.Series([100.0, 101.0]))
        assert result is None

    def test_empty_prob_history_returns_none(self):
        result = build_meta_features_from_trade(
            {"entry_date": "2026-01-05", "pnl": 100}, [], [], 0.0, pd.Series([100.0, 101.0])
        )
        assert result is None

    def test_returns_features_with_data(self):
        close = pd.Series(np.full(300, 100.0), index=pd.date_range("2026-01-01", periods=300, freq="D"))
        result = build_meta_features_from_trade(
            {"entry_date": "2026-01-05", "pnl": 100},
            [{"date": "2026-01-04", "confidence": 70, "signal": "BUY"}],
            [{"timestamp": "2026-01-04", "state": "GREEN", "periods_in_state": 5}],
            0.05,
            close,
            vol_regime="normal",
        )
        assert result is not None
        assert "primary_confidence" in result
        assert result["primary_confidence"] == 0.7
        assert result["regime_state_encoded"] == 2
        assert result["feature_stability_penalty"] == 0.05


class TestBuildMetaTrainingData:
    def test_empty_trade_log_returns_none(self):
        features, labels = build_meta_training_data([], [], [], 0.0, pd.Series())
        assert features is None
        assert labels is None

    def test_insufficient_trades_returns_none(self):
        close = pd.Series(np.full(300, 100.0), index=pd.date_range("2026-01-01", periods=300, freq="D"))
        trades = [{"entry_date": "2026-01-05", "pnl": 100}]
        features, labels = build_meta_training_data(trades, [], [], 0.0, close)
        assert features is None
        assert labels is None


class TestBuildInferenceFeatures:
    def test_returns_correct_keys(self):
        close = pd.Series(np.full(300, 100.0))
        result = build_inference_features(0.7, "GREEN", 10, 0.0, close)
        assert set(result.keys()) == set(FEATURE_NAMES)
        assert result["primary_confidence"] == 0.7
        assert result["regime_state_encoded"] == 2
        assert result["days_since_regime_change"] == 10.0
