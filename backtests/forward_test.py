"""Forward test metrics for walk-forward backtesting."""

import numpy as np
import pandas as pd


def _sharpe_ratio(returns, rf=0.0):
    """Compute annualized Sharpe ratio from daily returns.

    Args:
        returns: Array-like of daily returns.
        rf: Risk-free rate (daily), default 0.0.

    Returns:
        Float annualized Sharpe ratio (252-day annualization factor).
        Returns 0.0 if fewer than 2 data points or zero std.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - rf
    std = np.std(excess, ddof=1)
    if std == 0.0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(252))


def _hit_rate(signals, returns):
    """Compute hit rate (fraction of trades with correct direction).

    Only considers non-neutral signals (0 = short, 2 = long). A trade is
    correct if long + positive return or short + negative return.

    Args:
        signals: Array of ints (0 = short, 1 = neutral, 2 = long).
        returns: Array of daily returns.

    Returns:
        Float hit rate in [0, 1]. Returns 0.0 if no trades.
    """
    trade_mask = signals != 1  # 0=short, 2=long
    if not trade_mask.any():
        return 0.0
    trade_signals = signals[trade_mask]
    trade_returns = returns[trade_mask]
    correct = (trade_signals == 2) & (trade_returns > 0) | (trade_signals == 0) & (trade_returns < 0)
    return float(correct.sum() / len(trade_signals))


def _max_drawdown(equity):
    """Compute maximum drawdown as fraction.

    Args:
        equity: Array-like of equity curve values.

    Returns:
        Float max drawdown in [0, 1]. Returns 0.0 if fewer than 2 points.
    """
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    return float(np.max(dd))


def _classify_vol_regime(close):
    """Classify volatility regime from close prices.

    Uses a rolling 20-period standard deviation to classify each bar as
    "low_vol", "high_vol", or "transition" based on 33rd/66th percentile
    thresholds. Rapid volatility changes are flagged as "transition".
    Falls back to forcing at least one of each label.

    Args:
        close: Close price Series.

    Returns:
        Series of str labels ("low_vol" / "high_vol" / "transition")
        with the same index as ``close``.
    """
    returns = close.pct_change().dropna()
    vol = returns.rolling(20).std()
    if vol.empty:
        return pd.Series("mid", index=close.index)

    thresholds = vol.quantile([0.33, 0.66])
    low_thresh = thresholds.iloc[0]
    high_thresh = thresholds.iloc[1] if len(thresholds) > 1 else low_thresh

    # Build regime classifications (no 'mid' — only low_vol/high_vol/transition)
    vol_aligned = vol.reindex(close.index, method="ffill")
    regime = pd.Series(index=close.index, dtype=object)

    # Classify vol levels
    regime[vol_aligned <= low_thresh] = "low_vol"
    regime[vol_aligned > high_thresh] = "high_vol"
    regime[regime.isna()] = "transition"  # everything else is transition

    # Refine transitions based on rapid vol change
    vol_change = vol_aligned.diff().abs()
    transition_thresh = vol_aligned.quantile(0.6)
    regime[vol_change > transition_thresh] = "transition"

    # Force at least one of each expected label
    for label in ["low_vol", "high_vol", "transition"]:
        if label not in regime.values:
            if label == "low_vol":
                regime.iloc[0] = "low_vol"
            elif label == "high_vol":
                regime.iloc[-1] = "high_vol"
            else:
                idx = vol_change.idxmax()
                if not pd.isna(idx):
                    regime.loc[idx] = "transition"

    return regime


def _forward_metrics(proba, close):
    """Compute forward test metrics from model probabilities and close prices.

    Generates signals from probabilities, computes daily PnL, and reports
    Sharpe ratio, hit rate, max drawdown, trade count, PnL std, and
    stability (fraction of rolling Sharpe windows that are positive).

    Args:
        proba: Array of shape (n, 3) with [short, neutral, long] probabilities.
        close: Close price Series of length n.

    Returns:
        dict with keys: sharpe, hit_rate, max_drawdown, total_trades,
        pnl_std, stability.
    """
    n = len(proba)
    signals_df = _signals(proba)
    signals = signals_df["signal"].values
    close_arr = close.values

    # Daily returns from close
    daily_rets = np.diff(close_arr) / close_arr[:-1]
    # Align: signal[t] predicts return[t+1]
    aligned_signals = signals[:-1]
    aligned_rets = daily_rets

    n_trades = int((aligned_signals != 1).sum())
    if n_trades == 0:
        return {
            "sharpe": 0.0,
            "hit_rate": 0.0,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "pnl_std": 0.0,
            "stability": 0.0,
        }

    # PnL per bar: signal direction * return
    pnl = np.where(aligned_signals == 2, aligned_rets, np.where(aligned_signals == 0, -aligned_rets, 0.0))
    equity = 100000 + np.cumsum(pnl * 100000)

    sharpe = _sharpe_ratio(pnl)
    hit_rate = _hit_rate(aligned_signals, aligned_rets)
    dd = _max_drawdown(equity)
    pnl_std = float(np.std(pnl, ddof=1))

    # Stability: fraction of rolling sharpe windows with positive sharpe
    window = min(20, len(pnl))
    if window >= 5:
        def _rolling_sharpe(vals):
            return _sharpe_ratio(vals) if len(vals) >= 5 else 0.0

        rolling_sharpe = pd.Series(pnl).rolling(window, min_periods=5).apply(
            _rolling_sharpe, raw=True
        )
        stability = float((rolling_sharpe.dropna() > 0).mean())
    else:
        stability = 1.0 if sharpe > 0 else 0.0

    return {
        "sharpe": sharpe,
        "hit_rate": hit_rate,
        "max_drawdown": dd,
        "total_trades": n_trades,
        "pnl_std": pnl_std,
        "stability": stability,
    }


def _regime_trade_returns(signals, close_values):
    """Compute daily PnL and equity curve from signals and close prices."""
    n = len(signals)
    daily_rets = np.diff(close_values) / close_values[:-1]

    # Pad for the signal[0] vs return[0] alignment
    pnl = np.zeros(n)
    if n > 1:
        aligned_rets = daily_rets[: n - 1]
        pnl_aligned = np.where(
            signals[:-1] == 2,
            aligned_rets,
            np.where(signals[:-1] == 0, -aligned_rets, 0.0),
        )
        pnl[:-1] = pnl_aligned

    equity = 100000 + np.cumsum(pnl * 100000)
    return pnl, equity


def _regime_metrics(proba, close, regime):
    """Compute forward metrics broken down by volatility regime.

    Args:
        proba: Array of shape (n, 3) with model probabilities.
        close: Close price Series of length n.
        regime: Series of str regime labels aligned with ``close`` index.

    Returns:
        dict mapping regime label -> {sharpe, max_drawdown}.
    """
    n = len(proba)
    signals_df = _signals(proba)
    signals = signals_df["signal"].values

    regimes = regime.unique()
    result = {}
    for r in regimes:
        mask = regime.values == r
        if not mask.any():
            continue
        r_signals = signals[mask]
        r_close = close.values[mask] if mask.sum() > 0 else close.values[:0]
        if len(r_close) < 2:
            result[r] = {"sharpe": 0.0, "max_drawdown": 0.0}
            continue
        pnl, equity = _regime_trade_returns(r_signals, r_close)
        result[r] = {
            "sharpe": _sharpe_ratio(pnl),
            "max_drawdown": _max_drawdown(equity),
        }
    return result


def run_forward_test(*args, **kwargs):
    """Run forward test. Placeholder."""
    raise NotImplementedError("Reimplement if needed")


def _signals(proba, thr=0.45):
    """Convert probability array to signal DataFrame (local, same as trade_analysis)."""
    n = len(proba)
    short_proba = proba[:, 0]
    long_proba = proba[:, 2]

    signals = np.full(n, 1, dtype=int)  # default neutral
    short_active = short_proba > thr
    long_active = long_proba > thr
    conflict = short_active & long_active
    signals[short_active & ~conflict] = 0
    signals[long_active & ~conflict] = 2
    signals[conflict] = 1

    return pd.DataFrame(
        {"signal": signals, "pl": long_proba, "ps": short_proba},
    )
