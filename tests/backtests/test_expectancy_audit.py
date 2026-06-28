import numpy as np
import pandas as pd

from backtests.expectancy_audit import calculate_expectancy, run_expectancy_audit


class TestCalculateExpectancy:
    def test_empty_trades(self):
        trades = pd.DataFrame({"pnl": []})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 0
        assert result["expectancy"] == 0

    def test_all_wins(self):
        trades = pd.DataFrame({"pnl": [0.01, 0.02, 0.015]})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 3
        assert result["win_rate"] == 1.0
        assert result["avg_loss"] == 0
        assert result["expectancy"] > 0

    def test_all_losses(self):
        trades = pd.DataFrame({"pnl": [-0.01, -0.02, -0.015]})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 3
        assert result["win_rate"] == 0.0
        assert result["avg_win"] == 0
        assert result["expectancy"] < 0

    def test_mixed_trades(self):
        trades = pd.DataFrame({"pnl": [0.02, -0.01, 0.03, -0.02, 0.01]})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 5
        assert result["win_rate"] == 0.6
        assert result["rrr"] > 0
        assert result["profit_factor"] > 0

    def test_recovery_factor_and_max_drawdown(self):
        trades = pd.DataFrame({"pnl": [0.05, -0.03, 0.04, -0.02, 0.06]})
        result = calculate_expectancy(trades)
        assert result["recovery_factor"] > 0
        assert result["profit_factor"] > 0

    def test_single_trade_win(self):
        trades = pd.DataFrame({"pnl": [0.01]})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 1
        assert result["win_rate"] == 1.0

    def test_single_trade_loss(self):
        trades = pd.DataFrame({"pnl": [-0.01]})
        result = calculate_expectancy(trades)
        assert result["n_trades"] == 1
        assert result["win_rate"] == 0.0

    def test_max_loss_returns_zero_when_no_losses(self):
        trades = pd.DataFrame({"pnl": [0.01, 0.02]})
        result = calculate_expectancy(trades)
        assert result["max_loss"] == 0


class TestRunExpectancyAudit:
    def test_runs_with_valid_data(self):
        signals = pd.DataFrame(
            {
                "signal": [0, 2, 0, 2, 0, 2, 0, 2, 0, 2],
                "risk_multiplier": [1.0] * 10,
                "regime": ["low", "low", "mid", "mid", "mid", "high", "high", "high", "low", "low"],
            },
        )
        returns = pd.Series(np.random.randn(10) * 0.01)

        results = run_expectancy_audit(signals, returns)
        assert isinstance(results, dict)
        for regime in ["low", "mid", "high"]:
            assert regime in results
