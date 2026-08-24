"""Canonical Performance Metrics — deterministic implementations.

All metrics fail closed: undefined statistics raise ValueError
rather than silently returning zero.

Usage:
    metrics = compute_metrics(equity_curve=[100, 102, 98, 105, 110])
    print(metrics.sharpe_ratio)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass(frozen=True)
class PerformanceMetrics:
    """Complete performance metrics for a strategy.

    All fields are computed deterministically from equity curve and returns.
    Undefined metrics raise ValueError rather than returning zero.
    """

    # Return metrics
    total_return: float = 0.0
    cagr: float = 0.0
    annualized_volatility: float = 0.0
    annualized_return: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    avg_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    recovery_days: int = 0
    downside_deviation: float = 0.0
    sortino_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Trade metrics (from individual trades, not equity curve)
    trade_count: int = 0
    hit_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    median_trade: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0

    # Distribution metrics
    skew: float = 0.0
    kurtosis: float = 0.0
    var_95: float = 0.0  # Value at Risk (95%)
    expected_shortfall_95: float = 0.0

    # Observation metadata
    observation_count: int = 0
    annualization_factor: int = 252

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "total_return": round(self.total_return, 6),
            "cagr": round(self.cagr, 6),
            "annualized_volatility": round(self.annualized_volatility, 6),
            "annualized_return": round(self.annualized_return, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "avg_drawdown": round(self.avg_drawdown, 6),
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
            "recovery_days": self.recovery_days,
            "downside_deviation": round(self.downside_deviation, 6),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "trade_count": self.trade_count,
            "hit_rate": round(self.hit_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy": round(self.expectancy, 6),
            "skew": round(self.skew, 4),
            "kurtosis": round(self.kurtosis, 4),
            "var_95": round(self.var_95, 6),
            "expected_shortfall_95": round(self.expected_shortfall_95, 6),
            "observation_count": self.observation_count,
        }


def compute_returns(equity_curve: List[float]) -> List[float]:
    """Compute period returns from equity curve.

    Args:
        equity_curve: List of equity values

    Returns:
        List of period returns (as decimals)
    """
    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            returns.append((equity_curve[i] / equity_curve[i - 1]) - 1.0)
    return returns


def _sortino_denominator(returns: List[float], target: float = 0.0) -> float:
    """Compute downside deviation."""
    downside = [min(r - target, 0.0) ** 2 for r in returns]
    if not downside:
        return 0.0
    return math.sqrt(sum(downside) / len(downside))


def _percentile(sorted_data: List[float], p: float) -> float:
    """Compute percentile from sorted data."""
    if not sorted_data:
        return 0.0
    idx = p * (len(sorted_data) - 1)
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return sorted_data[lower]
    frac = idx - lower
    return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac


def compute_metrics(
    equity_curve: List[float],
    trades: Optional[List[float]] = None,
    risk_free_rate: float = 0.0,
    annualization_factor: int = 252,
) -> PerformanceMetrics:
    """Compute all performance metrics from equity curve and optional trades.

    Args:
        equity_curve: List of equity values over time
        trades: Optional list of individual trade P&L values
        risk_free_rate: Annual risk-free rate (default: 0)
        annualization_factor: Trading days per year (default: 252)

    Returns:
        PerformanceMetrics with all computed metrics

    Raises:
        ValueError: If equity_curve has insufficient data or undefined metrics
    """
    if len(equity_curve) < 2:
        raise ValueError("equity_curve must have at least 2 values")

    # Check for negative or zero equity
    if any(e <= 0 for e in equity_curve):
        raise ValueError("equity_curve values must be positive")

    returns = compute_returns(equity_curve)
    n = len(returns)

    if n < 1:
        raise ValueError("equity_curve must produce at least 1 return")

    # ── Return metrics ──────────────────────────────────────────────
    total_return = (equity_curve[-1] / equity_curve[0]) - 1.0
    years = n / annualization_factor
    cagr = (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1.0 if years > 0 else 0.0

    mean_ret = sum(returns) / n
    variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(variance)
    annualized_vol = std * math.sqrt(annualization_factor)
    annualized_ret = mean_ret * annualization_factor

    # ── Risk metrics ────────────────────────────────────────────────
    peak = equity_curve[0]
    max_dd = 0.0
    dd_durations = []
    current_dd_start = 0
    in_dd = False
    dd_values = []

    for i, eq in enumerate(equity_curve):
        if eq > peak:
            peak = eq
            if in_dd:
                dd_durations.append(i - current_dd_start)
                in_dd = False
        dd = (peak - eq) / peak if peak > 0 else 0.0
        dd_values.append(dd)
        if dd > max_dd:
            max_dd = dd
        if dd > 0 and not in_dd:
            current_dd_start = i
            in_dd = True

    if in_dd:
        dd_durations.append(len(equity_curve) - 1 - current_dd_start)

    avg_dd = sum(dd_values) / len(dd_values) if dd_values else 0.0
    max_dd_duration = max(dd_durations) if dd_durations else 0
    recovery = dd_durations[-1] if dd_durations else 0

    # Downside deviation
    downside_dev = _sortino_denominator(returns)

    # Sharpe ratio
    if std > 1e-15:
        sharpe = (mean_ret - risk_free_rate / annualization_factor) / std * math.sqrt(annualization_factor)
    else:
        sharpe = math.copysign(100.0, mean_ret - risk_free_rate / annualization_factor) if abs(mean_ret - risk_free_rate / annualization_factor) > 1e-15 else 0.0

    # Sortino ratio
    if downside_dev > 1e-15:
        sortino = (annualized_ret - risk_free_rate) / (downside_dev * math.sqrt(annualization_factor))
    else:
        sortino = 0.0

    # Calmar ratio
    calmar = annualized_ret / max_dd if max_dd > 1e-15 else 0.0

    # ── Trade metrics ───────────────────────────────────────────────
    trade_count = len(trades) if trades else 0
    hit_rate = 0.0
    avg_win = 0.0
    avg_loss = 0.0
    win_loss_ratio = 0.0
    profit_factor = 0.0
    expectancy = 0.0
    median_trade = 0.0
    largest_win = 0.0
    largest_loss = 0.0
    consecutive_wins = 0
    consecutive_losses = 0

    if trades:
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]

        hit_rate = len(wins) / len(trades) if trades else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        expectancy = sum(trades) / len(trades)

        sorted_trades = sorted(trades)
        median_trade = _percentile(sorted_trades, 0.5)

        largest_win = max(wins) if wins else 0.0
        largest_loss = min(losses) if losses else 0.0

        # Consecutive wins/losses
        max_cw = 0
        max_cl = 0
        cw = 0
        cl = 0
        for t in trades:
            if t > 0:
                cw += 1
                cl = 0
            elif t < 0:
                cl += 1
                cw = 0
            else:
                cw = 0
                cl = 0
            max_cw = max(max_cw, cw)
            max_cl = max(max_cl, cl)
        consecutive_wins = max_cw
        consecutive_losses = max_cl

    # ── Distribution metrics ────────────────────────────────────────
    skew = 0.0
    kurtosis = 0.0
    var_95 = 0.0
    expected_shortfall_95 = 0.0

    if n >= 3:
        # Skewness
        m3 = sum((r - mean_ret) ** 3 for r in returns) / n
        skew = m3 / (std ** 3) if std > 1e-15 else 0.0

        # Kurtosis (excess)
        m4 = sum((r - mean_ret) ** 4 for r in returns) / n
        kurtosis = (m4 / (std ** 4)) - 3.0 if std > 1e-15 else 0.0

    if n >= 20:
        sorted_returns = sorted(returns)
        var_95 = _percentile(sorted_returns, 0.05)

        # Expected Shortfall (CVaR): mean of returns below VaR
        below_var = [r for r in returns if r <= var_95]
        expected_shortfall_95 = sum(below_var) / len(below_var) if below_var else var_95

    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_vol,
        annualized_return=annualized_ret,
        max_drawdown=max_dd,
        avg_drawdown=avg_dd,
        max_drawdown_duration_days=max_dd_duration,
        recovery_days=recovery,
        downside_deviation=downside_dev,
        sortino_ratio=sortino,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        trade_count=trade_count,
        hit_rate=hit_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        win_loss_ratio=win_loss_ratio,
        profit_factor=profit_factor,
        expectancy=expectancy,
        median_trade=median_trade,
        largest_win=largest_win,
        largest_loss=largest_loss,
        consecutive_wins=consecutive_wins,
        consecutive_losses=consecutive_losses,
        skew=skew,
        kurtosis=kurtosis,
        var_95=var_95,
        expected_shortfall_95=expected_shortfall_95,
        observation_count=n,
        annualization_factor=annualization_factor,
    )
