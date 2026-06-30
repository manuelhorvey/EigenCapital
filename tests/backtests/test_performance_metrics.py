import pandas as pd
import pytest

from backtests.performance_metrics import calculate_regime_performance


class TestCalculateRegimePerformance:
    def test_basic_regime_decomposition(self):
        signals = pd.DataFrame(
            {
                "signal": [1, 2, 0, 1, 2, 0, 1, 2, 0, 1],
                "risk_multiplier": [1.0] * 10,
                "regime": ["low", "low", "low", "mid", "mid", "mid", "high", "high", "high", "high"],
            },
        )
        returns = pd.Series([0.01, -0.005, 0.02, -0.01, 0.015, -0.02, 0.005, -0.01, 0.025, 0.0])

        metrics = calculate_regime_performance(signals, returns)

        assert set(metrics.keys()) == {"low", "mid", "high"}
        for regime in ["low", "mid", "high"]:
            m = metrics[regime]
            assert "total_return" in m
            assert "sharpe" in m
            assert "count" in m
            assert "win_rate" in m
            assert 0 <= m["win_rate"] <= 1

    def test_single_regime(self):
        signals = pd.DataFrame(
            {
                "signal": [1, 1, 1, 1, 1],
                "risk_multiplier": [1.0] * 5,
                "regime": ["low"] * 5,
            },
        )
        returns = pd.Series([0.01, 0.02, -0.01, 0.005, 0.015])

        metrics = calculate_regime_performance(signals, returns)
        assert list(metrics.keys()) == ["low"]

    def test_signal_alignment_with_next_bar_return(self):
        signals = pd.DataFrame(
            {
                "signal": [2, 2, 2, 2, 2],
                "risk_multiplier": [1.0] * 5,
                "regime": ["low"] * 5,
            },
        )
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])

        metrics = calculate_regime_performance(signals, returns)
        # signal[t] * return[t+1]: last signal has no next return (NaN), gets dropped
        # 2 * 0.02 + 2 * 0.03 + 2 * 0.04 + 2 * 0.05 = 0.28
        assert metrics["low"]["total_return"] == pytest.approx(0.28, abs=1e-6)

    def test_empty_regime_skipped(self):
        signals = pd.DataFrame(
            {
                "signal": [0, 0, 0, 0, 0],
                "risk_multiplier": [1.0] * 5,
                "regime": ["low", "low", "mid", "mid", "mid"],
            },
        )
        returns = pd.Series([0.01] * 5)

        metrics = calculate_regime_performance(signals, returns)
        # regime "high" does not appear, so not in output
        assert "high" not in metrics

    def test_sharpe_zero_when_std_zero(self):
        signals = pd.DataFrame(
            {
                "signal": [1, 1, 1, 1, 1],
                "risk_multiplier": [1.0] * 5,
                "regime": ["low"] * 5,
            },
        )
        returns = pd.Series([0.01] * 5)

        metrics = calculate_regime_performance(signals, returns)
        assert metrics["low"]["sharpe"] == 0.0
