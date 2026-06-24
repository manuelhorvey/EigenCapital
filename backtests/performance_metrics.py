"""Performance metrics for backtesting analysis."""

import numpy as np


def calculate_regime_performance(signals, returns):
    """Calculate performance metrics broken down by volatility regime.

    Args:
        signals: DataFrame with columns 'signal', 'risk_multiplier', 'regime'
        returns: Series of returns aligned with signals index

    Returns:
        dict mapping regime -> {total_return, sharpe, count, win_rate}
    """
    if "regime" not in signals.columns:
        return {}

    metrics = {}
    for regime in signals["regime"].unique():
        mask = signals["regime"] == regime
        regime_signals = signals.loc[mask]
        regime_returns = returns.loc[mask]

        # Align: signal[t] * return[t+1]
        if len(regime_signals) > 1:
            signal_values = regime_signals["signal"].values[: len(regime_signals) - 1]
            return_values = regime_returns.iloc[1:].values
        else:
            metrics[regime] = {"total_return": 0.0, "sharpe": 0.0, "count": 0, "win_rate": 0.0}
            continue

        # Only count trades (signal != 1)
        trade_mask = signal_values != 1
        if not trade_mask.any():
            metrics[regime] = {"total_return": 0.0, "sharpe": 0.0, "count": len(regime_signals), "win_rate": 0.0}
            continue

        trade_signals = signal_values[trade_mask]
        trade_returns = return_values[trade_mask]

        # PnL = signal * return
        pnl = trade_signals.astype(float) * trade_returns

        total_return = float(np.sum(pnl))
        win_rate = float((pnl > 0).sum() / len(pnl)) if len(pnl) > 0 else 0.0
        std = float(np.std(pnl, ddof=1)) if len(pnl) > 1 else 0.0
        sharpe = total_return / (std * np.sqrt(len(pnl))) if std > 0 else 0.0

        metrics[regime] = {
            "total_return": round(total_return, 6),
            "sharpe": round(sharpe, 4),
            "count": len(regime_signals),
            "win_rate": round(win_rate, 4),
        }

    return metrics
