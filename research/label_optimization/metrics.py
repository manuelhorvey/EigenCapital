"""Standalone metric computations for label optimization experiments."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import entropy


def label_distribution(labels: pd.Series) -> dict:
    """Compute label distribution stats from raw triple-barrier labels (-1, 0, 1)."""
    labels = labels.dropna().astype(int)
    n_total = len(labels)
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_timeout = int((labels == 0).sum())
    buy_pct = n_buy / n_total if n_total else 0.0
    sell_pct = n_sell / n_total if n_total else 0.0
    timeout_pct = n_timeout / n_total if n_total else 0.0
    non_buy = n_sell + n_timeout
    imbalance = non_buy / max(n_buy, 1)  # scale_pos_weight analog
    dist = np.array([buy_pct, sell_pct, timeout_pct])
    dist = dist[dist > 0]
    ent = entropy(dist, base=3) if len(dist) > 1 else 0.0
    return {
        "buy_pct": round(buy_pct, 6),
        "sell_pct": round(sell_pct, 6),
        "timeout_pct": round(timeout_pct, 6),
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_timeout": n_timeout,
        "n_total": n_total,
        "entropy": round(ent, 6),
        "imbalance_ratio": round(imbalance, 4),
    }


def compute_ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_indices = np.digitize(probs, bin_edges, right=False) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)
    ece = 0.0
    for i in range(n_bins):
        mask = bin_indices == i
        if mask.sum() == 0:
            continue
        bin_conf = probs[mask].mean()
        bin_acc = labels[mask].mean()
        ece += np.abs(bin_conf - bin_acc) * mask.sum()
    return ece / len(probs)


def compute_brier(probs: np.ndarray, labels: np.ndarray) -> float:
    """Brier score."""
    return float(np.mean((probs - labels) ** 2))


def calibration_curve(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> dict:
    """Reliability diagram statistics."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_indices = np.digitize(probs, bin_edges, right=False) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)
    confs, accs, counts = [], [], []
    for i in range(n_bins):
        mask = bin_indices == i
        if mask.sum() == 0:
            confs.append(bin_centers[i])
            accs.append(bin_centers[i])
            counts.append(0)
        else:
            confs.append(probs[mask].mean())
            accs.append(labels[mask].mean())
            counts.append(int(mask.sum()))
    confs = np.array(confs)
    accs = np.array(accs)
    valid = np.array(counts) > 0
    slope, intercept = 0.0, 0.0
    if valid.sum() >= 2:
        slope, intercept = np.polyfit(confs[valid], accs[valid], 1)
    max_dev = float(np.max(np.abs(confs[valid] - accs[valid]))) if valid.any() else 0.0
    return {
        "ece": round(compute_ece(probs, labels, n_bins), 6),
        "brier": round(compute_brier(probs, labels), 6),
        "calibration_slope": round(float(slope), 4),
        "calibration_intercept": round(float(intercept), 4),
        "reliability_max_dev": round(max_dev, 4),
    }


def behavioral_metrics(probs: np.ndarray, signals: np.ndarray) -> dict:
    """Prediction distribution and behavioral diagnostics."""
    buy_probs = probs[signals == 1] if (signals == 1).any() else np.array([])
    sell_probs = probs[signals == -1] if (signals == -1).any() else np.array([])
    avg_pred_buy = float(probs.mean())
    avg_pred_sell = float((1 - probs).mean())
    # Entropy of prediction distribution
    bins = np.linspace(0, 1, 11)
    hist, _ = np.histogram(probs, bins=bins, density=True)
    hist = hist[hist > 0]
    pred_ent = float(entropy(hist, base=2)) if len(hist) > 1 else 0.0
    # Calibration inversion rate: fraction of predictions where
    # the predicted direction disagrees with the calibrated direction
    cal_inv_rate = 0.0
    if len(buy_probs) > 0 or len(sell_probs) > 0:
        middle = (probs > 0.4) & (probs < 0.6)
        cal_inv_rate = float(middle.mean()) if len(middle) > 0 else 0.0
    return {
        "cal_inversion_rate": round(cal_inv_rate, 6),
        "avg_pred_buy_pct": round(avg_pred_buy, 6),
        "avg_pred_sell_pct": round(avg_pred_sell, 6),
        "pred_entropy": round(pred_ent, 6),
        "sell_only_blocks": 0,
        "conf_rejections": 0,
    }


