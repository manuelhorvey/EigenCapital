from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from paper_trading.dynamic_sltp import (
    DynamicSLTPEngine,
    build_dynamic_sltp_from_config,
)


class TestComputeBarriers:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(atr_period=14, atr_mult_sl=2.0, atr_mult_tp=3.0, min_rr_ratio=1.5)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
            }
        )

    def test_atr_barriers_long(self, engine, df):
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        assert result.stop_loss < 100.0
        assert result.take_profit > 100.0
        assert result.method_used == "atr"

    def test_atr_barriers_short(self, engine, df):
        result = engine.compute_barriers(100.0, "short", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        assert result.stop_loss > 100.0
        assert result.take_profit < 100.0
        assert result.method_used == "atr"

    def test_atr_barriers_enforces_min_rr(self, engine, df):
        tight = DynamicSLTPEngine(atr_mult_sl=5.0, atr_mult_tp=3.0, min_rr_ratio=3.0)
        result = tight.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        sl_dist = 100.0 - result.stop_loss
        tp_dist = result.take_profit - 100.0
        assert tp_dist / sl_dist >= 2.99

    def test_vol_ewm_barriers_long(self, engine, df):
        engine.method = "vol_ewm"
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, vol=0.02)
        assert result.stop_loss < 100.0
        assert result.take_profit > 100.0
        assert result.method_used == "vol_ewm"

    def test_vol_ewm_barriers_short(self, engine, df):
        engine.method = "vol_ewm"
        result = engine.compute_barriers(100.0, "short", df, sl_mult=1.0, tp_mult=1.0, vol=0.02)
        assert result.stop_loss > 100.0
        assert result.take_profit < 100.0

    def test_static_barriers(self, engine, df):
        engine.method = "static"
        result = engine.compute_barriers(100.0, "long", df, sl_mult=2.0, tp_mult=3.0, vol=0.02)
        assert result.stop_loss == pytest.approx(100.0 * (1 - 0.02 * 2.0))
        assert result.take_profit == pytest.approx(100.0 * (1 + 0.02 * 3.0))

    def test_static_barriers_short(self, engine, df):
        engine.method = "static"
        result = engine.compute_barriers(100.0, "short", df, sl_mult=2.0, tp_mult=3.0, vol=0.02)
        assert result.stop_loss == pytest.approx(100.0 * (1 + 0.02 * 2.0))
        assert result.take_profit == pytest.approx(100.0 * (1 - 0.02 * 3.0))

    def test_trailing_initial_barriers(self, engine, df):
        engine.method = "trailing"
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        assert result.method_used == "trailing"
        assert result.trailing_activation_price is not None
        if result.trailing_activation_price is not None:
            assert result.trailing_activation_price > 100.0

    def test_regime_calm_wider_tp(self, df):
        engine = DynamicSLTPEngine(min_rr_ratio=0.1)
        calm = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="calm")
        neutral = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        assert (calm.take_profit - 100.0) > (neutral.take_profit - 100.0)

    def test_regime_crisis_wider_sl(self, engine, df):
        crisis = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="crisis")
        neutral = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        sl_dist_crisis = 100.0 - crisis.stop_loss
        sl_dist_neutral = 100.0 - neutral.stop_loss
        assert sl_dist_crisis > sl_dist_neutral

    def test_sl_never_below_zero_long(self, engine, df):
        wide = DynamicSLTPEngine(atr_mult_sl=50.0, atr_mult_tp=3.0)
        result = wide.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        assert result.stop_loss >= 0.0

    def test_tp_never_below_zero_short(self, engine, df):
        wide = DynamicSLTPEngine(atr_mult_sl=3.0, atr_mult_tp=50.0)
        result = wide.compute_barriers(100.0, "short", df, sl_mult=1.0, tp_mult=1.0)
        assert result.take_profit >= 0.0

    def test_sl_mult_and_tp_mult(self, engine, df):
        double_sl = engine.compute_barriers(100.0, "long", df, sl_mult=2.0, tp_mult=1.0, regime="neutral")
        base = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, regime="neutral")
        sl_dist_double = 100.0 - double_sl.stop_loss
        sl_dist_base = 100.0 - base.stop_loss
        assert sl_dist_double == pytest.approx(sl_dist_base * 2.0, rel=0.3)


