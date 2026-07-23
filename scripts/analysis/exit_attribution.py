#!/usr/bin/env python3
"""
Exit Attribution Decomposition.

For every trade, decompose PnL into:
  Stage 1 — Entry alpha: what does the trade return at T+1, T+3, T+5? 
  Stage 2 — Static exit: what would fixed TP/SL have produced?
  Stage 3 — Adaptive exit contribution: actual R - static R
  Stage 4 — Tail capture attribution: for top 5%, how much comes from each stage?
"""

from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime

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

def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
for t in all_trades:
    t["_entry_dt"] = parse_dt(t["entry_date"])
all_trades.sort(key=lambda t: t["_entry_dt"])

# ── Helper: calculate R from price move ─────────────────────────────────────
def calc_r(entry, exit_price, sl, tp, side):
    risk = abs(entry - sl)
    if risk < 1e-10:
        return 0.0
    if side == "BUY":
        raw = exit_price - entry
    else:
        raw = entry - exit_price
    return raw / risk

# ── Static exit simulation ──────────────────────────────────────────────────
def simulate_static_exit(t):
    """Simulate what happens with fixed TP/SL only. Returns (exit_candle, exit_price, exit_reason, r)."""
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    side = t["side"]
    highs = t.get("highs", [])
    lows = t.get("lows", [])
    
    if not highs or not lows:
        return None
    
    n_candles = min(len(highs), len(lows))
    
    for i in range(n_candles):
        if side == "SELL":
            # SL hit if price goes above SL
            if highs[i] >= sl:
                return (i, sl, "sl", calc_r(entry, sl, sl, tp, side))
            # TP hit if price goes below TP
            if lows[i] <= tp:
                return (i, tp, "tp", calc_r(entry, tp, sl, tp, side))
        else:  # BUY
            # SL hit if price goes below SL
            if lows[i] <= sl:
                return (i, sl, "sl", calc_r(entry, sl, sl, tp, side))
            # TP hit if price goes above TP
            if highs[i] >= tp:
                return (i, tp, "tp", calc_r(entry, tp, sl, tp, side))
    
    # Neither hit — exit at last price
    last_price = t.get("prices", None)
    if isinstance(last_price, str):
        try:
            last_price = float(last_price.strip().split("\n")[-1].split()[-1])
        except:
            last_price = entry
    return (n_candles - 1, last_price, "expiry", calc_r(entry, last_price, sl, tp, side))

# ── Entry alpha (T+N returns) ───────────────────────────────────────────────
def entry_alpha(t, n_candles):
    """Return R if exited at candle n_candles (1 = next candle)."""
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    side = t["side"]
    prices = t.get("prices", "")
    
    if isinstance(prices, str):
        lines = prices.strip().split("\n")
        vals = []
        for l in lines:
            if "dtype:" in l:
                continue
            parts = l.strip().split()
            if len(parts) >= 2:
                try:
                    vals.append(float(parts[-1]))
                except ValueError:
                    continue
        if not vals:
            return None
        prices_arr = np.array(vals)
    elif isinstance(prices, list):
        prices_arr = np.array(prices, dtype=float)
    else:
        return None
    
    idx = min(n_candles - 1, len(prices_arr) - 1)
    if idx < 0:
        return None
    return calc_r(entry, prices_arr[idx], sl, tp, side)

# ── Compute for every trade ─────────────────────────────────────────────────
results = []
failed = 0
for t in all_trades:
    static = simulate_static_exit(t)
    if static is None:
        failed += 1
        continue
    
    static_candle, static_price, static_reason, static_r = static
    actual_r = t["r_multiple"]
    adaptive_alpha = actual_r - static_r
    
    # Entry alpha at T+1, T+3, T+5
    ea1 = entry_alpha(t, 1)
    ea3 = entry_alpha(t, 3)
    ea5 = entry_alpha(t, 5)
    
    results.append({
        "asset": t["asset"],
        "side": t["side"],
        "actual_r": actual_r,
        "static_r": static_r,
        "static_reason": static_reason,
        "static_candle": static_candle,
        "adaptive_alpha": adaptive_alpha,
        "entry_alpha_t1": ea1,
        "entry_alpha_t3": ea3,
        "entry_alpha_t5": ea5,
        "exit_reason": t["exit_reason"],
        "is_winner": actual_r > 0,
        "is_top5pct": actual_r >= np.percentile(r_vals, 95),
        "is_top10pct": actual_r >= np.percentile(r_vals, 90),
    })

print(f"Processed {len(results)} trades ({failed} failed to simulate)")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 1: ENTRY ALPHA
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"STAGE 1: ENTRY ALPHA (What does the trade return if exited early?)")
print(f"{'='*80}")

t1_vals = np.array([r["entry_alpha_t1"] for r in results if r["entry_alpha_t1"] is not None])
t3_vals = np.array([r["entry_alpha_t3"] for r in results if r["entry_alpha_t3"] is not None])
t5_vals = np.array([r["entry_alpha_t5"] for r in results if r["entry_alpha_t5"] is not None])

