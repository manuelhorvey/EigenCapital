"""Walk-Forward Analysis — purged and embargoed out-of-sample validation.

Walk-forward prevents overfitting by:
1. Training on a rolling window
2. Testing on a forward window (unseen data)
3. Purging overlap to prevent label leakage
4. Embargoing bars immediately after each test window so serial-correlation
   leakage cannot re-enter subsequent training sets

Purge vs. embargo: the purge gap sits BEFORE the test window and removes
training bars whose label horizon could overlap test labels. The embargo
gap sits AFTER the test window and removes those bars from every later
training slice. Window geometry is unaffected by either; only training
composition changes.

A strategy that works in-sample but fails walk-forward
is likely curve-fitted, not genuinely predictive.

Usage:
    result = purged_walk_forward(
        equity_curve=equity_curve,
        train_bars=500,
        test_bars=100,
        purge_bars=10,
        embargo_bars=5,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple


@dataclass(frozen=True)
class WalkForwardWindow:
    """A single walk-forward window.

    Attributes:
        window_id: Window identifier (0-indexed)
        train_start: Index of first bar in training window
        train_end: Index of last bar in training window (exclusive)
        test_start: Index of first bar in test window
        test_end: Index of last bar in test window (exclusive)
        in_sample_sharpe: Sharpe ratio from training period
        out_of_sample_sharpe: Sharpe ratio from test period
        in_sample_return: Total return from training period
        out_of_sample_return: Total return from test period
    """

    window_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    in_sample_sharpe: float = 0.0
    out_of_sample_sharpe: float = 0.0
    in_sample_return: float = 0.0
    out_of_sample_return: float = 0.0
    train_indices: Tuple[int, ...] = ()


@dataclass(frozen=True)
class WalkForwardResult:
    """Results of walk-forward analysis.

    Attributes:
        windows: Individual walk-forward windows
        mean_oos_sharpe: Mean out-of-sample Sharpe across windows
        std_oos_sharpe: Standard deviation of OOS Sharpe
        min_oos_sharpe: Worst window OOS Sharpe
        max_oos_sharpe: Best window OOS Sharpe
        degradation_ratio: mean(IS sharpe) / mean(OOS sharpe)
        pct_profitable_windows: % of windows with positive OOS return
        total_windows: Total number of windows
        oos_return_mean: Mean OOS return
        oos_return_std: Std of OOS returns
    """

    windows: List[WalkForwardWindow] = field(default_factory=list)
    mean_oos_sharpe: float = 0.0
    std_oos_sharpe: float = 0.0
    min_oos_sharpe: float = 0.0
    max_oos_sharpe: float = 0.0
    degradation_ratio: float = 0.0
    pct_profitable_windows: float = 0.0
    total_windows: int = 0
    oos_return_mean: float = 0.0
    oos_return_std: float = 0.0
    purge_bars: int = 0
    embargo_bars: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "total_windows": self.total_windows,
            "mean_oos_sharpe": round(self.mean_oos_sharpe, 4),
            "std_oos_sharpe": round(self.std_oos_sharpe, 4),
            "min_oos_sharpe": round(self.min_oos_sharpe, 4),
            "max_oos_sharpe": round(self.max_oos_sharpe, 4),
            "degradation_ratio": round(self.degradation_ratio, 4),
            "pct_profitable_windows": round(self.pct_profitable_windows, 2),
            "oos_return_mean": round(self.oos_return_mean, 4),
            "oos_return_std": round(self.oos_return_std, 4),
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
        }


def _compute_sharpe(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Compute annualized Sharpe ratio from a series of returns.

    Args:
        returns: List of period returns (not cumulative)
        risk_free_rate: Annual risk-free rate (default: 0)

    Returns:
        Annualized Sharpe ratio
    """
    if len(returns) < 2:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std < 1e-15:
        # Near-zero variance: return sign of mean * large number
        if abs(mean_return) < 1e-15:
            return 0.0
        return math.copysign(100.0, mean_return)

    # Annualize (assuming ~252 trading days)
    annual_return = mean_return * 252
    annual_std = std * math.sqrt(252)
    annual_rf = risk_free_rate

    return (annual_return - annual_rf) / annual_std


def _compute_returns(equity_curve: List[float]) -> List[float]:
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


def _returns_from_segments(segments: List[List[float]]) -> List[float]:
    """Compute period returns within contiguous segments only.

    Returns are never computed across a segment boundary, so embargoed
    bars cannot leak information through a bridging return.
    """
    returns = []
    for segment in segments:
        returns.extend(_compute_returns(segment))
    return returns


def _contiguous_segments(
    indices: List[int], equity_curve: List[float]
) -> List[List[float]]:
    """Split bar indices into contiguous runs and map them to equity values."""
    segments: List[List[float]] = []
    current: List[int] = []
    for idx in indices:
        if current and idx != current[-1] + 1:
            segments.append([equity_curve[i] for i in current])
            current = []
        current.append(idx)
    if current:
        segments.append([equity_curve[i] for i in current])
    return segments


