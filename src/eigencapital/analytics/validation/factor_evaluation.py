"""Factor Evaluation — Alphalens-style signal quality diagnostics.

Implements the evaluation standards for any candidate factor/feature
(Jansen 2020, Ch. 4 "Separating signal from noise"):

1. Information Coefficient (IC): per-period Spearman rank correlation
   between signal and forward returns, with mean/std/IR/t-stat.
2. Quantile analysis: bucket signals into quantiles; forward returns
   must separate monotonically (top minus bottom spread).
3. Factor turnover: share of top-quantile membership changing between
   consecutive rebalances, plus rank autocorrelation.

These are descriptive diagnostics — they do NOT confer validity. A factor
becomes a candidate hypothesis only after surviving the full validation
engine (evidence gate, multiple-testing controls, cost stress).

Usage:
    panels = [[(signal, fwd_return), ...], ...]   # one list per period
    ic = information_coefficient(panels)
    qa = quantile_analysis(signals, forward_returns, n_quantiles=5)
    to = factor_turnover(rankings_by_period)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Mapping, Sequence, Set, Tuple


def _ranks(values: Sequence[float]) -> List[float]:
    """Average ranks (1-based) with ties resolved by averaging."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def spearman_correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation between paired samples.

    Args:
        xs: First sample
        ys: Second sample (same length)

    Returns:
        Rank correlation in [-1, 1]; 0.0 when undefined (< 2 pairs or
        zero variance in either rank vector)
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have equal length")
    if len(xs) < 2:
        return 0.0
    rx = _ranks(list(xs))
    ry = _ranks(list(ys))
    mean_rx = sum(rx) / len(rx)
    mean_ry = sum(ry) / len(ry)
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    denom = math.sqrt(var_x * var_y)
    if denom <= 1e-15:
        return 0.0
    return cov / denom


@dataclass(frozen=True)
class ICResult:
    """Information coefficient statistics across periods.

    Attributes:
        mean_ic: Mean per-period Spearman IC
        std_ic: Standard deviation of IC across periods
        ic_ir: IC information ratio (mean / std)
        t_stat: t-statistic under H0: mean IC = 0
        n_periods: Number of cross-sectional periods evaluated
        avg_names_per_period: Mean number of names per period
        pct_positive: Share of periods with positive IC
        ic_series: Per-period IC values (chronological)
    """

    mean_ic: float = 0.0
    std_ic: float = 0.0
    ic_ir: float = 0.0
    t_stat: float = 0.0
    n_periods: int = 0
    avg_names_per_period: float = 0.0
    pct_positive: float = 0.0
    ic_series: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "mean_ic": round(self.mean_ic, 6),
            "std_ic": round(self.std_ic, 6),
            "ic_ir": round(self.ic_ir, 4),
            "t_stat": round(self.t_stat, 4),
            "n_periods": self.n_periods,
            "avg_names_per_period": round(self.avg_names_per_period, 2),
            "pct_positive": round(self.pct_positive, 4),
            "ic_series": [round(v, 6) for v in self.ic_series],
        }


def information_coefficient(
    panels: Sequence[Sequence[Tuple[float, float]]],
    min_names: int = 5,
) -> ICResult:
    """Compute per-period Spearman IC between signals and forward returns.

    Args:
        panels: One entry per rebalance period; each entry is a list of
            (signal, forward_return) pairs for that period's cross-section
        min_names: Minimum cross-section width for a period to count;
            narrower periods are skipped rather than diluting the series

    Returns:
        ICResult aggregating the per-period IC series
    """
    ic_series: List[float] = []
    widths: List[int] = []
    for panel in panels:
        if len(panel) < min_names:
            continue
        signals = [p[0] for p in panel]
        fwd_returns = [p[1] for p in panel]
        ic_series.append(spearman_correlation(signals, fwd_returns))
        widths.append(len(panel))

    if not ic_series:
        return ICResult()

    n = len(ic_series)
    mean_ic = sum(ic_series) / n
    variance = sum((v - mean_ic) ** 2 for v in ic_series) / max(1, n - 1)
    std_ic = math.sqrt(variance)
    ic_ir = mean_ic / std_ic if std_ic > 1e-15 else 0.0
    t_stat = mean_ic / (std_ic / math.sqrt(n)) if std_ic > 1e-15 else 0.0

    return ICResult(
        mean_ic=mean_ic,
        std_ic=std_ic,
        ic_ir=ic_ir,
        t_stat=t_stat,
        n_periods=n,
        avg_names_per_period=sum(widths) / len(widths),
        pct_positive=sum(1 for v in ic_series if v > 0) / n,
        ic_series=tuple(ic_series),
    )


