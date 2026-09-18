"""Per-Point Evaluation — one preregistered grid point → PointMetrics.

R3 Phase B1 (docs/research/R3_PARAMETER_STABILITY.md): runs the FULL
preregistered pipeline for a single grid point. The signal and simulation
stages are INJECTED (dependency injection) so this src module never imports
from scripts/: the runner passes the R1 exporter's `compute_r4_signal` /
`simulate_portfolio` unchanged — zero signal-logic duplication (contract
item 5, verified in R3-A).

Daily-path realization (pre-execution addendum, frozen): path metrics and
the WF equity input come from a close-to-close daily portfolio path built
from the EXECUTED weight path (step function updated at weekly execution
dates, one-day lag), minus per-change costs |Δw| × cost_one_way. Trade-level
metrics (count, hit rate, payoff) come from the round-trip ledger. These are
two documented realizations of one simulation.

Deterministic and side-effect-free — safe for multiprocessing workers.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult,
    purged_walk_forward,
)
from eigencapital.research.parameter_stability.grid import (
    WF_EMBARGO_BARS,
    WF_PURGE_BARS,
    WF_TEST_BARS,
    WF_TRAIN_BARS,
    PointMetrics,
)

TRADING_DAYS = 252.0

SignalFn = Callable[[Dict[str, Any], Dict[str, pd.DataFrame]], pd.DataFrame]
SimulateFn = Callable[
    [Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, Any]],
    Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Tuple[float, float]]]],
]


def daily_portfolio_path(
    data: Dict[str, pd.DataFrame],
    weights: pd.DataFrame,
    cost_one_way: float,
) -> pd.Series:
    """Close-to-close daily portfolio return series from the executed weights.

    Preregistered realization (pre-execution addendum):
    - target weights W(t) (the signal DataFrame) are executed NEXT BAR:
      executed weight E(t) = W(t−1) for the close-to-close move from t−1 to t;
    - when E changes at t, cost |ΔE(t)| × cost_one_way is charged that day;
    - the portfolio daily return is Σ_sym E_sym(t) × r_sym(t).
    """
    closes = pd.DataFrame({sym: df["close"] for sym, df in data.items()})
    returns = closes.pct_change().fillna(0.0)

    aligned = weights.reindex(closes.index).ffill()
    executed = aligned.shift(1).fillna(0.0)
    delta = executed.diff().abs()
    first = executed.abs().iloc[0] if len(executed) else executed * 0.0
    costs = delta.fillna(first).sum(axis=1) * cost_one_way

    port = (executed * returns).sum(axis=1) - costs
    return port


def equity_curve_from_returns(returns: pd.Series) -> List[float]:
    """Compounded equity curve starting at 1.0 (len = n_days + 1)."""
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + float(r)))
    return equity


def _full_path_metrics(returns: pd.Series, equity: List[float]) -> Dict[str, float]:
    """CAGR, ann vol, max DD, Sharpe on the daily path (fixed list, item 6)."""
    n = len(returns)
    total = equity[-1] / equity[0] - 1.0
    years = n / TRADING_DAYS
    cagr = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 and equity[-1] > 0 else -1.0

    std = float(np.std(returns, ddof=1)) if n > 1 else 0.0
    ann_vol = std * math.sqrt(TRADING_DAYS)
    mean_daily = float(np.mean(returns)) if n else 0.0
    sharpe = (mean_daily * TRADING_DAYS) / ann_vol if ann_vol > 1e-15 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - v / peak)

    return {"cagr": cagr, "ann_vol": ann_vol, "max_drawdown": max_dd, "sharpe": sharpe}


def evaluate_grid_point(
    params: Dict[str, float],
    data: Dict[str, pd.DataFrame],
    base_params: Dict[str, Any],
    signal_fn: SignalFn,
    simulate_fn: SimulateFn,
) -> PointMetrics:
    """Evaluate ONE preregistered grid point through the full pipeline.

    Args:
        params: The grid point's axis overrides (e.g. lookback=220). Only
            preregistered axis keys are honored; everything else comes from
            `base_params` (the frozen config values).
        data: Symbol → OHLC frame (identical object across all points —
            contract item 5).
        base_params: Frozen baseline from the exporter's `load_config_params()`.
        signal_fn: The exporter's `compute_r4_signal` (injected — no
            scripts-import from src).
        simulate_fn: The exporter's `simulate_portfolio` (injected).

    Returns:
        PointMetrics with the preregistered metric list.

    Raises:
        Any pipeline exception propagates to the caller, which records a
        PointError (never a silent drop).
    """
    merged = dict(base_params)
    merged.update({k: (int(v) if float(v).is_integer() else v) for k, v in params.items()})

    weights = signal_fn(data, merged)
    _, trades_by_symbol = simulate_fn(data, weights, merged)
    all_pnls = [p for trades in trades_by_symbol.values() for p, _ in trades]

    # Trade-level metrics from the round-trip ledger (R1-compatible view)
    n_trades = len(all_pnls)
    wins = [p for p in all_pnls if p > 0]
    losses = [p for p in all_pnls if p <= 0]
    hit_rate = len(wins) / n_trades if n_trades else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    payoff = avg_win / avg_loss if avg_loss > 1e-15 else 0.0
    total_pnl = sum(all_pnls)

    # Daily-path metrics + WF aggregate (preregistered realization)
    returns = daily_portfolio_path(data, weights, float(merged["cost_one_way"]))
    equity = equity_curve_from_returns(returns)
    path = _full_path_metrics(returns, equity)
    wf = _walk_forward(equity)

    turnover = float(np.abs(weights).sum(axis=1).mean()) if len(weights) else 0.0

    return PointMetrics(
        params=dict(params),
        cagr=path["cagr"],
        ann_vol=path["ann_vol"],
        max_drawdown=path["max_drawdown"],
        sharpe=path["sharpe"],
        total_pnl=total_pnl,
        trade_count=n_trades,
        turnover=turnover,
        hit_rate=hit_rate,
        payoff_ratio=payoff,
        wf_total_windows=wf.total_windows,
        wf_mean_oos_sharpe=wf.mean_oos_sharpe,
        wf_pct_profitable_windows=wf.pct_profitable_windows,
        wf_oos_return_mean=wf.oos_return_mean,
        wf_oos_return_std=wf.oos_return_std,
        wf_note="",
    )


def _walk_forward(equity: List[float]) -> WalkForwardResult:
    """Preregistered WF geometry; total_windows=0 when it cannot fit."""
    n = len(equity)
    if n < WF_TRAIN_BARS + WF_PURGE_BARS + WF_TEST_BARS:
        return WalkForwardResult(
            total_windows=0,
            purge_bars=WF_PURGE_BARS,
            embargo_bars=WF_EMBARGO_BARS,
        )
    return purged_walk_forward(
        equity_curve=equity,
        train_bars=WF_TRAIN_BARS,
        test_bars=WF_TEST_BARS,
        purge_bars=WF_PURGE_BARS,
        embargo_bars=WF_EMBARGO_BARS,
        anchored=True,
    )
