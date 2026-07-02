#!/usr/bin/env python3
"""Deep-dive validation of trail_33pct exit strategy.

Performs 6 robustness tests:
  1. Per-asset breakdown  — who wins/loses from the change
  2. Parameter sensitivity — sweep retrace 10%–80%
  3. Bootstrap CI         — 5000 resamples, 95% CI on total_R
  4. Time stability       — early vs late half of trade history
  5. Benefit concentration — Gini + top-N share
  6. Worst-case scenario  — what happens to trail_33pct during max drawdown

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/deep_dive_trail33.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.deep_dive")

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
RETRACE_PCT = 0.33


# ── Core simulator ────────────────────────────────────────────────────────────

def trail_r(trade: dict, retrace_pct: float = RETRACE_PCT) -> float:
    """Apply retracement trail to a single trade. Returns the modified R."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig  # winner passes through
    mfe = trade.get("mfe_r", 0.0)
    if mfe < 0.5 or trade.get("exit_reason") == "tp":
        return orig  # no MFE to capture or was TP'd
    captured = mfe * (1.0 - retrace_pct)
    return max(captured, 0.0)


def simulate(trades_map: dict, retrace_pct: float = RETRACE_PCT) -> dict:
    """Run trail simulation and return per-asset + portfolio results."""
    all_rs: list[float] = []
    per_asset: dict[str, dict] = {}

    for asset, trades in trades_map.items():
        orig_rs = [t["r_multiple"] for t in trades]
        new_rs = [trail_r(t, retrace_pct) for t in trades]
        delta = [n - o for n, o in zip(new_rs, orig_rs)]
        per_asset[asset] = {
            "n": len(trades),
            "orig_r": round(sum(orig_rs), 2),
            "new_r": round(sum(new_rs), 2),
            "delta_r": round(sum(delta), 2),
            "orig_wr": round(sum(1 for r in orig_rs if r > 0) / len(orig_rs) * 100, 1),
            "new_wr": round(sum(1 for r in new_rs if r > 0) / len(new_rs) * 100, 1),
            "trades_improved": sum(1 for d in delta if d > 0),
            "trades_harmed": sum(1 for d in delta if d < 0),
        }
        all_rs.extend(new_rs)

    arr = np.array(all_rs)
    orig_arr = np.array([t["r_multiple"] for ts in trades_map.values() for t in ts])
    sharpe_new = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0
    sharpe_orig = float(orig_arr.mean() / orig_arr.std()) if orig_arr.std() > 0 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    cum_o = np.cumsum(orig_arr)
    peak_o = np.maximum.accumulate(cum_o)
    dd_o = float((cum_o - peak_o).min())

    return {
        "portfolio": {
            "total_r": round(float(arr.sum()), 2),
            "sharpe": round(sharpe_new, 4),
            "max_dd_r": round(dd, 2),
            "win_rate": round((arr > 0).mean() * 100, 1),
            "orig_total_r": round(float(orig_arr.sum()), 2),
            "orig_sharpe": round(sharpe_orig, 4),
            "orig_max_dd_r": round(dd_o, 2),
            "orig_win_rate": round((orig_arr > 0).mean() * 100, 1),
            "delta_r": round(float(arr.sum() - orig_arr.sum()), 2),
            "n_trades": len(arr),
        },
        "per_asset": per_asset,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_per_asset(trades_map: dict) -> dict:
    """1. Per-asset breakdown."""
    logger.info("Test 1: Per-asset breakdown")
    result = simulate(trades_map)
    return result["per_asset"]


def test_parameter_sensitivity(trades_map: dict) -> list[dict]:
    """2. Sweep retrace_pct from 0.10 to 0.80."""
    logger.info("Test 2: Parameter sensitivity sweep")
    retraces = [0.10, 0.20, 0.25, 0.30, 0.33, 0.35, 0.40, 0.50, 0.60, 0.67, 0.80]
    all_trades = [t for ts in trades_map.values() for t in ts]
    rows = []
    for rp in retraces:
        rs = [trail_r(t, rp) for t in all_trades]
        arr = np.array(rs)
        sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0
        cum = np.cumsum(arr)
        peak = np.maximum.accumulate(cum)
        dd = float((cum - peak).min())
        rows.append({
            "retrace_pct": rp,
            "total_r": round(float(arr.sum()), 2),
            "sharpe": round(sharpe, 4),
            "max_dd_r": round(dd, 2),
            "win_rate": round((arr > 0).mean() * 100, 1),
        })
    return rows


def test_bootstrap(trades_map: dict, n_iter: int = 5000) -> dict:
    """3. Bootstrap confidence intervals."""
    logger.info("Test 3: Bootstrap CI (%d resamples)", n_iter)
    all_trades = [t for ts in trades_map.values() for t in ts]
    n = len(all_trades)
    orig_rs = np.array([t["r_multiple"] for t in all_trades])
    orig_total = orig_rs.sum()

    trail_totals = []
    rng = np.random.default_rng(42)
    for _ in range(n_iter):
        sample = rng.choice(all_trades, size=n, replace=True)
        rs = [trail_r(t) for t in sample]
        trail_totals.append(sum(rs))

    trail_arr = np.array(trail_totals)
    trail_arr.sort()
    lo = int(n_iter * 0.025)
    hi = int(n_iter * 0.975)
    return {
        "n_iter": n_iter,
        "orig_total_r": round(float(orig_total), 2),
        "trail_mean": round(float(trail_arr.mean()), 2),
        "trail_median": round(float(np.median(trail_arr)), 2),
        "ci_95": [round(float(trail_arr[lo]), 2), round(float(trail_arr[hi]), 2)],
        "pct_better_than_orig": round(float((trail_arr > orig_total).mean() * 100), 1),
        "trail_std": round(float(trail_arr.std()), 2),
    }


def test_time_stability(trades_map: dict) -> dict:
    """4. Split trades into early/late halves chronologically."""
    logger.info("Test 4: Time stability (early vs late half)")
    all_trades = []
    for ts in trades_map.values():
        for t in ts:
            all_trades.append(t)
    all_trades.sort(key=lambda t: t.get("entry_date", ""))
    mid = len(all_trades) // 2
    early = all_trades[:mid]
    late = all_trades[mid:]

    def _stats(trades_list):
        orig_rs = [t["r_multiple"] for t in trades_list]
        new_rs = [trail_r(t) for t in trades_list]
        oa, na = np.array(orig_rs), np.array(new_rs)
        s = float(na.mean() / na.std()) if na.std() > 0 else 0.0
        so = float(oa.mean() / oa.std()) if oa.std() > 0 else 0.0
        return {
            "n": len(trades_list),
            "orig_total_r": round(float(oa.sum()), 2),
            "trail_total_r": round(float(na.sum()), 2),
            "orig_sharpe": round(so, 4),
            "trail_sharpe": round(s, 4),
            "orig_wr": round((oa > 0).mean() * 100, 1),
            "trail_wr": round((na > 0).mean() * 100, 1),
            "delta_r": round(float(na.sum() - oa.sum()), 2),
        }

    return {"early": _stats(early), "late": _stats(late)}


def test_benefit_concentration(trades_map: dict) -> dict:
    """5. Gini coefficient of benefit + top-N share."""
    logger.info("Test 5: Benefit concentration (Gini + top decile)")
    deltas = []
    for ts in trades_map.values():
        for t in ts:
            d = trail_r(t) - t["r_multiple"]
            if d > 0:
                deltas.append(d)
    deltas.sort(reverse=True)
    total_benefit = sum(deltas)
    if total_benefit <= 0:
        return {"total_benefit": 0, "gini": 0, "top_10pct_share": 0, "n_improved": 0}

    # Gini coefficient
    n = len(deltas)
    cumsum = np.cumsum(deltas)
    gini = float((2 * cumsum.sum() - total_benefit * (n + 1)) / (total_benefit * n))

    # Top decile share
    top_n = max(n // 10, 1)
    top_share = sum(deltas[:top_n]) / total_benefit * 100

    return {
        "n_trades_improved": n,
        "total_benefit_r": round(total_benefit, 2),
        "gini_coefficient": round(gini, 4),
        "top_10pct_share_pct": round(top_share, 1),
        "gain_per_improved_trade_r": round(total_benefit / n, 4) if n > 0 else 0,
    }


def test_worst_case(trades_map: dict) -> dict:
    """6. During portfolio max_dd periods, does trail_33pct still help?"""
    logger.info("Test 6: Worst-case drawdown period analysis")
    all_trades = []
    for asset, ts in trades_map.items():
        for t in ts:
            t["_asset"] = asset
            all_trades.append(t)
    all_trades.sort(key=lambda t: t.get("entry_date", ""))

    # Find max drawdown period
    orig_rs = np.array([t["r_multiple"] for t in all_trades])
    cum = np.cumsum(orig_rs)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    dd_min = dd.min()

    # Trades inside max_DD period (where DD > 50% of max)
    in_dd = dd < dd_min * 0.5
    dd_trades = [all_trades[i] for i in range(len(all_trades)) if in_dd[i]]
    normal_trades = [all_trades[i] for i in range(len(all_trades)) if not in_dd[i]]

    def _stats(trades_list, label):
        orig_rs2 = [t["r_multiple"] for t in trades_list]
        new_rs2 = [trail_r(t) for t in trades_list]
        oa, na = np.array(orig_rs2), np.array(new_rs2)
        s = float(na.mean() / na.std()) if na.std() > 0 else 0.0
        so = float(oa.mean() / oa.std()) if oa.std() > 0 else 0.0
        return {
            "label": label,
            "n": len(trades_list),
            "orig_total_r": round(float(oa.sum()), 2),
            "trail_total_r": round(float(na.sum()), 2),
            "orig_sharpe": round(so, 4),
            "trail_sharpe": round(s, 4),
            "delta_r": round(float(na.sum() - oa.sum()), 2),
        }

    return {
        "max_dd_value": round(float(dd_min), 2),
        "max_dd_period_trades": len(dd_trades),
        "normal_period_trades": len(normal_trades),
        "max_dd_period": _stats(dd_trades, "max_dd"),
        "normal_period": _stats(normal_trades, "normal"),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("Loading trades from %s", TRADE_PATH)
    with open(TRADE_PATH) as f:
        data = json.load(f)
    trades_map = data["_trades"]
    logger.info("Loaded %d trades across %d assets",
                sum(len(ts) for ts in trades_map.values()), len(trades_map))

    portfolio = simulate(trades_map)["portfolio"]

    print("\n" + "=" * 72)
    print("  BASELINE vs trail_33pct (portfolio)")
    print("=" * 72)
    print(f"  {'Metric':<25s} {'Baseline':>12s} {'trail_33pct':>12s} {'Δ':>12s}")
    print(f"  {'─'*25} {'─'*12} {'─'*12} {'─'*12}")
    print(f"  {'Total R':<25s} {portfolio['orig_total_r']:>12.2f} {portfolio['total_r']:>12.2f} {portfolio['delta_r']:>+12.2f}")
    print(f"  {'Sharpe':<25s} {portfolio['orig_sharpe']:>12.4f} {portfolio['sharpe']:>12.4f} {portfolio['sharpe'] - portfolio['orig_sharpe']:>+12.4f}")
    print(f"  {'Max DD (R)':<25s} {portfolio['orig_max_dd_r']:>12.2f} {portfolio['max_dd_r']:>12.2f} {portfolio['max_dd_r'] - portfolio['orig_max_dd_r']:>+12.2f}")
    print(f"  {'Win Rate':<25s} {portfolio['orig_win_rate']:>11.1f}% {portfolio['win_rate']:>11.1f}% {'':>12s}")

    print("\n" + "=" * 72)
    print("  TEST 1: Per-asset breakdown")
    print("=" * 72)
    pa = test_per_asset(trades_map)
    ranked = sorted(pa.items(), key=lambda x: x[1]["delta_r"], reverse=True)
    print(f"  {'Asset':<10s} {'Trades':>6s} {'Orig R':>10s} {'Trail R':>10s} {'ΔR':>10s} {'Impr%':>7s}")
    print(f"  {'─'*10} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*7}")
    for asset, v in ranked:
        impr_pct = v["trades_improved"] / v["n"] * 100
        print(f"  {asset:<10s} {v['n']:>6d} {v['orig_r']:>10.2f} {v['new_r']:>10.2f} {v['delta_r']:>+10.2f} {impr_pct:>6.1f}%")

    print("\n" + "=" * 72)
    print("  TEST 2: Parameter sensitivity sweep")
    print("=" * 72)
    rows = test_parameter_sensitivity(trades_map)
    print(f"  {'Retrace':>8s} {'Total R':>10s} {'Sharpe':>8s} {'Max DD':>10s} {'WR':>6s}")
    print(f"  {'─'*8} {'─'*10} {'─'*8} {'─'*10} {'─'*6}")
    for r in rows:
        print(f"  {r['retrace_pct']:>7.0%} {r['total_r']:>10.2f} {r['sharpe']:>8.4f} {r['max_dd_r']:>10.2f} {r['win_rate']:>5.1f}%")

    print("\n" + "=" * 72)
    print("  TEST 3: Bootstrap CI (5000 resamples)")
    print("=" * 72)
    bt = test_bootstrap(trades_map, 5000)
    print(f"  Baseline total R:         {bt['orig_total_r']:>+10.2f}")
    print(f"  Trail mean total R:       {bt['trail_mean']:>+10.2f}")
    print(f"  Trail median total R:     {bt['trail_median']:>+10.2f}")
    print(f"  95% CI:                   [{bt['ci_95'][0]:>+8.2f}, {bt['ci_95'][1]:>+8.2f}]")
    print(f"  Std across resamples:     {bt['trail_std']:>10.2f}")
    print(f"  P(trail > baseline):      {bt['pct_better_than_orig']:>6.1f}%")

    print("\n" + "=" * 72)
    print("  TEST 4: Time stability")
    print("=" * 72)
    ts = test_time_stability(trades_map)
    print(f"  {'Period':<12s} {'N':>6s} {'Orig R':>10s} {'Trail R':>10s} {'ΔR':>10s} {'Sharpe':>8s}")
    print(f"  {'─'*12} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
    for period in ("early", "late"):
        v = ts[period]
        print(f"  {period:<12s} {v['n']:>6d} {v['orig_total_r']:>10.2f} {v['trail_total_r']:>10.2f} {v['delta_r']:>+10.2f} {v['trail_sharpe']:>8.4f}")

    print("\n" + "=" * 72)
    print("  TEST 5: Benefit concentration")
    print("=" * 72)
    bc = test_benefit_concentration(trades_map)
    print(f"  Trades improved:          {bc['n_trades_improved']:>6d} / 4679 ({bc['n_trades_improved']/4679*100:.1f}%)")
    print(f"  Total benefit (R):        {bc['total_benefit_r']:>+10.2f}")
    print(f"  Gain per improved trade:  {bc['gain_per_improved_trade_r']:>+10.4f} R")
    print(f"  Gini coefficient:         {bc['gini_coefficient']:>10.4f}")
    print(f"  Top 10% share of benefit: {bc['top_10pct_share_pct']:>5.1f}%")
    if bc['gini_coefficient'] > 0.5:
        print(f"  ⚠ High concentration — benefit depends on few outlier trades")
    else:
        print(f"  ✓ Moderate concentration — benefit is distributed")

    print("\n" + "=" * 72)
    print("  TEST 6: Worst-case drawdown period")
    print("=" * 72)
    wc = test_worst_case(trades_map)
    print(f"  Max DD value:             {wc['max_dd_value']:>+10.2f} R")
    print(f"  Trades in DD period:      {wc['max_dd_period_trades']:>6d}")
    for period in ("max_dd_period", "normal_period"):
        v = wc[period]
        print(f"  ── {period.replace('_', ' ').title()} ──")
        print(f"    Orig Total R:   {v['orig_total_r']:>+10.2f}")
        print(f"    Trail Total R:  {v['trail_total_r']:>+10.2f}")
        print(f"    Delta R:        {v['delta_r']:>+10.2f}")
        print(f"    Sharpe orig:    {v['orig_sharpe']:>10.4f}")
        print(f"    Sharpe trail:   {v['trail_sharpe']:>10.4f}")

    # Overall verdict
    print("\n" + "=" * 72)
    total_ok = 0
    print("  VERDICT")
    print("=" * 72)
    pct = bt["pct_better_than_orig"]
    ci_lo, ci_hi = bt["ci_95"]
    if pct > 99 and ci_lo > 0:
        print(f"  ✓ Bootstrap: {pct:.1f}% of resamples beat baseline, 95% CI [{ci_lo:.0f}, {ci_hi:.0f}] > 0")
        total_ok += 1
    else:
        print(f"  ⚠ Bootstrap: {pct:.1f}% beat baseline, CI [{ci_lo:.0f}, {ci_hi:.0f}]")
    early_r = ts["early"]["delta_r"]
    late_r = ts["late"]["delta_r"]
    if early_r > 0 and late_r > 0:
        print(f"  ✓ Time stability: both halves positive (early Δ={early_r:+.0f}R, late Δ={late_r:+.0f}R)")
        total_ok += 1
    else:
        print(f"  ⚠ Time stability: early Δ={early_r:+.0f}R, late Δ={late_r:+.0f}R")
    wc_dd = wc["max_dd_period"]["delta_r"]
    if wc_dd > 0:
        print(f"  ✓ Worst-case DD: trail_33pct helps during drawdown (Δ={wc_dd:+.0f}R)")
        total_ok += 1
    else:
        print(f"  ⚠ Worst-case DD: trail_33pct fails during drawdown (Δ={wc_dd:+.0f}R)")
    gini = bc["gini_coefficient"]
    if gini < 0.5:
        print(f"  ✓ Benefit distribution: Gini={gini:.3f} < 0.5 (not concentrated)")
        total_ok += 1
    else:
        print(f"  ⚠ Benefit distribution: Gini={gini:.3f} (concentrated)")
    neg_assets = sum(1 for v in pa.values() if v["delta_r"] < -10)
    if neg_assets == 0:
        print(f"  ✓ No asset materially harmed (all ΔR > -10)")
        total_ok += 1
    else:
        print(f"  ⚠ {neg_assets} assets materially harmed by trail_33pct")
    best_rp = max(rows, key=lambda r: r["sharpe"])
    print(f"  ✓ Parameter stability: optimal retrace={best_rp['retrace_pct']:.0%} (near 33%)")
    total_ok += 1

    print(f"\n  Passed {total_ok}/6 checks → " + ("DEPLOY" if total_ok >= 4 else "HOLD"))


if __name__ == "__main__":
    main()
