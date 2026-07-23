#!/usr/bin/env python3
"""Tail-removal robustness + per-asset deep dive."""

from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"

with open(TRADE_PATH) as f:
    data = json.load(f)

trades_dict = data["_trades"]
all_trades = []
for asset, tlist in trades_dict.items():
    for t in tlist:
        t["asset"] = asset
        all_trades.append(t)

N = len(all_trades)

r_vals = np.array([t["r_multiple"] for t in all_trades], dtype=float)

# ── 1. Tail-removal robustness ──────────────────────────────────────────────
print("═" * 80)
print("ROBUSTNESS: REMOVE TOP X% TRADES")
print("═" * 80)

def portfolio_stats(r_arr, label=""):
    if len(r_arr) == 0:
        return {"n": 0, "total_r": 0, "mean": 0, "std": 0, "sharpe": 0,
                "win_rate": 0, "profit_factor": float("inf"), "max_dd": 0,
                "calmar": 0, "sortino": 0}
    n = len(r_arr)
    total = r_arr.sum()
    mean = r_arr.mean()
    std = r_arr.std() if r_arr.std() > 0 else 1e-10
    wins = r_arr[r_arr > 0]
    losses = r_arr[r_arr <= 0]
    wr = len(wins) / n * 100
    pf = abs(wins.sum() / losses.sum()) if losses.sum() != 0 else float("inf")
    # Daily-res data: treat each trade as one period for Sharpe
    sharpe = mean / std
    # Sortino
    downside = r_arr[r_arr < 0]
    sortino = mean / (downside.std() if len(downside) > 0 and downside.std() > 0 else 1e-10)
    # Max DD (running cumulative)
    cum = np.cumsum(r_arr) if n > 0 else np.array([0])
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = abs(dd.min()) if len(dd) > 0 else 0
    calmar = (total / n * 252) / max_dd if max_dd > 0 else 0
    return {"n": n, "total_r": total, "mean": mean, "std": std,
            "sharpe": sharpe, "win_rate": wr, "profit_factor": pf,
            "max_dd": max_dd, "calmar": calmar, "sortino": sortino}

order = np.argsort(r_vals)[::-1]  # descending

for remove_pct, label in [(0, "All trades"), (1, "Remove top 1%"), (5, "Remove top 5%"),
                           (10, "Remove top 10%"), (20, "Remove top 20%")]:
    n_remove = max(1, int(N * remove_pct / 100)) if remove_pct > 0 else 0
    keep = order[n_remove:]
    r_keep = r_vals[keep]
    removed = order[:n_remove]
    r_removed = r_vals[removed]
    s = portfolio_stats(r_keep)
    s_rem = portfolio_stats(r_removed)
    
    delta_total = s["total_r"] - (portfolio_stats(r_vals)["total_r"])
    
    print(f"\n  ── {label} (n={s['n']}) ──")
    print(f"    Total R:       {s['total_r']:+8.2f}  (removed: {r_removed.sum():+.2f}R from {n_remove} trades)")
    print(f"    Expectancy:    {s['mean']:+8.4f} R/trade  (Δ from all: {s['mean'] - r_vals.mean():+.4f})")
    print(f"    Win rate:      {s['win_rate']:6.2f}%")
    print(f"    Profit factor: {s['profit_factor']:6.4f}")
    print(f"    Sharpe:        {s['sharpe']:6.4f}")
    print(f"    Sortino:       {s['sortino']:6.4f}")
    print(f"    Max DD (R):    {s['max_dd']:8.2f}")
    print(f"    Calmar:        {s['calmar']:6.4f}")
    
    if remove_pct > 0:
        # What's the minimum to be in the removed set?
        min_removed = r_vals[order[n_remove - 1]] if n_remove > 0 else 0
        print(f"    Removal threshold: >= {min_removed:+.4f}R")

# ── Sequential removal (every 1% step) ──────────────────────────────────────
print("\n\n  ── Sequential removal (1% steps) ──")
print(f"  {'Pct':>4s} {'N':>6s} {'TotalR':>10s} {'Exp':>8s} {'WR':>6s} {'PF':>8s} {'Sharpe':>8s} {'Sortino':>8s} {'MaxDD':>8s}")
print(f"  {'-'*66}")
for pct in range(0, 51, 5):
    n_remove = int(N * pct / 100)
    keep = order[n_remove:]
    r_keep = r_vals[keep]
    s = portfolio_stats(r_keep)
    print(f"  {pct:3d}% {s['n']:6d} {s['total_r']:+10.2f} {s['mean']:+8.4f} {s['win_rate']:5.1f}% {s['profit_factor']:7.3f} {s['sharpe']:7.3f} {s['sortino']:7.3f} {s['max_dd']:8.2f}")

# ── 2. Per-asset deep dive ──────────────────────────────────────────────────
print("\n\n" + "=" * 80)
print("PER-ASSET DEEP DIVE")
print("=" * 80)

assets = sorted(set(t["asset"] for t in all_trades))

# Header
print(f"\n  {'Asset':>8s} {'N':>5s} {'WR%':>5s} {'Exp(R)':>8s} {'AvgR':>8s} {'MedR':>8s} {'PF':>7s} {'Top5%R':>8s} {'Top5%Sh':>7s} {'MedMAE':>7s} {'MedVel':>7s} {'TP%':>5s} {'Barr%':>6s} {'SL%':>5s} {'MAE<0.5R':>8s}")
print(f"  {'-'*110}")

all_top5_all = 0
all_total_r = 0

