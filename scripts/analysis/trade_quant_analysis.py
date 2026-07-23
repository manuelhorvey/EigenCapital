#!/usr/bin/env python3
"""Three quant analyses requested by the user."""

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
print(f"Total trades loaded: {N}")
print(f"{'='*80}\n")

# ── 1. Exit reasons by outcome ──────────────────────────────────────────────
print("═" * 80)
print("ANALYSIS 1: EXIT REASONS BY OUTCOME")
print("═" * 80)

winners = [t for t in all_trades if t["r_multiple"] > 0]
losers = [t for t in all_trades if t["r_multiple"] <= 0]
print(f"  Winners: {len(winners)} ({len(winners)/N*100:.1f}%)")
print(f"  Losers:  {len(losers)} ({len(losers)/N*100:.1f}%)")

for label, subset in [("ALL", all_trades), ("WINNERS", winners), ("LOSERS", losers)]:
    reasons = defaultdict(int)
    for t in subset:
        reasons[t["exit_reason"]] += 1
    print(f"\n  ── {label} ({len(subset)} trades) ──")
    total_r = sum(t["r_multiple"] for t in subset)
    for reason in sorted(reasons):
        n = reasons[reason]
        pct = n / len(subset) * 100
        r_trades = [t for t in subset if t["exit_reason"] == reason]
        r_sum = sum(t["r_multiple"] for t in r_trades)
        print(f"    {reason:20s}  n={n:5d}  ({pct:5.1f}%)  total_R={r_sum:+8.2f}")

# ── 2. Trade concentration ──────────────────────────────────────────────────
print("\n" + "═" * 80)
print("ANALYSIS 2: TRADE CONCENTRATION (top-N % of trades)")
print("═" * 80)

r_vals = np.array([t["r_multiple"] for t in all_trades])
sorted_r = np.sort(r_vals)[::-1]  # descending
total_r = sorted_r.sum()

for pct in [1, 5, 10, 20, 50]:
    n_top = max(1, int(N * pct / 100))
    top_r = sorted_r[:n_top].sum()
    share = top_r / total_r * 100
    print(f"  Top {pct:2d}% of trades ({n_top:5d}): {share:5.1f}% of total PnL (={top_r:+9.2f}R)")

# Top 5% detail
n_top5 = max(1, int(N * 5 / 100))
top5 = sorted_r[:n_top5]
print(f"\n  Top 5% R range: [{top5[-1]:+.4f}R, {top5[0]:+.4f}R]")
print(f"  Top 5% min threshold: {top5[-1]:+.4f}R")

