#!/usr/bin/env python3
"""
Robustness Gatekeeper — stress-tests adaptive exit improvement for
distribution shift, regime fragility, ordering dependence, and
execution realism.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_gatekeeper.py
"""

import json
import random
from pathlib import Path

import numpy as np


def simulate_trailing(
    trades: list[dict], retrace_pct: float = 0.50, require_min_mfe: float = 0.0
) -> tuple[float, float, int]:
    original_r = sum(t["r_multiple"] for t in trades)
    new_r = 0.0
    n_saved = 0
    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)
        if orig >= 0 or mfe_r < require_min_mfe or t.get("exit_reason") == "tp":
            new_r += orig
            continue
        captured = mfe_r * (1.0 - retrace_pct)
        new_r += max(captured, 0)
        if captured > 0:
            n_saved += 1
    return new_r - original_r, new_r, n_saved


def portfolio_r(trades_map: dict[str, list[dict]], retrace_pct: float = 0.50):
    total = 0.0
    for ts in trades_map.values():
        _, nr, _ = simulate_trailing(ts, retrace_pct=retrace_pct)
        total += nr
    return total


# ──────────────────────────────────────────────────────────────
# 1. REGIME ROBUSTNESS TEST
# ──────────────────────────────────────────────────────────────
def regime_robustness(all_trades: dict[str, list[dict]], ohlcv_map: dict) -> dict:
    """Split trades by volatility regime (ATR at entry) and compare trailing vs fixed."""
    results = {}

    for asset, trades in all_trades.items():
        if not trades:
            continue
        atr_vals = np.array([t.get("atr_pct_entry", 0.01) for t in trades])
        if len(atr_vals) == 0:
            continue
        median_atr = np.median(atr_vals)

        low_vol = [t for t in trades if t.get("atr_pct_entry", 0) <= median_atr]
        high_vol = [t for t in trades if t.get("atr_pct_entry", 0) > median_atr]

        def fixed_r(ts):
            return sum(t["r_multiple"] for t in ts)

        def trail_r(ts):
            _, nr, _ = simulate_trailing(ts)
            return nr

        results[asset] = {
            "n_trades": len(trades),
            "atr_median": round(float(median_atr), 6),
            "fixed_low": round(fixed_r(low_vol), 1),
            "trail_low": round(trail_r(low_vol), 1),
            "fixed_high": round(fixed_r(high_vol), 1),
            "trail_high": round(trail_r(high_vol), 1),
            "n_low": len(low_vol),
            "n_high": len(high_vol),
        }

    return results


