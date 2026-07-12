import datetime as _dt
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from paper_trading.inference.decision_builder import build_decision
from paper_trading.inference.feature_builder import FeatureBuilder
from paper_trading.inference.pipeline import AssetInferencePipeline


@pytest.fixture
def mock_asset():
    asset = MagicMock()
    asset.name = "EURUSD"
    asset.ticker = "EURUSD"
    asset.current_price = 1.1050
    asset.model = MagicMock()
    asset._model_iface = MagicMock()
    asset._ensemble = None
    asset._regime_model = None
    asset._meta_label_model = None
    asset._sizing_strategy = MagicMock()
    asset._signal_strategy = MagicMock()
    asset._sizing_config = MagicMock(return_value={})
    asset._calibration_registry = None
    asset._archetype_classifier = None
    asset._importance_store = MagicMock()
    asset._psi_monitor = MagicMock()
    asset._psi_drift_initialized = False
    asset._wal_writer = None
    asset._last_regime_long_prob = None
    asset._last_regime_raw_probas = None
    asset._last_regime_features = None
    asset._alpha_feature_cols = None
    asset.pos_mgr = MagicMock()
    asset.pos_mgr.current_side.return_value = None
    asset.pos_mgr.has_position.return_value = False
    asset.check_halt_conditions.return_value = {}
    asset._trained = True
    asset._suppress_until = 0.0
    asset._risk_off = False
    asset._last_bar_count = None
    asset._last_cycle_features = None
    asset._last_feature_vector = None
    asset._last_feature_hash = ""
    asset._last_feature_schema = None
    asset._apply_decision = MagicMock()
    asset._decision_to_dict = MagicMock(return_value={})
    asset._reg = MagicMock()
    asset._reg.validate_strategies = MagicMock()
    asset.config = {}
    asset.features = ["close", "volume"]
    # init pipeline state attrs set by pipeline
    asset._calibration_applied = False
    asset._last_macro_dir = None
    asset._last_blend_dir = None
    asset._entry_signal_dir = 0
    asset.signal_data = None
    asset.last_signal_date = None
    asset._last_regime_row = None
    asset._current_regime = "neutral"
    asset._ensemble_breakdown = {}
    asset._last_psi_drift = None
    asset._risk_signal = None
    asset._shadow_drift_intel = None
    asset._shadow_action = None
    asset._shadow_learning = None
    asset._last_meta_proba = None
    asset._calibrated_confidence = None  # D-01: override not set when calibration is disabled
    asset.regime_classifier = MagicMock()
    asset.regime_classifier.classify = MagicMock(
        return_value=pd.DataFrame({"regime": ["trending"], "P_trend": [0.8], "P_range": [0.1], "P_volatile": [0.1]})
    )
    return asset


def _make_price_df(n=300):
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99, "volume": 1000000})


@pytest.fixture
def pipeline(mock_asset):
    return AssetInferencePipeline(mock_asset)


class TestInit:
    def test_sets_asset(self, mock_asset):
        p = AssetInferencePipeline(mock_asset)
        assert p.asset is mock_asset
        assert p._truncation_validated is False
        assert p._validated_model_id == -1
        assert p._truncate_inference is False
        assert p._feature_builder._regime_cache_cycle == -1
        assert p._feature_builder._regime_features_cache is None


class TestDetectBarJump:
    def test_sets_suppress_when_bar_count_jumps(self, pipeline):
        asset = pipeline.asset
        asset._last_bar_count = 200
        with patch("time.time", return_value=1000.0):
            pipeline._detect_bar_jump(asset, 350)
        assert asset._suppress_until == 1000.0 + 3600

    def test_no_suppress_when_bar_count_stable(self, pipeline):
        asset = pipeline.asset
        asset._last_bar_count = 200
        with patch("time.time", return_value=1000.0):
            pipeline._detect_bar_jump(asset, 210)
        assert asset._suppress_until == 0.0

    def test_updates_last_bar_count(self, pipeline):
        asset = pipeline.asset
        pipeline._detect_bar_jump(asset, 300)
        assert asset._last_bar_count == 300

    def test_noop_on_first_call(self, pipeline):
        asset = pipeline.asset
        assert asset._last_bar_count is None
        pipeline._detect_bar_jump(asset, 300)
        assert asset._last_bar_count == 300


