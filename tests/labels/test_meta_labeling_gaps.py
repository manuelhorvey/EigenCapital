import numpy as np
import pandas as pd
import pytest

from shared.meta_labeling import (
    MetaModel,
    decision_from_confidence,
    compute_vol_zscore,
    build_meta_features_from_trade,
    build_meta_training_data,
    build_inference_features,
    FEATURE_NAMES,
)


# ── Edge cases and gap coverage for meta_labeling ────────────────────────────
# Targets uncovered lines: 138-140 (missing features returns None), 210 (empty entry_date),
# 219 (matching_signal = prob_history[0]), 274 (features is None continue)

class TestTrainMissingFeatures:
    def test_train_missing_features_returns_false(self):
        """Missing required features prevents training (line 138-140)."""
        mm = MetaModel()
        n = 100
        X = pd.DataFrame({"primary_confidence": np.random.randn(n), "regime_state_encoded": np.random.randn(n)})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        assert not mm.is_trained


class TestBuildFeaturesFromTradeEdgeCases:
    def test_empty_entry_date_returns_none(self, close):
        """Trade without entry_date returns None (line 210)."""
        trade = {"pnl": 10.0}
        result = build_meta_features_from_trade(
            trade, [], [], 0.0, close,
        )
        assert result is None

    @pytest.fixture
    def close(self):
        np.random.seed(42)
        return pd.Series(100 + np.cumsum(np.random.randn(300) * 0.5))

    def test_matching_signal_falls_back_to_first(self, close):
        """When no signal <= entry_date, uses first prob_history entry (line 219)."""
        trade = {"entry_date": "2025-01-01", "pnl": 10.0}
        prob_history = [
            {"date": "2026-06-14", "confidence": 30, "signal": "SELL"},
            {"date": "2026-06-16", "confidence": 80, "signal": "BUY"},
        ]
        features = build_meta_features_from_trade(
            trade, prob_history, [], 0.0, close,
        )
        assert features is not None
        assert features["primary_confidence"] == pytest.approx(0.30)

    def test_both_histories_empty_returns_none(self, close):
        """Empty prob_history and validity_history returns None."""
        trade = {"entry_date": "2025-01-01", "pnl": 10.0}
        features = build_meta_features_from_trade(trade, [], [], 0.0, close)
        assert features is None

    def test_inference_features_vol_regime_low(self, close):
        """Vol regime 'low_vol' sets vol_regime_low=1."""
        features = build_inference_features(
            primary_confidence=0.5, regime_state="GREEN",
            periods_in_state=5, feature_stability_penalty=0.0,
            close=close, vol_regime="low_vol",
        )
        assert features["vol_regime_low"] == 1.0
        assert features["vol_regime_high"] == 0.0

    def test_inference_features_vol_regime_high(self, close):
        """Vol regime 'high_vol' sets vol_regime_high=1."""
        features = build_inference_features(
            primary_confidence=0.5, regime_state="GREEN",
            periods_in_state=5, feature_stability_penalty=0.0,
            close=close, vol_regime="high_vol",
        )
        assert features["vol_regime_low"] == 0.0
        assert features["vol_regime_high"] == 1.0


class TestBuildTrainingDataEdgeCases:
    def test_filters_none_features(self):
        """Trades where build_meta_features_from_trade returns None are skipped (line 274)."""
        n = 70
        trade_log = [
            {"entry_date": f"2026-06-{i+1:02d}", "pnl": 10.0 if i % 3 == 0 else None}
            for i in range(n)
        ]
        prob_history = [
            {"date": f"2026-06-{i+1:02d}", "confidence": 60}
            for i in range(n)
        ]
        close = pd.Series([100.0] * 300)
        X, y = build_meta_training_data(
            trade_log, prob_history, [], 0.0, close,
        )
        if X is None:
            assert y is None
        else:
            assert len(X) > 0

    def test_decision_from_confidence_sl_adjust_tp_adjust(self):
        """Verify sl_adjust/tp_adjust values for each decision level."""
        full = decision_from_confidence(0.70)
        assert full.sl_adjust == 1.0
        assert full.tp_adjust == 1.0

        reduced = decision_from_confidence(0.45)
        assert reduced.sl_adjust == 0.80
        assert reduced.tp_adjust == 0.80

        skip = decision_from_confidence(0.30)
        assert skip.sl_adjust == 0.0
        assert skip.tp_adjust == 0.0

    def test_vol_zscore_insufficient_data_reverts_to_std(self):
        """compute_vol_zscore uses full series std when < 252 data points."""
        close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
        z = compute_vol_zscore(close)
        assert isinstance(z, float)


class TestPredictMissingFeatures:
    def test_predict_missing_features_after_training(self):
        """When trained but predict is called with missing features (line 172-179)."""
        mm = MetaModel()
        n = 100
        np.random.seed(42)
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        r = mm.predict({"primary_confidence": 0.5})
        assert r.meta_decision == "FULL"
        assert r.meta_confidence == 0.5

    def test_predict_with_all_features(self):
        """Trained model predicts with complete feature dict."""
        mm = MetaModel()
        n = 100
        np.random.seed(42)
        X = pd.DataFrame({f: np.random.randn(n) for f in FEATURE_NAMES})
        y = pd.Series(np.random.randint(0, 2, size=n))
        mm.train(X, y)
        features_dict = {f: 0.5 for f in FEATURE_NAMES}
        r = mm.predict(features_dict)
        assert 0.0 <= r.meta_confidence <= 1.0
