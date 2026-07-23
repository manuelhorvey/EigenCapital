#!/usr/bin/env python3
"""
Early Failure Analysis.

Profiles the 45% of trades that die within 3 candles (fast_sl)
vs everything else. Goal: find entry-time signals to avoid the
most obvious failures.

Questions:
  1. Feature profile: confidence, implied R, ATR, asset, side, signal age
  2. Asset concentration
  3. Regime / volatility clustering
  4. Confidence × asset interaction
  5. Can we build a simple rule to trim 10-20% of failures?
"""

from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
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

# ── Classify trades ─────────────────────────────────────────────────────────
fast_sl = []
survivors = []
other_sl = []  # medium + slow SL
tp_trades = []
barrier_trades = []

for t in all_trades:
    side = t["side"]
    pl = t.get("prob_long", 0.5)
    ps = t.get("prob_short", 0.5)
    conf = pl if side == "BUY" else ps
    gap = abs(pl - ps)
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    risk = abs(entry - sl)
    implied_r = abs(entry - tp) / risk if risk > 0 else 0
    atr = t.get("atr_pct_entry", 0.01)
    
    # Duration
    prices = t.get("prices", "")
    dur = 0
    if isinstance(prices, str):
        dur = len([l for l in prices.strip().split("\n") if "dtype:" not in l and l.strip()])
    
    metadata = {
        "asset": t["asset"],
        "side": side,
        "conf": conf,
        "gap": gap,
        "implied_r": implied_r,
        "atr": atr,
        "dur": dur,
        "r": t["r_multiple"],
        "mae_r": t.get("mae_r", 0),
        "exit_reason": t["exit_reason"],
    }
    
    if t["exit_reason"] == "sl":
        if dur <= 3:
            fast_sl.append(metadata)
        else:
            other_sl.append(metadata)
    elif t["exit_reason"] == "tp":
        tp_trades.append(metadata)
    elif t["exit_reason"] == "barrier":
        barrier_trades.append(metadata)
    else:
        survivors.append(metadata)

# Also create a "non-failure" group for comparison
non_failures = survivors + tp_trades + barrier_trades  # trades with positive outcome
other_sl_only = other_sl  # slower losses
all_non_fast = survivors + tp_trades + barrier_trades + other_sl

print(f"Classification:")
print(f"  fast_sl (≤3c):    {len(fast_sl):6d} ({len(fast_sl)/N*100:.1f}%)")
print(f"  other_sl (>3c):   {len(other_sl):6d} ({len(other_sl)/N*100:.1f}%)")
print(f"  tp:               {len(tp_trades):6d} ({len(tp_trades)/N*100:.1f}%)")
print(f"  barrier:          {len(barrier_trades):6d} ({len(barrier_trades)/N*100:.1f}%)")
print(f"  other (expiry):   {len(survivors):6d} ({len(survivors)/N*100:.1f}%)")
print(f"  Total:            {N}")

# ═════════════════════════════════════════════════════════════════════════════
# 1. FEATURE PROFILE
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("1. FEATURE PROFILE: FAST SL vs ALL OTHERS")
print(f"{'='*80}")

features = ["conf", "gap", "implied_r", "atr"]

for feat in features:
    fs = np.array([t[feat] for t in fast_sl])
    nf = np.array([t[feat] for t in all_non_fast])
    diff = fs.mean() - nf.mean()
    pooled_std = np.sqrt((fs.var() + nf.var()) / 2)
    d = diff / pooled_std if pooled_std > 0 else 0
    print(f"\n  {feat}:")
    print(f"    fast_sl:     mean={fs.mean():.4f} median={np.median(fs):.4f}")
    print(f"    non-failure: mean={nf.mean():.4f} median={np.median(nf):.4f}")
    print(f"    Δ={diff:+8.4f}  Cohen's d={d:+.3f}")
    for p in [10, 25, 50, 75, 90]:
        print(f"      P{p:2d}: fast_sl={np.percentile(fs,p):.4f}  non_fail={np.percentile(nf,p):.4f}")

# ═════════════════════════════════════════════════════════════════════════════
# 2. ASSET CONCENTRATION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("2. ASSET CONCENTRATION OF FAST SL")
print(f"{'='*80}")