class TestDetectRiskOff:
    def test_sets_risk_off_when_vix_up_spx_down(self, pipeline):
        asset = pipeline.asset
        asset.name = "AUDUSD"
        asset.config = {"risk_off_enabled": True}
        df = pd.DataFrame({"vix_mom_5d": [0.5], "spx_mom_5d": [-0.3]})
        FeatureBuilder._detect_risk_off(asset, df)
        assert asset._risk_off

    def test_clears_risk_off_when_not_both_conditions(self, pipeline):
        asset = pipeline.asset
        asset.name = "AUDUSD"
        asset.config = {"risk_off_enabled": True}
        df = pd.DataFrame({"vix_mom_5d": [-0.1], "spx_mom_5d": [-0.3]})
        FeatureBuilder._detect_risk_off(asset, df)
        assert not asset._risk_off

    def test_disabled_by_default_for_all_assets(self, pipeline):
        asset = pipeline.asset
        asset.name = "AUDUSD"
        asset.config = {}  # no risk_off_enabled
        df = pd.DataFrame({"vix_mom_5d": [0.5], "spx_mom_5d": [-0.3]})
        FeatureBuilder._detect_risk_off(asset, df)
        assert not asset._risk_off

    def test_missing_columns_no_error(self, pipeline):
        asset = pipeline.asset
        asset.name = "AUDUSD"
        asset.config = {"risk_off_enabled": True}
        df = pd.DataFrame({"close": [1.0]})
        FeatureBuilder._detect_risk_off(asset, df)
        assert not asset._risk_off


class TestCheckArchetypeNans:
    def test_warns_when_nan_exceeds_threshold(self, pipeline, caplog):
        caplog.set_level("WARNING")
        df = pd.DataFrame({"adx": [np.nan] * 40, "rsi": [1.0] * 40, "bb_zscore": [1.0] * 40, "ema_spread": [1.0] * 40})
        pipeline._check_archetype_nans(pipeline.asset, df)
        assert "has 40 NaN rows" in caplog.text

    def test_no_warning_when_nan_below_threshold(self, pipeline, caplog):
        caplog.set_level("WARNING")
        df = pd.DataFrame({"adx": [np.nan] * 10, "rsi": [1.0] * 10, "bb_zscore": [1.0] * 10, "ema_spread": [1.0] * 10})
        pipeline._check_archetype_nans(pipeline.asset, df)
        assert "NaN" not in caplog.text


class TestCheckPsiDrift:
    def test_initializes_on_first_call(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"feat1": [1.0, 2.0]})
        pipeline._check_psi_drift(asset, x)
        assert asset._psi_drift_initialized is True

    def test_skips_when_no_snapshots(self, pipeline):
        asset = pipeline.asset
        asset._psi_drift_initialized = True
        asset._importance_store.get_latest_two_snapshots.return_value = (None, None)
        x = pd.DataFrame({"feat1": [1.0] * 300})
        pipeline._check_psi_drift(asset, x)
        asset._psi_monitor.compute_drift.assert_not_called()


class TestValidateAndTruncate:
    def test_truncates_when_validated(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"a": range(300)})
        features_df = x.copy()
        pipeline._truncation_validated = True
        pipeline._validated_model_id = id(asset.model)
        pipeline._truncate_inference = True
        x_out, f_out = pipeline._validate_and_truncate(asset, x, features_df)
        assert len(x_out) == 1
        assert len(f_out) == 1

    def test_runs_validation_on_first_call(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"a": range(300)})
        features_df = x.copy()
        n_warm = len(x) - 253
        asset._model_iface.predict.side_effect = [
            np.ones((n_warm, 2)),
            np.ones((1, 2)),
        ]
        x_out, f_out = pipeline._validate_and_truncate(asset, x, features_df)
        assert pipeline._truncation_validated is True

    def test_no_truncation_when_disabled(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"a": range(300)})
        features_df = x.copy()
        pipeline._truncation_validated = True
        pipeline._validated_model_id = id(asset.model)
        pipeline._truncate_inference = False
        x_out, f_out = pipeline._validate_and_truncate(asset, x, features_df)
        assert len(x_out) == 300


