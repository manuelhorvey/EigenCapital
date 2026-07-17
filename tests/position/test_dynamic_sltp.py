from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st

from paper_trading.position.dynamic_sltp import (
    DynamicSLTPEngine,
    build_dynamic_sltp_from_config,
)
from shared.volatility import compute_latest_atr, estimate_ewm_vol, estimate_gap_risk


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
        atr = compute_latest_atr(sample_price_data, period=14)
        assert atr > 0

    def test_estimate_vol(self, sample_price_data):
        vol = estimate_ewm_vol(sample_price_data["close"])
        assert vol > 0

    def test_estimate_gap_risk(self, sample_price_data):
        gap = estimate_gap_risk(sample_price_data)
        assert gap >= 0

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


class TestTrailingActivationRace:
    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99})

    def test_trailing_activates_on_gap_through(self, df):
        engine = DynamicSLTPEngine(
            method="trailing", trailing_activation_mult=1.5, trailing_distance_mult=2.0, atr_period=14
        )
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        engine.reset_best_price(100.0)
        trail = engine.compute_trailing_stop(
            "long", 100.0, 108.0, result.stop_loss, result.stop_loss, result.take_profit, df=df
        )
        assert trail.activated
        assert trail.trailing_sl is not None

    def test_trailing_does_not_activate_below_threshold(self, df):
        engine = DynamicSLTPEngine(
            method="trailing", trailing_activation_mult=2.0, trailing_distance_mult=2.0, atr_period=14
        )
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        engine.reset_best_price(100.0)
        trail = engine.compute_trailing_stop(
            "long", 100.0, 101.5, result.stop_loss, result.stop_loss, result.take_profit, df=df
        )
        assert not trail.activated
        assert trail.trailing_sl is None

    def test_trailing_only_tightens_not_widens(self, df):
        engine = DynamicSLTPEngine(
            method="trailing", trailing_activation_mult=1.0, trailing_distance_mult=3.0, atr_period=14
        )
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        engine.reset_best_price(100.0)
        t1 = engine.compute_trailing_stop(
            "long", 100.0, 103.0, result.stop_loss, result.stop_loss, result.take_profit, df=df
        )
        t2 = engine.compute_trailing_stop(
            "long", 100.0, 102.0, result.stop_loss, t1.trailing_sl or result.stop_loss, result.take_profit, df=df
        )
        if t1.activated and t2.activated:
            assert (t2.trailing_sl is None) or (t2.trailing_sl >= t1.trailing_sl)


class TestPostEntryAdjustBoundaries:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(post_adjust_interval_bars=3, max_sl_widen_pct=0.0)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99})

    def test_no_adjust_before_min_bars(self, engine, df):
        adj = engine.post_entry_adjust("long", 100.0, 98.0, 105.0, df, vol=0.02, bars_since_entry=1)
        assert adj.new_sl is None
        assert adj.new_tp is None

    def test_vol_spike_tightens_sl(self, engine, df):
        """Vol spike > 1.3x entry vol should tighten SL."""
        engine.post_adjust_interval_bars = 0
        adj = engine.post_entry_adjust("long", 100.0, 98.0, 105.0, df, vol=0.005, bars_since_entry=10)
        assert adj.new_sl is not None
        assert "vol_spike" in (adj.reason or "")

    def test_vol_collapse_does_not_tighten(self, engine, df):
        """Vol collapse < 0.7x entry vol should NOT tighten SL (no action)."""
        engine.post_adjust_interval_bars = 0
        adj = engine.post_entry_adjust("long", 100.0, 98.0, 105.0, df, vol=0.05, bars_since_entry=10)
        assert adj.new_sl is None

    def test_no_widen_when_disabled(self, engine, df):
        engine.post_adjust_interval_bars = 0
        adj = engine.post_entry_adjust("long", 100.0, 98.0, 105.0, df, vol=0.01, bars_since_entry=10)
        if adj.new_sl is not None:
            assert adj.new_sl >= 98.0


