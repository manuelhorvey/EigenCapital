#!/usr/bin/env python3
"""
Circuit breaker Monte Carlo calibration — bootstraps daily portfolio returns
from walk-forward OOS signal parquets to estimate consecutive-loss-streak
distribution, simulate breaker logic, and produce a threshold sensitivity
table for max_consecutive_losses.

Shares the block-bootstrap core with monte_carlo_drawdown.py but tracks
loss-streak time series per simulation path instead of just drawdown
aggregates.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/circuit_breaker_sim.py
    PYTHONPATH=$PYTHONPATH:. python scripts/circuit_breaker_sim.py --n-sim 100000 --output cb_results.json

CAVEAT (read before interpreting results):
    This simulation is calibrated against a 14-month bull market sample
    (Oct 2024 - May 2026).  The block bootstrap cannot synthesise a crisis
    unlike anything in the 280-day sample.  Any threshold recommendation
    below is conditional on the next 12 months resembling the last 14.

    The breaker's real test is a regime it has never seen, not the one it
    is being calibrated against.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("circuit_breaker_sim")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF", "AUDUSD", "ES", "NQ", "NZDCHF",
        "EURAUD", "^DJI", "USDCHF", "EURCHF",
        "NZDUSD", "EURNZD",
    }
)

# ── Data loading (shared with monte_carlo_drawdown) ────────────────────────


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def compute_r(signal: int, label: int, tp: float, sl: float) -> float:
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


def load_daily_portfolio_returns(sell_only: bool = True) -> pd.Series:
    """Load all signal parquets and compute daily equal-weighted portfolio
    return (mean R-multiple across all assets with active signals)."""
    files = sorted(Path(WALKDIR).glob("*_wf_signals.parquet"))
    if not files:
        raise FileNotFoundError(f"No signal parquets found in {WALKDIR}")

    pt_sl = load_pt_sl()

    asset_dfs: dict[str, pd.DataFrame] = {}
    for fpath in files:
        name = fpath.stem.replace("_wf_signals", "")
        df = pd.read_parquet(fpath)
        asset_dfs[name] = df

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


# ── Loss-streak-aware Monte Carlo ──────────────────────────────────────────


def _streaks_from_returns(returns: np.ndarray) -> np.ndarray:
    """Return the consecutive-loss-streak time series.

    streak[t] = number of consecutive negative returns ending at t
    (resets to 0 on any non-negative return).
    """
    streaks = np.zeros(len(returns), dtype=int)
    current = 0
    for i, r in enumerate(returns):
        if r < 0:
            current += 1
        else:
            current = 0
        streaks[i] = current
    return streaks


def simulate_paths(
    daily_returns: np.ndarray,
    n_simulations: int = 10_000,
    horizons_days: list[int] | None = None,
    block_size: int = 10,
    seed: int = 42,
) -> dict[int, list[dict]]:
    """Block-bootstrap simulation that tracks loss-streak time series.

    For each path stores:
        - total_r
        - max_dd_r
        - max_streak (longest consecutive loss run)
        - daily_returns (the resampled return sequence, needed for breaker replay)
        - equity curve
        - drawdown curve
        - streak time series

    Returns dict[horizon_days, list[path_dict]].
    """
    if horizons_days is None:
        horizons_days = [252, 756, 1260]

    rng = np.random.default_rng(seed)
    n_obs = len(daily_returns)
    n_blocks_total = n_obs - block_size + 1

    results: dict[int, list[dict]] = {h: [] for h in horizons_days}

    logger.info(
        "Running %d simulations across %d horizons (block_size=%d)...",
        n_simulations, len(horizons_days), block_size,
    )
    t0 = time.monotonic()

    for sim_idx in range(n_simulations):
        if sim_idx > 0 and sim_idx % 2000 == 0:
            elapsed = time.monotonic() - t0
            rate = sim_idx / elapsed
            eta = (n_simulations - sim_idx) / rate
            logger.info("  %d/%d simulations (%.1f/s, ETA %.0fs)", sim_idx, n_simulations, rate, eta)

        for h in horizons_days:
            n_blocks_needed = int(np.ceil(h / block_size))
            n_total = n_blocks_needed * block_size
            sampled = np.empty(n_total, dtype=daily_returns.dtype)

            for b in range(n_blocks_needed):
                start = rng.integers(0, n_blocks_total)
                sampled[b * block_size: (b + 1) * block_size] = daily_returns[start: start + block_size]

            returns = sampled[:h]
            equity = np.cumsum(returns)
            peak = np.maximum.accumulate(equity)
            dd = equity - peak
            streaks = _streaks_from_returns(returns)

            results[h].append(
                {
                    "daily_returns": returns,
                    "equity": equity,
                    "drawdown": dd,
                    "streaks": streaks,
                    "total_r": float(np.sum(returns)),
                    "max_dd_r": float(np.min(dd)),
                    "max_streak": int(np.max(streaks)),
                }
            )

    elapsed = time.monotonic() - t0
    logger.info("Done — %d simulations in %.1fs (%.1f/s)", n_simulations, elapsed, n_simulations / elapsed)
    return results


# ── Breaker replay ─────────────────────────────────────────────────────────


def breaker_replay(
    path: dict,
    thresholds: list[int],
    max_drawdown_pct: float = 0.25,
    vol_spike_threshold: float = 3.0,
    baseline_vol: float | None = None,
) -> dict:
    """Simulate the live CircuitBreaker.check() logic on a single path.

    Checks three conditions (halt_ratio skipped — can't simulate actor state):
        1. Drawdown > max_drawdown_pct  (using equity as value proxy)
        2. Vol spike > baseline_vol * vol_spike_threshold
        3. Consecutive loss streak >= threshold

    Returns dict with keys:
        - tripped_any: bool
        - first_condition: str | None
        - first_day: int | None
        - conditions: dict mapping condition name -> (day, value) when it tripped
    """
    returns = path["daily_returns"]
    equity = path["equity"]
    streaks = path["streaks"]

    n = len(returns)

    # Track first trip day per condition
    first_trip: dict[str, tuple[int, float]] = {}

    # 1. Drawdown (in % terms, using equity relative to peak)
    #    We need a peak-initial-value for percentage calculation.
    #    Since R-multiples are additive from 0, treat initial "value" as
    #    the first non-zero equity level to avoid divide-by-zero.
    equity_offset = equity + abs(equity.min()) + 1.0 if equity.min() < 0 else equity + 1.0
    peak_offset = np.maximum.accumulate(equity_offset)
    dd_pct = (equity_offset - peak_offset) / peak_offset

    for t in range(n):
        if dd_pct[t] <= -max_drawdown_pct:
            first_trip["drawdown"] = (t, float(dd_pct[t]))
            break

    # 2. Vol spike: rolling 10-day vol vs baseline
    if baseline_vol is not None and baseline_vol > 0:
        for t in range(20, n):
            window = returns[t - 20: t]
            rolling_vol = float(np.std(window))
            if rolling_vol >= baseline_vol * vol_spike_threshold:
                first_trip["vol_spike"] = (t, rolling_vol / baseline_vol if baseline_vol else 0.0)
                break

    # 3. Consecutive loss streak (per threshold)
    #    Record the first threshold that trips and which threshold value
    for threshold in thresholds:
        for t in range(n):
            if streaks[t] >= threshold:
                first_trip[f"streak_{threshold}"] = (t, float(streaks[t]))
                break

    # Determine first overall condition
    tripped_any = len(first_trip) > 0
    first_condition: str | None = None
    first_day: int | None = None

    if tripped_any:
        first_condition = min(first_trip, key=lambda k: first_trip[k][0])
        first_day = first_trip[first_condition][0]

    return {
        "tripped_any": tripped_any,
        "first_condition": first_condition,
        "first_day": first_day,
        "conditions": first_trip,
    }


def replay_all(
    results: dict[int, list[dict]],
    thresholds: list[int],
    baseline_vol: float | None = None,
) -> dict:
    """Run breaker_replay across all paths and aggregate."""
    replay: dict[int, list[dict]] = {}
    for h, paths in results.items():
        horizon_replay = []
        for p in paths:
            decision = breaker_replay(p, thresholds, baseline_vol=baseline_vol)
            horizon_replay.append(decision)
        replay[h] = horizon_replay
    return replay


# ── Analysis ───────────────────────────────────────────────────────────────


def compute_cdf(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Return sorted values and their CDF positions."""
    sorted_v = np.sort(values)
    p = np.arange(1, len(sorted_v) + 1) / len(sorted_v)
    return sorted_v, p


def analyze_streak_distribution(
    results: dict[int, list[dict]],
) -> dict:
    """Compute per-horizon streak distribution summary."""
    summary: dict = {}
    for h, paths in results.items():
        streaks = [p["max_streak"] for p in paths]
        streaks_arr = np.array(streaks)

        # CDF of max streak
        streak_vals, streak_cdf = compute_cdf(streaks)

        # Tail probabilities for thresholds 3-15
        tail_probs = {}
        for t in range(3, 16):
            tail_probs[f"P(streak≥{t})"] = float(np.mean(streaks_arr >= t))

        # Also compute P(streak == k) for KDE
        unique, counts = np.unique(streaks_arr, return_counts=True)
        pmf = {int(k): int(c) for k, c in zip(unique, counts)}

        # Max streak percentiles
        p50 = int(np.percentile(streaks_arr, 50))
        p90 = int(np.percentile(streaks_arr, 90))
        p95 = int(np.percentile(streaks_arr, 95))
        p99 = int(np.percentile(streaks_arr, 99))

        summary[h] = {
            "horizon_days": h,
            "n_simulations": len(paths),
            "max_streak_p50": p50,
            "max_streak_p90": p90,
            "max_streak_p95": p95,
            "max_streak_p99": p99,
            "max_streak_max": int(streaks_arr.max()),
            "max_streak_mean": float(np.mean(streaks_arr)),
            "tail_probs": tail_probs,
            "pmf": pmf,
        }
    return summary


def analyze_breaker_replay(
    replay: dict[int, list[dict]],
    results: dict[int, list[dict]],
    thresholds: list[int],
) -> dict:
    """Aggregate breaker replay results."""
    agg: dict = {}
    for h, decisions in replay.items():
        paths = results[h]
        n = len(decisions)

        # Which condition trips first?
        condition_counts: dict[str, int] = {}
        for d in decisions:
            if d["first_condition"]:
                # Normalize streak_X to just "streak" for aggregation
                cond = d["first_condition"]
                if cond.startswith("streak_"):
                    cond = "streak"
                condition_counts[cond] = condition_counts.get(cond, 0) + 1

        # Per-threshold
        threshold_metrics: dict[int, dict] = {}
        for th in thresholds:
            key = f"streak_{th}"
            tripped = [d for d in decisions if key in d.get("conditions", {})]
            p_trip = len(tripped) / n if n > 0 else 0.0

            # False positive: tripped by this threshold but total_R > 0
            false_positives = [
                (t, p)
                for t, p in zip(tripped, paths)
                if key in t.get("conditions", {}) and p["total_r"] > 0
            ]
            fp_rate = len(false_positives) / len(tripped) if tripped else 0.0

            # Of those that trip, what's the median drawdown?
            dd_at_trip = []
            for d, p in zip(tripped, paths):
                if key in d["conditions"]:
                    day = d["conditions"][key][0]
                    if day < len(p["drawdown"]):
                        dd_at_trip.append(p["drawdown"][day])
            median_dd = float(np.median(dd_at_trip)) if dd_at_trip else 0.0

            # Recovered? (total_R > 0 at horizon end after tripping)
            recovered = [
                p for t, p in zip(tripped, paths)
                if key in t.get("conditions", {}) and p["total_r"] > 0
            ]
            recovery_rate = len(recovered) / len(tripped) if tripped else 0.0

            threshold_metrics[th] = {
                "p_trip": round(p_trip, 4),
                "n_trip": len(tripped),
                "false_positive_rate": round(fp_rate, 4),
                "median_dd_at_trip_r": round(median_dd, 2),
                "recovery_rate": round(recovery_rate, 4),
            }

        agg[h] = {
            "horizon_days": h,
            "n_simulations": n,
            "first_condition_counts": condition_counts,
            "threshold_metrics": threshold_metrics,
        }
    return agg


def make_threshold_recommendation(
    streak_summary: dict,
    breaker_agg: dict,
    n_empirical_days: int,
) -> tuple[str, int]:
    """Generate the threshold recommendation with dual-conditional caveat.

    The recommendation is the LAST thing in the report, not a clean number
    stated up top.
    """
    # Pick the 1-year horizon for the recommendation
    h = 252
    if h not in streak_summary:
        h = min(streak_summary.keys())

    s = streak_summary.get(h, {})
    b = breaker_agg.get(h, {})

    if not s or not b:
        return "Insufficient data for recommendation.", 7

    tail = s.get("tail_probs", {})
    tm = b.get("threshold_metrics", {})

    # Find the lowest threshold where false_positive_rate < 10%
    # and P(trip) is in a useful range (5-50%)
    best_th = 7
    for th in sorted(tm.keys()):
        metrics = tm[th]
        p_trip = metrics.get("p_trip", 0.0)
        fp = metrics.get("false_positive_rate", 0.0)
        if 0.03 <= p_trip <= 0.50 and fp < 0.10:
            best_th = th
            break

    p_streak_ge_best = tail.get(f"P(streak≥{best_th})", "N/A")
    fp_best = tm.get(best_th, {}).get("false_positive_rate", "N/A")

    lines: list[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("THRESHOLD RECOMMENDATION")
    lines.append("=" * 72)
    lines.append("")
    lines.append(
        f"  Recommended max_consecutive_losses: {best_th}"
    )
    lines.append(
        f"  (Assuming the next 12 months resemble the last {n_empirical_days} trading days.)"
    )
    lines.append("")
    lines.append("  At this threshold (1-year horizon):")
    lines.append(f"    P(streak ≥ {best_th}):          {p_streak_ge_best}")
    lines.append(f"    False positive rate:             {fp_best}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  CAVEAT (MUST READ BEFORE ACTING ON THIS NUMBER)")
    lines.append("")
    lines.append(
        "  This recommendation is conditional on the calibration window "
        f"(Oct 2024 - May 2026, {n_empirical_days} trading days, a bull market "
        "for risk assets)."
    )
    lines.append("")
    lines.append(
        "  The block bootstrap cannot synthesise a crisis unlike anything "
        "in the 280-day sample.  A threshold calibrated to fire at the right "
        "percentile of a calm-market distribution may fire too early, too late, "
        "or at the wrong severity level during a genuine regime break."
    )
    lines.append("")
    lines.append(
        "  The breaker's real test is a regime it has never seen, not the one "
        "it is being calibrated against."
    )
    lines.append("")
    lines.append("  WHEN TO REVISIT THIS NUMBER:")
    lines.append(
        "  Re-run this simulation after 6 months of additional live data "
        "are available, or immediately if a portfolio-level drawdown "
        "exceeding -10R occurs in live trading, whichever comes first."
    )
    lines.append("")
    lines.append(
        "  Until then, treat this as a baseline calibration from a "
        "non-stress sample — better than uncalibrated, but not trustworthy "
        "as a permanent answer."
    )
    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines), best_th


# ── Report ─────────────────────────────────────────────────────────────────


def format_report(
    n_empirical_days: int,
    empirical_stats: dict,
    streak_summary: dict,
    breaker_agg: dict,
    thresholds: list[int],
) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CIRCUIT BREAKER MONTE CARLO CALIBRATION")
    lines.append("=" * 72)
    lines.append("SELL_ONLY filter active: True (11 of 18 assets)")
    lines.append(f"Empirical window: {n_empirical_days} trading days (Oct 2024 - May 2026)")
    lines.append("Block bootstrap: 10-day blocks, 10,000 simulations")
    lines.append("")
    lines.append(f"Empirical portfolio: total_R={empirical_stats['total_r']:.2f}  "
                 f"max_dd={empirical_stats['max_dd']:.2f}R  "
                 f"max_streak={empirical_stats['max_streak']}  "
                 f"sharpe={empirical_stats['sharpe']:.2f}")
    lines.append("")

    for h in sorted(streak_summary.keys()):
        s = streak_summary[h]
        b = breaker_agg[h]
        year_label = f"{h // 252}y" if h % 252 == 0 else f"{h}d"

        lines.append("-" * 72)
        lines.append(f"Horizon: {year_label} ({h} trading days, {s['n_simulations']:,} sims)")
        lines.append("")
        lines.append("  ── Max consecutive loss streak distribution ──")
        lines.append(f"    Mean:          {s['max_streak_mean']:.1f}")
        lines.append(f"    P50:           {s['max_streak_p50']}")
        lines.append(f"    P90:           {s['max_streak_p90']}")
        lines.append(f"    P95:           {s['max_streak_p95']}")
        lines.append(f"    P99:           {s['max_streak_p99']}")
        lines.append(f"    Max observed:  {s['max_streak_max']}")
        lines.append("")
        lines.append("  ── Tail probabilities ──")
        tail = s["tail_probs"]
        for t in sorted(thresholds + [10, 12, 15]):
            key = f"P(streak≥{t})"
            if key in tail:
                lines.append(f"    P(streak ≥ {t:>2d}):  {tail[key]:>7.1%}")
        lines.append("")
        lines.append("  ── First condition to trip ──")
        fc = b["first_condition_counts"]
        total = sum(fc.values())
        for cond, count in sorted(fc.items(), key=lambda x: -x[1]):
            pct = count / total * 100 if total > 0 else 0.0
            lines.append(f"    {cond:>20s}:  {count:>6d} ({pct:>5.1f}%)")
        lines.append("")
        lines.append("  ── Threshold sensitivity table ──")
        lines.append(f"  {'Threshold':>10s}  {'P(trip)':>8s}  {'N(trip)':>8s}  "
                     f"{'FP rate':>8s}  {'Recov rate':>10s}  {'Med DD@trip':>12s}")
        lines.append(f"  {'-' * 10}  {'-' * 8}  {'-' * 8}  {'-' * 8}  "
                     f"{'-' * 10}  {'-' * 12}")
        for th in sorted(b["threshold_metrics"].keys()):
            m = b["threshold_metrics"][th]
            lines.append(
                f"  {th:>10d}  {m['p_trip']:>7.1%}  {m['n_trip']:>8d}  "
                f"{m['false_positive_rate']:>7.1%}  {m['recovery_rate']:>9.1%}  "
                f"{m['median_dd_at_trip_r']:>8.2f}R"
            )
        lines.append("")

    # Full CDF for the 1-year horizon
    if 252 in streak_summary:
        s = streak_summary[252]
        pmf = s["pmf"]
        lines.append("  ── Max streak PMF (1-year horizon) ──")
        lines.append(f"  {'Streak':>8s}  {'Count':>8s}  {'Pct':>6s}")
        lines.append(f"  {'-' * 8}  {'-' * 8}  {'-' * 6}")
        for k in sorted(pmf.keys()):
            pct = pmf[k] / s["n_simulations"] * 100
            lines.append(f"  {k:>8d}  {pmf[k]:>8d}  {pct:>5.1f}%")
        lines.append("")

    lines.append("=" * 72)
    lines.append("NOTE: R-multiples are NOT currency. 1R = ATR * sl_mult per asset.")
    lines.append("Drawdowns are in R-units, not % of capital.")
    lines.append("=" * 72)

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Circuit breaker Monte Carlo calibration from walk-forward OOS data"
    )
    parser.add_argument(
        "--n-sim", type=int, default=10_000,
        help="Number of simulations (default: 10,000)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Path to save JSON results (optional)",
    )
    args = parser.parse_args()

    logger.info("Loading daily portfolio returns...")
    daily_returns = load_daily_portfolio_returns(sell_only=True)
    n_days = len(daily_returns)
    logger.info("Loaded %d daily returns (%.4f ± %.4f)", n_days, daily_returns.mean(), daily_returns.std())

    # Empirical stats
    emp_equity = np.cumsum(daily_returns.values)
    emp_peak = np.maximum.accumulate(emp_equity)
    emp_dd = emp_equity - emp_peak
    emp_streaks = _streaks_from_returns(daily_returns.values)
    emp_sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0.0

    empirical_stats = {
        "total_r": round(float(daily_returns.sum()), 2),
        "max_dd": round(float(emp_dd.min()), 2),
        "max_streak": int(emp_streaks.max()),
        "sharpe": round(emp_sharpe, 2),
    }

    thresholds = [3, 5, 7, 10]

    results = simulate_paths(
        daily_returns=daily_returns.values,
        n_simulations=args.n_sim,
        horizons_days=[252, 756, 1260],
    )

    # Baseline vol (for vol spike check)
    baseline_vol = float(daily_returns.std())

    logger.info("Analyzing streak distribution...")
    streak_summary = analyze_streak_distribution(results)

    logger.info("Running breaker replay...")
    replayed = replay_all(results, thresholds, baseline_vol=baseline_vol)
    breaker_agg = analyze_breaker_replay(replayed, results, thresholds)

    report = format_report(
        n_empirical_days=n_days,
        empirical_stats=empirical_stats,
        streak_summary=streak_summary,
        breaker_agg=breaker_agg,
        thresholds=thresholds,
    )
    print(report)

    recommendation_text, best_th = make_threshold_recommendation(streak_summary, breaker_agg, n_days)
    print(recommendation_text)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(
                {
                    "n_simulations": args.n_sim,
                    "n_empirical_days": n_days,
                    "empirical_stats": empirical_stats,
                    "streak_summary": {str(k): v for k, v in streak_summary.items()},
                    "breaker_agg": {str(k): v for k, v in breaker_agg.items()},
                    "thresholds": thresholds,
                    "recommendation": best_th,
                },
                f,
                indent=2,
            )
        logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