class TestRunInference:
    def test_2col_output_converts_to_3col(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"a": [1.0]})
        features_df = x.copy()
        asset._model_iface.predict.return_value = np.array([[0.3, 0.7]])
        proba, idx = pipeline._run_inference(asset, x, features_df)
        assert proba.shape[1] == 3
        assert proba[0, 0] == pytest.approx(0.3)
        assert proba[0, 2] == pytest.approx(0.7)

    def test_3col_output_passthrough(self, pipeline):
        asset = pipeline.asset
        x = pd.DataFrame({"a": [1.0]})
        features_df = x.copy()
        expected = np.array([[0.2, 0.3, 0.5]])
        asset._model_iface.predict.return_value = expected
        proba, idx = pipeline._run_inference(asset, x, features_df)
        np.testing.assert_array_equal(proba, expected)

    def test_writes_wal_inference_output(self, pipeline):
        asset = pipeline.asset
        asset._wal_writer = MagicMock()
        asset._model_hash = "abcdef123456"
        x = pd.DataFrame({"a": [1.0]})
        features_df = x.copy()
        asset._model_iface.predict.return_value = np.array([[0.2, 0.3, 0.5]])
        pipeline._run_inference(asset, x, features_df, feature_hash="hash123")
        assert asset._wal_writer.write.called
        call_kwargs = asset._wal_writer.write.call_args[0]
        assert call_kwargs[0] == "inference_output"
        assert call_kwargs[1]["feature_hash"] == "hash123"
        assert call_kwargs[1]["model_hash"] == "abcdef123456"

    def test_meta_label_inference(self, pipeline):
        asset = pipeline.asset
        asset._meta_label_model = MagicMock()
        asset._meta_label_model._trained = True
        asset._meta_label_model.predict_proba.return_value = 0.85
        x = pd.DataFrame({"a": [1.0]})
        features_df = x.copy()
        asset._model_iface.predict.return_value = np.array([[0.2, 0.3, 0.5]])
        pipeline._run_inference(asset, x, features_df)
        assert asset._last_meta_proba == 0.85


class TestRunInferenceEnsemble:
    def test_ensemble_blend_with_regime_features(self, pipeline):
        asset = pipeline.asset
        asset._ensemble = MagicMock()
        asset._ensemble.base_weight = 0.6
        asset._ensemble.regime_weight = 0.4
        asset._ensemble.combine_and_expand.return_value = (np.array([[0.1, 0.2, 0.7]]), None)
        asset._regime_model = MagicMock()
        asset._regime_model._feature_names = ["GC_hurst"]
        asset._regime_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        x = pd.DataFrame({"a": [1.0]})
        features_df = pd.DataFrame({"GC_hurst": [0.5]})
        asset._model_iface.predict.return_value = np.array([[0.3, 0.7]])
        proba, idx = pipeline._run_inference(asset, x, features_df)
        assert asset._last_regime_long_prob == pytest.approx(0.7)
        assert asset._last_regime_features is not None

    def test_ensemble_skipped_when_no_regime_features_in_df(self, pipeline):
        asset = pipeline.asset
        asset._ensemble = MagicMock()
        asset._regime_model = MagicMock()
        asset._regime_model._feature_names = ["GC_hurst"]
        x = pd.DataFrame({"a": [1.0]})
        features_df = pd.DataFrame({"close": [1.0]})
        asset._model_iface.predict.return_value = np.array([[0.3, 0.7]])
        proba, idx = pipeline._run_inference(asset, x, features_df)
        assert asset._last_regime_long_prob is None