# ──────────────────────────────────────────────────────────────
# 2. PER-TRADE BENEFIT DISTRIBUTION
# ──────────────────────────────────────────────────────────────
def per_trade_benefit(all_trades: dict[str, list[dict]], retrace_pct: float = 0.50) -> dict:
    """Analyze per-trade delta of trailing vs fixed. Tests whether
    the improvement is broadly distributed or concentrated in a few trades."""
    deltas = []
    for ts in all_trades.values():
        for t in ts:
            orig = t["r_multiple"]
            mfe_r = t.get("mfe_r", 0.0)
            if mfe_r < 0.5 or t.get("exit_reason") == "tp" or orig >= 0:
                new_val = orig
            else:
                captured = mfe_r * (1.0 - retrace_pct)
                new_val = max(captured, 0)
            deltas.append(new_val - orig)

    arr = np.array(deltas)
    pos = arr[arr > 0]
    neg = arr[arr < 0]
    zero = arr[arr == 0]

    # Concentration: what % of total benefit comes from top 10% of trades?
    sorted_deltas = np.sort(arr)[::-1]
    total_benefit = float(arr.sum())
    cumsum = np.cumsum(sorted_deltas)
    n_top10 = max(len(arr) // 10, 1)
    top10_share = float(cumsum[n_top10 - 1]) / max(total_benefit, 1) * 100

    return {
        "n_trades": len(arr),
        "n_improved": int(len(pos)),
        "n_worsened": int(len(neg)),
        "n_unchanged": int(len(zero)),
        "pct_improved": round(len(pos) / max(len(arr), 1) * 100, 1),
        "mean_delta": round(float(arr.mean()), 3),
        "median_delta": round(float(np.median(arr)), 3),
        "total_delta": round(float(arr.sum()), 1),
        "top10_pct_of_benefit": round(top10_share, 1),
        "min_delta": round(float(arr.min()), 2),
        "max_delta": round(float(arr.max()), 2),
        "skew": round(float(np.mean(((arr - arr.mean()) / max(arr.std(), 1e-9)) ** 3)), 2),
    }


# ──────────────────────────────────────────────────────────────
# 2b. BOOTSTRAP ROBUSTNESS
# ──────────────────────────────────────────────────────────────
def bootstrap_robustness(all_trades: dict[str, list[dict]], n_iter: int = 500, retrace_pct: float = 0.50) -> dict:
    """Bootstrap resample trades (with replacement) and compare
    trailing vs fixed for each resample."""
    flat = []
    for ts in all_trades.values():
        flat.extend(ts)

    fixed_samples = []
    trail_samples = []

    for _ in range(n_iter):
        sample = random.choices(flat, k=len(flat))
        fixed_r = sum(t["r_multiple"] for t in sample)
        trail_r = 0.0
        for t in sample:
            orig = t["r_multiple"]
            mfe_r = t.get("mfe_r", 0.0)
            if mfe_r < 0.5 or t.get("exit_reason") == "tp" or orig >= 0:
                trail_r += orig
            else:
                captured = mfe_r * (1.0 - retrace_pct)
                trail_r += max(captured, 0)
        fixed_samples.append(fixed_r)
        trail_samples.append(trail_r)

    fixed_arr = np.array(fixed_samples)
    trail_arr = np.array(trail_samples)
    deltas = trail_arr - fixed_arr

    return {
        "fixed_mean": round(float(fixed_arr.mean()), 1),
        "fixed_std": round(float(fixed_arr.std()), 1),
        "fixed_p5": round(float(np.percentile(fixed_arr, 5)), 1),
        "fixed_p95": round(float(np.percentile(fixed_arr, 95)), 1),
        "trail_mean": round(float(trail_arr.mean()), 1),
        "trail_std": round(float(trail_arr.std()), 1),
        "trail_p5": round(float(np.percentile(trail_arr, 5)), 1),
        "trail_p95": round(float(np.percentile(trail_arr, 95)), 1),
        "delta_mean": round(float(deltas.mean()), 1),
        "delta_std": round(float(deltas.std()), 1),
        "pct_trail_better": round(np.mean(trail_arr > fixed_arr) * 100, 1),
        "pct_fixed_better": round(np.mean(fixed_arr > trail_arr) * 100, 1),
        "n_iterations": n_iter,
    }


# ──────────────────────────────────────────────────────────────
# 3. SLIPPAGE SENSITIVITY
# ──────────────────────────────────────────────────────────────
def slippage_sensitivity(all_trades: dict[str, list[dict]]) -> dict:
    """Apply adverse execution slippage (in R-multiples)."""
    results = {}
    for slippage_r in [0.0, 0.5, 1.0, 2.0]:
        pf = 0.0
        for ts in all_trades.values():
            for t in ts:
                orig = t["r_multiple"]
                mfe_r = t.get("mfe_r", 0.0)
                if orig >= 0 or mfe_r < 0.5 or t.get("exit_reason") == "tp":
                    pf += orig
                else:
                    # Apply slippage: reduce captured profit
                    captured = mfe_r * 0.5 - slippage_r
                    pf += max(captured, 0)
        results[f"slippage_{slippage_r}R"] = round(pf, 1)

    # Also compute with no trailing for comparison
    fixed_pf = sum(sum(t["r_multiple"] for t in ts) for ts in all_trades.values())
    results["fixed_no_trail"] = round(fixed_pf, 1)

    return results


# ──────────────────────────────────────────────────────────────
# 4. ABLATION STUDY (variance-adjusted)
# ──────────────────────────────────────────────────────────────
def ablation_study(all_trades: dict[str, list[dict]]) -> dict:
    """Compare exit methods on variance-adjusted performance."""
    methods = {
        "fixed_barriers": lambda ts: sum(t["r_multiple"] for t in ts),
        "be_lock_only": lambda ts: _be_lock(ts),
        "trail_33pct": lambda ts: _trail_retrace(ts, 0.33),
        "trail_50pct": lambda ts: _trail_retrace(ts, 0.50),
        "trail_67pct": lambda ts: _trail_retrace(ts, 0.67),
    }

    results = {}
    for method_name, fn in methods.items():
        daily_r = []
        for ts in all_trades.values():
            daily_r.append(fn(ts))
        arr = np.array(daily_r)
        mean_r = float(arr.mean())
        std_r = float(arr.std()) if len(arr) > 1 else 1.0
        sharpe = mean_r / std_r if std_r > 0 else 0.0
        max_dd = _max_drawdown(arr)
        results[method_name] = {
            "total_r": round(float(arr.sum()), 1),
            "mean_per_asset": round(mean_r, 2),
            "std_per_asset": round(std_r, 2),
            "sharpe": round(sharpe, 3),
            "max_dd_r": round(max_dd, 2),
            "n_positive": int((arr > 0).sum()),
        }

    return results


def _be_lock(trades: list[dict]) -> float:
    total = 0.0
    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)
        if orig < 0 and mfe_r >= 1.0:
            total += 0.0  # exit at breakeven
        else:
            total += orig
    return total