# Bottom 50% (worst half)
bottom50 = np.sort(r_vals)[:N//2]
print(f"  Bottom 50% total R: {bottom50.sum():+.2f}R")

# Top 1 trade
if len(sorted_r) > 0:
    print(f"  Best single trade: {sorted_r[0]:+.4f}R")
    print(f"  Worst single trade: {sorted_r[-1]:+.4f}R")

# ── 3. MAE before first profit ──────────────────────────────────────────────
print("\n" + "═" * 80)
print("ANALYSIS 3: MAE DISTRIBUTION BEFORE FIRST PROFIT")
print("═" * 80)

ever_profitable = [t for t in all_trades if t["candles_to_first_profit"] is not None]
never_profitable = [t for t in all_trades if t["candles_to_first_profit"] is None]

print(f"  Ever profitable:     {len(ever_profitable):5d} ({len(ever_profitable)/N*100:.1f}%)")
print(f"  Never profitable:    {len(never_profitable):5d} ({len(never_profitable)/N*100:.1f}%)")

if ever_profitable:
    # Classify MAE relative to first profit candle
    mae_before = []
    mae_after = []
    mae_overall = []
    for t in ever_profitable:
        mae_r = t["mae_r"]
        candle_of_mae = t["candle_of_mae"]
        fp_candle = t["candles_to_first_profit"]
        mae_overall.append(mae_r)
        if candle_of_mae is not None and fp_candle is not None:
            if candle_of_mae < fp_candle:
                mae_before.append(mae_r)
            else:
                mae_after.append(mae_r)
    
    def stats(arr, label):
        if not arr:
            print(f"\n  {label}: no trades")
            return
        arr = np.array(arr)
        print(f"\n  {label} (n={len(arr)})")
        print(f"    Mean MAE:   {arr.mean():+.4f}R")
        print(f"    Median MAE: {np.median(arr):+.4f}R")
        for p in [25, 50, 75, 90, 95, 99]:
            print(f"    P{p:2d} MAE:     {np.percentile(arr, p):+.4f}R")
    
    stats(mae_before, "MAE occurred BEFORE first profit")
    stats(mae_after, "MAE occurred AFTER first profit")
    stats(mae_overall, "MAE overall (ever-profitable trades)")

    # Bucketed MAE before first profit
    if mae_before:
        mae_b_arr = np.array(mae_before)
        print("\n  MAE-before-first-profit buckets:")
        for threshold in [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]:
            pct_le = (mae_b_arr <= threshold).mean() * 100
            print(f"    MAE <= {threshold:.2f}R: {pct_le:5.1f}%")

# ── 4. Never-profitable trade profile ────────────────────────────────────────
print("\n" + "═" * 80)
print("ANALYSIS 4: NEVER-PROFITABLE TRADE PROFILE")
print("═" * 80)

if never_profitable:
    losses = np.array([t["r_multiple"] for t in never_profitable])
    durations = []
    exit_reasons_np = defaultdict(int)
    assets_np = defaultdict(int)
    for t in never_profitable:
        entry = t.get("entry_date", "")
        exit_d = t.get("exit_date", "")
        durs = t.get("candles_to_breakeven")
        if durs is not None:
            durations.append(durs)
        else:
            prices = t.get("prices", "")
            if isinstance(prices, str):
                durations.append(len(prices.split("\n")))
            else:
                durations.append(0)
        exit_reasons_np[t["exit_reason"]] += 1
        assets_np[t["asset"]] += 1
    
    print(f"  Count: {len(losses)} trades")
    print(f"  Avg loss:  {losses.mean():+.4f}R")
    print(f"  Median loss: {np.median(losses):+.4f}R")
    print(f"  Total loss: {losses.sum():+.4f}R")
    for p in [25, 50, 75, 90, 95, 99]:
        print(f"    P{p:2d} loss: {np.percentile(losses, p):+.4f}R")
    
    print(f"\n  Exit reasons:")
    for reason in sorted(exit_reasons_np):
        n = exit_reasons_np[reason]
        print(f"    {reason:20s}: {n:5d} ({n/len(never_profitable)*100:.1f}%)")
    
    print(f"\n  Top assets by never-profitable count:")
    for asset, n in sorted(assets_np.items(), key=lambda x: -x[1])[:10]:
        total_for_asset = sum(1 for t in all_trades if t["asset"] == asset)
        print(f"    {asset:10s}: {n:4d}/{total_for_asset:4d} ({n/total_for_asset*100:.1f}%)")

# ── 5. Winners: exit reason breakdown ────────────────────────────────────────
print("\n" + "═" * 80)
print("ANALYSIS 5: WINNER EXIT REASON DETAIL")
print("═" * 80)

win_reasons = defaultdict(list)
for t in winners:
    win_reasons[t["exit_reason"]].append(t["r_multiple"])

for reason in sorted(win_reasons):
    vals = np.array(win_reasons[reason])
    print(f"  {reason:20s}: n={len(vals):5d}, avg_R={vals.mean():+.4f}, median_R={np.median(vals):+.4f}, "
          f"total_R={vals.sum():+.2f}, min={vals.min():+.4f}, max={vals.max():+.4f}")

# ── Bonus: profit velocity ───────────────────────────────────────────────────
print("\n" + "═" * 80)
print("BONUS: PROFIT VELOCITY (R/day for winners)")
print("═" * 80)

velocities = []
for t in winners:
    dur = t.get("candles_to_first_profit")
    total_dur = None
    prices = t.get("prices", "")
    if isinstance(prices, str):
        total_dur = len(prices.split("\n"))
    else:
        total_dur = len(prices) if isinstance(prices, list) else 0
    if total_dur and total_dur > 0:
        velocities.append(t["r_multiple"] / total_dur)

if velocities:
    v = np.array(velocities)
    print(f"  Mean profit velocity:   {v.mean():+.4f} R/day")
    print(f"  Median profit velocity: {np.median(v):+.4f} R/day")
    for p in [25, 75, 90]:
        print(f"  P{p:2d} profit velocity:   {np.percentile(v, p):+.4f} R/day")

print("\nDone.")