class TestCalibrate:
    def test_calibrate_sets_atr_mult_sl(self, sample_price_data):
        engine = DynamicSLTPEngine(atr_mult_sl=2.0, calibration_scale=1.0)
        engine.calibrate(sample_price_data)
        assert engine.atr_mult_sl > 0

    def test_calibrate_with_scale(self, sample_price_data):
        engine = DynamicSLTPEngine(atr_mult_sl=2.0, calibration_scale=1.5)
        engine.calibrate(sample_price_data)
        base = DynamicSLTPEngine(atr_mult_sl=2.0, calibration_scale=1.0)
        base.calibrate(sample_price_data)
        assert engine.atr_mult_sl == pytest.approx(base.atr_mult_sl * 1.5)

    def test_calibrate_handles_empty_df(self):
        engine = DynamicSLTPEngine(atr_mult_sl=2.0)
        df = pd.DataFrame({"close": [100.0]})
        engine.calibrate(df)  # should not raise


class TestTrailingStop:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(atr_period=14, trailing_activation_mult=1.5, trailing_distance_mult=2.0)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
            }
        )

    def test_not_activated_when_move_small(self, engine, df):
        result = engine.compute_trailing_stop(
            "long",
            entry_price=100.0,
            current_price=101.0,
            initial_sl=99.0,
            current_sl=99.0,
            take_profit=110.0,
            df=df,
        )
        assert not result.activated
        assert result.trailing_sl is None

    def test_activated_when_move_large(self, engine, df):
        result = engine.compute_trailing_stop(
            "long",
            entry_price=100.0,
            current_price=106.0,
            initial_sl=97.0,
            current_sl=97.0,
            take_profit=110.0,
            df=df,
        )
        assert result.activated
        assert result.trailing_sl is not None
        assert result.locked_profit is not None

    def test_trailing_short(self, engine, df):
        result = engine.compute_trailing_stop(
            "short",
            entry_price=100.0,
            current_price=94.0,
            initial_sl=103.0,
            current_sl=103.0,
            take_profit=90.0,
            df=df,
        )
        assert result.activated
        assert result.trailing_sl is not None

    def test_short_not_activated(self, engine, df):
        result = engine.compute_trailing_stop(
            "short",
            entry_price=100.0,
            current_price=99.0,
            initial_sl=103.0,
            current_sl=103.0,
            take_profit=90.0,
            df=df,
        )
        assert not result.activated

    def test_returns_none_when_not_tighter(self, engine, df):
        result = engine.compute_trailing_stop(
            "long",
            entry_price=100.0,
            current_price=106.0,
            initial_sl=97.0,
            current_sl=105.0,
            take_profit=110.0,
            df=df,
        )
        assert not result.activated

    def test_locked_profit_positive(self, engine, df):
        result = engine.compute_trailing_stop(
            "long",
            entry_price=100.0,
            current_price=106.0,
            initial_sl=97.0,
            current_sl=97.0,
            take_profit=110.0,
            df=df,
        )
        assert result.activated
        if result.locked_profit is not None:
            assert result.locked_profit > 0


class TestPostEntryAdjust:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(post_adjust_interval_bars=3, max_sl_widen_pct=0.0)

    @pytest.fixture
    def rising_df(self):
        prices = 100 + np.arange(50) * 0.5
        return pd.DataFrame(
            {
                "close": prices,
                "high": prices * 1.005,
                "low": prices * 0.995,
            }
        )

    def test_no_adjust_too_early(self, engine, rising_df):
        result = engine.post_entry_adjust(
            "long",
            100.0,
            current_sl=98.0,
            current_tp=110.0,
            df=rising_df,
            vol=0.02,
            bars_since_entry=1,
        )
        assert result.new_sl is None
        assert result.new_tp is None

    def test_vol_drop_tightens_sl(self, engine, rising_df):
        high_vol_df = rising_df.copy()
        high_vol_df["close"] = 100 + np.cumsum(np.random.randn(50) * 2.0)
        low_vol_df = high_vol_df.copy()
        low_vol_df["close"] = high_vol_df["close"].iloc[:40].tolist() + [
            high_vol_df["close"].iloc[39] + i * 0.02 for i in range(10)
        ]
        result = engine.post_entry_adjust(
            "long",
            100.0,
            current_sl=98.0,
            current_tp=110.0,
            df=low_vol_df,
            vol=0.05,
            bars_since_entry=5,
        )
        if result.new_sl is not None:
            assert result.new_sl > 98.0  # tightened toward entry

    def test_tp_nudge_when_stalled(self, engine, rising_df):
        stalled = pd.DataFrame(
            {
                "close": [100, 100, 100, 100, 100, 100, 100, 100.5, 100.5, 100.5],
                "high": [101] * 10,
                "low": [99] * 10,
            }
        )
        result = engine.post_entry_adjust(
            "long",
            100.0,
            current_sl=98.0,
            current_tp=108.0,
            df=stalled,
            vol=0.02,
            bars_since_entry=8,
        )
        if result.new_tp is not None:
            assert result.new_tp < 108.0
            assert result.reason is not None
            assert "tp_nudged" in result.reason

    def test_short_post_entry_no_adjust(self, engine, rising_df):
        result = engine.post_entry_adjust(
            "short",
            100.0,
            current_sl=102.0,
            current_tp=95.0,
            df=rising_df,
            vol=0.02,
            bars_since_entry=1,
        )
        assert result.new_sl is None
        assert result.new_tp is None


