"""Regime Analysis — performance stability across market regimes.

A genuine edge should work across different market conditions,
not just in one favorable regime. We test:
- Trending vs mean-reverting periods
- High volatility vs low volatility
- Crisis vs normal

Usage:
    result = regime_analysis(
        regime_returns={"trending": [0.01, 0.02], "choppy": [-0.01, 0.005]},
        regime_labels=["trending", "choppy"],
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RegimeMetrics:
    """Performance metrics for a single regime.

    Attributes:
        regime: Regime name
        bar_count: Number of bars in this regime
        mean_return: Mean period return
        sharpe: Annualized Sharpe ratio
        total_return: Total cumulative return
        max_drawdown: Maximum drawdown during regime
        win_rate: % of positive-return periods
    """

    regime: str
    bar_count: int = 0
    mean_return: float = 0.0
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "bar_count": self.bar_count,
            "mean_return": round(self.mean_return, 6),
            "sharpe": round(self.sharpe, 4),
            "total_return": round(self.total_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 2),
        }


@dataclass(frozen=True)
class RegimeResult:
    """Results of regime analysis.

    Attributes:
        regimes: Per-regime metrics
        worst_regime: Name of worst-performing regime
        best_regime: Name of best-performing regime
        sharpe_range: max_sharpe - min_sharpe across regimes
        regime_dependent: True if performance varies wildly by regime
        min_sharpe: Worst regime Sharpe
        max_sharpe: Best regime Sharpe
    """

    regimes: List[RegimeMetrics] = field(default_factory=list)
    worst_regime: str = ""
    best_regime: str = ""
    sharpe_range: float = 0.0
    regime_dependent: bool = False
    min_sharpe: float = 0.0
    max_sharpe: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worst_regime": self.worst_regime,
            "best_regime": self.best_regime,
            "sharpe_range": round(self.sharpe_range, 4),
            "regime_dependent": self.regime_dependent,
            "min_sharpe": round(self.min_sharpe, 4),
            "max_sharpe": round(self.max_sharpe, 4),
            "regimes": [r.to_dict() for r in self.regimes],
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


def regime_analysis(
    regime_returns: Dict[str, List[float]],
    sharpe_threshold: float = 1.0,
) -> RegimeResult:
    """Analyze performance across market regimes.

    Args:
        regime_returns: Dict mapping regime name → list of period returns
        sharpe_threshold: Threshold for regime-dependent flag (range > threshold)

    Returns:
        RegimeResult with per-regime and aggregate analysis
    """
    regimes = []
    sharpes = []

    for regime_name, returns in regime_returns.items():
        if not returns:
            continue

        mean_ret = sum(returns) / len(returns)
        sharpe = _compute_sharpe(returns)
        total_ret = 1.0
        for r in returns:
            total_ret *= 1 + r
        total_ret -= 1.0

        max_dd = _compute_max_drawdown(returns)
        win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100

        regimes.append(
            RegimeMetrics(
                regime=regime_name,
                bar_count=len(returns),
                mean_return=mean_ret,
                sharpe=sharpe,
                total_return=total_ret,
                max_drawdown=max_dd,
                win_rate=win_rate,
            )
        )
        sharpes.append(sharpe)

    if not regimes:
        return RegimeResult()

    min_s = min(sharpes)
    max_s = max(sharpes)
    sharpe_range = max_s - min_s

    worst_idx = sharpes.index(min_s)
    best_idx = sharpes.index(max_s)

    return RegimeResult(
        regimes=regimes,
        worst_regime=regimes[worst_idx].regime,
        best_regime=regimes[best_idx].regime,
        sharpe_range=sharpe_range,
        regime_dependent=sharpe_range > sharpe_threshold,
        min_sharpe=min_s,
        max_sharpe=max_s,
    )