class TestCalibrationApply:
    """C-03: regression coverage for the calibration simplex-preserving fix.

    These tests pin down ``AssetInferencePipeline._apply_calibration``,
    which previously overwrote ``proba[:, 0]`` with ``1 - cal_p_long``
    and broke the 3-class softmax simplex.
    """

    def _cal_registry_mock(self, calibrated_value: float):
        reg = MagicMock()
        reg.calibrate.return_value = np.array([calibrated_value])
        reg._calibrators = {asset_label(): MagicMock()}
        return reg

    def test_no_registry_returns_false(self, pipeline):
        asset = pipeline.asset
        asset._calibration_registry = None
        proba = np.array([[0.2, 0.3, 0.5]])
        applied = pipeline._apply_calibration(asset, proba)
        assert applied is False
        # proba unchanged
        np.testing.assert_array_equal(proba, [[0.2, 0.3, 0.5]])

    def test_calibration_disabled_returns_false(self, pipeline):
        asset = pipeline.asset
        asset._calibration_registry = self._cal_registry_mock(0.9)
        with patch("paper_trading.inference.pipeline.get_config") as cfg:
            cfg.return_value.defaults.get.return_value = {"enabled": False}
            proba = np.array([[0.1, 0.2, 0.7]])
            applied = pipeline._apply_calibration(asset, proba)
        assert applied is False
        np.testing.assert_array_equal(proba, [[0.1, 0.2, 0.7]])

    def test_calibration_preserves_simplex(self, pipeline):
        """Calibrated p_long replaces only col-2; the simplex stays normalized.

        Regression for C-03: previously ``proba[:, 0]`` was overwritten with
        ``1 - cal_p_long``, doubling BUY and SELL confidence simultaneously.
        """
        asset = pipeline.asset
        asset._calibration_registry = self._cal_registry_mock(0.85)
        with patch("paper_trading.inference.pipeline.get_config") as cfg:
            cfg.return_value.defaults.get.return_value = {"enabled": True}
            proba = np.array([[0.1, 0.2, 0.7]])
            proba.setflags(write=True)
            applied = pipeline._apply_calibration(asset, proba)
        assert applied is True
        # Renormalized: each column divided by 1.15 (the new row sum)
        assert proba[0, 0] == pytest.approx(0.1 / 1.15)
        assert proba[0, 1] == pytest.approx(0.2 / 1.15)
        assert proba[0, 2] == pytest.approx(0.85 / 1.15)
        # Rows sum to 1.0
        assert proba.sum(axis=1)[0] == pytest.approx(1.0)
        # Crucially: SELL column was NOT forced to (1 - cal_p_long)
        assert proba[0, 0] != pytest.approx(1.0 - 0.85)
        # Raw SELL info (0.1) was preserved proportionally — it's now 0.087
        # not 0.15 (which is what 1 - 0.85 would give)

    def test_calibration_failure_returns_false(self, pipeline):
        asset = pipeline.asset
        reg = MagicMock()
        reg.calibrate.side_effect = ValueError("bad input")
        reg._calibrators = {asset_label(): MagicMock()}
        asset._calibration_registry = reg
        with patch("paper_trading.inference.pipeline.get_config") as cfg:
            cfg.return_value.defaults.get.return_value = {"enabled": True}
            proba = np.array([[0.1, 0.2, 0.7]])
            applied = pipeline._apply_calibration(asset, proba)
        assert applied is False
        np.testing.assert_array_equal(proba, [[0.1, 0.2, 0.7]])


def asset_label() -> str:
    return "EURUSD"


class TestBuildDecision:
    def test_creates_trade_decision(self, pipeline):
        asset = pipeline.asset
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.7], "prob_short": [0.2], "prob_neutral": [0.1]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        asset.last_signal_date = None
        asset._last_meta_proba = None
        asset._calibrated_confidence = None  # Calibration not applied — fallback to result.confidence_pct
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "BUY"
        result.label = 1
        result.confidence_pct = 75.0
        df = pd.DataFrame({"close": [1.1050]})
        decision = build_decision(
            asset, result, pos_size=0.02, archetype="TREND", df=df, feature_hash="abc123"
        )
        assert decision.asset == "EURUSD"
        assert decision.signal == "BUY"
        assert decision.confidence == 75.0
        assert decision.feature_hash == "abc123"
        assert decision.position_size == 0.02
        assert decision.meta_label_confidence is None

    def test_meta_label_confidence_populated(self, pipeline):
        """When ``_last_meta_proba`` is set, the decision carries it as a
        percentage in [0, 100] alongside the direction-conditional confidence.
        """
        asset = pipeline.asset
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.7], "prob_short": [0.2], "prob_neutral": [0.1]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        asset.last_signal_date = None
        asset._last_meta_proba = 0.68321
        asset._calibrated_confidence = None  # Calibration not applied — fallback to result.confidence_pct
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "BUY"
        result.label = 1
        result.confidence_pct = 75.0
        df = pd.DataFrame({"close": [1.1050]})
        decision = build_decision(
            asset, result, pos_size=0.02, archetype="TREND", df=df, feature_hash="abc123"
        )
        assert decision.meta_label_confidence == pytest.approx(68.32, abs=0.01)
        # The legacy ``confidence`` field is unchanged (fallback when calibration not applied)
        assert decision.confidence == 75.0

    def test_uses_calibrated_confidence_when_available(self, pipeline):
        """When ``_calibrated_confidence`` is set (D-01 fix), the decision's
        confidence uses the calibrated P(win|direction) instead of
        ``result.confidence_pct`` (which uses ``max(prob_long, prob_short)``).
        """
        asset = pipeline.asset
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.7], "prob_short": [0.2], "prob_neutral": [0.1]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        asset.last_signal_date = None
        asset._last_meta_proba = None
        asset._calibrated_confidence = 0.653  # DirectionalCalibrator: P(TP hit | direction) = 65.3%
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "BUY"
        result.label = 1
        result.confidence_pct = 75.0  # Old max(prob_long, prob_short) — would be wrong
        df = pd.DataFrame({"close": [1.1050]})
        decision = build_decision(
            asset, result, pos_size=0.02, archetype="TREND", df=df, feature_hash="abc123"
        )
        assert decision.confidence == pytest.approx(65.3, abs=0.01)  # 0.653 * 100 = 65.3


