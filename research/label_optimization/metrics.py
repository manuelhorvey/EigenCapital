"""Metric computations — fold-level, aggregate, production cost, edge retention."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import entropy


def label_distribution(labels: pd.Series) -> dict:
    labels = labels.dropna().astype(int)
    n_total = len(labels)
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_timeout = int((labels == 0).sum())
    buy_pct = n_buy / n_total if n_total else 0.0
    sell_pct = n_sell / n_total if n_total else 0.0
    timeout_pct = n_timeout / n_total if n_total else 0.0
    non_buy = n_sell + n_timeout
    imbalance = non_buy / max(n_buy, 1)
    dist = np.array([buy_pct, sell_pct, timeout_pct])
    dist = dist[dist > 0]
    ent = entropy(dist, base=3) if len(dist) > 1 else 0.0
    return {
        "buy_pct": round(buy_pct, 6), "sell_pct": round(sell_pct, 6),
        "timeout_pct": round(timeout_pct, 6),
        "n_buy": n_buy, "n_sell": n_sell, "n_timeout": n_timeout,
        "n_total": n_total,
        "entropy": round(ent, 6), "imbalance_ratio": round(imbalance, 4),
    }


def compute_ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_indices = np.clip(np.digitize(probs, bin_edges, right=False) - 1, 0, n_bins - 1)
    ece = 0.0
    for i in range(n_bins):
        mask = bin_indices == i
        if mask.sum() == 0:
            continue
        ece += np.abs(probs[mask].mean() - labels[mask].mean()) * mask.sum()
    return ece / len(probs)


def compute_brier(probs: np.ndarray, labels: np.ndarray) -> float:
    return float(np.mean((probs - labels) ** 2))


def fold_metrics(fold_signals: pd.DataFrame, fold_close: np.ndarray | None = None) -> dict:
    """Compute all metrics for a single walk-forward fold."""
    m: dict[str, float | int] = {}
    labels = fold_signals["label"].values.astype(int) if "label" in fold_signals.columns else np.array([])
    probs = fold_signals["p_long"].values.astype(float) if "p_long" in fold_signals.columns else np.array([])
    sigs = fold_signals["signal"].values.astype(int) if "signal" in fold_signals.columns else np.array([])

    # Label distribution
    n_total = len(labels)
    n_buy = int((labels == 1).sum())
    n_sell = int((labels == 0).sum())  # in binary: 1=buy, 0=sell
    # But for raw labels, we also need the original pre-binary labels
    # Actually the fold_signals have y_te which is already binary (0, 1)
    # We don't have timeout info at binary level
    m["n_train"] = 0  # set by caller
    m["n_test"] = n_total
    m["n_buy"] = n_buy
    m["n_sell"] = n_total - n_buy
    m["n_timeout"] = 0
    m["buy_pct"] = round(n_buy / max(n_total, 1), 6)
    m["sell_pct"] = round((n_total - n_buy) / max(n_total, 1), 6)
    imba = (n_total - n_buy) / max(n_buy, 1)
    m["imbalance_ratio"] = round(imba, 4)
    dist_arr = np.array([m["buy_pct"], m["sell_pct"]])
    dist_arr = dist_arr[dist_arr > 0]
    m["entropy"] = round(float(entropy(dist_arr, base=2) if len(dist_arr) > 1 else 0.0), 6)

    # Calibration
    if len(probs) > 0 and len(labels) > 0 and len(probs) == len(labels):
        m["ece"] = round(compute_ece(probs, labels), 6)
        m["brier"] = round(compute_brier(probs, labels), 6)
    else:
        m["ece"] = m["brier"] = 0.0

    # Behavioral
    if len(probs) > 0 and len(sigs) > 0 and len(probs) == len(sigs):
        middle = ((probs > 0.4) & (probs < 0.6)).mean()
        m["cal_inversion_rate"] = round(float(middle), 6)
    else:
        m["cal_inversion_rate"] = 0.0

    # Trading simulation
    if len(sigs) > 0 and fold_close is not None and len(fold_close) == len(sigs):
        close_ret = np.diff(fold_close) / fold_close[:-1]
        close_ret = np.append(close_ret, 0)
        pnl = sigs[:-1] * close_ret[:-1]
        pnl = np.append(pnl, 0)
        cum_pnl = np.cumprod(1 + pnl) - 1
        m["total_return_pct"] = round(float(cum_pnl[-1] * 100), 4)
        m["max_drawdown_pct"] = round(float(np.min(cum_pnl)), 4)
        if pnl.std() > 0:
            m["sharpe"] = round(float(pnl.mean() / pnl.std() * np.sqrt(252)), 4)
        else:
            m["sharpe"] = 0.0
        gross_profit = float(pnl[pnl > 0].sum()) if (pnl > 0).any() else 0.0
        gross_loss = float(abs(pnl[pnl < 0].sum())) if (pnl < 0).any() else 0.0
        m["profit_factor"] = round(gross_profit / max(gross_loss, 1e-10), 4)
    else:
        m["total_return_pct"] = m["max_drawdown_pct"] = m["sharpe"] = m["profit_factor"] = 0.0

    # Signal rates
    if len(sigs) > 0:
        m["directional"] = round(float((sigs != 0).mean()), 4)  # signal rate
        m["spearman_ic"] = 0.0
        m["flat_rate"] = round(float((sigs == 0).mean()), 4)
    else:
        m["directional"] = m["spearman_ic"] = m["flat_rate"] = 0.0

    return m


def edge_retention(current_sharpe: float, baseline_sharpe: float) -> float:
    """Fraction of production Sharpe retained."""
    if baseline_sharpe is None or baseline_sharpe == 0:
        return 1.0
    return round(current_sharpe / baseline_sharpe, 4)


def production_cost_metrics(
    experiment_id: str,
    cal_inversion_rate: float,
    avg_cal_correction: float,
    edge_retention: float,
    sharpe_ratio: float,
    baseline_sharpe: float,
) -> dict:
    """Downstream operational cost estimates."""
    return {
        "sell_only_avoids": 0,
        "conf_overrides": 0,
        "cal_correction_mean": round(avg_cal_correction, 6),
        "threshold_reject_rate": round(cal_inversion_rate, 6),
        "edge_retention": edge_retention,
        "parity_ratio": round(sharpe_ratio / max(baseline_sharpe, 1e-10), 4) if baseline_sharpe else 1.0,
    }
