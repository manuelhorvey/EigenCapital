import numpy as np
import pandas as pd
import pytest

from backtests.trade_analysis import (
    DASHBOARD_TICKERS,
    MODEL_DEPTH,
    REGIME_GEOM,
    SLTP_CFG,
    _signals,
    aggregate,
    flip_quality,
    paper_stats,
)


class TestSignals:
    def test_basic_signal_generation(self):
        n = 10
        proba = np.zeros((n, 3))
        proba[:, 0] = [0.6, 0.2, 0.2, 0.3, 0.1, 0.5, 0.4, 0.2, 0.3, 0.5]
        proba[:, 1] = 0.3
        proba[:, 2] = [0.1, 0.5, 0.6, 0.4, 0.7, 0.2, 0.3, 0.6, 0.4, 0.2]

        result = _signals(proba)
        assert "signal" in result
        assert "pl" in result
        assert "ps" in result
        assert len(result) == n

    def test_threshold_parameter(self):
        n = 5
        proba = np.zeros((n, 3))
        proba[:, 2] = [0.4, 0.5, 0.6, 0.3, 0.46]

        result = _signals(proba, thr=0.5)
        # Default signal is 1 (neutral); only > thr activates
        expected = [1, 1, 2, 1, 1]
        assert list(result["signal"]) == expected

    def test_ambiguous_signals_resolved(self):
        n = 3
        proba = np.zeros((n, 3))
        proba[:, 0] = [0.6, 0.4, 0.5]
        proba[:, 1] = [0.1, 0.1, 0.1]
        proba[:, 2] = [0.3, 0.5, 0.4]

        result = _signals(proba, thr=0.45)
        # Default signal is 1 (neutral)
        # Row 0: short=0.6 > 0.45 -> 0, long=0.3 no -> 0
        # Row 1: short=0.4 no, long=0.5 > 0.45 -> 2
        # Row 2: short=0.5 > 0.45 -> 0, long=0.4 no -> 0 (and c check: both>0.45? long=0.4 no -> c=False)
        assert list(result["signal"]) == [0, 2, 0]


class TestAggregate:
    def test_empty_trades(self):
        result = aggregate([])
        assert result["n_trades"] == 0

    def test_basic_aggregation(self):
        trades = [
            {
                "asset": "EURUSD",
                "return": 0.01,
                "exit_reason": "tp",
                "bars_held": 5,
                "r_multiple": 1.5,
                "mae_r": 0.5,
                "mfe_r": 1.0,
                "entry_date": "2020-01-01",
                "exit_date": "2020-01-10",
            },
            {
                "asset": "EURUSD",
                "return": -0.005,
                "exit_reason": "sl",
                "bars_held": 3,
                "r_multiple": -1.0,
                "mae_r": 1.0,
                "mfe_r": 0.3,
                "entry_date": "2020-01-02",
                "exit_date": "2020-01-05",
            },
            {
                "asset": "GBPUSD",
                "return": 0.02,
                "exit_reason": "tp",
                "bars_held": 7,
                "r_multiple": 2.0,
                "mae_r": 0.3,
                "mfe_r": 2.0,
                "entry_date": "2020-01-03",
                "exit_date": "2020-01-12",
            },
        ]
        result = aggregate(trades)
        assert result["n_trades"] == 3
        assert result["n_assets"] == 2
        assert "overall" in result
        assert "by_asset" in result
        assert "duration_by_reason" in result
        assert "duration_distribution" in result

    def test_overall_metrics(self):
        trades = [
            {
                "asset": "A",
                "return": 0.01,
                "exit_reason": "tp",
                "bars_held": 5,
                "r_multiple": 1.0,
                "mae_r": 0.5,
                "mfe_r": 1.0,
                "entry_date": "2020-01-01",
                "exit_date": "2020-01-10",
            },
            {
                "asset": "A",
                "return": 0.02,
                "exit_reason": "tp",
                "bars_held": 4,
                "r_multiple": 2.0,
                "mae_r": 0.3,
                "mfe_r": 2.0,
                "entry_date": "2020-01-02",
                "exit_date": "2020-01-06",
            },
        ]
        o = aggregate(trades)["overall"]
        assert o["win_rate"] == 1.0
        assert o["loss_rate"] == 0.0
        assert o["profit_factor"] > 0
        assert "avg_mae_r" in o
        assert "avg_mfe_r" in o
        assert "efficiency" in o

    def test_duration_distribution(self):
        trades = [
            {
                "asset": "A",
                "return": 0.01,
                "exit_reason": "tp",
                "bars_held": 2,
                "r_multiple": 1.0,
                "mae_r": 0.5,
                "mfe_r": 1.0,
                "entry_date": "2020-01-01",
                "exit_date": "2020-01-03",
            },
            {
                "asset": "A",
                "return": 0.02,
                "exit_reason": "sl",
                "bars_held": 10,
                "r_multiple": -1.0,
                "mae_r": 1.0,
                "mfe_r": 0.5,
                "entry_date": "2020-01-05",
                "exit_date": "2020-01-15",
            },
            {
                "asset": "A",
                "return": -0.01,
                "exit_reason": "tp",
                "bars_held": 20,
                "r_multiple": 1.5,
                "mae_r": 0.8,
                "mfe_r": 1.5,
                "entry_date": "2020-02-01",
                "exit_date": "2020-02-21",
            },
        ]
        result = aggregate(trades)
        dist = result["duration_distribution"]
        assert "1-3d" in dist
        assert "8-14d" in dist
        assert "15-30d" in dist
        assert dist["1-3d"]["count"] == 1
        assert dist["8-14d"]["count"] == 1

    def test_by_asset_breakdown(self):
        trades = [
            {
                "asset": "EURUSD",
                "return": 0.01,
                "exit_reason": "tp",
                "bars_held": 5,
                "r_multiple": 1.5,
                "mae_r": 0.5,
                "mfe_r": 1.0,
                "entry_date": "2020-01-01",
                "exit_date": "2020-01-10",
            },
            {
                "asset": "GBPUSD",
                "return": -0.005,
                "exit_reason": "sl",
                "bars_held": 3,
                "r_multiple": -1.0,
                "mae_r": 1.0,
                "mfe_r": 0.3,
                "entry_date": "2020-01-02",
                "exit_date": "2020-01-05",
            },
        ]
        result = aggregate(trades)
        ba = result["by_asset"]
        assert "EURUSD" in ba
        assert "GBPUSD" in ba
        assert ba["EURUSD"]["n_trades"] == 1