print(f"\n  {'Horizon':>10s} {'N':>6s} {'MeanR':>8s} {'MedR':>8s} {'WR%':>6s} {'AvgWinR':>9s} {'AvgLossR':>9s} {'PF':>7s}")
print(f"  {'-'*64}")
for label, vals in [("T+1", t1_vals), ("T+3", t3_vals), ("T+5", t5_vals)]:
    if len(vals) == 0: continue
    wins = vals[vals > 0]; losses = vals[vals <= 0]
    wr = len(wins)/len(vals)*100; pf = abs(wins.sum()/losses.sum()) if losses.sum()!=0 else float("inf")
    print(f"  {label:>10s} {len(vals):6d} {vals.mean():+8.4f} {np.median(vals):+8.4f} "
          f"{wr:5.1f}% {wins.mean():+9.4f} {losses.mean():+9.4f} {pf:7.3f}")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2: STATIC EXIT VS ACTUAL
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"STAGE 2: STATIC EXIT (what fixed TP/SL would have produced)")
print(f"{'='*80}")

static_rs = np.array([r["static_r"] for r in results])
actual_rs = np.array([r["actual_r"] for r in results])

for label, arr in [("Static TP/SL", static_rs), ("Actual (adaptive)", actual_rs)]:
    wins = arr[arr > 0]; losses = arr[arr <= 0]
    wr = len(wins)/len(arr)*100; pf = abs(wins.sum()/losses.sum()) if losses.sum()!=0 else float("inf")
    print(f"  {label:<25s}: total_R={arr.sum():+8.2f} mean={arr.mean():+8.4f} "
          f"median={np.median(arr):+8.4f} WR={wr:5.1f}% PF={pf:7.3f}")

# Static exit reasons
static_reasons = defaultdict(int)
for r in results:
    static_reasons[r["static_reason"]] += 1
print(f"\n  Static exit reason distribution:")
for reason, n in sorted(static_reasons.items()):
    print(f"    {reason:10s}: {n:5d} ({n/len(results)*100:.1f}%)")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 3: ADAPTIVE EXIT CONTRIBUTION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"STAGE 3: ADAPTIVE EXIT CONTRIBUTION (actual R - static R)")
print(f"{'='*80}")

adaptive_alphas = np.array([r["adaptive_alpha"] for r in results])
total_static = static_rs.sum()
total_actual = actual_rs.sum()
total_adaptive = adaptive_alphas.sum()

print(f"  Total PnL decomposition:")
print(f"    Static TP/SL contribution:   {total_static:+8.2f}R  ({total_static/total_actual*100:.1f}%)")
print(f"    Adaptive exit contribution:  {total_adaptive:+8.2f}R  ({total_adaptive/total_actual*100:.1f}%)")
print(f"    Total (actual):              {total_actual:+8.2f}R")

# Positive adaptive alpha rate
pos_adaptive = (adaptive_alphas > 0).mean() * 100
neg_adaptive = (adaptive_alphas < 0).mean() * 100
print(f"\n  Adaptive alpha positive: {pos_adaptive:.1f}% of trades")
print(f"  Adaptive alpha negative: {neg_adaptive:.1f}% of trades")

# By exit reason
print(f"\n  By actual exit reason:")
for reason in ["tp", "sl", "barrier"]:
    mask = np.array([r["exit_reason"] == reason for r in results])
    n = mask.sum()
    if n == 0: continue
    aa = adaptive_alphas[mask]; sa = static_rs[mask]; aa_ = actual_rs[mask]
    print(f"    {reason:15s}: n={n:5d} | static_R={sa.sum():+8.2f} | adaptive_R={aa.sum():+8.2f} | "
          f"actual_R={aa_.sum():+8.2f} | mean_adaptive={aa.mean():+8.4f}")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 4: TAIL CAPTURE ATTRIBUTION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"STAGE 4: TAIL CAPTURE ATTRIBUTION (where do top 5% winners come from?)")
print(f"{'='*80}")

top5_r = np.array([r["actual_r"] for r in results if r["is_top5pct"]])
top5_static = np.array([r["static_r"] for r in results if r["is_top5pct"]])
top5_adaptive = np.array([r["adaptive_alpha"] for r in results if r["is_top5pct"]])
top5_ea1 = np.array([r["entry_alpha_t1"] for r in results if r["is_top5pct"] if r["entry_alpha_t1"] is not None])
top5_ea3 = np.array([r["entry_alpha_t3"] for r in results if r["is_top5pct"] if r["entry_alpha_t3"] is not None])