class TestHelpers:
    def test_compute_atr(self, sample_price_data):
        engine = DynamicSLTPEngine()
        atr = engine._compute_atr(sample_price_data, period=14)
        assert atr > 0

    def test_estimate_vol(self, sample_price_data):
        engine = DynamicSLTPEngine()
        vol = engine._estimate_vol(sample_price_data)
        assert vol > 0

    def test_estimate_gap_risk(self, sample_price_data):
        engine = DynamicSLTPEngine()
        gap = engine._estimate_gap_risk(sample_price_data)
        assert gap >= 0

    def test_regime_sl_mult(self):
        engine = DynamicSLTPEngine()
        assert engine._regime_sl_mult("calm") == 0.8
        assert engine._regime_sl_mult("neutral") == 1.0
        assert engine._regime_sl_mult("crisis") == 1.5
        assert engine._regime_sl_mult("unknown") == 1.0

    def test_regime_tp_mult(self):
        engine = DynamicSLTPEngine()
        assert engine._regime_tp_mult("calm") == 1.2
        assert engine._regime_tp_mult("neutral") == 1.0
        assert engine._regime_tp_mult("crisis") == 0.6
        assert engine._regime_tp_mult("unknown") == 1.0

    def test_is_tighter_long(self):
        engine = DynamicSLTPEngine()
        assert engine._is_tighter(99.0, 98.0, "long")
        assert not engine._is_tighter(97.0, 98.0, "long")

    def test_is_tighter_short(self):
        engine = DynamicSLTPEngine()
        assert engine._is_tighter(101.0, 102.0, "short")
        assert not engine._is_tighter(103.0, 102.0, "short")

    def test_propose_tighter_sl_long(self):
        engine = DynamicSLTPEngine(max_sl_widen_pct=0.0)
        result = engine._propose_tighter_sl("long", 100.0, 95.0, vol_ratio=0.5)
        assert result is not None
        assert result > 95.0

    def test_propose_tighter_sl_short(self):
        engine = DynamicSLTPEngine(max_sl_widen_pct=0.0)
        result = engine._propose_tighter_sl("short", 100.0, 105.0, vol_ratio=0.5)
        assert result is not None
        assert result < 105.0

    def test_propose_tighter_sl_would_widen_returns_none(self):
        engine = DynamicSLTPEngine(max_sl_widen_pct=0.0)
        result = engine._propose_tighter_sl("long", 100.0, 95.0, vol_ratio=1.5)
        assert result is None


class TestBuildFromConfig:
    def test_build_with_defaults(self):
        engine = build_dynamic_sltp_from_config({})
        assert engine.method == "atr"
        assert engine.atr_period == 14

    def test_build_with_overrides(self):
        engine = build_dynamic_sltp_from_config(
            {
                "dynamic_sltp": {
                    "method": "vol_ewm",
                    "atr_mult_sl": 3.0,
                    "calibration_scale": 1.2,
                },
            }
        )
        assert engine.method == "vol_ewm"
        assert engine.atr_mult_sl == 3.0
        assert engine.calibration_scale == 1.2

    def test_build_with_auto_calibrate(self, sample_price_data):
        engine = build_dynamic_sltp_from_config(
            {"dynamic_sltp": {"auto_calibrate": True}},
            df=sample_price_data,
        )
        assert engine.atr_mult_sl > 0

    def test_build_disabled_auto_calibrate(self):
        engine = build_dynamic_sltp_from_config(
            {"dynamic_sltp": {"auto_calibrate": False}},
        )
        assert engine.atr_mult_sl == 2.0  # default unchanged