def trading_metrics_from_signals(signals: pd.DataFrame, ohlcv: pd.DataFrame) -> dict:
    """Simulate basic trading metrics from walk-forward OOS signals."""
    if signals is None or signals.empty:
        return {k: 0.0 for k in [
            "sharpe", "sortino", "profit_factor", "cagr_pct",
            "total_return_pct", "max_drawdown_pct", "win_rate_pct",
            "avg_r", "total_r", "trade_count", "turnover", "calmar_ratio",
        ]}
    signals_df = signals.copy()
    signals_df = signals_df.sort_index()
    if "close" in signals_df.columns:
        close = signals_df["close"].values
    elif ohlcv is not None and not ohlcv.empty:
        aligned = ohlcv["close"].reindex(signals_df.index)
        signals_df["close"] = aligned.values
        close = aligned.values
    else:
        return {k: 0.0 for k in [
            "sharpe", "sortino", "profit_factor", "cagr_pct",
            "total_return_pct", "max_drawdown_pct", "win_rate_pct",
            "avg_r", "total_r", "trade_count", "turnover", "calmar_ratio",
        ]}
    signal = signals_df["signal"].values if "signal" in signals_df.columns else np.zeros(len(signals_df))
    label = signals_df["label"].values if "label" in signals_df.columns else np.zeros(len(signals_df))
    p_long = signals_df["p_long"].values if "p_long" in signals_df.columns else np.zeros(len(signals_df))
    n = len(signal)
    if n < 10:
        return {k: 0.0 for k in [
            "sharpe", "sortino", "profit_factor", "cagr_pct",
            "total_return_pct", "max_drawdown_pct", "win_rate_pct",
            "avg_r", "total_r", "trade_count", "turnover", "calmar_ratio",
        ]}
    # Simple trade simulation: position = signal (long=1, short=-1, flat=0)
    # Return = signal * close_ret (next day)
    close_ret = np.diff(close) / close[:-1]
    close_ret = np.append(close_ret, 0)
    pos = signal
    pnl = pos[:-1] * close_ret[:-1]
    pnl = np.append(pnl, 0)
    cum_pnl = np.cumprod(1 + pnl) - 1
    total_return = float(cum_pnl[-1])
    # Sharpe
    if pnl.std() > 0:
        sharpe = float(pnl.mean() / pnl.std() * np.sqrt(252))
    else:
        sharpe = 0.0
    # Sortino
    downside = pnl[pnl < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino = float(pnl.mean() / downside.std() * np.sqrt(252))
    else:
        sortino = 0.0
    # Max drawdown
    peak = np.maximum.accumulate(1 + cum_pnl)
    drawdown = (1 + cum_pnl) / peak - 1
    max_dd = float(np.min(drawdown))
    # CAGR
    years = n / 252
    cagr = ((1 + total_return) ** (1 / max(years, 0.01)) - 1) if years > 0 else 0.0
    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
    # Win rate
    trade_pnl = pnl[pnl != 0]
    win_rate = float((trade_pnl > 0).mean()) if len(trade_pnl) > 0 else 0.0
    # Profit factor
    gross_profit = float(pnl[pnl > 0].sum()) if pnl[pnl > 0].sum() > 0 else 0.0
    gross_loss = float(abs(pnl[pnl < 0].sum())) if pnl[pnl < 0].sum() < 0 else 0.0
    profit_factor = gross_profit / max(gross_loss, 1e-10)
    # Trade count and avg R
    pos_changes = np.diff(np.concatenate([[0], signal]))
    entries = (pos_changes == 1).sum() + (pos_changes == -1).sum()
    trade_count = int(entries)
    avg_r = float(pnl[pnl != 0].mean()) if (pnl != 0).any() else 0.0
    total_r = float(pnl.sum())
    # Turnover
    flips = int(np.abs(np.diff(np.concatenate([[0], signal]))).sum())
    turnover = flips / max(n, 1) * 252
    return {
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "profit_factor": round(profit_factor, 4),
        "cagr_pct": round(cagr * 100, 4),
        "total_return_pct": round(total_return * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "win_rate_pct": round(win_rate * 100, 4),
        "avg_r": round(avg_r, 6),
        "total_r": round(total_r, 6),
        "trade_count": trade_count,
        "turnover": round(turnover, 4),
        "calmar_ratio": round(calmar, 4),
    }