print(f"\n  Top 5% trades: {len(top5_r)}")
print(f"  Total R (actual):       {top5_r.sum():+8.2f}")
print(f"  Static would have been: {top5_static.sum():+8.2f}")
print(f"  Adaptive added:         {top5_adaptive.sum():+8.2f}")
print(f"\n  Per-trade decomposition:")
print(f"    Actual R:   mean={top5_r.mean():+.4f} median={np.median(top5_r):+.4f}")
print(f"    Static R:   mean={top5_static.mean():+.4f} median={np.median(top5_static):+.4f}")
print(f"    Adaptive α: mean={top5_adaptive.mean():+.4f} median={np.median(top5_adaptive):+.4f}")
print(f"    Entry T+1:  mean={top5_ea1.mean():+.4f} (available at next candle)")

# How many top-5% are already top-5% under static?
top5_static_th = np.percentile(static_rs, 95)
top5_static_is_top5 = (top5_static >= top5_static_th).mean() * 100
print(f"\n  Of actual top-5% trades, {top5_static_is_top5:.1f}% were already top-5% under static TP/SL")

# Top 5% static vs actual comparison
print(f"\n  Top 5% exit reason breakdown:")
for reason in ["tp", "sl", "barrier"]:
    mask = np.array([r["exit_reason"] == reason for r in results if r["is_top5pct"]])
    n = mask.sum()
    if n == 0: continue
    top5_indices = [i for i, r in enumerate(results) if r["is_top5pct"]]
    top5_adaptive_subset = np.array([results[i]["adaptive_alpha"] for i in top5_indices])
    top5_static_subset = np.array([results[i]["static_r"] for i in top5_indices])
    top5_actual_subset = np.array([results[i]["actual_r"] for i in top5_indices])
    avg_a = top5_adaptive_subset[mask].mean()
    avg_s = top5_static_subset[mask].mean()
    avg_r_ = top5_actual_subset[mask].mean()
    print(f"    {reason:15s}: n={n:4d} | avg_actual_R={avg_r_:+.4f} | avg_static_R={avg_s:+.4f} | avg_adaptive_α={avg_a:+.4f}")

# ═════════════════════════════════════════════════════════════════════════════
# FULL PORTFOLIO DECOMPOSITION TABLE
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"FULL DECOMPOSITION BY ASSET")
print(f"{'='*80}")

assets = sorted(set(r["asset"] for r in results))
print(f"\n  {'Asset':>8s} {'N':>5s} {'ActR':>8s} {'StaticR':>8s} {'AdaptR':>8s} {'Adpt%':>7s} {'EA_T+1':>8s} {'EA_T+5':>8s} {'ActWR':>6s} {'StatWR':>6s}")
print(f"  {'-'*82}")
for asset in assets:
    ar = [r for r in results if r["asset"] == asset]
    n = len(ar)
    act = np.sum([r["actual_r"] for r in ar])
    sta = np.sum([r["static_r"] for r in ar])
    ada = np.sum([r["adaptive_alpha"] for r in ar])
    ada_pct = ada / act * 100 if act != 0 else 0
    ea1 = np.mean([r["entry_alpha_t1"] for r in ar if r["entry_alpha_t1"] is not None])
    ea5 = np.mean([r["entry_alpha_t5"] for r in ar if r["entry_alpha_t5"] is not None])
    act_wr = np.mean([r["actual_r"] > 0 for r in ar]) * 100
    sta_wr = np.mean([r["static_r"] > 0 for r in ar]) * 100
    print(f"  {asset:>8s} {n:5d} {act:+8.2f} {sta:+8.2f} {ada:+8.2f} {ada_pct:6.1f}% {ea1:+8.4f} {ea5:+8.4f} {act_wr:5.1f}% {sta_wr:5.1f}% ")

# ═════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print(f"EXECUTIVE SUMMARY")
print(f"{'='*80}")

print(f"""
  Total portfolio:
    Actual PnL:          {total_actual:+8.2f}R  (100%)
    Static TP/SL PnL:    {total_static:+8.2f}R  ({total_static/total_actual*100:.1f}%)
    Adaptive exit α:     {total_adaptive:+8.2f}R  ({total_adaptive/total_actual*100:.1f}%)

  Entry quality (T+1):
    Mean T+1 return:     {t1_vals.mean():+.4f}R
    T+1 win rate:        {(t1_vals>0).mean()*100:.1f}%

  Static exit:
    Win rate:            {(static_rs>0).mean()*100:.1f}%
    Profit factor:       {abs(static_rs[static_rs>0].sum()/static_rs[static_rs<=0].sum()) if static_rs[static_rs<=0].sum()!=0 else float('inf'):.3f}

  Adaptive exit impact:
    Trades improved:     {(adaptive_alphas>0).mean()*100:.1f}%
    Trades harmed:       {(adaptive_alphas<0).mean()*100:.1f}%
    Mean adaptive α:     {adaptive_alphas.mean():+.4f}R

  Top 5% trades:
    Count:               {len(top5_r)}
    % of total PnL:      {top5_r.sum()/total_actual*100:.1f}%
    Adaptive α share:    {top5_adaptive.sum()/top5_r.sum()*100:.1f}%
    Static would have:   {top5_static.sum()/total_actual*100:.1f}% of total (if only TP/SL)
""")

print("Done.")