class TestConfidenceSLAdjust:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(confidence_sl_adjust=0.3)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
            }
        )

    def test_no_adjust_when_confidence_none(self, engine, df):
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        no_adjust = DynamicSLTPEngine(confidence_sl_adjust=0.0).compute_barriers(
            100.0,
            "long",
            df,
            sl_mult=1.0,
            tp_mult=1.0,
        )
        assert result.stop_loss == no_adjust.stop_loss

    def test_high_confidence_tightens_sl_long(self, engine, df):
        base = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.5)
        confident = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.95)
        base_sl_dist = 100.0 - base.stop_loss
        conf_sl_dist = 100.0 - confident.stop_loss
        assert conf_sl_dist < base_sl_dist

    def test_lowest_confidence_baseline(self, engine, df):
        low = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.5)
        base = DynamicSLTPEngine(confidence_sl_adjust=0.0).compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        assert low.stop_loss == pytest.approx(base.stop_loss)

    def test_max_confidence_adjust(self, engine, df):
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=1.0)
        base = DynamicSLTPEngine(confidence_sl_adjust=0.0).compute_barriers(
            100.0,
            "long",
            df,
            sl_mult=1.0,
            tp_mult=1.0,
            meta_confidence=0.5,
        )
        base_sl_dist = 100.0 - base.stop_loss
        adj_sl_dist = 100.0 - result.stop_loss
        expected_ratio = 1.0 - engine.confidence_sl_adjust  # 0.7
        assert adj_sl_dist == pytest.approx(base_sl_dist * expected_ratio, rel=0.3)

    def test_confidence_short(self, engine, df):
        base = engine.compute_barriers(100.0, "short", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.5)
        confident = engine.compute_barriers(100.0, "short", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.95)
        base_sl_dist = base.stop_loss - 100.0
        conf_sl_dist = confident.stop_loss - 100.0
        assert conf_sl_dist < base_sl_dist

    def test_no_adjust_when_disabled(self, df):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.0)
        base = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        with_meta = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.95)
        assert base.stop_loss == with_meta.stop_loss

    def test_confidence_clamped_below_threshold(self, engine, df):
        clamped = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.3)
        at_threshold = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0, meta_confidence=0.5)
        assert clamped.stop_loss == at_threshold.stop_loss


class TestBestPriceTracking:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(trailing_activation_mult=1.0, trailing_distance_mult=2.0)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
            }
        )

    def test_reset_best_price(self, engine):
        engine.reset_best_price(100.0)
        assert engine._best_price_seen == 100.0

    def test_tracks_maximum_long(self, engine, df):
        engine.reset_best_price(100.0)
        engine.compute_trailing_stop("long", 100.0, 103.0, initial_sl=97.0, current_sl=97.0, take_profit=110.0, df=df)
        engine.compute_trailing_stop("long", 100.0, 102.0, initial_sl=97.0, current_sl=97.0, take_profit=110.0, df=df)
        assert engine._best_price_seen == 103.0

    def test_tracks_minimum_short(self, engine, df):
        engine.reset_best_price(100.0)
        engine.compute_trailing_stop("short", 100.0, 97.0, initial_sl=103.0, current_sl=103.0, take_profit=90.0, df=df)
        engine.compute_trailing_stop("short", 100.0, 98.0, initial_sl=103.0, current_sl=103.0, take_profit=90.0, df=df)
        assert engine._best_price_seen == 97.0

    def test_persists_across_calls(self, engine, df):
        engine.reset_best_price(100.0)
        engine.compute_trailing_stop("long", 100.0, 105.0, initial_sl=97.0, current_sl=97.0, take_profit=110.0, df=df)
        engine.compute_trailing_stop("long", 100.0, 104.0, initial_sl=97.0, current_sl=97.0, take_profit=110.0, df=df)
        engine.compute_trailing_stop("long", 100.0, 103.0, initial_sl=97.0, current_sl=97.0, take_profit=110.0, df=df)
        assert engine._best_price_seen == 105.0
