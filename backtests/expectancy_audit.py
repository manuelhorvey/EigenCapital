"""Expectancy audit — compute trade expectancy and related metrics."""

import numpy as np
import pandas as pd


def calculate_expectancy(trades):
    """Calculate trade expectancy and related metrics from a DataFrame of trades.

    Args:
        trades: DataFrame with 'pnl' column

    Returns:
        dict with expectancy, win_rate, avg_win, avg_loss, rrr, profit_factor, etc.
    """
    if len(trades) == 0:
        return {
            "n_trades": 0,
            "expectancy": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_loss": 0.0,
            "rrr": 0.0,
            "profit_factor": 0.0,
            "recovery_factor": 0.0,
            "max_drawdown": 0.0,
        }

    pnl = trades["pnl"].values
    n_trades = len(pnl)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / n_trades if n_trades > 0 else 0.0

    avg_win = float(np.mean(wins)) if n_wins > 0 else 0.0
    avg_loss = float(np.mean(losses)) if n_losses > 0 else 0.0
    max_loss = float(np.min(losses)) if n_losses > 0 else 0.0

    # Expectancy = (Win% × AvgWin) - (Loss% × AvgLoss)
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss if n_trades > 0 else 0.0

    # RRR (Reward-to-Risk Ratio)
    rrr = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    # Profit factor
    total_wins = float(np.sum(wins)) if n_wins > 0 else 0.0
    total_losses = abs(float(np.sum(losses))) if n_losses > 0 else 0.0
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf") if total_wins > 0 else 0.0

    # Max drawdown (from cumulative PnL)
    cumulative = np.cumsum(pnl)
    peak = np.maximum.accumulate(cumulative)
    dd = (peak - cumulative) / peak if peak[-1] != 0 else np.zeros_like(cumulative)
    max_drawdown = float(np.max(dd)) if len(dd) > 0 else 0.0

    # Recovery factor: total_net_profit / max_drawdown_value
    total_net = float(np.sum(pnl))
    max_dd_value = float(np.max(peak - cumulative)) if len(cumulative) > 0 else 0.0
    recovery_factor = total_net / max_dd_value if max_dd_value > 0 else 0.0

    return {
        "n_trades": n_trades,
        "expectancy": round(expectancy, 6),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "max_loss": round(max_loss, 6),
        "rrr": round(rrr, 4),
        "profit_factor": round(profit_factor, 4),
        "recovery_factor": round(recovery_factor, 4),
        "max_drawdown": round(max_drawdown, 4),
    }


def run_expectancy_audit(signals, returns):
    """Run expectancy audit broken down by regime.

    Args:
        signals: DataFrame with columns 'signal', 'risk_multiplier', 'regime'
        returns: Series of returns

    Returns:
        dict mapping regime -> expectancy metrics
    """
    if "regime" not in signals.columns:
        return {}

    results = {}
    for regime in signals["regime"].unique():
        mask = signals["regime"] == regime
        regime_signals = signals.loc[mask]
        regime_returns = returns.loc[mask]

        if len(regime_signals) <= 1:
            continue

        # Build trades from signals
        signal_values = regime_signals["signal"].values[: len(regime_signals) - 1]
        return_values = regime_returns.iloc[1:].values

        trade_mask = signal_values != 1
        if not trade_mask.any():
            continue

        trade_signals = signal_values[trade_mask]
        trade_returns = return_values[trade_mask]

        pnl = np.where(
            trade_signals == 2,
            trade_returns,
            np.where(trade_signals == 0, -trade_returns, 0.0),
        )

        trades_df = pd.DataFrame({"pnl": pnl})
        results[regime] = calculate_expectancy(trades_df)

    return results
