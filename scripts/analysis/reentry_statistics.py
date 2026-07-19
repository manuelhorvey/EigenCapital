#!/usr/bin/env python3
"""
Re-entry Statistical Validation Suite.

Bootstrap resampling, Monte Carlo simulation, regime analysis,
and sensitivity sweeps for the re-entry policy comparison.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_statistics.py
"""

import json
import logging
import os
from pathlib import Path
import sys
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

sys.path.insert(0, os.path.join(Path(__file__).resolve().parent, "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reentry_statistics")

R_FREE = 0.0


def _deflated_sharpe_ratio(
    sharpe: float,
    n: int,
    num_trials: int = 1,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Compute Deflated Sharpe Ratio (DSR) for a given Sharpe."""
    from scipy.stats import norm

    if n < 2:
        return 0.0
    var_sharpe = (1 + 0.5 * kurt * sharpe**2 - skew * sharpe) / (n - 1)
    e_max_sigma = np.sqrt(var_sharpe) * (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / num_trials) + np.euler_gamma * norm.ppf(1 - 1.0 / (num_trials * np.e))
    )
    dsr_num = sharpe - e_max_sigma
    dsr_den = np.sqrt(1 + var_sharpe)
    if dsr_den <= 0:
        return 0.0
    z = dsr_num / dsr_den
    if z > 8.2:
        return 1.0
    if z < -8.2:
        return 0.0
    return float(norm.cdf(z))


def _probabilistic_sharpe_ratio(sharpe: float, n: int) -> float:
    """Compute Probabilistic Sharpe Ratio (PSR)."""
    from scipy.stats import norm

    if n < 2:
        return 0.0
    sr_sharpe = (1 + 0.5 * sharpe**2) / (n - 1)
    if sr_sharpe <= 0:
        return 0.0
    z = sharpe / np.sqrt(sr_sharpe)
    if z > 8.2:
        return 1.0
    if z < -8.2:
        return 0.0
    return float(norm.cdf(z))


def load_results(path: str = "/tmp/reentry_full_results.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _daily_r_series(policy_trades: dict[str, list[dict]]) -> np.ndarray:
    """Build daily R series from per-asset trade list."""
    daily_map: dict[str, float] = {}
    for asset, trades in policy_trades.items():
        for t in trades:
            date = str(t.get("entry_date", "")).split(" ")[0]
            daily_map[date] = daily_map.get(date, 0.0) + t.get("r_multiple", 0.0)
    if not daily_map:
        return np.array([0.0])
    return np.array([v for _, v in sorted(daily_map.items())])


def bootstrap_delta(
    r_a: np.ndarray,
    r_b: np.ndarray,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap the difference in Sharpe between two policies."""
    rng = np.random.default_rng(seed)
    n = len(r_a)
    delta_sharpes = np.zeros(n_resamples)
    delta_rs = np.zeros(n_resamples)

    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        bs_a = r_a[idx]
        bs_b = r_b[idx]

        sharpe_a = np.mean(bs_a) / max(np.std(bs_a, ddof=1), 1e-10)
        sharpe_b = np.mean(bs_b) / max(np.std(bs_b, ddof=1), 1e-10)
        delta_sharpes[i] = sharpe_b - sharpe_a
        delta_rs[i] = np.sum(bs_b) - np.sum(bs_a)

    pct_improve = float(np.mean(delta_sharpes > 0) * 100)
    return {
        "delta_sharpe_mean": float(np.mean(delta_sharpes)),
        "delta_sharpe_std": float(np.std(delta_sharpes, ddof=1)),
        "delta_sharpe_ci_95": [float(np.percentile(delta_sharpes, 2.5)), float(np.percentile(delta_sharpes, 97.5))],
        "pct_improve": pct_improve,
        "p_value_improve": 1.0 - pct_improve / 100.0,
        "delta_r_mean": float(np.mean(delta_rs)),
        "delta_r_ci_95": [float(np.percentile(delta_rs, 2.5)), float(np.percentile(delta_rs, 97.5))],
        "pct_r_improve": float(np.mean(delta_rs > 0) * 100),
        "n_resamples": n_resamples,
    }


def monte_carlo_equity(
    daily_r: np.ndarray,
    n_sims: int = 5_000,
    horizon_days: int = 252,
    seed: int = 42,
) -> dict[str, Any]:
    """Monte Carlo equity curve simulation with bootstrap resampling."""
    rng = np.random.default_rng(seed)
    final_equities = np.zeros(n_sims)
    max_dds = np.zeros(n_sims)

    for i in range(n_sims):
        idx = rng.integers(0, len(daily_r), size=horizon_days)
        path = np.cumsum(daily_r[idx])
        final_equities[i] = path[-1]
        peak = np.maximum.accumulate(path)
        dd = peak - path
        max_dds[i] = np.max(dd)

    p_positive = float(np.mean(final_equities > 0) * 100)
    return {
        "n_sims": n_sims,
        "horizon_days": horizon_days,
        "p_positive": p_positive,
        "mean_final_r": float(np.mean(final_equities)),
        "median_final_r": float(np.median(final_equities)),
        "final_r_ci_95": [float(np.percentile(final_equities, 2.5)), float(np.percentile(final_equities, 97.5))],
        "mean_max_dd": float(np.mean(max_dds)),
        "max_dd_ci_95": [float(np.percentile(max_dds, 2.5)), float(np.percentile(max_dds, 97.5))],
        "worst_max_dd": float(np.max(max_dds)),
    }


def regime_analysis(
    results: dict,
    r_a: np.ndarray,
    r_b: np.ndarray,
) -> dict[str, Any]:
    """Compare policy performance across volatility regimes."""
    regimes: dict[str, Any] = {}
    daily_a = r_a
    daily_b = r_b

    vol = pd.Series(np.abs(daily_a)).rolling(21, min_periods=5).mean().dropna().values
    if len(vol) < 10:
        return {"error": "insufficient data for regime analysis"}
    median_vol = np.median(vol)

    low_vol_mask = vol <= median_vol
    high_vol_mask = vol > median_vol

    n_low = min(len(daily_a[-len(vol) :][low_vol_mask]), len(daily_b[-len(vol) :][low_vol_mask]))
    n_high = min(len(daily_a[-len(vol) :][high_vol_mask]), len(daily_b[-len(vol) :][high_vol_mask]))

    for regime_name, mask in [("low_vol", low_vol_mask), ("high_vol", high_vol_mask)]:
        a_vals = daily_a[-len(mask) :][mask]
        b_vals = daily_b[-len(mask) :][mask]
        if len(a_vals) < 5:
            regimes[regime_name] = {"n_periods": 0, "error": "too few periods"}
            continue
        regimes[regime_name] = {
            "n_periods": int(len(a_vals)),
            "a_total_r": float(np.sum(a_vals)),
            "b_total_r": float(np.sum(b_vals)),
            "delta_r": float(np.sum(b_vals) - np.sum(a_vals)),
            "a_sharpe": float(np.mean(a_vals) / max(np.std(a_vals, ddof=1), 1e-10)),
            "b_sharpe": float(np.mean(b_vals) / max(np.std(b_vals, ddof=1), 1e-10)),
            "delta_sharpe": float(
                np.mean(b_vals) / max(np.std(b_vals, ddof=1), 1e-10)
                - np.mean(a_vals) / max(np.std(a_vals, ddof=1), 1e-10)
            ),
        }

    return regimes


def sensitivity_sweep(
    results: dict,
) -> dict[str, Any]:
    """Analyze re-entry policy sensitivity across asset sub-groups."""
    policies = ["A", "B", "C"]
    per_asset: dict[str, list[dict]] = {p: [] for p in policies}

    max_positions_data: dict[int, list[float]] = {}

    for p_name in policies:
        pol = results["policies"][p_name]
        for asset, trades in pol["trades"].items():
            total_r = sum(t.get("r_multiple", 0.0) for t in trades)
            n_trades = len(trades)
            per_asset[p_name].append({"asset": asset, "total_r": total_r, "n_trades": n_trades})

    degrade_count = 0
    degrade_assets = []
    improve_assets = []
    for asset_entry_a in per_asset["A"]:
        asset = asset_entry_a["asset"]
        r_a = asset_entry_a["total_r"]

        entry_b = next((e for e in per_asset["B"] if e["asset"] == asset), None)
        r_b = entry_b["total_r"] if entry_b else r_a
        delta_r = r_b - r_a

        if delta_r < -2.0:
            degrade_count += 1
            degrade_assets.append({"asset": asset, "total_r_a": r_a, "total_r_b": r_b, "delta_r": delta_r})
        elif delta_r > 2.0:
            improve_assets.append({"asset": asset, "total_r_a": r_a, "total_r_b": r_b, "delta_r": delta_r})

    return {
        "degrade_threshold_r": -2.0,
        "improve_threshold_r": 2.0,
        "n_degrade_assets": degrade_count,
        "degrade_assets": sorted(degrade_assets, key=lambda x: x["delta_r"]),
        "n_improve_assets": len(improve_assets),
        "improve_assets": sorted(improve_assets, key=lambda x: x["delta_r"], reverse=True),
    }


def max_positions_sweep(
    results: dict,
) -> dict[str, Any]:
    """Compare performance across max_positions=1,2,3."""
    policies = ["A", "B", "C"]
    max_pos_map: dict[str, int] = {"A": 1, "B": 2, "C": 3}
    sweep = {}
    for p_name in policies:
        pol = results["policies"][p_name]
        trades_list = []
        for asset, trades in pol["trades"].items():
            trades_list.extend(trades)
        total_r = sum(t.get("r_multiple", 0.0) for t in trades_list)
        n_trades = len(trades_list)
        daily = _daily_r_series(pol["trades"])
        sharpe = float(np.mean(daily) / max(np.std(daily, ddof=1), 1e-10))
        max_dd = _compute_max_dd(daily)
        calmar = sharpe / max(max_dd, 1e-10) * 252
        sweep[p_name] = {
            "max_positions": max_pos_map[p_name],
            "total_r": round(total_r, 2),
            "n_trades": n_trades,
            "sharpe": round(sharpe, 4),
            "max_dd_r": round(max_dd, 2),
            "calmar": round(calmar, 3),
        }
    return sweep


def _compute_max_dd(daily_r: np.ndarray) -> float:
    if len(daily_r) == 0:
        return 0.0
    cum = np.cumsum(daily_r)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(np.max(dd))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Re-entry statistical validation")
    parser.add_argument("--input", default="/tmp/reentry_full_results.json")
    parser.add_argument("--output", default="/tmp/reentry_statistics.json")
    parser.add_argument("--n-bootstrap", type=int, default=10_000)
    parser.add_argument("--n-monte-carlo", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logger.info("Loading results from %s", args.input)
    data = load_results(args.input)

    r_a = _daily_r_series(data["policies"]["A"]["trades"])
    r_b = _daily_r_series(data["policies"]["B"]["trades"])
    r_c = _daily_r_series(data["policies"]["C"]["trades"])

    metrics: dict[str, Any] = {
        "config": {
            "n_bootstrap": args.n_bootstrap,
            "n_monte_carlo": args.n_monte_carlo,
            "seed": args.seed,
            "timestamp": str(pd.Timestamp.now()),
        },
    }

    # Bootstrap
    logger.info("Running bootstrap (%d resamples)...", args.n_bootstrap)
    metrics["bootstrap"] = {
        "A_vs_B": bootstrap_delta(r_a, r_b, args.n_bootstrap, args.seed),
        "A_vs_C": bootstrap_delta(r_a, r_c, args.n_bootstrap, args.seed + 1),
        "B_vs_C": bootstrap_delta(r_b, r_c, args.n_bootstrap, args.seed + 2),
    }

    # Monte Carlo
    logger.info("Running Monte Carlo (%d sims)...", args.n_monte_carlo)
    metrics["monte_carlo"] = {
        "Policy_A": monte_carlo_equity(r_a, args.n_monte_carlo, seed=args.seed),
        "Policy_B": monte_carlo_equity(r_b, args.n_monte_carlo, seed=args.seed + 1),
        "Policy_C": monte_carlo_equity(r_c, args.n_monte_carlo, seed=args.seed + 2),
    }

    # Regime analysis
    logger.info("Running regime analysis...")
    metrics["regime"] = regime_analysis(data, r_a, r_b)

    # Sensitivity sweep
    logger.info("Running sensitivity sweep...")
    metrics["sensitivity"] = sensitivity_sweep(data)
    metrics["max_positions_sweep"] = max_positions_sweep(data)

    # Write output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(metrics, f, indent=2, cls=EigenCapitalJSONEncoder)
        logger.info("Results saved to %s", args.output)

    # Print summary
    bs = metrics["bootstrap"]
    print("\n" + "=" * 70)
    print("RE-ENTRY STATISTICAL VALIDATION")
    print("=" * 70)

    print("\n--- Bootstrap: Sharpe Improvement (A vs B) ---")
    b = bs["A_vs_B"]
    print(f"  ΔSharpe mean: {b['delta_sharpe_mean']:+.5f}")
    print(f"  ΔSharpe 95% CI: [{b['delta_sharpe_ci_95'][0]:+.5f}, {b['delta_sharpe_ci_95'][1]:+.5f}]")
    print(f"  P(ΔSharpe > 0): {b['pct_improve']:.1f}%")
    print(f"  ΔR mean: {b['delta_r_mean']:+.1f}")
    print(f"  ΔR 95% CI: [{b['delta_r_ci_95'][0]:+.1f}, {b['delta_r_ci_95'][1]:+.1f}]")

    print("\n--- Bootstrap: Sharpe Improvement (A vs C) ---")
    b = bs["A_vs_C"]
    print(f"  ΔSharpe mean: {b['delta_sharpe_mean']:+.5f}")
    print(f"  P(ΔSharpe > 0): {b['pct_improve']:.1f}%")

    print("\n--- Monte Carlo: 1-Year Equity Projection ---")
    for p_name in ["Policy_A", "Policy_B", "Policy_C"]:
        mc = metrics["monte_carlo"][p_name]
        print(
            f"  {p_name}: P(positive)={mc['p_positive']:.1f}%, mean_final={mc['mean_final_r']:+.1f}R, "
            f"95% CI=[{mc['final_r_ci_95'][0]:+.1f}, {mc['final_r_ci_95'][1]:+.1f}], "
            f"mean_max_dd={mc['mean_max_dd']:.1f}R"
        )

    print("\n--- Regime Analysis ---")
    for regime_name, reg in metrics.get("regime", {}).items():
        if isinstance(reg, dict) and "error" not in reg:
            print(f"  {regime_name}: ΔR={reg.get('delta_r', 0):+.1f}, ΔSharpe={reg.get('delta_sharpe', 0):+.4f}")

    print("\n--- Sensitivity: Degrading Assets ---")
    sens = metrics["sensitivity"]
    for entry in sens.get("degrade_assets", []):
        print(f"  {entry['asset']}: ΔR={entry['delta_r']:+.1f} ({entry['total_r_a']:+.1f}→{entry['total_r_b']:+.1f})")
    print(
        f"  Total degrading: {sens['n_degrade_assets']} / {sens['n_degrade_assets'] + sens['n_improve_assets']} assets"
    )

    print("\n--- Max Positions Sweep ---")
    for p_name in ["A", "B", "C"]:
        s = metrics["max_positions_sweep"][p_name]
        print(
            f"  {p_name} (max={s['max_positions']}): total_R={s['total_r']:+.1f}, "
            f"trades={s['n_trades']}, Sharpe={s['sharpe']:.4f}, max_dd={s['max_dd_r']:.1f}R"
        )

    return metrics


if __name__ == "__main__":
    main()