class TestValidateInferenceTruncation:
    def test_disables_when_insufficient_rows(self, pipeline, caplog):
        caplog.set_level("WARNING")
        asset = pipeline.asset
        x = pd.DataFrame({"a": range(10)})
        pipeline._validate_inference_truncation(asset, x)
        assert pipeline._truncate_inference is False
        assert "insufficient rows" in caplog.text

    def test_enables_when_diff_within_tolerance(self, pipeline):
        asset = pipeline.asset
        n = 300
        x = pd.DataFrame({"a": range(n)})
        n_warm = len(x) - 253
        asset._model_iface.predict.side_effect = [
            np.ones((n_warm, 2)),
            np.ones((1, 2)),
        ]
        pipeline._validate_inference_truncation(asset, x)
        assert pipeline._truncate_inference is True

    def test_disables_when_diff_exceeds_tolerance(self, pipeline):
        asset = pipeline.asset
        n = 300
        x = pd.DataFrame({"a": range(n)})
        n_warm = len(x) - 253
        asset._model_iface.predict.side_effect = [
            np.ones((n_warm, 2)),
            np.zeros((1, 2)),
        ]
        pipeline._validate_inference_truncation(asset, x)
        assert pipeline._truncate_inference is False


class TestSizingAndSignal:
    def test_regime_sizing_path(self, pipeline):
        asset = pipeline.asset
        asset.config = {"regime_sizing": True}
        asset._sizing_config.return_value = {"size": 0.02}
        asset._sizing_strategy.compute.return_value = 0.02
        asset._signal_strategy.compute.return_value = MagicMock(confidence_pct=70.0)
        df = _make_price_df(300)
        proba = np.array([[0.2, 0.3, 0.5]])
        infer_idx = df.index[-1:]
        result, pos_size = pipeline._compute_sizing_and_signal(asset, df, proba, infer_idx, threshold=0.45)
        assert pos_size == 0.02

    def test_non_regime_sizing_path(self, pipeline):
        asset = pipeline.asset
        asset.config = {}
        asset._sizing_config.return_value = {"size": 0.02}
        asset._sizing_strategy.compute.return_value = 0.015
        asset._signal_strategy.compute.return_value = MagicMock(confidence_pct=65.0)
        df = _make_price_df(100)
        proba = np.array([[0.2, 0.3, 0.5]])
        infer_idx = df.index[-1:]
        result, pos_size = pipeline._compute_sizing_and_signal(asset, df, proba, infer_idx, threshold=0.45)
        assert pos_size == 0.015


