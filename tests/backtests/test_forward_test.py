import numpy as np
import pandas as pd
import pytest

from backtests.forward_test import (
    _classify_vol_regime,
    _forward_metrics,
    _hit_rate,
    _max_drawdown,
    _regime_metrics,
    _regime_trade_returns,
    _sharpe_ratio,
)


class TestSharpeRatio:
    def test_positive_sharpe(self):
        returns = np.array([0.01, 0.02, 0.015, 0.005, 0.01])
        sr = _sharpe_ratio(returns)
        assert sr > 0

    def test_negative_sharpe(self):
        returns = np.array([-0.01, -0.02, -0.015, -0.005, -0.01])
        sr = _sharpe_ratio(returns)
        assert sr < 0

    def test_zero_std(self):
        returns = np.array([0.01, 0.01, 0.01])
        assert _sharpe_ratio(returns) == 0.0

    def test_zero_risk_free_rate(self):
        returns = np.array([0.01, 0.02])
        sr = _sharpe_ratio(returns, rf=0.0)
        assert sr > 0

    def test_single_return(self):
        returns = np.array([0.01])
        assert _sharpe_ratio(returns) == 0.0


class TestHitRate:
    def test_all_correct(self):
        signals = np.array([2, 2, 0, 0, 1])
        returns = np.array([0.01, 0.02, -0.01, -0.02, 0.005])
        hr = _hit_rate(signals, returns)
        assert hr == 1.0

    def test_all_wrong(self):
        signals = np.array([2, 2, 0, 0, 1])
        returns = np.array([-0.01, -0.02, 0.01, 0.02, 0.005])
        hr = _hit_rate(signals, returns)
        assert hr == 0.0

    def test_no_trades(self):
        signals = np.array([1, 1, 1])
        returns = np.array([0.01, 0.02, 0.03])
        assert _hit_rate(signals, returns) == 0.0

    def test_all_long_correct(self):
        signals = np.array([2, 2, 2, 1, 1])
        returns = np.array([0.01, 0.02, 0.03, 0.01, 0.02])
        hr = _hit_rate(signals, returns)
        assert hr == 1.0

    def test_all_long_wrong(self):
        signals = np.array([2, 2, 2, 1, 1])
        returns = np.array([-0.01, -0.02, -0.03, 0.01, 0.02])
        hr = _hit_rate(signals, returns)
        assert hr == 0.0

    def test_mixed_hit_rate(self):
        signals = np.array([2, 0, 1, 2])
        returns = np.array([0.01, -0.01, 0.01, -0.02])
        hr = _hit_rate(signals, returns)
        assert 0 < hr < 1


class TestMaxDrawdown:
    def test_increasing_equity(self):
        equity = np.array([100, 101, 102, 103, 104])
        assert _max_drawdown(equity) == 0.0

    def test_decreasing_equity(self):
        equity = np.array([100, 99, 98, 97, 96])
        assert _max_drawdown(equity) == pytest.approx(0.04, abs=1e-6)

    def test_with_recovery(self):
        equity = np.array([100, 110, 90, 105, 115])
        dd = _max_drawdown(equity)
        assert 0 < dd < 0.2

    def test_single_value(self):
        assert _max_drawdown(np.array([100])) == 0.0


class TestClassifyVolRegime:
    def test_returns_series(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
        regime = _classify_vol_regime(close)
        assert isinstance(regime, pd.Series)
        assert all(r in ("low_vol", "mid", "transition", "high_vol") for r in regime.unique())

    def test_output_length(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(50) * 0.5))
        regime = _classify_vol_regime(close)
        assert len(regime) == len(close)

    def test_includes_all_expected_regimes(self):
        np.random.seed(42)
        close = pd.Series(100 + np.cumsum(np.random.randn(500) * 0.5))
        regime = _classify_vol_regime(close)
        expected = {"low_vol", "transition", "high_vol"}
        assert expected.issuperset(regime.unique())


class TestForwardMetrics:
    def test_returns_dict_with_expected_keys(self):
        np.random.seed(42)
        n = 100
        proba = np.random.dirichlet(np.ones(3), size=n)
        close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5))

        metrics = _forward_metrics(proba, close)
        assert "sharpe" in metrics
        assert "hit_rate" in metrics
        assert "max_drawdown" in metrics
        assert "total_trades" in metrics
        assert "pnl_std" in metrics
        assert "stability" in metrics
        assert 0 <= metrics["stability"] <= 1

    def test_no_signals(self):
        n = 50
        proba = np.zeros((n, 3))
        proba[:, 1] = 1.0  # all neutral
        close = pd.Series(np.ones(n) * 100)

        metrics = _forward_metrics(proba, close)
        assert metrics["hit_rate"] == 0.0
        assert metrics["total_trades"] == 0


class TestRegimeTradeReturns:
    def test_returns_tuple(self):
        n = 50
        signals = np.full(n, 1, dtype=int)
        signals[10:20] = 2
        signals[30:40] = 0
        close = pd.Series(np.ones(n) * 100)
        daily_pnl, equity = _regime_trade_returns(signals, close.values)
        assert isinstance(daily_pnl, np.ndarray)
        assert isinstance(equity, np.ndarray)
        assert len(daily_pnl) == n
        assert len(equity) == n

    def test_no_trades(self):
        n = 10
        signals = np.full(n, 1, dtype=int)
        close = pd.Series(np.ones(n) * 100)
        daily_pnl, equity = _regime_trade_returns(signals, close.values)
        # Flat throughout: no PnL from trades, but equity tracks
        assert equity[-1] == 100000.0


class TestRegimeMetrics:
    def test_returns_dict_by_regime(self):
        np.random.seed(42)
        n = 200
        proba = np.random.dirichlet(np.ones(3), size=n)
        close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5))
        regime = pd.Series(np.random.choice(["low_vol", "high_vol", "transition"], size=n))

        result = _regime_metrics(proba, close, regime)
        assert "low_vol" in result
        assert "high_vol" in result
        assert "transition" in result
        for r in ["low_vol", "high_vol", "transition"]:
            assert "sharpe" in result[r]
            assert "max_drawdown" in result[r]