@dataclass(frozen=True)
class QuantileResult:
    """Quantile analysis of signal predictive power.

    Attributes:
        n_quantiles: Number of buckets (1 = highest signals)
        quantile_mean_returns: Mean forward return per quantile
        quantile_sizes: Names per quantile
        top_minus_bottom: Q1 mean minus bottom-quantile mean
        monotonic: Whether quantile means are non-increasing from Q1
            to bottom (for a positive-expected-edge signal) OR strictly
            monotonic in either direction is reported via direction
        direction: "positive" (Q1 > bottom), "negative", or "none"
        spread_series: Top-minus-bottom spread when computed per period
            via quantile_spread_series (empty here)
    """

    n_quantiles: int = 0
    quantile_mean_returns: Tuple[float, ...] = ()
    quantile_sizes: Tuple[int, ...] = ()
    top_minus_bottom: float = 0.0
    monotonic: bool = False
    direction: str = "none"
    spread_series: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "n_quantiles": self.n_quantiles,
            "quantile_mean_returns": [
                round(v, 8) for v in self.quantile_mean_returns
            ],
            "quantile_sizes": list(self.quantile_sizes),
            "top_minus_bottom": round(self.top_minus_bottom, 8),
            "monotonic": self.monotonic,
            "direction": self.direction,
            "spread_series": [round(v, 8) for v in self.spread_series],
        }


def _assign_quantiles(
    signals: Sequence[float], n_quantiles: int
) -> List[int]:
    """Assign each observation a quantile bucket 0 (bottom) .. n-1 (top).

    Observations are ranked by signal; buckets are as even as possible.
    Ties keep their rank position (same policy as _ranks ordering).
    """
    n = len(signals)
    order = sorted(range(n), key=lambda i: signals[i])
    assignment = [0] * n
    for position, idx in enumerate(order):
        assignment[idx] = position * n_quantiles // n
    return assignment


def quantile_analysis(
    signals: Sequence[float],
    forward_returns: Sequence[float],
    n_quantiles: int = 5,
) -> QuantileResult:
    """Bucket a pooled cross-section into quantiles and compare forward returns.

    Quantile 0 holds the LOWEST signals; quantile n-1 the HIGHEST.

    Args:
        signals: Signal values (one per name)
        forward_returns: Matching forward returns
        n_quantiles: Number of buckets (>= 2)

    Returns:
        QuantileResult with per-bucket means and monotonicity verdict

    Raises:
        ValueError: on mismatched inputs or n_quantiles < 2
    """
    if len(signals) != len(forward_returns):
        raise ValueError("signals and forward_returns must have equal length")
    if n_quantiles < 2:
        raise ValueError("n_quantiles must be >= 2")
    if not signals:
        return QuantileResult(n_quantiles=n_quantiles)

    assignment = _assign_quantiles(signals, n_quantiles)
    sums = [0.0] * n_quantiles
    counts = [0] * n_quantiles
    for sig_q, ret in zip(assignment, forward_returns):
        sums[sig_q] += ret
        counts[sig_q] += 1

    means = tuple(sums[q] / counts[q] if counts[q] else 0.0 for q in range(n_quantiles))
    sizes = tuple(counts)
    spread = means[-1] - means[0]

    non_increasing = all(
        means[i] >= means[i + 1] - 1e-12 for i in range(n_quantiles - 1)
    )
    non_decreasing = all(
        means[i] <= means[i + 1] + 1e-12 for i in range(n_quantiles - 1)
    )

    if spread > 0:
        direction = "positive"
        monotonic = non_increasing or non_decreasing
    elif spread < 0:
        direction = "negative"
        monotonic = non_increasing or non_decreasing
    else:
        direction = "none"
        monotonic = False

    return QuantileResult(
        n_quantiles=n_quantiles,
        quantile_mean_returns=means,
        quantile_sizes=sizes,
        top_minus_bottom=spread,
        monotonic=monotonic,
        direction=direction,
    )