class TestGenerateAndApply:
    def test_full_pipeline_with_mock_features(self, pipeline):
        asset = pipeline.asset
        asset._model_iface.predict.return_value = np.array([[0.3, 0.7]])

        prep_df = _make_price_df(300)
        _fetch_mock = patch.object(pipeline, "_fetch_and_prepare_data", return_value=prep_df)
        _fad_mock = patch("features.data_fetch.fetch_asset_data")
        _ohlcv_mock = patch("features.data_fetch.fetch_asset_ohlcv")
        _sf_mock = patch("features.alpha_features._compute_shared_features")
        _af_mock = patch("features.alpha_features.build_alpha_features")
        _rf_mock = patch("features.regime_features.generate_regime_features")
        _dq_mock = patch("paper_trading.inference.pipeline.get_diagnostics_queue")

        with (
            _fetch_mock,
            _fad_mock as mock_fad,
            _ohlcv_mock as mock_ohlcv,
            _sf_mock as mock_sf,
            _af_mock as mock_af,
            _rf_mock as mock_rf,
            _dq_mock as mock_dq,
        ):
            mock_fad.return_value = (
                _make_price_df(300),
                pd.DataFrame(),
                pd.DataFrame({"close": [1.0]}),
                pd.DataFrame({"close": [1.0]}),
                pd.DataFrame({"close": [1.0]}),
                pd.DataFrame({"close": [1.0]}),
            )
            ohlcv = _make_price_df(100)
            mock_ohlcv.return_value = ohlcv
            mock_sf.return_value = pd.DataFrame(index=_make_price_df(300).index)
            af = pd.DataFrame(
                {
                    "CLOSE_mom_21d": [0.01] * 300,
                    "CLOSE_carry_vol_adj": [0.0] * 300,
                    "CLOSE_mom_63d": [0.01] * 300,
                    "CLOSE_zscore_20": [0.0] * 300,
                    "CLOSE_dow_signal": [0.0] * 300,
                    "CLOSE_vol_ratio": [1.0] * 300,
                },
                index=_make_price_df(300).index,
            )
            mock_af.return_value = af
            mock_rf.return_value = pd.DataFrame({"hurst": [0.5]}, index=ohlcv.index[-1:])
            mock_dq.return_value = MagicMock()
            asset._signal_strategy.compute.return_value = MagicMock(
                signal_type="BUY",
                label=1,
                confidence_pct=75.0,
                signal_data=pd.DataFrame(
                    {
                        "close": [1.0],
                        "prob_long": [0.7],
                        "prob_short": [0.2],
                        "prob_neutral": [0.1],
                    },
                    index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=_dt.timezone.utc)]),
                ),
            )
            asset._sizing_strategy.compute.return_value = 0.02
            asset._sizing_config.return_value = {}
            result = pipeline.generate_signal(threshold=0.45)
            assert result is not None


class TestRecordInferenceProxies:
    """Proxy direction logic is now in build_decision (decision_builder.py)."""

    def test_buy_signal_sets_dir(self, pipeline):
        asset = pipeline.asset
        asset._last_macro_dir = None
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.7], "prob_short": [0.2], "prob_neutral": [0.1]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "BUY"
        result.label = 1
        result.confidence_pct = 75.0
        asset._last_meta_proba = None
        asset._calibrated_confidence = None
        df = pd.DataFrame({"close": [1.1050]})
        build_decision(asset, result, pos_size=0.02, archetype="TREND", df=df)
        assert asset._entry_signal_dir == 1

    def test_sell_signal_sets_dir(self, pipeline):
        asset = pipeline.asset
        asset._last_macro_dir = None
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.2], "prob_short": [0.7], "prob_neutral": [0.1]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "SELL"
        result.label = -1
        result.confidence_pct = 75.0
        asset._last_meta_proba = None
        asset._calibrated_confidence = None
        df = pd.DataFrame({"close": [1.1050]})
        build_decision(asset, result, pos_size=0.02, archetype="TREND", df=df)
        assert asset._entry_signal_dir == -1

    def test_flat_signal_sets_dir_zero(self, pipeline):
        asset = pipeline.asset
        asset._last_macro_dir = None
        tz_utc = _dt.timezone.utc
        asset.signal_data = pd.DataFrame(
            {"close": [1.1050], "prob_long": [0.2], "prob_short": [0.2], "prob_neutral": [0.6]},
            index=pd.DatetimeIndex([_dt.datetime(2025, 6, 1, tzinfo=tz_utc)]),
        )
        result = MagicMock()
        result.signal_data = asset.signal_data
        result.signal_type = "FLAT"
        result.label = 0
        result.confidence_pct = 50.0
        asset._last_meta_proba = None
        asset._calibrated_confidence = None
        df = pd.DataFrame({"close": [1.1050]})
        build_decision(asset, result, pos_size=0.02, archetype="TREND", df=df)
        assert asset._entry_signal_dir == 0
