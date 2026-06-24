#!/usr/bin/env python3
"""
Monte Carlo drawdown simulation — bootstraps daily portfolio returns from
walk-forward OOS signal parquets to estimate drawdown risk over
1-year, 3-year, and 5-year horizons.

Uses block bootstrap (entire days sampled together) to preserve the
cross-asset correlation structure.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/monte_carlo_drawdown.py
    PYTHONPATH=$PYTHONPATH:. python scripts/monte_carlo_drawdown.py --n-sim 50000 --output mc_results.json
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("monte_carlo")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "AUDUSD",
        "ES",
        "NQ",
        "NZDCHF",
        "EURAUD",
        "^DJI",
        "USDCHF",
        "EURCHF",
        "NZDUSD",
        "EURNZD",
    }
)

SELL_ONLY_ACTIVE = True

# ── Core R computation (same as backtest) ────────────────────────────────


def compute_r(signal: int, label: int, tp: float, sl: float) -> float:
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


# ── Load data ────────────────────────────────────────────────────────────


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def load_daily_portfolio_returns(
    sell_only: bool = True,
) -> pd.Series:
    """Load all signal parquets and compute daily equal-weighted portfolio
    return (mean R-multiple across all assets with active signals).

    Returns a Series indexed by date with daily portfolio return.
    """
    pattern = os.path.join(WALKDIR, "*_wf_signals.parquet")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No signal parquets found in {WALKDIR}")

    pt_sl = load_pt_sl()

    # Load all assets
    asset_dfs: dict[str, pd.DataFrame] = {}
    for fpath in files:
        name = os.path.basename(fpath).replace("_wf_signals.parquet", "")
        df = pd.read_parquet(fpath)
        asset_dfs[name] = df

    # Compute daily portfolio return
    all_dates = sorted(set(d for df in asset_dfs.values() for d in df.index))
    daily_rs: list[float] = []

    for d in all_dates:
        day_rs: list[float] = []
        for name, df in asset_dfs.items():
            if d not in df.index:
                continue
            row = df.loc[d]
            sig = int(row["signal"])
            if sell_only and name in SELL_ONLY_ASSETS and sig == 1:
                sig = 0
            if sig == 0:
                continue
            lbl = int(row["label"])
            tp, sl = pt_sl.get(name, (2.0, 2.0))
            r = compute_r(sig, lbl, tp, sl)
            day_rs.append(r)

        daily_rs.append(float(np.mean(day_rs)) if day_rs else 0.0)

    return pd.Series(daily_rs, index=pd.DatetimeIndex(all_dates))


# ── Monte Carlo simulation ───────────────────────────────────────────────


def simulate_equity_curves(
    daily_returns: np.ndarray,
    n_simulations: int = 10_000,
    horizons_days: list[int] | None = None,
    block_size: int = 10,
    seed: int = 42,
) -> dict:
    """Run Monte Carlo simulation using block bootstrap.

    Samples blocks of consecutive days (block_size) to preserve temporal
    dependence (e.g., clusters of consecutive loss days). Within each
    horizon, draws N/block_size blocks with replacement.

    Returns a dict of horizon -> list of (total_return, max_drawdown, n_up_days).
    """
    if horizons_days is None:
        horizons_days = [252, 756, 1260]

    rng = np.random.default_rng(seed)
    n_obs = len(daily_returns)
    n_blocks_total = n_obs - block_size + 1

    results: dict[int, list[dict]] = {}
    for h in horizons_days:
        results[h] = []

    logger.info(
        "Running %d simulations across %d horizons (block_size=%d)...", n_simulations, len(horizons_days), block_size
    )
    t0 = time.monotonic()

    for sim_idx in range(n_simulations):
        if sim_idx > 0 and sim_idx % 2000 == 0:
            elapsed = time.monotonic() - t0
            rate = sim_idx / elapsed
            eta = (n_simulations - sim_idx) / rate
            logger.info("  %d/%d simulations (%.1f/s, ETA %.0fs)", sim_idx, n_simulations, rate, eta)

        for h in horizons_days:
            # Block bootstrap: sample blocks of consecutive days with replacement
            n_blocks_needed = int(np.ceil(h / block_size))
            n_total = n_blocks_needed * block_size
            sampled = np.empty(n_total, dtype=daily_returns.dtype)

            for b in range(n_blocks_needed):
                start = rng.integers(0, n_blocks_total)
                sampled[b * block_size : (b + 1) * block_size] = daily_returns[start : start + block_size]

            sampled_returns = sampled[:h]

            # R-multiples are additive, not multiplicative.
            # Equity = cumulative sum of R, peak = running max.
            # Drawdown in R-units = equity - peak (negative = below peak).
            equity = np.cumsum(sampled_returns)
            peak = np.maximum.accumulate(equity)
            drawdown = equity - peak

            total_r = float(np.sum(sampled_returns))
            max_dd = float(np.min(drawdown))
            n_up = int(np.sum(sampled_returns > 0))

            results[h].append(
                {
                    "total_r": total_r,
                    "max_dd": max_dd,
                    "n_up": n_up,
                    "n_total": h,
                }
            )

    elapsed = time.monotonic() - t0
    logger.info("Done — %d simulations in %.1fs (%.1f/s)", n_simulations, elapsed, n_simulations / elapsed)

    return results


# ── Analysis ─────────────────────────────────────────────────────────────


def compute_dd_var(values: list[float], percentile: float) -> float:
    """Compute Value at Risk at given percentile (e.g. 0.05 for 95% VaR)."""
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * percentile)
    return sorted_v[idx]


def analyze_results(results: dict[int, list[dict]]) -> dict:
    """Compute summary statistics for each horizon."""
    summary: dict = {}
    for horizon, sims in results.items():
        dd_values = [s["max_dd"] for s in sims]
        tr_values = [s["total_r"] for s in sims]
        up_ratios = [s["n_up"] / s["n_total"] for s in sims]

        year_label = f"{horizon // 252}y" if horizon % 252 == 0 else f"{horizon}d"
        summary[year_label] = {
            "horizon_days": horizon,
            "n_simulations": len(sims),
            "expected_total_r": round(float(np.mean(tr_values)), 2),
            "median_total_r": round(float(np.median(tr_values)), 2),
            "std_total_r": round(float(np.std(tr_values)), 2),
            "expected_max_dd": round(float(np.mean(dd_values)), 4),
            "median_max_dd": round(float(np.median(dd_values)), 4),
            "std_max_dd": round(float(np.std(dd_values)), 4),
            "var_95_dd": round(compute_dd_var(dd_values, 0.05), 4),
            "var_99_dd": round(compute_dd_var(dd_values, 0.01), 4),
            "worst_dd": round(float(np.min(dd_values)), 4),
            "best_dd": round(float(np.max(dd_values)), 4),
            "p_dd_lt_minus_5r": round(float(np.mean([v < -5.0 for v in dd_values])), 4),
            "p_dd_lt_minus_10r": round(float(np.mean([v < -10.0 for v in dd_values])), 4),
            "p_dd_lt_minus_20r": round(float(np.mean([v < -20.0 for v in dd_values])), 4),
            "p_dd_lt_minus_50r": round(float(np.mean([v < -50.0 for v in dd_values])), 4),
            "p_positive_return": round(float(np.mean([v > 0 for v in tr_values])), 4),
            "expected_up_ratio": round(float(np.mean(up_ratios)), 4),
        }

    return summary


# ── Report ───────────────────────────────────────────────────────────────


def format_report(summary: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("MONTE CARLO DRAWDOWN SIMULATION")
    lines.append("=" * 72)
    lines.append(f"SELL_ONLY filter active: {SELL_ONLY_ACTIVE}")
    lines.append("Assets: 18 (11 SELL_ONLY, 7 full)")
    lines.append("")

    for label in sorted(summary.keys()):
        s = summary[label]
        lines.append("-" * 72)
        lines.append(f"Horizon: {label} ({s['horizon_days']} trading days)")
        lines.append(f"Simulations: {s['n_simulations']:,}")
        lines.append("")
        lines.append("  ── Return ──")
        lines.append(f"  Expected total R:   {s['expected_total_r']:>8.2f}")
        lines.append(f"  Median total R:     {s['median_total_r']:>8.2f}")
        lines.append(f"  Std total R:        {s['std_total_r']:>8.2f}")
        lines.append(f"  P(positive return): {s['p_positive_return']:>7.1%}")
        lines.append("")
        lines.append("  ── Drawdown ──")
        lines.append(f"  Expected max DD:    {s['expected_max_dd']:>8.2f}R")
        lines.append(f"  Median max DD:      {s['median_max_dd']:>8.2f}R")
        lines.append(f"  95% VaR of DD:      {s['var_95_dd']:>8.2f}R  (5% chance of worse)")
        lines.append(f"  99% VaR of DD:      {s['var_99_dd']:>8.2f}R  (1% chance of worse)")
        lines.append(f"  Worst DD observed:  {s['worst_dd']:>8.2f}R")
        lines.append("")
        lines.append("  ── Tail probabilities ──")
        lines.append(f"  P(DD < -5R):  {s['p_dd_lt_minus_5r']:>7.1%}")
        lines.append(f"  P(DD < -10R): {s['p_dd_lt_minus_10r']:>7.1%}")
        lines.append(f"  P(DD < -20R): {s['p_dd_lt_minus_20r']:>7.1%}")
        lines.append(f"  P(DD < -50R): {s['p_dd_lt_minus_50r']:>7.1%}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("NOTE: R-multiples are NOT currency. 1R = ATR * sl_mult per asset.")
    lines.append("Drawdowns are in R-units, not % of capital.")
    lines.append("=" * 72)
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo drawdown simulation from walk-forward OOS data")
    parser.add_argument("--n-sim", type=int, default=10_000, help="Number of simulations (default: 10,000)")
    parser.add_argument("--output", default=None, help="Path to save JSON results (optional)")
    parser.add_argument("--no-sell-only", action="store_true", help="Disable SELL_ONLY filter for comparison")

    args = parser.parse_args()

    global SELL_ONLY_ACTIVE
    SELL_ONLY_ACTIVE = not args.no_sell_only

    logger.info("Loading daily portfolio returns...")
    daily_returns = load_daily_portfolio_returns(sell_only=SELL_ONLY_ACTIVE)
    logger.info("Loaded %d daily returns (%.4f ± %.4f)", len(daily_returns), daily_returns.mean(), daily_returns.std())

    # Print empirical stats (R-multiples are additive)
    emp_equity = np.cumsum(daily_returns.values)
    emp_peak = np.maximum.accumulate(emp_equity)
    emp_dd = emp_equity - emp_peak
    emp_sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0
    logger.info(
        "Empirical portfolio: total_R=%.2f  max_dd=%.2fR  Sharpe=%.2f", daily_returns.sum(), emp_dd.min(), emp_sharpe
    )

    results = simulate_equity_curves(
        daily_returns=daily_returns.values,
        n_simulations=args.n_sim,
        horizons_days=[252, 756, 1260],
    )

    summary = analyze_results(results)
    report = format_report(summary)
    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(
                {
                    "sell_only_active": SELL_ONLY_ACTIVE,
                    "n_simulations": args.n_sim,
                    "n_empirical_days": len(daily_returns),
                    "empirical_total_r": round(float(daily_returns.sum()), 2),
                    "empirical_max_dd": round(float(emp_dd.min()), 4),
                    "summary": summary,
                },
                f,
                indent=2,
            )
        logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