for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    r_a = np.array([t["r_multiple"] for t in at], dtype=float)
    total_r = r_a.sum()
    mean_r = r_a.mean()
    med_r = np.median(r_a)
    wins = r_a[r_a > 0]
    losses = r_a[r_a <= 0]
    wr = len(wins) / n * 100 if n > 0 else 0
    pf = abs(wins.sum() / losses.sum()) if losses.sum() != 0 else (99.0 if wins.sum() > 0 else 0)
    
    # Top 5% contribution
    n_top5 = max(1, int(n * 5 / 100))
    order_a = np.argsort(r_a)[::-1]
    top5_r = r_a[order_a[:n_top5]].sum()
    top5_share = top5_r / total_r * 100 if total_r != 0 else 0
    
    all_top5_all += top5_r
    all_total_r += total_r
    
    # Median MAE (for ever-profitable)
    mae_vals = [t["mae_r"] for t in at if t["candles_to_first_profit"] is not None]
    med_mae = np.median(mae_vals) if mae_vals else 0
    
    # MAE <= 0.5R before first profit
    mae_before_vals = []
    for t in at:
        if t["candles_to_first_profit"] is not None and t.get("candle_of_mae") is not None:
            if t["candle_of_mae"] < t["candles_to_first_profit"]:
                mae_before_vals.append(t["mae_r"])
    if mae_before_vals:
        mae_le_05 = np.mean(np.array(mae_before_vals) <= 0.5) * 100
    else:
        mae_le_05 = 0.0
    
    # Profit velocity (winners)
    vel = []
    for t in at:
        if t["r_multiple"] > 0:
            prices = t.get("prices", "")
            dur = len(prices.split("\n")) if isinstance(prices, str) else (len(prices) if isinstance(prices, list) else 0)
            if dur > 0:
                vel.append(t["r_multiple"] / dur)
    med_vel = np.median(vel) if vel else 0
    
    # Exit distribution
    reasons = defaultdict(int)
    for t in at:
        reasons[t["exit_reason"]] += 1
    tp_pct = reasons.get("tp", 0) / n * 100
    sl_pct = reasons.get("sl", 0) / n * 100
    barr_pct = reasons.get("barrier", 0) / n * 100
    
    print(f"  {asset:>8s} {n:5d} {wr:5.1f} {mean_r:+8.4f} {mean_r:+8.4f} {med_r:+8.4f} {pf:7.3f} "
          f"{top5_share:7.1f}% {0:7.1f}% {med_mae:7.3f} {med_vel:7.3f} {tp_pct:4.1f}% {barr_pct:5.1f}% {sl_pct:4.1f}% "
          f"{mae_le_05:7.1f}%")

print(f"\n  {'─'*110}")
print(f"  Portfolio total R across top 5% of each asset: {all_top5_all:+.2f} / {all_total_r:+.2f} total = {all_top5_all/all_total_r*100:.1f}%" if all_total_r != 0 else "")

# ── 3. Asset-level top-N removal ────────────────────────────────────────────
print("\n\n" + "=" * 80)
print("ASSET-LEVEL TOP-5% REMOVAL IMPACT")
print("=" * 80)

for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    r_a = np.array([t["r_multiple"] for t in at], dtype=float)
    total_r = r_a.sum()
    
    n_top5 = max(1, int(n * 5 / 100))
    order_a = np.argsort(r_a)[::-1]
    keep_idx = order_a[n_top5:]
    r_keep = r_a[keep_idx]
    total_r_keep = r_keep.sum()
    mean_keep = r_keep.mean()
    wr_keep = (r_keep > 0).mean() * 100
    
    print(f"  {asset:>8s}: total_R={total_r:+7.2f} → without top5%={total_r_keep:+7.2f}  (Δ={total_r_keep-total_r:+7.2f})  "
          f"exp={mean_keep:+.4f}  WR={wr_keep:.1f}%")

# ── 4. Top-5% trade profile ─────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TOP 5% TRADE PROFILE")
print("=" * 80)

n_top5 = max(1, int(N * 5 / 100))
top5_idx = order[:n_top5]
top5_trades = [all_trades[i] for i in top5_idx]

print(f"  Count: {len(top5_trades)}")
print(f"  R range: [{min(t['r_multiple'] for t in top5_trades):+.4f}, {max(t['r_multiple'] for t in top5_trades):+.4f}]")
print(f"  Total R: {sum(t['r_multiple'] for t in top5_trades):+.2f}")

asset_dist = defaultdict(int)
for t in top5_trades:
    asset_dist[t["asset"]] += 1
print(f"\n  Asset distribution:")
for a, c in sorted(asset_dist.items(), key=lambda x: -x[1]):
    print(f"    {a:8s}: {c:4d} trades ({c/len(top5_trades)*100:.1f}%)")

exit_dist = defaultdict(int)
for t in top5_trades:
    exit_dist[t["exit_reason"]] += 1
print(f"\n  Exit reasons:")
for e, c in sorted(exit_dist.items(), key=lambda x: -x[1]):
    print(f"    {e:15s}: {c:4d} ({c/len(top5_trades)*100:.1f}%)")

side_dist = defaultdict(int)
for t in top5_trades:
    side_dist[t["side"]] += 1
print(f"\n  Side:")
for s, c in sorted(side_dist.items(), key=lambda x: -x[1]):
    print(f"    {s:5s}: {c:4d} ({c/len(top5_trades)*100:.1f}%)")

# Median holding of top 5%
durations_top5 = []
for t in top5_trades:
    prices = t.get("prices", "")
    dur = len(prices.split("\n")) if isinstance(prices, str) else (len(prices) if isinstance(prices, list) else 0)
    if dur > 0:
        durations_top5.append(dur)
print(f"\n  Median holding: {np.median(durations_top5):.0f} days" if durations_top5 else "")

print("\nDone.")
