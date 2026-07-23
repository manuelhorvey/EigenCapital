#!/usr/bin/env python3
"""
A: TP Architecture Research.
B: Barrier Exit Optimization.
C: Trade Lifecycle State Machine.

Three analyses in one pass from the trade lifecycle data.
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

def parse_prices(t):
    p = t.get("prices", "")
    if isinstance(p, str):
        vals = []
        for l in p.strip().split("\n"):
            if "dtype:" in l: continue
            parts = l.strip().split()
            if len(parts) >= 2:
                try: vals.append(float(parts[-1]))
                except: pass
        return np.array(vals) if vals else None
    return np.array(p, dtype=float) if isinstance(p, list) else None

def calc_r(entry, price, sl, tp, side):
    risk = abs(entry - sl)
    if risk < 1e-10: return 0.0
    return ((entry - price) if side == "SELL" else (price - entry)) / risk

# ── Per-trade features ──────────────────────────────────────────────────────
for t in all_trades:
    side = t["side"]
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    risk = abs(entry - sl)
    t["_risk"] = risk
    t["_implied_r"] = abs(entry - tp) / risk if risk > 0 else 0
    t["_actual_r"] = t["r_multiple"]
    t["_tp_reached"] = False
    t["_sl_reached"] = False
    t["_max_reached_r"] = 0.0
    t["_tp_touched_candle"] = None
    t["_exit_candle"] = None

    highs = t.get("highs", [])
    lows = t.get("lows", [])
    n = min(len(highs), len(lows))
    
    for i in range(n):
        if side == "SELL":
            if lows[i] <= tp:  # price hit TP (went below for sell)
                t["_tp_reached"] = True
                if t["_tp_touched_candle"] is None:
                    t["_tp_touched_candle"] = i
            if highs[i] >= sl:
                t["_sl_reached"] = True
        else:
            if highs[i] >= tp:
                t["_tp_reached"] = True
                if t["_tp_touched_candle"] is None:
                    t["_tp_touched_candle"] = i
            if lows[i] <= sl:
                t["_sl_reached"] = True
    
    if n > 0:
        t["_exit_candle"] = n - 1

print(f"Loaded {N} trades\n")

# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS A: TP ARCHITECTURE RESEARCH
# ═════════════════════════════════════════════════════════════════════════════
print("=" * 80)
print("ANALYSIS A: TP ARCHITECTURE RESEARCH")
print("=" * 80)

# A1. TP multiplier distribution
implied_rs = np.array([t["_implied_r"] for t in all_trades])
print(f"\nA1. TP Multiplier (Implied R) Distribution:")
print(f"  {'Stat':>10s} {'Value':>10s}")
print(f"  {'-'*22}")
for p in [5, 10, 25, 50, 75, 90, 95, 99]:
    print(f"  P{p:>3d}: {np.percentile(implied_rs, p):>9.2f}x")
print(f"  Mean: {implied_rs.mean():>9.2f}x")
print(f"  Min:  {implied_rs.min():>9.2f}x")
print(f"  Max:  {implied_rs.max():>9.2f}x")

# By asset
print(f"\n  By asset:")
for asset in sorted(set(t["asset"] for t in all_trades)):
    at = [t for t in all_trades if t["asset"] == asset]
    irs = np.array([t["_implied_r"] for t in at])
    print(f"  {asset:>8s}: mean={irs.mean():.2f}x median={np.median(irs):.2f}x P90={np.percentile(irs,90):.2f}x")

# A2. TP Hit Probability
tp_reached = sum(1 for t in all_trades if t["_tp_reached"])
sl_reached = sum(1 for t in all_trades if t["_sl_reached"])
both_reached = sum(1 for t in all_trades if t["_tp_reached"] and t["_sl_reached"])
neither = sum(1 for t in all_trades if not t["_tp_reached"] and not t["_sl_reached"])

print(f"\nA2. Barrier Hit Probability:")
print(f"  TP touched at any point: {tp_reached:6d} ({tp_reached/N*100:.1f}%)")
print(f"  SL touched at any point: {sl_reached:6d} ({sl_reached/N*100:.1f}%)")
print(f"  Both touched:            {both_reached:6d} ({both_reached/N*100:.1f}%)")
print(f"  Neither touched:         {neither:6d} ({neither/N*100:.1f}%)")

# TP hit probability by implied R bucket
print(f"\n  TP hit probability by implied R bucket:")
buckets_ir = [(0, 2), (2, 3), (3, 3.5), (3.5, 4), (4, 5), (5, 8), (8, 999)]
for lo, hi in buckets_ir:
    mask = (implied_rs >= lo) & (implied_rs < hi)
    n = mask.sum()
    if n == 0: continue
    tp_hit = sum(1 for t in all_trades if t["_tp_reached"] and lo <= t["_implied_r"] < hi)
    print(f"    ImpliedR [{lo:4.0f},{hi:4.0f}): n={n:5d} | TP_touched={tp_hit:4d} ({tp_hit/n*100:.1f}%)")

# A3. TP Efficiency (for TP-exit trades)
tp_trades = [t for t in all_trades if t["exit_reason"] == "tp"]
tp_efficiencies = []
for t in tp_trades:
    implied = t["_implied_r"]
    actual = t["_actual_r"]
    eff = actual / implied * 100 if implied > 0 else 0
    tp_efficiencies.append(eff)

print(f"\nA3. TP Efficiency (actual R / implied R for TP-exit trades):")
tp_eff = np.array(tp_efficiencies)
print(f"  Trades: {len(tp_eff)}")
print(f"  Mean efficiency: {tp_eff.mean():.1f}%")
print(f"  Median efficiency: {np.median(tp_eff):.1f}%")
for p in [10, 25, 75, 90]:
    print(f"  P{p:2d} efficiency: {np.percentile(tp_eff, p):.1f}%")

# For top-5% TP trades, how much overshoot?
top5_th = np.percentile(r_vals, 95)
tp_top5 = [t for t in tp_trades if t["_actual_r"] >= top5_th]
if tp_top5:
    top5_eff = np.array([t["_actual_r"] / t["_implied_r"] * 100 for t in tp_top5])
    print(f"\n  For top-5% TP trades ({len(tp_top5)}):")
    print(f"    Mean efficiency: {top5_eff.mean():.1f}%")
    print(f"    Mean implied R: {np.mean([t['_implied_r'] for t in tp_top5]):.2f}x")
    print(f"    Mean overshoot: {np.mean([t['_actual_r'] - t['_implied_r'] for t in tp_top5]):+.4f}R")

# A4. When TP was touched vs when exit happened
print(f"\nA4. Candle of first TP touch vs exit (for TP-exit trades):")
for asset in sorted(set(t["asset"] for t in tp_trades)):
    at = [t for t in tp_trades if t["asset"] == asset]
    if not at: continue
    touch_to_exit = []
    for t in at:
        tc = t["_tp_touched_candle"]
        xc = t["_exit_candle"]
        if tc is not None and xc is not None:
            touch_to_exit.append(max(0, xc - tc))
    if touch_to_exit:
        print(f"  {asset:>8s}: n={len(at):4d} | mean_candles_after_touch={np.mean(touch_to_exit):.1f} | median={np.median(touch_to_exit):.0f}")

# A5. TP-not-hit trades: what happened?
tp_not_hit = [t for t in all_trades if not t["_tp_reached"]]
tp_not_hit_exits = defaultdict(int)
for t in tp_not_hit:
    tp_not_hit_exits[t["exit_reason"]] += 1
print(f"\nA5. Trades where TP was never touched ({len(tp_not_hit)}):")
for reason, n in sorted(tp_not_hit_exits.items()):
    print(f"  {reason:15s}: {n:5d} ({n/len(tp_not_hit)*100:.1f}%)")

# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS B: BARRIER EXIT OPTIMIZATION
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("ANALYSIS B: BARRIER EXIT OPTIMIZATION")
print("=" * 80)

barrier_trades = [t for t in all_trades if t["exit_reason"] == "barrier"]
n_barrier = len(barrier_trades)
barrier_winners = [t for t in barrier_trades if t["_actual_r"] > 0]
barrier_losers = [t for t in barrier_trades if t["_actual_r"] <= 0]

print(f"\nB1. Barrier exit summary:")
print(f"  Total barrier exits: {n_barrier} ({n_barrier/N*100:.1f}% of all trades)")
print(f"  Barrier winners:     {len(barrier_winners)} ({len(barrier_winners)/n_barrier*100:.1f}% win rate)")
print(f"  Barrier losers:      {len(barrier_losers)}")
print(f"  Total barrier PnL:   {sum(t['_actual_r'] for t in barrier_trades):+.2f}R")

# Metrics at time of barrier exit
print(f"\nB2. Barrier exit characteristics:")
for label, subset in [("Winners", barrier_winners), ("Losers", barrier_losers), ("All", barrier_trades)]:
    if not subset: continue
    rs = [t["_actual_r"] for t in subset]
    mae = [t["mae_r"] for t in subset]
    duration = []
    for t in subset:
        prices = t.get("prices", "")
        if isinstance(prices, str):
            d = len([l for l in prices.strip().split("\n") if "dtype:" not in l])
            duration.append(d if d > 0 else 1)
        else:
            duration.append(1)
    print(f"  {label:10s}: n={len(subset):4d} | avg_R={np.mean(rs):+.4f} | "
          f"avg_MAE={np.mean(mae):+.4f}R | avg_dur={np.mean(duration):.1f}c")

# B3. Confidence at barrier entry
print(f"\nB3. Confidence at entry for barrier trades:")
for label, subset in [("Winners", barrier_winners), ("Losers", barrier_losers)]:
    if not subset: continue
    confs = []
    prob_gaps = []
    for t in subset:
        side = t["side"]
        pl = t.get("prob_long", 0.5)
        ps = t.get("prob_short", 0.5)
        c = pl if side == "BUY" else ps
        confs.append(c)
        prob_gaps.append(abs(pl - ps))
    confs = np.array(confs)
    print(f"  {label:10s}: mean_conf={confs.mean():.4f} median_conf={np.median(confs):.4f} "
          f"mean_gap={np.mean(prob_gaps):.4f}")

# B4. Time to barrier exit
print(f"\nB4. When does the barrier trigger?")
for label, subset in [("All barrier", barrier_trades), ("Winners", barrier_winners), ("Losers", barrier_losers)]:
    if not subset: continue
    candles_at_exit = []
    for t in subset:
        c = t.get("_exit_candle")
        if c is not None:
            candles_at_exit.append(c)
    if candles_at_exit:
        ca = np.array(candles_at_exit)
        print(f"  {label:12s}: n={len(subset):4d} | exit_candle_mean={ca.mean():.1f} median={np.median(ca):.0f} P90={np.percentile(ca,90):.0f}")

# B5. Barrier by asset
print(f"\nB5. Barrier exit by asset:")
assets_barrier = sorted(set(t["asset"] for t in barrier_trades))
for asset in assets_barrier:
    at = [t for t in barrier_trades if t["asset"] == asset]
    n = len(at)
    wins = sum(1 for t in at if t["_actual_r"] > 0)
    wr = wins / n * 100
    total_r = sum(t["_actual_r"] for t in at)
    all_for_asset = [t for t in all_trades if t["asset"] == asset]
    barrier_pct = n / len(all_for_asset) * 100
    print(f"  {asset:>8s}: barrier_n={n:4d} ({barrier_pct:.0f}% of trades) | "
          f"WR={wr:.1f}% | total_R={total_r:+.2f}")

# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS C: TRADE LIFECYCLE STATE MACHINE
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("ANALYSIS C: TRADE LIFECYCLE STATE MACHINE")
print("=" * 80)

# Define states based on observable data:
# STATE 0: Entry (candle 0)
# STATE 1: Early (candles 1-3) — validation period
# STATE 2: Mid (candles 4-10) — trend developing
# STATE 3: Late (candles 11+) — extended hold
# STATE 4: Barrier-activated (only for barrier exits)
# STATE 5: Exit

# For each trade, classify into a path
paths = defaultdict(list)
for t in all_trades:
    r = t["_actual_r"]
    exit_reason = t["exit_reason"]
    duration = t.get("_exit_candle", 0) or 0
    
    tp_touched = t["_tp_reached"]
    sl_touched = t["_sl_reached"]
    tp_candle = t.get("_tp_touched_candle")
    
    # Build path signature
    if exit_reason == "tp":
        if tp_candle is not None and tp_candle <= 5:
            path = "fast_tp"
        elif tp_candle is not None and tp_candle <= 15:
            path = "medium_tp"
        else:
            path = "slow_tp"
    elif exit_reason == "barrier":
        path = "barrier"
    else:  # sl
        if duration <= 3:
            path = "fast_sl"
        elif duration <= 10:
            path = "medium_sl"
        else:
            path = "slow_sl"
    
    paths[path].append({
        "r": r,
        "asset": t["asset"],
        "duration": duration,
        "tp_touched": tp_touched,
        "sl_touched": sl_touched,
    })

print(f"\nC1. Trade lifecycle paths:")
print(f"  {'Path':<20s} {'N':>6s} {'Pct':>6s} {'AvgR':>8s} {'MedR':>8s} {'WR%':>6s} {'PF':>7s} {'AvgDur':>7s}")
print(f"  {'-'*70}")
for path in ["fast_tp", "medium_tp", "slow_tp", "barrier", "fast_sl", "medium_sl", "slow_sl"]:
    group = paths.get(path, [])
    if not group: continue
    n = len(group)
    rs = np.array([g["r"] for g in group])
    wins = rs[rs > 0]; losses = rs[rs <= 0]
    wr = len(wins)/n*100
    pf = abs(wins.sum()/losses.sum()) if losses.sum()!=0 else float("inf")
    durs = [g["duration"] for g in group]
    print(f"  {path:<20s} {n:6d} {n/N*100:5.1f}% {rs.mean():+8.4f} {np.median(rs):+8.4f} "
          f"{wr:5.1f}% {pf:7.3f} {np.mean(durs):6.1f}")

# C2. State transition matrix: what happens at each candle
print(f"\nC2. Trade progression by candle:")
for nc in [1, 3, 5, 10, 20, 30]:
    survived = [t for t in all_trades if (t.get("_exit_candle") or 999) >= nc]
    still_alive = len(survived)
    if still_alive == 0: continue
    # How many of these are in profit at this point?
    in_profit = 0
    for t in survived:
        prices = t.get("prices", "")
        if isinstance(prices, str):
            vals = []
            for l in prices.strip().split("\n"):
                if "dtype:" in l: continue
                parts = l.strip().split()
                if len(parts) >= 2:
                    try: vals.append(float(parts[-1]))
                    except: pass
            if len(vals) > nc:
                p = vals[min(nc, len(vals)-1)]
                entry = t["entry_price"]
                sl = t["sl_price"]
                tp = t["tp_price"]
                side = t["side"]
                r_at_c = ((entry - p) if side == "SELL" else (p - entry)) / max(0.0001, abs(entry - sl))
                if r_at_c > 0:
                    in_profit += 1
    
    pct_profit = in_profit / still_alive * 100
    # Average R at this point
    rs_at_c = []
    for t in survived:
        prices = t.get("prices", "")
        if isinstance(prices, str):
            vals = []
            for l in prices.strip().split("\n"):
                if "dtype:" in l: continue
                parts = l.strip().split()
                if len(parts) >= 2:
                    try: vals.append(float(parts[-1]))
                    except: pass
            if len(vals) > nc:
                p = vals[min(nc, len(vals)-1)]
                entry = t["entry_price"]
                sl = t["sl_price"]
                side = t["side"]
                r_at_c = ((entry - p) if side == "SELL" else (p - entry)) / max(0.0001, abs(entry - sl))
                rs_at_c.append(r_at_c)
    mean_r = np.mean(rs_at_c) if rs_at_c else 0
    print(f"  Candle {nc:2d}: {still_alive:5d} trades alive ({still_alive/N*100:.1f}%) | "
          f"{pct_profit:.1f}% in profit | mean_R={mean_r:+.4f}")

# C3. Path profitability by asset
print(f"\nC3. Dominant path by asset:")
for asset in sorted(set(t["asset"] for t in all_trades)):
    at = [t for t in all_trades if t["asset"] == asset]
    path_counts = defaultdict(int)
    path_r = defaultdict(float)
    for t in at:
        r = t["_actual_r"]
        exit_reason = t["exit_reason"]
        duration = t.get("_exit_candle", 0) or 0
        tp_candle = t.get("_tp_touched_candle")
        
        if exit_reason == "tp":
            if tp_candle is not None and tp_candle <= 5: p = "fast_tp"
            elif tp_candle is not None and tp_candle <= 15: p = "medium_tp"
            else: p = "slow_tp"
        elif exit_reason == "barrier": p = "barrier"
        else:
            if duration <= 3: p = "fast_sl"
            elif duration <= 10: p = "medium_sl"
            else: p = "slow_sl"
        path_counts[p] += 1
        path_r[p] += r
    
    if path_counts:
        dominant = max(path_counts, key=path_counts.get)
        dominant_pct = path_counts[dominant] / len(at) * 100
        print(f"  {asset:>8s}: dominant={dominant:15s} ({dominant_pct:.0f}% of trades) | "
              f"top3: {', '.join(sorted(path_counts, key=path_counts.get, reverse=True)[:3])}")

print("\nDone.")
