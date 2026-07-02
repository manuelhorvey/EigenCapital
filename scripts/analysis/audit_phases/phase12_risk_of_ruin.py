"""Phase 12 — Risk of Ruin Analysis.

Monte Carlo simulation from the actual trade sequence:
  - Estimates daily DD breach probability
  - Overall DD breach probability (% capital)
  - Worst losing streak
  - Capital survival at 95/99% confidence
  - Confidence intervals on cumulative return
"""

from __future__ import annotations

import logging
import random
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase12_ruin")

N_SIMULATIONS = 10_000
N_DAYS = 252 * 3  # 3 years
DD_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.30]  # 5%, 10%, 15%, 20%, 30%


def _atr_to_return_pct(r: float, atr_pct: float) -> float:
    """Convert an R-multiple to portfolio % return using ATR."""
    return r * atr_pct


def run(trades_map: dict[str, list[dict]], initial_capital: float = 100_000.0) -> dict[str, Any]:
    logger.info("Phase 12: Risk of ruin (%d sims × %d days)", N_SIMULATIONS, N_DAYS)

    # Build a pool of daily returns from actual trade sequence
    daily_returns: list[float] = []
    for asset, trades in trades_map.items():
        for t in trades:
            r = t.get("r_multiple", 0.0)
            atr = t.get("atr_pct_entry", 0.01)
            pct_ret = _atr_to_return_pct(r, atr)
            daily_returns.append(pct_ret)

    if not daily_returns:
        return {"error": "no trade returns available"}

    daily_returns = np.array(daily_returns)

    # IID Bootstrap
    capital_results = []
    max_drawdowns = []
    max_losing_streaks = []
    ruin_probabilities = {f"dd_{int(t * 100)}pct": 0 for t in DD_THRESHOLDS}

    rng = random.Random(42)

    for sim in range(N_SIMULATIONS):
        capital = initial_capital
        peak = capital
        sim_max_dd = 0.0
        losing_streak = 0
        max_losing = 0
        equity_curve = [capital]

        for day in range(N_DAYS):
            ret = float(rng.choice(daily_returns))
            capital *= (1 + ret)
            equity_curve.append(capital)

            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            sim_max_dd = max(sim_max_dd, dd)

            if ret < 0:
                losing_streak += 1
                max_losing = max(max_losing, losing_streak)
            else:
                losing_streak = 0

        capital_results.append(capital)
        max_drawdowns.append(sim_max_dd)
        max_losing_streaks.append(max_losing)

        for thresh in DD_THRESHOLDS:
            if sim_max_dd >= thresh:
                ruin_probabilities[f"dd_{int(thresh * 100)}pct"] += 1

    # Convert to probabilities
    for k in ruin_probabilities:
        ruin_probabilities[k] = round(ruin_probabilities[k] / N_SIMULATIONS * 100, 2)

    cap_arr = np.array(capital_results)
    dd_arr = np.array(max_drawdowns)

    return {
        "simulation_params": {
            "n_simulations": N_SIMULATIONS,
            "n_days": N_DAYS,
            "initial_capital": initial_capital,
        },
        "capital_outcomes": {
            "median": round(float(np.median(cap_arr)), 0),
            "mean": round(float(np.mean(cap_arr)), 0),
            "p5": round(float(np.percentile(cap_arr, 5)), 0),
            "p25": round(float(np.percentile(cap_arr, 25)), 0),
            "p75": round(float(np.percentile(cap_arr, 75)), 0),
            "p95": round(float(np.percentile(cap_arr, 95)), 0),
            "pct_gain": round((cap_arr > initial_capital).mean() * 100, 1),
        },
        "drawdown_risk": {
            "median_max_dd_pct": round(float(np.median(dd_arr)) * 100, 2),
            "p95_max_dd_pct": round(float(np.percentile(dd_arr, 95)) * 100, 2),
            "p99_max_dd_pct": round(float(np.percentile(dd_arr, 99)) * 100, 2),
            "worst_max_dd_pct": round(float(dd_arr.max()) * 100, 2),
        },
        "ruin_probability": ruin_probabilities,
        "losing_streaks": {
            "median": int(np.median(max_losing_streaks)),
            "p95": int(np.percentile(max_losing_streaks, 95)),
            "worst": int(np.max(max_losing_streaks)),
        },
        "verdict": _verdict(ruin_probabilities),
    }


def _verdict(ruin: dict[str, float]) -> str:
    if ruin.get("dd_30pct", 0) > 5:
        return "HIGH_RISK"
    elif ruin.get("dd_20pct", 0) > 10:
        return "MODERATE_RISK"
    elif ruin.get("dd_15pct", 0) > 5:
        return "LOW_RISK"
    else:
        return "LOW_RISK"
