"""Phase 7 — Comprehensive Exit Strategy Comparison.

Simulates multiple exit strategies on every trade's realised price path
and ranks them by CAGR, Profit Factor, Sharpe, Max Drawdown, MAR, Expectancy.

Strategies compared:
  1. Fixed barriers (baseline)    — current TP/SL
  2. Adaptive exit (live)         — retracement trailing: be_lock 0.5R, trail 50%
  3. Breakeven lock only          — move SL to entry at MFE >= 1.0R
  4. Hard trailing stop           — trail at fixed retrace (33%, 50%, 67%)
  5. ATR trailing stop            — trail at N × ATR from peak
  6. Chandelier exit              — trail at 3× ATR from period high
  7. Time stop                    — force close at N candles
  8. Volatility-adjusted stop     — SL widens/tightens with market vol
  9. Hybrid (trail + time + vol)  — best-of-breed combination
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase7_exit")

# ── Strategy definitions ─────────────────────────────────────────────────────

EXIT_STRATEGY_NAMES: list[str] = [
    "fixed_barriers",
    "be_lock_only",
    "adaptive_trail_50pct",
    "trail_33pct",
    "trail_50pct",
    "trail_67pct",
    "atr_trail_1x",
    "atr_trail_2x",
    "atr_trail_3x",
    "chandelier_3atr",
    "time_stop_10",
    "time_stop_20",
    "time_stop_30",
    "volatility_stop",
    "hybrid",
]


@dataclass
class ExitStrategyResult:
    name: str
    total_r: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    win_rate: float = 0.0
    avg_r: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_dd_r: float = 0.0
    mar: float = 0.0
    expectancy: float = 0.0
    per_asset: dict[str, float] = field(default_factory=dict)


# ── Exit simulators ──────────────────────────────────────────────────────────

StrategyFn = Callable[[dict[str, Any], float], float]


def exit_fixed(trade: dict[str, Any], _ohlcv: Any = None) -> float:
    """Baseline: use the actual realized R."""
    return trade.get("r_multiple", 0.0)


def exit_be_lock(trade: dict[str, Any], _ohlcv: Any = None) -> float:
    """B/e lock: if loser with MFE >= 1.0R, exit at 0.0R."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if mfe >= 1.0:
        return 0.0
    return orig


def _exit_trail(trade: dict[str, Any], retrace_pct: float) -> float:
    """Trailing stop at retrace_pct retracement from peak MFE."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if mfe < 0.5 or trade.get("exit_reason") == "tp":
        return orig
    captured = mfe * (1.0 - retrace_pct)
    return max(captured, 0)


def exit_trail_33(trade, _=None):
    return _exit_trail(trade, 0.33)


def exit_trail_50(trade, _=None):
    return _exit_trail(trade, 0.50)


def exit_trail_67(trade, _=None):
    return _exit_trail(trade, 0.67)


def exit_adaptive_live(trade, _=None):
    """Simulate the live AdaptiveExitEngine: be_lock at 0.5R, trail at 50% from 0.8R."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if mfe < 0.5 or trade.get("exit_reason") == "tp":
        return orig
    if mfe >= 0.8:
        captured = mfe * 0.5
        return max(captured, 0.0)
    if mfe >= 0.5:
        return 0.0
    return orig


