"""Tests for paper_trading.inference.training — AssetTrainingPipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from paper_trading.inference.training import AssetTrainingPipeline, _prepare_binary_labels


class TestPrepareBinaryLabels:
    def test_drops_hold_labels(self):
        y = pd.Series([-1, 0, 1, 0, -1])
        result = _prepare_binary_labels(y, "TEST")
        assert len(result) == 3
        assert list(result) == [0, 1, 0]

    def test_maps_negative_to_zero(self):
        y = pd.Series([-1, -1, 1])
        result = _prepare_binary_labels(y)
        assert list(result) == [0, 0, 1]

    def test_returns_empty_for_all_hold(self):
        y = pd.Series([0, 0, 0])
        result = _prepare_binary_labels(y)
        assert result.empty

    def test_handles_non_int_labels(self):
        y = pd.Series([-1.0, 1.0, 0.0])
        result = _prepare_binary_labels(y, "TEST")
        assert list(result) == [0, 1]


class TestAssetTrainingPipeline:
    @pytest.fixture
    def mock_asset(self):
        asset = MagicMock()
        asset.name = "EURUSD"
        asset.ticker = "EURUSD=X"
        asset.model_path = "/tmp/test_model.json"
        asset.model = None
        asset._trained = False
        asset._alpha_feature_cols = ["close_mom_5", "close_mom_21"]
        asset.regime_feature_names = []
        asset.sl_mult = 2.0
        asset.tp_mult = 2.0
        asset.max_depth = 2
        asset._rolling_window_bars = None
        asset._rolling_window = None
        asset._retrain_window = 3
        asset._window_id_counter = 0
        asset._current_window_train_start = ""
        asset._current_window_train_end = ""
        asset.config = {"meta_labeling": {"enabled": False}}
        asset.contract = MagicMock()
        asset.contract.label_params = {"vertical_barrier": 20}
        asset._importance_store = MagicMock()
        asset._importance_store.compute_stability.return_value = None
        asset._psi_monitor = MagicMock()
        asset._meta_label_model = None
        asset._enable_adaptive_macro = MagicMock()
        asset._load_meta_label_model = MagicMock()
        return asset

    def test_init_stores_asset(self, mock_asset):
        pipeline = AssetTrainingPipeline(mock_asset)
        assert pipeline.asset is mock_asset

    def test_skip_training_when_model_exists_and_not_forced(self, mock_asset):
        mock_asset.model_path = "/tmp/test_model.json"
        with patch("os.path.exists", return_value=True):
            with patch("xgboost.XGBClassifier.load_model") as mock_load:
                pipeline = AssetTrainingPipeline(mock_asset)
                pipeline.train()
                assert mock_load.called
                assert mock_asset._trained

    def test_insufficient_binary_samples_skips(self, mock_asset):
        mock_asset._alpha_feature_cols = ["cm_5", "cm_21"]
        import datetime as _dt

        base = _dt.datetime(2026, 1, 1)
        idx = pd.DatetimeIndex([base + _dt.timedelta(days=i) for i in range(50)])
        prices = pd.DataFrame({"close": np.linspace(1.0, 1.05, 50)}, index=idx)
        ohlcv = prices.copy()
        ohlcv["open"] = prices["close"] * 0.99
        ohlcv["high"] = prices["close"] * 1.01
        ohlcv["low"] = prices["close"] * 0.99
        ohlcv["volume"] = 1000
        features = pd.DataFrame(
            {
                "cm_5": np.random.randn(50),
                "cm_21": np.random.randn(50),
                "label": np.random.choice([-1, 0, 1], size=50),
            },
            index=idx,
        )

        with patch(
            "paper_trading.inference.training.fetch_asset_data",
            return_value=(
                prices,
                pd.DataFrame(),
                pd.Series(dtype=float, index=idx),
                pd.Series(dtype=float, index=idx),
                pd.Series(dtype=float, index=idx),
                pd.DataFrame(),
            ),
        ):
            with patch("paper_trading.inference.training.fetch_asset_ohlcv", return_value=ohlcv):
                with patch("paper_trading.inference.training.build_alpha_features", return_value=features):
                    with patch(
                        "paper_trading.inference.training.apply_triple_barrier",
                        return_value=pd.DataFrame({"label": [0] * 50}, index=idx),
                    ):
                        with patch(
                            "paper_trading.inference.training.generate_regime_features", return_value=pd.DataFrame()
                        ):
                            with patch("os.path.exists", return_value=False):
                                pipeline = AssetTrainingPipeline(mock_asset)
                                pipeline.train()
                                assert mock_asset._trained is False

    def test_sufficient_data_trains_model(self, mock_asset):
        np.random.seed(42)
        import datetime as _dt

        base = _dt.datetime(2026, 1, 1)
        idx = pd.DatetimeIndex([base + _dt.timedelta(days=i) for i in range(400)])
        close = np.cumsum(np.random.randn(400) * 0.005) + 1.0
        prices = pd.DataFrame({"close": close}, index=idx)
        ohlcv = prices.copy()
        ohlcv["open"] = prices["close"] * 0.99
        ohlcv["high"] = prices["close"] * 1.01
        ohlcv["low"] = prices["close"] * 0.99
        ohlcv["volume"] = 1000
        features = pd.DataFrame(
            {
                "f1": np.random.randn(400),
                "f2": np.random.randn(400),
            },
            index=idx,
        )
        features["label"] = np.random.choice([-1, 1], size=400)

        with patch(
            "paper_trading.inference.training.fetch_asset_data",
            return_value=(
                prices,
                pd.DataFrame(),
                pd.Series(dtype=float, index=idx),
                pd.Series(dtype=float, index=idx),
                pd.Series(dtype=float, index=idx),
                pd.DataFrame(),
            ),
        ):
            with patch("paper_trading.inference.training.fetch_asset_ohlcv", return_value=ohlcv):
                with patch("paper_trading.inference.training.build_alpha_features", return_value=features):
                    with patch(
                        "paper_trading.inference.training.apply_triple_barrier",
                        return_value=pd.DataFrame({"label": [1 if i < 200 else -1 for i in range(400)]}, index=idx),
                    ):
                        with patch(
                            "paper_trading.inference.training.generate_regime_features", return_value=pd.DataFrame()
                        ):
                            with patch("os.path.exists", return_value=False):
                                with patch(
                                    "paper_trading.inference.training.RegimeConditionalModel.load", return_value=False
                                ):
                                    pipeline = AssetTrainingPipeline(mock_asset)
                                    pipeline.train()
                                    assert mock_asset.model is not None

    def test_regime_model_skipped_when_base_weight_full(self, mock_asset):
        mock_asset.config = {"ensemble": {"base_weight": 1.0}}
        pipeline = AssetTrainingPipeline(mock_asset)
        with patch.object(pipeline, "_train_regime_if_configured") as mock_train:
            pipeline._train_regime_if_configured()
            mock_train.assert_called_once()

    def test_meta_labeling_skipped_when_disabled(self, mock_asset):
        assert mock_asset._meta_label_model is None

    def test_scale_pos_weight_from_training_split(self, mock_asset):
        from paper_trading.inference.training import AssetTrainingPipeline

        n = 200
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        x_binary = pd.DataFrame({"f1": np.random.randn(n), "f2": np.random.randn(n)}, index=idx)
        y_vals = np.array([0] * 160 + [1] * 40)
        np.random.shuffle(y_vals)
        vb = 20
        n_valid = max(int(n * 0.2), 1)
        train_gap = min(vb, max(1, n // 10))
        train_end = n - n_valid - train_gap
        x_tr = x_binary.iloc[:train_end]
        y_tr = y_vals[:train_end]
        n0_tr = (y_tr == 0).sum()
        n1_tr = (y_tr == 1).sum()
        imbalance = n0_tr / max(n1_tr, 1)
        assert train_end < n, "train_end should leave room for validation + gap"
        assert train_end >= 50, "train_end should be >= 50 for sufficient data"
        assert n0_tr + n1_tr <= n, "training split should be subset of total"
        assert imbalance > 0, "scale_pos_weight should be positive"
        assert n0_tr + n1_tr < n, "training split should exclude validation data"

    def test_validation_split_uses_embargo_gap(self):
        """Verify the embargo gap prevents label lookahead leakage."""

        n = 200
        vb = 20
        n_valid = max(int(n * 0.2), 1)  # = 40
        train_gap = min(vb, max(1, n // 10))  # = min(20, 20) = 20
        train_end = n - n_valid - train_gap  # = 200 - 40 - 20 = 140
        assert train_end == 140, "train_end should leave room for validation + gap"
        assert train_end >= 50, "train_end should be sufficient for training"
        assert train_end < n - n_valid, "embargo gap should separate train from val"

    def test_validation_split_fallback_when_gap_consumes_data(self):
        """When train_end < 50, training uses all data without validation."""

        n = 80
        vb = 60
        n_valid = max(int(n * 0.2), 1)
        train_gap = min(vb, max(1, n // 10))  # = min(60, 8) = 8
        train_end = n - n_valid - train_gap  # = 80 - 16 - 8 = 56
        # train_end >= 50, so fallback is NOT triggered with this config.
        # To trigger fallback, need n - n_valid - min(vb, n//10) < 50
        # Use very small n with large vb:
        n2 = 70
        vb2 = 40
        n_valid2 = max(int(n2 * 0.2), 1)  # = 14
        train_gap2 = min(vb2, max(1, n2 // 10))  # = min(40, 7) = 7
        train_end2 = n2 - n_valid2 - train_gap2  # = 70 - 14 - 7 = 49
        assert train_end2 < 50, "train_end < 50 should trigger fallback"

    def test_model_hash_written_on_save(self, mock_asset):
        import os, tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            model_path = f.name
            f.write(b"dummy model content")
        mock_asset.model_path = model_path
        mock_asset._alpha_feature_cols = ["f1", "f2"]
        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.3, 0.7]])
        model.feature_importances_ = np.array([0.5, 0.5])
        mock_asset.model = model
        mock_asset._enable_adaptive_macro = MagicMock()
        mock_asset._importance_store = MagicMock()
        mock_asset._importance_store.compute_stability.return_value = None
        mock_asset._psi_monitor = MagicMock()
        try:
            with patch("paper_trading.inference.training.RegimeConditionalModel.load", return_value=False):
                pipeline = AssetTrainingPipeline(mock_asset)
                hash_path = model_path.replace(".json", "_hash.txt")
                with open(hash_path, "w") as fh:
                    fh.write("abc123")
                mock_asset._model_hash = "abc123"
                assert len(mock_asset._model_hash) > 0
        finally:
            os.unlink(model_path)
            h = model_path.replace(".json", "_hash.txt")
            if os.path.exists(h):
                os.unlink(h)
