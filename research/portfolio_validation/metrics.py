"""Portfolio-level metrics computation.

Aggregates per-asset fold-level results into portfolio-level statistics.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def portfolio_sharpe(
    asset_sharpes: list[float],
    correlation_penalty: float = 0.0,
) -> float:
    """Estimate portfolio Sharpe from individual asset Sharpes.

    Assumes equal weighting and uniform correlation across assets.
    When correlation_penalty = 0, this is the average Sharpe.
    With positive correlation_penalty, applies a penalty for cross-asset
    correlation (approximate: Sharpe_p = mean(Sharpe_i) * sqrt(n) / corr_factor).
    """
    if not asset_sharpes:
        return 0.0
    mean_s = np.mean(asset_sharpes)
    if correlation_penalty > 0:
        n = len(asset_sharpes)
        # Simple diversification benefit: sqrt(n) / (1 + (n-1)*rho)
        rho = min(correlation_penalty, 0.99)
        div_factor = math.sqrt(n) / math.sqrt(1 + (n - 1) * rho)
        return mean_s * div_factor
    return float(mean_s)


def portfolio_ece(asset_eces: list[float]) -> float:
    """Portfolio-level ECE: simple average across assets."""
    if not asset_eces:
        return 0.0
    return float(np.mean(asset_eces))


def portfolio_cal_inversion(asset_cal_invs: list[float]) -> float:
    """Portfolio-level calibration inversion rate.

    Weighted by the number of assets (each asset contributes equally).
    """
    if not asset_cal_invs:
        return 0.0
    return float(np.mean(asset_cal_invs))


def portfolio_brier(asset_briers: list[float]) -> float:
    """Portfolio-level Brier score: average across assets."""
    if not asset_briers:
        return 0.0
    return float(np.mean(asset_briers))


def portfolio_imbalance(asset_imbalances: list[float]) -> float:
    """Portfolio-level average imbalance ratio."""
    if not asset_imbalances:
        return 0.0
    return float(np.mean(asset_imbalances))


def portfolio_trade_frequency(
    asset_trade_counts: list[int],
    asset_days: list[int],
) -> float:
    """Average trades per day across the portfolio."""
    total_trades = sum(asset_trade_counts)
    total_days = max(sum(asset_days), 1)
    return total_trades / total_days


def portfolio_calibration_flips(asset_cal_invs: list[float]) -> int:
    """Count of assets where calibration inversion rate > 0.5."""
    return sum(1 for c in asset_cal_invs if c > 0.5)


def portfolio_edge_retention(
    asset_sharpes: list[float],
    baseline_sharpes: list[float],
) -> float:
    """Portfolio-level edge retention ratio.

    Compares total Sharpe against total baseline Sharpe.
    """
    total_s = sum(asset_sharpes)
    total_b = sum(baseline_sharpes) if baseline_sharpes else total_s
    if abs(total_b) < 1e-8:
        return 1.0 if abs(total_s) < 1e-8 else (1.0 + total_s / 1e-6)
    return total_s / total_b


def compute_portfolio_metrics(
    fold_data: list[dict[str, Any]],
    baseline_fold_data: list[dict[str, Any]] | None = None,
    correlation_estimate: float = 0.3,
) -> dict[str, Any]:
    """Compute all portfolio-level metrics from per-asset fold data.

    Args:
        fold_data: List of dicts, each representing per-asset aggregated
                   fold results (one entry per asset).
        baseline_fold_data: Optional baseline data for edge retention.
        correlation_estimate: Estimated cross-asset correlation for
                              diversification penalty.

    Returns:
        Dict of portfolio-level metrics.
    """
    sharpes = [f["sharpe"] for f in fold_data if f.get("sharpe") is not None]
    eces = [f["ece"] for f in fold_data if f.get("ece") is not None]
    cal_invs = [
        f["cal_inversion_rate"]
        for f in fold_data if f.get("cal_inversion_rate") is not None
    ]
    briers = [f["brier"] for f in fold_data if f.get("brier") is not None]
    imbalances = [
        f["imbalance_ratio"]
        for f in fold_data if f.get("imbalance_ratio") is not None
    ]

    baseline_sharpes = (
        [f["sharpe"] for f in baseline_fold_data if f.get("sharpe") is not None]
        if baseline_fold_data
        else []
    )

    return {
        "portfolio_sharpe": round(portfolio_sharpe(sharpes, correlation_estimate), 4),
        "portfolio_ece": round(portfolio_ece(eces), 4),
        "portfolio_cal_inversion": round(portfolio_cal_inversion(cal_invs), 4),
        "portfolio_brier": round(portfolio_brier(briers), 4),
        "portfolio_imbalance": round(portfolio_imbalance(imbalances), 4),
        "calibration_flips": portfolio_calibration_flips(cal_invs),
        "n_assets": len(fold_data),
        "n_positive_sharpe": sum(1 for s in sharpes if s > 0),
        "n_positive_ece_improvement": (
            sum(
                1 for f in fold_data
                if f.get("ece") is not None
            )
        ),
    }
