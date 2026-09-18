"""Path Metrics — equity-path diagnostics for Monte Carlo permutations.

R1 Phase B1 (docs/research/R1_MONTE_CARLO.md): reconstruct an equity path
from a sequence of closed-trade P&Ls and compute the path-dependent metrics
the permutation distribution is built from.

Key invariant (frozen handoff, B1):

> Pure permutation preserves the exact set of trades. Metrics that depend only
> on the unordered trade set (total P&L, trade count) are therefore invariant
> under permutation; path-dependent metrics (drawdown, streaks, recovery)
> can change.

Design notes:
- Default ``initial_equity=1.0`` puts metrics in return space so streams of
  different account sizes are comparable. For currency-unit streams pass the
  account's starting equity explicitly. Callers choose ONE space; mixing
  ``realized_pnl`` with a default initial equity of 1.0 is the caller's
  explicit decision (use ``use_return_r=True`` for normalized R-space paths).
- Drawdowns are fractional relative to the running peak.
- All metrics are pure functions of the P&L sequence: deterministic, no
  randomness, no state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from eigencapital.research.monte_carlo.schema import TradeStream, TradeStreamError


@dataclass(frozen=True)
class PathMetrics:
    """Path-dependent diagnostics for one ordering of the trade set.

    Attributes:
        total_pnl: Sum of trade P&Ls (set-invariant under permutation).
        trade_count: Number of trades (set-invariant).
        max_drawdown: Largest peak-to-trough decline as a fraction of the
            running peak (0.0 when the path never declines).
        max_drawdown_duration: Longest number of consecutive trades whose
            closing equity is below the running peak (underwater length).
        longest_losing_streak: Longest run of consecutive trades with
            negative P&L.
        recovery_time: Trades from the deepest-trough trade to the trade that
            first regains the pre-drawdown peak (None if never drew down or
            never recovered within the path).
        min_equity: Lowest equity value reached on the path.
        time_under_water: Number of trades whose closing equity is below the
            running peak at that point.
        final_equity: Equity after the last trade.
    """

    total_pnl: float
    trade_count: int
    max_drawdown: float
    max_drawdown_duration: int
    longest_losing_streak: int
    recovery_time: int | None
    min_equity: float
    time_under_water: int
    final_equity: float


def trade_pnls(stream: TradeStream, use_return_r: bool = False) -> tuple[float, ...]:
    """Extract the ordered P&L sequence from a stream.

    Args:
        stream: The persisted trade stream.
        use_return_r: When True, use each trade's ``return_r`` (requires every
            trade to define it). When False, use ``realized_pnl``.

    Returns:
        The P&L sequence in stream (chronological) order.

    Raises:
        TradeStreamError: If ``use_return_r`` is requested but any trade lacks
            a return_r value.
    """
    if use_return_r:
        missing = [t.trade_index for t in stream.trades if t.return_r is None]
        if missing:
            raise TradeStreamError(f"use_return_r=True but trades {missing[:5]} lack return_r values")
        return tuple(float(t.return_r) for t in stream.trades if t.return_r is not None)
    return tuple(t.realized_pnl for t in stream.trades)


def compute_path_metrics(
    pnls: Sequence[float],
    initial_equity: float = 1.0,
) -> PathMetrics:
    """Compute path metrics for one ordering of the trade set.

    Args:
        pnls: Closed-trade P&Ls in path order.
        initial_equity: Starting equity. Default 1.0 (return space).

    Returns:
        PathMetrics for this ordering.

    Raises:
        TradeStreamError: On empty input or non-finite values.
    """
    if not pnls:
        raise TradeStreamError("cannot compute path metrics for an empty trade sequence")
    values: list[float] = []
    for p in pnls:
        v = float(p)
        if not math.isfinite(v):
            raise TradeStreamError("path metrics require finite trade P&L values")
        values.append(v)

    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    underwater_run = 0
    max_underwater_run = 0
    underwater_count = 0
    losing_streak = 0
    longest_losing_streak = 0
    min_equity = initial_equity

    for pnl in values:
        equity += pnl
        if equity < peak:
            underwater_count += 1
            underwater_run += 1
            if underwater_run > max_underwater_run:
                max_underwater_run = underwater_run
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        else:
            underwater_run = 0
            peak = equity

        if equity < min_equity:
            min_equity = equity

        if pnl < 0:
            losing_streak += 1
            if losing_streak > longest_losing_streak:
                longest_losing_streak = losing_streak
        else:
            losing_streak = 0

    total_pnl = math.fsum(values)

    return PathMetrics(
        total_pnl=total_pnl,
        trade_count=len(values),
        max_drawdown=max_dd,
        max_drawdown_duration=max_underwater_run,
        longest_losing_streak=longest_losing_streak,
        recovery_time=_recovery_time(values, initial_equity),
        min_equity=min_equity,
        time_under_water=underwater_count,
        final_equity=initial_equity + total_pnl,
    )


def _recovery_time(pnls: Sequence[float], initial_equity: float) -> int | None:
    """Trades from the deepest-trough trade to the trade that first regains
    the pre-drawdown peak.

    Semantics (deterministic):
    - The trough is the trade whose closing equity is farthest below the
      running peak (fractional drawdown); ties resolve to the FIRST deepest.
    - Recovery counts the trades strictly after the trough trade up to and
      including the trade where equity first reaches the pre-trough peak.
    - Returns None when the path never draws down, or draws down but never
      recovers within the observed path.
    """
    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    trough_index = -1
    pre_peak = initial_equity
    for i, pnl in enumerate(pnls):
        equity += pnl
        if equity < peak:
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                trough_index = i
                pre_peak = peak
        else:
            peak = equity
    if trough_index < 0:
        return None

    equity = initial_equity + math.fsum(pnls[: trough_index + 1])
    for j in range(trough_index + 1, len(pnls)):
        equity += pnls[j]
        if equity >= pre_peak:
            return j - trough_index
    return None