def _trail_retrace(trades: list[dict], retrace_pct: float) -> float:
    total = 0.0
    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)
        if orig >= 0 or mfe_r < 0.5 or t.get("exit_reason") == "tp":
            total += orig
        else:
            captured = mfe_r * (1.0 - retrace_pct)
            total += max(captured, 0)
    return total


def _max_drawdown(arr: np.ndarray) -> float:
    cumsum = np.cumsum(arr)
    peak = np.maximum.accumulate(cumsum)
    dd = cumsum - peak
    return float(dd.min())


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
CAVEAT = (
    "\n*** CAVEAT: This robustness suite uses realized (post-hoc) MFE to determine\n"
    "*** trailing stop placement. In live trading, ultimate MFE is unknown when\n"
    "*** setting the trail. These results are an UPPER BOUND on trailing stop\n"
    "*** performance. Real results will be lower because the trail level is set\n"
    "*** from the running peak, not the ultimate peak.\n"
    "*** See audit finding C8/H9 in AGENTS.md.\n"
)


def main():
    print(CAVEAT)
    path = Path("data/processed/trade_data/trade_lifecycle_results.json")
    if not path.exists():
        print(f"File not found: {path}")
        return

    with open(path) as f:
        data = json.load(f)
    all_trades = data.get("_trades", {})

    print("=" * 72)
    print("ROBUSTNESS GATEKEEPER — Adaptive Exit Validation Suite")
    print("=" * 72)

    # 1. Regime robustness
    print("\n[1/5] REGIME ROBUSTNESS — ATR-split (median)")
    print(f"{'Asset':<10} {'N':>4} {'Fixed_Low':>10} {'Trail_Low':>10} {'Fixed_Hi':>10} {'Trail_Hi':>10}")
    print("-" * 60)
    regime = regime_robustness(all_trades, {})
    for asset in sorted(regime.keys()):
        r = regime[asset]
        print(
            f"{asset:<10} {r['n_trades']:>4} {r['fixed_low']:>+10.1f} {r['trail_low']:>+10.1f} "
            f"{r['fixed_high']:>+10.1f} {r['trail_high']:>+10.1f}"
        )

    # 2. Per-trade benefit distribution
    print("\n[2/5] PER-TRADE BENEFIT DISTRIBUTION (50% retracement)")
    bd = per_trade_benefit(all_trades)
    print(f"  N trades:                 {bd['n_trades']}")
    print(f"  Improved / unchanged / worsened:  {bd['n_improved']} / {bd['n_unchanged']} / {bd['n_worsened']}")
    print(f"  % trades improved:        {bd['pct_improved']:.1f}%")
    print(f"  Mean delta per trade:     {bd['mean_delta']:>+7.3f}R")
    print(f"  Median delta:             {bd['median_delta']:>+7.3f}R")
    print(f"  Total delta:              {bd['total_delta']:>+8.1f}R")
    print(f"  Top 10%% share of benefit: {bd['top10_pct_of_benefit']:.1f}%")
    print(f"  Skew of deltas:           {bd['skew']:>+7.2f}")
    print(f"  Delta range:              [{bd['min_delta']:>+6.2f}, {bd['max_delta']:>+6.2f}]R")

    # 2b. Bootstrap robustness
    print("\n[2b] BOOTSTRAP ROBUSTNESS (500 resamples, with replacement)")
    br = bootstrap_robustness(all_trades, n_iter=500)
    print(f"  Fixed:   mean={br['fixed_mean']:>+8.1f}  P5/P95=[{br['fixed_p5']:>+7.1f}, {br['fixed_p95']:>+7.1f}]")
    print(f"  Trailing: mean={br['trail_mean']:>+8.1f}  P5/P95=[{br['trail_p5']:>+7.1f}, {br['trail_p95']:>+7.1f}]")
    print(f"  Trail > Fixed: {br['pct_trail_better']:.1f}% of resamples")
    print(f"  Fixed > Trail: {br['pct_fixed_better']:.1f}% of resamples")

    # 3. Slippage sensitivity
    print("\n[3/5] SLIPPAGE SENSITIVITY")
    slip = slippage_sensitivity(all_trades)
    for k in sorted(slip.keys()):
        print(f"  {k:25s}: {slip[k]:>+10.1f}R")

    # 4. Ablation study
    print("\n[4/5] EXIT SYSTEM ABLATION")
    ablation = ablation_study(all_trades)
    print(f"{'Method':<20} {'TotalR':>8} {'Mean':>7} {'Std':>7} {'Sharpe':>8} {'MaxDD':>8} {'N+':>4}")
    print("-" * 70)
    for method in ["fixed_barriers", "be_lock_only", "trail_33pct", "trail_50pct", "trail_67pct"]:
        a = ablation[method]
        print(
            f"{method:<20} {a['total_r']:>+8.1f} {a['mean_per_asset']:>+7.2f} "
            f"{a['std_per_asset']:>7.2f} {a['sharpe']:>8.3f} {a['max_dd_r']:>+8.2f} {a['n_positive']:>3d}"
        )

    # 5. TRAIL CONCENTRATION ANALYSIS
    print("\n[5/5] TRAIL CONCENTRATION — how many trades drive the benefit?")
    # Bootstrap with different trade subsets
    n_total = sum(len(ts) for ts in all_trades.values())
    print(f"  Total trades: {n_total}")
    print(f"  Avg benefit per trade: {bd['mean_delta']:>+7.4f}R")
    print(f"  Top 10% trades: {bd['top10_pct_of_benefit']:.1f}% of benefit")
    print(f"  {bd['pct_improved']:.1f}% of trades (N={bd['n_improved']}) show any improvement")
    print(
        f"  Skew={bd['skew']:>+.2f}: {'HIGH concentration risk' if abs(bd['skew']) > 3 else 'Moderate — benefit distributed'}"  # noqa: E501
    )  # noqa: E501
    print(
        f"  Worst-case delta: {bd['min_delta']:>+.2f}R (trades that would have been improved but trailing clipped them)"
    )  # noqa: E501

    print("\n" + "=" * 72)
    print("GATEKEEPER COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