def quantile_spread_series(
    panels: Sequence[Sequence[Tuple[float, float]]],
    n_quantiles: int = 5,
    min_names: int = 5,
) -> List[float]:
    """Top-minus-bottom quantile spread per period (signal decay view).

    Args:
        panels: One entry per period of (signal, forward_return) pairs
        n_quantiles: Buckets per period
        min_names: Periods narrower than this are skipped

    Returns:
        Chronological list of per-period spreads
    """
    spreads: List[float] = []
    for panel in panels:
        if len(panel) < min_names:
            continue
        result = quantile_analysis(
            [p[0] for p in panel], [p[1] for p in panel], n_quantiles
        )
        spreads.append(result.top_minus_bottom)
    return spreads


@dataclass(frozen=True)
class TurnoverResult:
    """Factor turnover and rank stability across rebalances.

    Attributes:
        mean_top_set_turnover: Mean share of top-quantile names that are
            new since the previous rebalance (Alphalens-style turnover)
        mean_rank_autocorrelation: Mean Spearman correlation between
            consecutive rank vectors over common names
        n_rebalances: Transitions evaluated (periods - 1)
        top_set_turnover_series: Per-transition top-set turnover
        rank_autocorrelation_series: Per-transition rank autocorrelation
    """

    mean_top_set_turnover: float = 0.0
    mean_rank_autocorrelation: float = 0.0
    n_rebalances: int = 0
    top_set_turnover_series: Tuple[float, ...] = ()
    rank_autocorrelation_series: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "mean_top_set_turnover": round(self.mean_top_set_turnover, 6),
            "mean_rank_autocorrelation": round(
                self.mean_rank_autocorrelation, 6
            ),
            "n_rebalances": self.n_rebalances,
            "top_set_turnover_series": [
                round(v, 6) for v in self.top_set_turnover_series
            ],
            "rank_autocorrelation_series": [
                round(v, 6) for v in self.rank_autocorrelation_series
            ],
        }


def _top_set(
    ranking: Mapping[str, float], top_fraction: float
) -> Set[str]:
    """Names in the top fraction of a ranking map."""
    if not ranking:
        return set()
    ordered = sorted(ranking.items(), key=lambda kv: kv[1], reverse=True)
    k = max(1, math.ceil(len(ordered) * top_fraction))
    return {name for name, _ in ordered[:k]}


def factor_turnover(
    rankings: Sequence[Mapping[str, float]],
    top_fraction: float = 0.2,
) -> TurnoverResult:
    """Measure turnover of top-quantile membership and rank autocorrelation.

    Args:
        rankings: Ranking maps (name → signal) per rebalance, chronological
        top_fraction: Fraction of names defining the top set

    Returns:
        TurnoverResult aggregated over all consecutive transitions

    Raises:
        ValueError: if top_fraction not in (0, 1]
    """
    if not 0.0 < top_fraction <= 1.0:
        raise ValueError("top_fraction must be in (0, 1]")
    if len(rankings) < 2:
        return TurnoverResult()

    turnover_series: List[float] = []
    autocorr_series: List[float] = []

    for prev, curr in zip(rankings, rankings[1:]):
        prev_top = _top_set(prev, top_fraction)
        curr_top = _top_set(curr, top_fraction)
        if curr_top:
            entering = len(curr_top - prev_top)
            turnover_series.append(entering / len(curr_top))

        common = sorted(set(prev) & set(curr))
        if len(common) >= 2:
            corr = spearman_correlation(
                [prev[name] for name in common],
                [curr[name] for name in common],
            )
            autocorr_series.append(corr)

    def _mean(series: List[float]) -> float:
        return sum(series) / len(series) if series else 0.0

    return TurnoverResult(
        mean_top_set_turnover=_mean(turnover_series),
        mean_rank_autocorrelation=_mean(autocorr_series),
        n_rebalances=len(rankings) - 1,
        top_set_turnover_series=tuple(turnover_series),
        rank_autocorrelation_series=tuple(autocorr_series),
    )