assets = sorted(set(t["asset"] for t in all_trades))
print(f"\n  {'Asset':>8s} {'N':>5s} {'FastSL':>7s} {'FastSL%':>8s} {'AvgLoss':>8s} {'MedLoss':>8s} {'Conf':>7s} {'ATR':>7s}")
print(f"  {'-'*65}")
for asset in assets:
    at = [t for t in fast_sl if t["asset"] == asset]
    n = len(at)
    total = sum(1 for t in all_trades if t["asset"] == asset)
    pct = n / total * 100 if total > 0 else 0
    losses = np.array([t["r"] for t in at])
    confs = np.array([t["conf"] for t in at])
    atrs = np.array([t["atr"] for t in at])
    print(f"  {asset:>8s} {total:5d} {n:7d} {pct:7.1f}% {losses.mean():+8.4f} {np.median(losses):+8.4f} "
          f"{confs.mean():.4f} {atrs.mean():.4f}")

# ═════════════════════════════════════════════════════════════════════════════
# 3. CONFIDENCE × ASSET INTERACTION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("3. FAST SL RATE BY CONFIDENCE × ASSET GROUP")
print(f"{'='*80}")

ASSET_GROUPS = {
    "FX-MAJOR":  ["AUDUSD", "GBPUSD", "USDJPY", "USDCAD", "NZDUSD"],
    "FX-CHF":    ["USDCHF", "EURCHF", "GBPCHF", "CADCHF", "NZDCHF"],
    "FX-CROSS":  ["EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "AUDJPY", "NZDJPY", "EURAUD"],
    "EQUITY":    ["^DJI"],
    "COMMODITY": ["GC"],
    "CRYPTO":    ["BTCUSD"],
}

def get_dur(t):
    ps = t.get("prices", "")
    if isinstance(ps, str):
        return len([l for l in ps.strip().split("\n") if "dtype:" not in l and l.strip()])
    return 0

def is_fast_sl(t):
    return t["exit_reason"] == "sl" and get_dur(t) <= 3

for gname, gassets in ASSET_GROUPS.items():
    print(f"\n  {gname}:")
    for lo, hi in [(0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]:
        bucket = [t for t in all_trades if t["asset"] in gassets and lo <= (
            (t["prob_long"] if t["side"]=="BUY" else t["prob_short"])) < hi]
        if not bucket:
            continue
        n = len(bucket)
        n_fast = sum(1 for t in bucket if is_fast_sl(t))
        pct = n_fast / n * 100 if n > 0 else 0
        print(f"    conf [{lo:.1f},{hi:.1f}): n={n:5d} | fast_sl={n_fast:4d} ({pct:5.1f}%)")

# ═════════════════════════════════════════════════════════════════════════════
# 4. WHAT IF WE REMOVE THE WORST X%?
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("4. COUNTERFACTUAL: REMOVE FAST SL BY RULE")
print(f"{'='*80}")

# Best single-rule: find threshold on each feature that maximizes
# (failures avoided) / (false positives)
# We want to filter out trades that LOOK like fast_sl at entry time.

for feat in features:
    fs_vals = np.array([t[feat] for t in fast_sl])
    nf_vals = np.array([t[feat] for t in all_non_fast])
    
    best_net = -9999
    best_th = 0
    best_dir = 0  # 1 = above, -1 = below
    
    for p in range(5, 100, 5):
        th = np.percentile(np.concatenate([fs_vals, nf_vals]), p)
        # Try: filter OUT trades above threshold
        for direction in [1, -1]:
            if direction == 1:
                # Filter out trades with feat >= th (these look like fast_sl)
                removed_fast = (fs_vals >= th).sum()
                removed_good = (nf_vals >= th).sum()
            else:
                removed_fast = (fs_vals < th).sum()
                removed_good = (nf_vals < th).sum()
            
            if removed_fast == 0:
                continue
            
            # Net benefit: failures avoided - good trades accidentally removed
            loss_per_fast = abs(np.mean([t["r"] for t in fast_sl]))  # ~0.76
            gain_per_good = abs(np.mean([t["r"] for t in all_non_fast]))  # ~0.5
            net = removed_fast * loss_per_fast - removed_good * gain_per_good
            
            if net > best_net:
                best_net = net
                best_th = th
                best_dir = direction
    
    # Report best rule
    if best_dir == 1:
        rule_desc = f"{feat} >= {best_th:.4f}"
        fs_removed = (fs_vals >= best_th).sum()
        nf_removed = (nf_vals >= best_th).sum()
    else:
        rule_desc = f"{feat} < {best_th:.4f}"
        fs_removed = (fs_vals < best_th).sum()
        nf_removed = (nf_vals < best_th).sum()
    
    loss_per_fast = abs(np.mean([t["r"] for t in fast_sl]))
    gain_per_good = np.mean([t["r"] for t in all_non_fast])
    net_r = fs_removed * loss_per_fast - nf_removed * gain_per_good
    pct_fast_removed = fs_removed / len(fast_sl) * 100
    pct_good_hit = nf_removed / len(all_non_fast) * 100
    
    print(f"\n  Best rule using '{feat}':")
    print(f"    Rule: {rule_desc}")
    print(f"    Removes {fs_removed}/{len(fast_sl)} fast_SL ({pct_fast_removed:.1f}%)")
    print(f"    Collateral damage: {nf_removed}/{len(all_non_fast)} non-fast-SL ({pct_good_hit:.1f}%)")
    print(f"    Net R benefit: ~{net_r:.1f}R")

# ═════════════════════════════════════════════════════════════════════════════
# 5. MULTIVARIATE: BEST 2-FEATURE COMBINATION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("5. BEST 2-FEATURE RULE (greedy search)")
print(f"{'='*80}")

# Try combinations: asset_group + confidence
for gname, gassets in ASSET_GROUPS.items():
    for lo, hi in [(0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]:
        bucket = []
        for t in all_trades:
            if t["asset"] not in gassets: continue
            side = t["side"]
            conf = t["prob_long"] if side == "BUY" else t["prob_short"]
            if lo <= conf < hi:
                bucket.append(t)
        n = len(bucket)
        if n < 50: continue
        n_fast = 0
        for t in bucket:
            ps = t.get("prices", "")
            dur = len([l for l in ps.strip().split("\n") if "dtype:" not in l and l.strip()]) if isinstance(ps, str) else 0
            if t["exit_reason"] == "sl" and dur <= 3:
                n_fast += 1
        pct = n_fast / n * 100

# ═════════════════════════════════════════════════════════════════════════════
# 6. SIMULATION: REMOVE WORST BUCKETS
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("6. COUNTERFACTUAL SIMULATION: SKIP HIGH-FAILURE BUCKETS")
print(f"{'='*80}")

# Identify buckets with >50% fast_sl rate
skip_rules = []
for gname, gassets in ASSET_GROUPS.items():
    for lo, hi in [(0.5, 0.7), (0.7, 0.8)]:
        bucket = [t for t in all_trades if t["asset"] in gassets and 
                  lo <= (t["prob_long"] if t["side"]=="BUY" else t["prob_short"]) < hi]
        n = len(bucket)
        if n < 50: continue
        n_fast = sum(1 for t in bucket if is_fast_sl(t))
        pct = n_fast / n * 100
        if pct > 45:
            total_r_bucket = sum(t["r_multiple"] for t in bucket)
            skip_rules.append((gname, lo, hi, n, pct, total_r_bucket))

print(f"  Identified {len(skip_rules)} buckets with >45% fast_sl rate:")
total_skipped = 0
total_saved = 0
for g, lo, hi, n, pct, tr in sorted(skip_rules, key=lambda x: -x[4]):
    print(f"    [{g:12s}, conf [{lo:.1f},{hi:.1f})]: n={n:4d} | fast_sl={pct:.0f}% | total_R={tr:+.2f}")
    total_skipped += n
    total_saved += tr

# Full simulation: skip these buckets
remaining = [t for t in all_trades if not any(
    t["asset"] in ASSET_GROUPS[g] and 
    lo <= (t["prob_long"] if t["side"]=="BUY" else t["prob_short"]) < hi
    for g, lo, hi, _, _, _ in skip_rules
)]

if remaining:
    r_remaining = np.array([t["r_multiple"] for t in remaining])
    r_all = np.array([t["r_multiple"] for t in all_trades])
    
    # Statistics
    print(f"\n  Simulation results:")
    print(f"  Skipped trades: {total_skipped} ({total_skipped/N*100:.1f}%)")
    print(f"  Total R (original):     {r_all.sum():+.2f}")
    print(f"  Total R (skipped R):    {total_saved:+.2f}")
    print(f"  Total R (after skip):   {r_remaining.sum():+.2f}")
    print(f"  Expectancy (original):  {r_all.mean():+.4f}")
    print(f"  Expectancy (after):     {r_remaining.mean():+.4f}")
    print(f"  WR (original):          {(r_all>0).mean()*100:.1f}%")
    print(f"  WR (after):             {(r_remaining>0).mean()*100:.1f}%")

print("\nDone.")