class TestFlipQuality:
    def test_empty_trades_raises(self):
        with pytest.raises(KeyError):
            flip_quality([])

    def test_no_flips(self):
        trades = [
            {
                "asset": "A",
                "entry_date": "2020-01-01",
                "exit_reason": "tp",
                "bars_held": 5,
                "r_multiple": 1.5,
                "mae_r": 0.5,
                "mfe_r": 1.0,
                "exit_price": 105.0,
                "entry_price": 100.0,
                "side": "long",
            },
        ]
        result = flip_quality(trades)
        assert result == {}

    def test_with_flips(self):
        trades = [
            {
                "asset": "A",
                "entry_date": "2020-01-01",
                "exit_reason": "signal_flip",
                "bars_held": 5,
                "r_multiple": -1.0,
                "mae_r": 1.0,
                "mfe_r": 0.5,
                "exit_price": 95.0,
                "entry_price": 100.0,
                "side": "long",
            },
            {
                "asset": "A",
                "entry_date": "2020-01-06",
                "exit_reason": "tp",
                "bars_held": 3,
                "r_multiple": 2.0,
                "mae_r": 0.3,
                "mfe_r": 2.0,
                "exit_price": 110.0,
                "entry_price": 100.0,
                "side": "long",
            },
        ]
        result = flip_quality(trades)
        assert result["total_flips_analyzed"] == 1
        assert "avg_r" in result
        assert "avg_next_r" in result
        assert "next_positive_rate" in result

    def test_flip_at_end_of_series(self):
        trades = [
            {
                "asset": "A",
                "entry_date": "2020-01-01",
                "exit_reason": "signal_flip",
                "bars_held": 5,
                "r_multiple": -1.0,
                "mae_r": 1.0,
                "mfe_r": 0.5,
                "exit_price": 95.0,
                "entry_price": 100.0,
                "side": "long",
            },
        ]
        result = flip_quality(trades)
        assert result["total_flips_analyzed"] == 1
        assert result["next_positive"] == 0


class TestPaperStats:
    def test_empty_trades(self):
        assert paper_stats([]) == {}

    def test_basic_stats(self):
        trades = [
            {"asset": "EURUSD", "reason": "tp", "return": 0.01, "bars": 5, "pnl": 0.01},
            {"asset": "EURUSD", "reason": "sl", "return": -0.005, "bars": 3, "pnl": -0.005},
            {"asset": "GBPUSD", "reason": "tp", "return": 0.02, "bars": 7, "pnl": 0.02},
        ]
        stats = paper_stats(trades)
        assert stats["n_trades"] == 3
        assert stats["win_rate"] == 2 / 3
        assert stats["tp_rate"] == 2 / 3
        assert stats["sl_rate"] == 1 / 3
        assert stats["avg_return"] == pytest.approx((0.01 - 0.005 + 0.02) / 3, abs=1e-6)
        assert "by_asset" in stats
        assert "EURUSD" in stats["by_asset"]
        assert "GBPUSD" in stats["by_asset"]

    def test_with_exit_reason_column(self):
        trades = [
            {"asset": "EURUSD", "exit_reason": "tp", "return": 0.01, "bars": 5, "pnl": 0.01},
        ]
        stats = paper_stats(trades)
        assert stats["n_trades"] == 1


class TestConstants:
    def test_sltp_cfg_has_expected_keys(self):
        expected = {
            "GC",
            "USDCHF",
            "EURUSD",
            "NZDUSD",
            "GBPAUD",
            "NZDCHF",
            "CADCHF",
            "AUDUSD",
            "AUDNZD",
            "EURCHF",
            "EURCAD",
            "EURNZD",
            "GBPCHF",
        }
        assert expected.issubset(set(SLTP_CFG.keys()))

    def test_dashboard_tickers_not_empty(self):
        assert len(DASHBOARD_TICKERS) > 0

    def test_model_depth_not_empty(self):
        assert len(MODEL_DEPTH) > 0

    def test_regime_geom_has_expected_keys(self):
        for key in ["low", "mid", "high"]:
            assert key in REGIME_GEOM
            assert "sl" in REGIME_GEOM[key]
            assert "tp" in REGIME_GEOM[key]