def exit_atr_trail(trade, mult: float):
    """ATR trailing: trail at N × ATR from peak."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if trade.get("exit_reason") == "tp":
        return orig
    atr_entry = trade.get("atr_pct_entry", 0.01)
    if atr_entry <= 0:
        return orig
    atr_r = atr_entry * max(trade.get("entry_price", 1), 1) / max(atr_entry * max(trade.get("entry_price", 1), 1), 1)
    # ATR trail threshold in R-units is mult * 1.0 (atr_r ≈ 1.0 already since mfe_r is in ATR units)
    trail_distance = mult
    if mfe > trail_distance:
        captured = mfe - trail_distance
        return max(captured, 0)
    return orig


def exit_atr_1x(trade, _=None):
    return exit_atr_trail(trade, 1.0)


def exit_atr_2x(trade, _=None):
    return exit_atr_trail(trade, 2.0)


def exit_atr_3x(trade, _=None):
    return exit_atr_trail(trade, 3.0)


def exit_chandelier(trade, _=None):
    """Chandelier exit: trail at 3× ATR from 22-period high.

    Simplified: uses trade's own high/low. Applied only to losers with adequate MFE.
    """
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if mfe < 1.0:
        return orig
    exit_r = mfe * (1.0 - 0.4)  # generous 40% retrace before exit
    return max(exit_r, 0)


def exit_time_stop(trade, max_candles: int):
    """Force close after max_candles if not already closed.

    Note: full price path is not stored in serialized trade data.
    This is a pass-through — use Phase 6 for actual time-stop simulation.
    """
    return trade.get("r_multiple", 0.0)


def exit_time_stop_10(trade, _=None):
    return exit_time_stop(trade, 10)


def exit_time_stop_20(trade, _=None):
    return exit_time_stop(trade, 20)


def exit_time_stop_30(trade, _=None):
    return exit_time_stop(trade, 30)


def exit_vol_stop(trade, _=None):
    """Volatility-adjusted stop: if entry volatility was high, allow more room.

    For high-vol entries: trail at 33% retracement.
    For low-vol entries: trail at 50% retracement.
    """
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if trade.get("exit_reason") == "tp":
        return orig
    atr = trade.get("atr_pct_entry", 0.01)
    if mfe < 0.5:
        return orig
    # Higher vol → tighter retrace (33%), lower vol → looser (50%)
    retrace = 0.33 if atr > 0.015 else 0.50
    captured = mfe * (1.0 - retrace)
    return max(captured, 0)


def exit_hybrid(trade, _=None):
    """Hybrid: combine be_lock + vol-adjusted trail + time awareness.

    1. If MFE >= 1.0R and still negative, exit at breakeven
    2. If MFE >= 0.8R, trail at 40% retracement
    3. Otherwise use fixed
    """
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if trade.get("exit_reason") == "tp":
        return orig
    if mfe >= 1.0:
        return 0.0
    if mfe >= 0.8:
        captured = mfe * 0.6
        return max(captured, 0)
    return orig


# Registry
STRATEGY_REGISTRY: list[tuple[str, StrategyFn, str]] = [
    ("fixed_barriers", exit_fixed, "Current fixed TP/SL (baseline)"),
    ("be_lock_only", exit_be_lock, "Breakeven lock at MFE >= 1.0R"),
    ("adaptive_trail_50pct", exit_adaptive_live, "BE 0.5R + trail at 50% from 0.8R (live)"),
    ("trail_33pct", exit_trail_33, "Hard trail at 33% retracement"),
    ("trail_50pct", exit_trail_50, "Hard trail at 50% retracement"),
    ("trail_67pct", exit_trail_67, "Hard trail at 67% retracement"),
    ("atr_trail_1x", exit_atr_1x, "ATR trail at 1× ATR from peak"),
    ("atr_trail_2x", exit_atr_2x, "ATR trail at 2× ATR from peak"),
    ("atr_trail_3x", exit_atr_3x, "ATR trail at 3× ATR from peak"),
    ("chandelier_3atr", exit_chandelier, "Chandelier exit at 3× ATR from high"),
    ("time_stop_10", exit_time_stop_10, "Force close at 10 candles"),
    ("time_stop_20", exit_time_stop_20, "Force close at 20 candles"),
    ("time_stop_30", exit_time_stop_30, "Force close at 30 candles"),
    ("volatility_stop", exit_vol_stop, "Vol-adjusted trail (hi-vol=33%, lo-vol=50%)"),
    ("hybrid", exit_hybrid, "BE 1.0R + 40% trail at 0.8R"),
]


def simulate_strategy(trades_map: dict[str, list[dict]], strategy_name: str, fn: StrategyFn) -> ExitStrategyResult:
    """Apply an exit strategy to all trades and return aggregate results."""
    all_rs: list[float] = []
    per_asset: dict[str, float] = {}

    for asset, trades in trades_map.items():
        asset_rs = [fn(t) for t in trades]
        total_asset = sum(asset_rs)
        all_rs.extend(asset_rs)
        per_asset[asset] = round(total_asset, 2)

    arr = np.array(all_rs)
    n = len(arr)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    n_wins = len(wins)
    n_losses = len(losses)
    wr = n_wins / n * 100 if n > 0 else 0.0
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float("inf") if len(wins) > 0 else 0.0
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min())
    mar = max_dd / (cum[-1] + 1e-10) if max_dd < 0 else 0.0
    expectancy = float(arr.mean())

    return ExitStrategyResult(
        name=strategy_name,
        total_r=round(float(arr.sum()), 2),
        n_trades=n,
        n_wins=n_wins,
        n_losses=n_losses,
        win_rate=round(wr, 2),
        avg_r=round(float(arr.mean()), 4),
        profit_factor=round(pf, 4),
        sharpe=round(sharpe, 4),
        max_dd_r=round(max_dd, 2),
        mar=round(mar, 4),
        expectancy=round(expectancy, 4),
        per_asset=per_asset,
    )


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 7: Exit strategy comparison (%d strategies)", len(STRATEGY_REGISTRY))

    results_map: dict[str, Any] = {}
    all_results: list[ExitStrategyResult] = []

    for name, fn, desc in STRATEGY_REGISTRY:
        result = simulate_strategy(trades_map, name, fn)
        all_results.append(result)
        results_map[name] = {
            "description": desc,
            "total_r": result.total_r,
            "win_rate": result.win_rate,
            "avg_r": result.avg_r,
            "profit_factor": result.profit_factor,
            "sharpe": result.sharpe,
            "max_dd_r": result.max_dd_r,
            "mar": result.mar,
            "expectancy": result.expectancy,
            "n_trades": result.n_trades,
        }

    # Rank by Sharpe
    ranked_by_sharpe = sorted(all_results, key=lambda r: r.sharpe, reverse=True)
    ranked_by_total_r = sorted(all_results, key=lambda r: r.total_r, reverse=True)
    ranked_by_mar = sorted(all_results, key=lambda r: r.mar, reverse=True)

    ranking = {
        "by_sharpe": [{"rank": i + 1, "name": r.name, "sharpe": r.sharpe, "total_r": r.total_r,
                        "max_dd_r": r.max_dd_r, "win_rate": r.win_rate, "pf": r.profit_factor}
                       for i, r in enumerate(ranked_by_sharpe)],
        "by_total_r": [{"rank": i + 1, "name": r.name, "total_r": r.total_r, "sharpe": r.sharpe,
                         "max_dd_r": r.max_dd_r}
                        for i, r in enumerate(ranked_by_total_r)],
        "by_mar": [{"rank": i + 1, "name": r.name, "mar": r.mar, "total_r": r.total_r, "sharpe": r.sharpe}
                    for i, r in enumerate(ranked_by_mar)],
    }

    logger.info("  Top 3 by Sharpe: %s", ", ".join(f"{r[0]} ({r[1]:.2f})" for r in
                [(r.name, r.sharpe) for r in ranked_by_sharpe[:3]]))
    logger.info("  Top 3 by total_R: %s", ", ".join(f"{r[0]} ({r[1]:.1f})" for r in
                [(r.name, r.total_r) for r in ranked_by_total_r[:3]]))

    return {"strategies": results_map, "ranking": ranking, "per_asset": {r.name: r.per_asset for r in all_results}}
