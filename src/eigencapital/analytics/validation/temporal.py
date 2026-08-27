"""Temporal Stability Analysis — performance decay, regime breaks.

Breaks performance into sequential periods and measures stability.
Looks for performance decay, dormant periods, structural breaks.

Usage:
    result = temporal_stability(
        equity_curve=equity_curve,
        window_size=252,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RollingMetrics:
    """Metrics for a single rolling window.

    Attributes:
        start_idx: Start index of window
        end_idx: End index of window
        sharpe: Sharpe ratio for this window
        volatility: Annualized volatility
        max_drawdown: Max drawdown within window
        mean_return: Mean period return
        win_rate: % of positive-return periods
    """

    start_idx: int = 0
    end_idx: int = 0
    sharpe: float = 0.0
    volatility: float = 0.0
    max_drawdown: float = 0.0
    mean_return: float = 0.0
    win_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "sharpe": round(self.sharpe, 4),
            "volatility": round(self.volatility, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "mean_return": round(self.mean_return, 6),
            "win_rate": round(self.win_rate, 4),
        }


@dataclass(frozen=True)
class TemporalStabilityResult:
    """Results of temporal stability analysis.

    Attributes:
        rolling_metrics: Per-window metrics
        sharpe_trend: Slope of rolling Sharpe (negative = decaying)
        sharpe_stability: Std of rolling Sharpe
        min_sharpe: Worst window Sharpe
        max_sharpe: Best window Sharpe
        pct_positive_sharpe: % of windows with positive Sharpe
        window_count: Number of rolling windows
        performance_decay: True if Sharpe trend is significantly negative
    """

    rolling_metrics: List[RollingMetrics] = field(default_factory=list)
    sharpe_trend: float = 0.0
    sharpe_stability: float = 0.0
    min_sharpe: float = 0.0
    max_sharpe: float = 0.0
    pct_positive_sharpe: float = 0.0
    window_count: int = 0
    performance_decay: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_count": self.window_count,
            "sharpe_trend": round(self.sharpe_trend, 6),
            "sharpe_stability": round(self.sharpe_stability, 4),
            "min_sharpe": round(self.min_sharpe, 4),
            "max_sharpe": round(self.max_sharpe, 4),
            "pct_positive_sharpe": round(self.pct_positive_sharpe, 2),
            "performance_decay": self.performance_decay,
        }


def _compute_sharpe(returns: List[float]) -> float:
    """Compute annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std < 1e-15:
        if abs(mean) < 1e-15:
            return 0.0
        return math.copysign(100.0, mean)
    return (mean * 252) / (std * math.sqrt(252))


def _compute_max_drawdown(returns: List[float]) -> float:
    """Compute maximum drawdown from return series."""
    if not returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def temporal_stability(
    equity_curve: List[float],
    window_size: int = 252,
    step_size: int = 63,
) -> TemporalStabilityResult:
    """Analyze temporal stability of strategy performance.

    Args:
        equity_curve: List of equity values
        window_size: Number of bars per rolling window
        step_size: Number of bars between window starts

    Returns:
        TemporalStabilityResult with rolling metrics and trend analysis
    """
    if len(equity_curve) < window_size + 1:
        return TemporalStabilityResult()

    # Compute returns from equity curve
    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            returns.append((equity_curve[i] / equity_curve[i - 1]) - 1.0)

    rolling = []
    start = 0

    while start + window_size <= len(returns):
        window_returns = returns[start : start + window_size]

        sharpe = _compute_sharpe(window_returns)
        mean_r = sum(window_returns) / len(window_returns)
        var_r = sum((r - mean_r) ** 2 for r in window_returns) / (len(window_returns) - 1)
        vol = math.sqrt(var_r) * math.sqrt(252)
        max_dd = _compute_max_drawdown(window_returns)
        win_rate = sum(1 for r in window_returns if r > 0) / len(window_returns) * 100

        rolling.append(
            RollingMetrics(
                start_idx=start,
                end_idx=start + window_size,
                sharpe=sharpe,
                volatility=vol,
                max_drawdown=max_dd,
                mean_return=mean_r,
                win_rate=win_rate,
            )
        )

        start += step_size

    if not rolling:
        return TemporalStabilityResult()

    sharpes = [m.sharpe for m in rolling]
    n = len(sharpes)

    # Compute trend (linear regression slope)
    x_mean = (n - 1) / 2.0
    y_mean = sum(sharpes) / n
    numerator = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(sharpes))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    trend = numerator / denominator if denominator > 0 else 0.0

    # Sharpe stability
    sharpe_var = sum((s - y_mean) ** 2 for s in sharpes) / n
    sharpe_std = math.sqrt(sharpe_var)

    min_s = min(sharpes)
    max_s = max(sharpes)
    pct_positive = sum(1 for s in sharpes if s > 0) / n * 100

    return TemporalStabilityResult(
        rolling_metrics=rolling,
        sharpe_trend=trend,
        sharpe_stability=sharpe_std,
        min_sharpe=min_s,
        max_sharpe=max_s,
        pct_positive_sharpe=pct_positive,
        window_count=n,
        performance_decay=trend < -0.01,  # Significant negative trend
    )