class TestComputeTrailingStopEdgeCases:
    @pytest.fixture
    def engine(self):
        return DynamicSLTPEngine(trailing_activation_mult=1.5, trailing_distance_mult=2.0)

    @pytest.fixture
    def df(self):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)
        return pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99})

    def test_no_best_price_init_uses_entry(self, engine, df):
        engine._best_price_seen = None
        result = engine.compute_trailing_stop(
            "long", 100.0, 102.0, initial_sl=98.0, current_sl=98.0, take_profit=110.0, df=df
        )
        assert engine._best_price_seen == 102.0

    def test_short_side_best_price_tracks_min(self, engine, df):
        engine.reset_best_price(100.0)
        engine.compute_trailing_stop("short", 100.0, 97.0, initial_sl=103.0, current_sl=103.0, take_profit=90.0, df=df)
        engine.compute_trailing_stop("short", 100.0, 96.0, initial_sl=103.0, current_sl=103.0, take_profit=90.0, df=df)
        assert engine._best_price_seen == 96.0

    def test_short_trailing_activates(self, engine, df):
        engine.reset_best_price(100.0)
        trail = engine.compute_trailing_stop(
            "short", 100.0, 95.0, initial_sl=103.0, current_sl=103.0, take_profit=90.0, df=df
        )
        if trail.activated:
            assert trail.trailing_sl is not None
            assert trail.trailing_sl < 103.0


class TestConfidenceFactorBoundary:
    def test_factor_at_threshold_returns_one(self):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.3)
        factor = engine._confidence_sl_factor(0.5)
        assert factor == 1.0

    def test_factor_at_max_returns_one_minus_adjust(self):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.3)
        factor = engine._confidence_sl_factor(1.0)
        assert factor == pytest.approx(0.70)

    def test_factor_at_zero_adjust(self):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.0)
        factor = engine._confidence_sl_factor(0.8)
        assert factor == 1.0

    def test_factor_clamped_below_threshold(self):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.3)
        factor = engine._confidence_sl_factor(0.3)
        assert factor == 1.0

    def test_factor_monotonic(self):
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.3)
        f1 = engine._confidence_sl_factor(0.6)
        f2 = engine._confidence_sl_factor(0.8)
        assert f2 <= f1


class TestGapProtection:
    @pytest.fixture
    def df_short(self):
        prices = np.array([100.0] * 10)
        return pd.DataFrame({"close": prices, "high": prices * 1.005, "low": prices * 0.995, "volume": 1_000_000})

    def test_gap_protection_with_insufficient_data(self):
        df = pd.DataFrame({"close": [100], "high": [101], "low": [99]})
        engine = DynamicSLTPEngine(use_gap_protection=True)
        result = engine.compute_barriers(100.0, "long", df, sl_mult=1.0, tp_mult=1.0)
        assert result.stop_loss < 100.0
        assert result.take_profit > 100.0


class TestCalibrationEdgeCases:
    def test_calibrate_with_zero_vol_does_not_crash(self):
        df = pd.DataFrame({"close": [100], "high": [101], "low": [99]})
        engine = DynamicSLTPEngine(atr_period=14)
        engine.calibrate(df)
        assert engine.atr_mult_sl > 0

    def test_calibrate_with_constant_prices(self):
        prices = np.full(50, 100.0)
        df = pd.DataFrame({"close": prices, "high": prices * 1.001, "low": prices * 0.999})
        engine = DynamicSLTPEngine(atr_period=14)
        engine.calibrate(df)
        assert engine.atr_mult_sl > 0


class TestHypothesisDynamicSLTP:
    @given(
        entry=st.floats(min_value=10.0, max_value=1000.0),
        vol=st.floats(min_value=0.001, max_value=0.1),
        sl_mult=st.floats(min_value=0.5, max_value=3.0),
        tp_mult=st.floats(min_value=0.5, max_value=5.0),
        side=st.sampled_from(["long", "short"]),
    )
    def test_sl_on_correct_side_of_entry(self, entry, vol, sl_mult, tp_mult, side):
        engine = DynamicSLTPEngine(method="vol_ewm", min_rr_ratio=0.1)
        result = engine.compute_barriers(entry, side, pd.DataFrame(), sl_mult=sl_mult, tp_mult=tp_mult, vol=vol)
        if side == "long":
            assert result.stop_loss < entry < result.take_profit
        else:
            assert result.stop_loss > entry > result.take_profit

    @given(
        entry=st.floats(min_value=10.0, max_value=1000.0),
        conf=st.floats(min_value=0.5, max_value=1.0),
        side=st.sampled_from(["long", "short"]),
    )
    def test_confidence_adjust_never_reverses_sl_side(self, entry, conf, side):
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(20) * 0.5)
        df = pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99})
        engine = DynamicSLTPEngine(confidence_sl_adjust=0.3)
        result = engine.compute_barriers(entry, side, df, sl_mult=1.0, tp_mult=1.0, meta_confidence=conf)
        if side == "long":
            assert result.stop_loss < entry
        else:
            assert result.stop_loss > entry