def _exclude_embargo_zones(
    train_start: int,
    train_end: int,
    embargo_zones: List[Tuple[int, int]],
) -> List[int]:
    """Return training bar indices with all embargo zones removed."""
    zones = sorted(embargo_zones)
    indices: List[int] = []
    cursor = train_start
    for zone_start, zone_end in zones:
        if zone_end <= cursor or zone_start >= train_end:
            continue
        upper = min(zone_start, train_end)
        indices.extend(range(cursor, upper))
        cursor = max(cursor, zone_end)
    if cursor < train_end:
        indices.extend(range(cursor, train_end))
    return indices


def purged_walk_forward(
    equity_curve: List[float],
    train_bars: int = 500,
    test_bars: int = 100,
    purge_bars: int = 10,
    embargo_bars: int = 0,
    anchored: bool = False,
) -> WalkForwardResult:
    """Perform purged and embargoed walk-forward analysis.

    Args:
        equity_curve: Full equity curve (list of equity values per bar)
        train_bars: Number of bars in training window
        test_bars: Number of bars in test window
        purge_bars: Number of bars to purge between train and test
        embargo_bars: Bars after each test window excluded from all later
            training slices (serial-correlation buffer). 0 disables.
        anchored: If True, training window starts at beginning (anchored)

    Returns:
        WalkForwardResult with per-window metrics and aggregates. Window
        geometry (train/test boundaries) is independent of embargo_bars;
        only training composition changes.
    """
    if train_bars <= 0 or test_bars <= 0 or purge_bars < 0 or embargo_bars < 0:
        raise ValueError(
            "train_bars and test_bars must be > 0; purge_bars and "
            "embargo_bars must be >= 0"
        )

    n = len(equity_curve)
    if n < train_bars + purge_bars + test_bars:
        return WalkForwardResult(total_windows=0)

    windows = []
    window_id = 0
    start = 0
    embargo_zones: List[Tuple[int, int]] = []

    while True:
        if anchored:
            # Anchored: training always starts at 0, test window slides
            train_start = 0
            train_end = train_bars
            test_start = train_end + purge_bars + window_id * test_bars
            test_end = test_start + test_bars
        else:
            train_start = start
            train_end = start + train_bars
            test_start = train_end + purge_bars
            test_end = test_start + test_bars

        if test_end > n:
            break

        # Compute returns for train and test periods
        if embargo_bars > 0:
            train_indices = _exclude_embargo_zones(
                train_start, train_end, embargo_zones
            )
            train_segments = _contiguous_segments(train_indices, equity_curve)
        else:
            train_indices = list(range(train_start, train_end))
            train_segments = [equity_curve[train_start:train_end]]
        test_equity = equity_curve[test_start:test_end]

        train_returns = _returns_from_segments(train_segments)
        test_returns = _compute_returns(test_equity)

        # Compute metrics
        is_sharpe = _compute_sharpe(train_returns)
        oos_sharpe = _compute_sharpe(test_returns)

        def _total_return(segment_equity: List[float]) -> float:
            if len(segment_equity) < 2 or segment_equity[0] <= 0:
                return 0.0
            compounded = 1.0
            for i in range(1, len(segment_equity)):
                compounded *= segment_equity[i] / segment_equity[i - 1]
            return compounded - 1.0

        is_return = (
            _total_return(train_segments[0]) if len(train_segments) == 1 else 0.0
        )
        oos_return = (
            (test_equity[-1] / test_equity[0] - 1) if test_equity[0] > 0 else 0.0
        )

        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                in_sample_sharpe=is_sharpe,
                out_of_sample_sharpe=oos_sharpe,
                in_sample_return=is_return,
                out_of_sample_return=oos_return,
                train_indices=tuple(train_indices),
            )
        )

        if embargo_bars > 0:
            embargo_zones.append((test_end, test_end + embargo_bars))

        window_id += 1
        start += test_bars  # Slide forward

    if not windows:
        return WalkForwardResult(total_windows=0)

    # Aggregate metrics
    oos_sharpes = [w.out_of_sample_sharpe for w in windows]
    is_sharpes = [w.in_sample_sharpe for w in windows]
    oos_returns = [w.out_of_sample_return for w in windows]

    mean_oos = sum(oos_sharpes) / len(oos_sharpes)
    var_oos = sum((s - mean_oos) ** 2 for s in oos_sharpes) / len(oos_sharpes)
    std_oos = math.sqrt(var_oos)

    mean_is = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0.0
    degradation = mean_is / mean_oos if mean_oos != 0 else float("inf")

    profitable = sum(1 for r in oos_returns if r > 0)
    pct_profitable = (profitable / len(windows)) * 100

    mean_oos_ret = sum(oos_returns) / len(oos_returns)
    var_oos_ret = sum((r - mean_oos_ret) ** 2 for r in oos_returns) / len(oos_returns)
    std_oos_ret = math.sqrt(var_oos_ret)

    return WalkForwardResult(
        windows=windows,
        mean_oos_sharpe=mean_oos,
        std_oos_sharpe=std_oos,
        min_oos_sharpe=min(oos_sharpes),
        max_oos_sharpe=max(oos_sharpes),
        degradation_ratio=degradation,
        pct_profitable_windows=pct_profitable,
        total_windows=len(windows),
        oos_return_mean=mean_oos_ret,
        oos_return_std=std_oos_ret,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
    )
