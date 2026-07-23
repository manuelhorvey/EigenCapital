#!/usr/bin/env python3
"""
Barrier Profit Protection Simulation.

Baseline: current barrier trades (20 candles, no intervention)
Experiment A: Peak giveback exit (exit if profit erodes X% from peak)
Experiment B: Partial profit lock (lock gains at threshold)
Experiment C: Time decay (tighten exit near barrier end)

Track: Total R, Expectancy, Top 5% contribution, WR, Avg winner
"""

from __future__ import annotations
import json, sys
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

def get_prices(t):
    ps = t.get("prices", "")
    if not isinstance(ps, str):
        return []
    return [float(l.split()[1]) for l in ps.strip().split("\n") 
            if l.strip() and "dtype:" not in l]

def side_mult(t):
    return 1 if t["side"] == "BUY" else -1

def compute_candle_r(prices, entry, risk, side):
    """Compute R multiple at each candle close."""
    if risk == 0:
        return [0.0] * len(prices)
    mult = 1 if side == "BUY" else -1
    return [mult * (p - entry) / risk for p in prices]

# ── Collect barrier trades ──────────────────────────────────────────────────
barrier_trades = [t for t in all_trades if t["exit_reason"] == "barrier"]
print(f"Barrier trades: {len(barrier_trades)}")

# Only use trades with enough price data
usable = []
for t in barrier_trades:
    prices = get_prices(t)
    if len(prices) >= 5:
        entry = t["entry_price"]
        sl = t["sl_price"]
        risk = abs(entry - sl)
        side = t["side"]
        r_prices = compute_candle_r(prices, entry, risk, side)
        usable.append({
            "asset": t["asset"],
            "actual_r": t["r_multiple"],
            "mfe_r": t.get("mfe_r", 0),
            "mae_r": t.get("mae_r", 0),
            "prices": r_prices,
            "candles": len(prices),
        })

print(f"Usable barrier trades: {len(usable)}")

# Add all trades for baseline comparison
all_r = np.array([t["r_multiple"] for t in all_trades])
baseline_total_r = all_r.sum()
baseline_top5_pct = np.percentile(all_r, 95)
sorted_r = np.sort(all_r)
baseline_top5_contrib = sorted_r[int(len(sorted_r) * 0.95):].sum()

print(f"\nBaseline (all trades):")
print(f"  Total R: {baseline_total_r:+.2f}")
print(f"  Expectancy: {all_r.mean():+.4f}")
print(f"  WR: {(all_r>0).mean()*100:.1f}%")
print(f"  Top 5% threshold: {baseline_top5_pct:.2f}R")
print(f"  Top 5% contribution: {baseline_top5_contrib:+.2f}R")
print(f"  Avg winner: {all_r[all_r>0].mean():.4f}R" if (all_r>0).any() else "  Avg winner: N/A")

# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT A: PEAK GIVEBACK
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("EXPERIMENT A: PEAK GIVEBACK EXIT")
print(f"{'='*80}")

# For each barrier trade, simulate: "exit if price drops X% below peak"
# Using candle-close R values (conservative vs intra-candle)
giveback_thresholds = [0.15, 0.20, 0.30, 0.40, 0.50, 0.60]

print(f"\n  {'Giveback':>10s} {'Sim_R':>8s} {'Δ_vs_actual':>13s} {'Saved?':>8s} {'Top5_contrib':>14s} {'AvgWin':>8s} {'WR':>6s}")
print(f"  {'-'*70}")

for gb in giveback_thresholds:
    sim_rs = []
    
    for t in usable:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]  # default: actual exit
        exited_early = False
        
        for r in r_prices:
            if r > peak:
                peak = r
            # Check giveback
            if peak > 0.2:  # only act if we've seen meaningful profit
                giveback = (peak - r) / peak if peak > 0 else 0
                if giveback >= gb:
                    exit_r = r
                    exited_early = True
                    break
            # Safety: don't let it go negative
            if peak > 0 and r < 0:
                break
        
        sim_rs.append(exit_r)
    
    sim_arr = np.array(sim_rs)
    
    # Replace barrier trade Rs with simulated ones
    full_sim = all_r.copy()
    for i, t in enumerate(barrier_trades):
        if t in [u for u in usable]:
            idx = barrier_trades.index(t)
            if idx < len(sim_rs):
                # Replace this trade's R
                pass  # We need matching
    
    # Better: build the full simulated portfolio
    sim_all = []
    actual_iter = iter(all_trades)
    sim_idx = 0
    
    for t in all_trades:
        if t["exit_reason"] == "barrier" and len(get_prices(t)) >= 5:
            # Use simulated value
            sim_all.append(sim_rs[sim_idx])
            sim_idx += 1
        else:
            sim_all.append(t["r_multiple"])
    
    sim_all = np.array(sim_all)
    
    # Metrics
    total_r = sim_all.sum()
    expectancy = sim_all.mean()
    wr = (sim_all > 0).mean() * 100
    sorted_sim = np.sort(sim_all)
    top5_contrib = sorted_sim[int(len(sorted_sim) * 0.95):].sum()
    avg_win = sim_all[sim_all > 0].mean() if (sim_all > 0).any() else 0
    
    # Compare to baseline
    r_diff = total_r - baseline_total_r
    saved_trades = sum(1 for i, t in enumerate(all_trades) 
                       if t["exit_reason"] == "barrier" and sim_all[i] > t["r_multiple"])
    pct_saved = saved_trades / len(barrier_trades) * 100
    
    print(f"  {gb*100:>8.0f}% {total_r:+8.2f} {r_diff:+9.2f}R ({pct_saved*100/(len(barrier_trades)):+.1f}%) "
          f"{'SAVE' if r_diff > 0 else 'LOSE':>8s} {top5_contrib:+9.2f}R {avg_win:+7.3f}R {wr:5.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT B: PARTIAL PROFIT LOCK
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("EXPERIMENT B: PARTIAL PROFIT LOCK")
print(f"{'='*80}")

# If peak profit exceeds threshold, lock at fraction of peak
# "if MFE > X*R, set floor at Y*R"

lock_configs = [
    ("1.5R lock @ 0.5R", 1.5, 0.5),
    ("1.5R lock @ 0.75R", 1.5, 0.75),
    ("1.5R lock @ 1.0R", 1.5, 1.0),
    ("2.0R lock @ 1.0R", 2.0, 1.0),
    ("2.0R lock @ 1.25R", 2.0, 1.25),
    ("2.0R lock @ 1.5R", 2.0, 1.5),
    ("2.5R lock @ 1.5R", 2.5, 1.5),
    ("2.5R lock @ 2.0R", 2.5, 2.0),
    ("3.0R lock @ 2.0R", 3.0, 2.0),
    ("3.0R lock @ 2.5R", 3.0, 2.5),
]

print(f"\n  {'Config':>25s} {'Sim_R':>8s} {'Δ_vs_actual':>13s} {'Saved?':>8s} {'Top5_contrib':>14s} {'AvgWin':>8s} {'WR':>6s}")
print(f"  {'-'*80}")

for label, lock_at_r, floor_r in lock_configs:
    sim_rs = []
    
    for t in usable:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        locked = False
        
        for r in r_prices:
            if r > peak:
                peak = r
                if peak >= lock_at_r and not locked:
                    locked = True
                    exit_r = max(r, floor_r)  # wouldn't actually exit here
            
            # If locked and price falls below floor, exit
            if locked and r < floor_r:
                exit_r = floor_r
                break
        
        sim_rs.append(exit_r)
    
    # Build full portfolio
    sim_all = np.array([t["r_multiple"] for t in all_trades])
    sim_idx = 0
    for i, t in enumerate(all_trades):
        if t["exit_reason"] == "barrier" and len(get_prices(t)) >= 5:
            sim_all[i] = sim_rs[sim_idx]
            sim_idx += 1
    
    total_r = sim_all.sum()
    expectancy = sim_all.mean()
    wr = (sim_all > 0).mean() * 100
    sorted_sim = np.sort(sim_all)
    top5_contrib = sorted_sim[int(len(sorted_sim) * 0.95):].sum()
    avg_win = sim_all[sim_all > 0].mean() if (sim_all > 0).any() else 0
    r_diff = total_r - baseline_total_r
    saved_trades = sum(1 for i, t in enumerate(all_trades) 
                       if t["exit_reason"] == "barrier" and sim_all[i] > t["r_multiple"])
    
    print(f"  {label:>25s} {total_r:+8.2f} {r_diff:+9.2f}R "
          f"{'SAVE' if r_diff > 0 else 'LOSE':>8s} {top5_contrib:+9.2f}R {avg_win:+7.3f}R {wr:5.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT C: TIME DECAY
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("EXPERIMENT C: TIME DECAY (TIGHTEN EXIT NEAR CANDLE 15-20)")
print(f"{'='*80}")

# As trade approaches barrier (candle 15-20), tighten exit conditions
# "if after candle N, trail at XR below peak"

time_configs = [
    ("c15+ trail @ 0.5R", 15, 0.5),
    ("c15+ trail @ 1.0R", 15, 1.0),
    ("c15+ trail @ 1.5R", 15, 1.5),
    ("c15+ trail @ 2.0R", 15, 2.0),
    ("c12+ trail @ 0.5R", 12, 0.5),
    ("c12+ trail @ 1.0R", 12, 1.0),
    ("c12+ trail @ 1.5R", 12, 1.5),
    ("c18+ trail @ 0.5R", 18, 0.5),
    ("c18+ trail @ 1.0R", 18, 1.0),
]

print(f"\n  {'Config':>25s} {'Sim_R':>8s} {'Δ_vs_actual':>13s} {'Saved?':>8s} {'Top5_contrib':>14s} {'AvgWin':>8s} {'WR':>6s}")
print(f"  {'-'*80}")

for label, start_candle, trail_dist in time_configs:
    sim_rs = []
    
    for t in usable:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        
        for idx, r in enumerate(r_prices):
            if r > peak:
                peak = r
            
            # After start_candle, trail
            if idx >= start_candle and peak > trail_dist:
                if r < peak - trail_dist:
                    exit_r = r
                    break
        
        sim_rs.append(exit_r)
    
    # Build full portfolio
    sim_all = np.array([t["r_multiple"] for t in all_trades])
    sim_idx = 0
    for i, t in enumerate(all_trades):
        if t["exit_reason"] == "barrier" and len(get_prices(t)) >= 5:
            sim_all[i] = sim_rs[sim_idx]
            sim_idx += 1
    
    total_r = sim_all.sum()
    expectancy = sim_all.mean()
    wr = (sim_all > 0).mean() * 100
    sorted_sim = np.sort(sim_all)
    top5_contrib = sorted_sim[int(len(sorted_sim) * 0.95):].sum()
    avg_win = sim_all[sim_all > 0].mean() if (sim_all > 0).any() else 0
    r_diff = total_r - baseline_total_r
    
    print(f"  {label:>25s} {total_r:+8.2f} {r_diff:+9.2f}R "
          f"{'SAVE' if r_diff > 0 else 'LOSE':>8s} {top5_contrib:+9.2f}R {avg_win:+7.3f}R {wr:5.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# COMBINED: BEST OF EACH
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("COMBINED: BEST CANDIDATES FROM EACH EXPERIMENT")
print(f"{'='*80}")

combos = [
    ("A: 40% giveback", "A", 0.40),
    ("A: 50% giveback", "A", 0.50),
    ("B: 2.0R lock @ 1.0R", "B", 0),
    ("B: 2.0R lock @ 1.5R", "B", 1),
    ("C: c15+ trail @ 1.0R", "C", 1.0),
    ("C: c15+ trail @ 1.5R", "C", 1.5),
    ("A30% + C15@1.0", "AC", 0.30),
    ("A40% + C15@1.5", "AC", 0.40),
    ("A50% + C15@2.0", "AC", 0.50),
]

# We also need the actual combined simulation
# For each combo type, re-run the appropriate simulation
def simulate_a(gb, ts=usable):
    sim_rs = []
    for t in ts:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        for r in r_prices:
            if r > peak:
                peak = r
            if peak > 0.2:
                giveback = (peak - r) / peak if peak > 0 else 0
                if giveback >= gb:
                    exit_r = r
                    break
            if peak > 0 and r < 0:
                break
        sim_rs.append(exit_r)
    return np.array(sim_rs)

def simulate_b(lock_at_r, floor_r, ts=usable):
    sim_rs = []
    for t in ts:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        locked = False
        for r in r_prices:
            if r > peak:
                peak = r
                if peak >= lock_at_r and not locked:
                    locked = True
            if locked and r < floor_r:
                exit_r = floor_r
                break
        sim_rs.append(exit_r)
    return np.array(sim_rs)

def simulate_c(start_candle, trail_dist, ts=usable):
    sim_rs = []
    for t in ts:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        for idx, r in enumerate(r_prices):
            if r > peak:
                peak = r
            if idx >= start_candle and peak > trail_dist:
                if r < peak - trail_dist:
                    exit_r = r
                    break
        sim_rs.append(exit_r)
    return np.array(sim_rs)

def simulate_combined(gb, start_candle, trail_dist, ts=usable):
    """Apply giveback first, then time decay."""
    sim_rs = []
    for t in ts:
        r_prices = t["prices"]
        peak = -999
        exit_r = t["actual_r"]
        for idx, r in enumerate(r_prices):
            if r > peak:
                peak = r
            # Giveback check
            if peak > 0.2:
                giveback = (peak - r) / peak if peak > 0 else 0
                if giveback >= gb:
                    exit_r = r
                    break
            # Time decay check (after giveback check)
            if idx >= start_candle and peak > trail_dist:
                if r < peak - trail_dist:
                    exit_r = r
                    break
            if peak > 0 and r < 0:
                break
        sim_rs.append(exit_r)
    return np.array(sim_rs)

def portfolio_from_sim(sim_rs):
    sim_all = np.array([t["r_multiple"] for t in all_trades])
    idx = 0
    for i, t in enumerate(all_trades):
        if t["exit_reason"] == "barrier" and len(get_prices(t)) >= 5:
            if idx < len(sim_rs):
                sim_all[i] = sim_rs[idx]
            idx += 1
    return sim_all

print(f"\n  {'Config':>25s} {'Sim_R':>8s} {'Δ_vs_actual':>13s} {'Top5_contrib':>14s} {'AvgWin':>8s} {'WR':>6s}")
print(f"  {'-'*75}")

# Top combo results
combo_results = []

# Re-run giveback at 30%, 40%, 50%
for gb in [0.30, 0.40, 0.50]:
    sr = simulate_a(gb)
    sa = portfolio_from_sim(sr)
    tr = sa.sum()
    rd = tr - baseline_total_r
    top5 = np.sort(sa)[int(len(sa)*0.95):].sum()
    aw = sa[sa>0].mean() if (sa>0).any() else 0
    wr = (sa>0).mean()*100
    combo_results.append((tr, rd, top5, aw, wr, f"Giveback {gb*100:.0f}%"))

# Best lock (include top performers from experiment B)
for lock_r, floor_r in [(2.0, 1.0), (2.0, 1.5), (2.5, 1.5), (2.5, 2.0), (3.0, 2.0), (3.0, 2.5)]:
    sr = simulate_b(lock_r, floor_r)
    sa = portfolio_from_sim(sr)
    tr = sa.sum()
    rd = tr - baseline_total_r
    top5 = np.sort(sa)[int(len(sa)*0.95):].sum()
    aw = sa[sa>0].mean() if (sa>0).any() else 0
    wr = (sa>0).mean()*100
    combo_results.append((tr, rd, top5, aw, wr, f"Lock {lock_r}R@{floor_r}R"))

# Best time decay
for sc, td in [(15, 1.0), (15, 1.5), (12, 1.5)]:
    sr = simulate_c(sc, td)
    sa = portfolio_from_sim(sr)
    tr = sa.sum()
    rd = tr - baseline_total_r
    top5 = np.sort(sa)[int(len(sa)*0.95):].sum()
    aw = sa[sa>0].mean() if (sa>0).any() else 0
    wr = (sa>0).mean()*100
    combo_results.append((tr, rd, top5, aw, wr, f"Trail c{sc}+ @{td}R"))

# Combined
sr = simulate_combined(0.40, 15, 1.5)
sa = portfolio_from_sim(sr)
tr = sa.sum()
rd = tr - baseline_total_r
top5 = np.sort(sa)[int(len(sa)*0.95):].sum()
aw = sa[sa>0].mean() if (sa>0).any() else 0
wr = (sa>0).mean()*100
combo_results.append((tr, rd, top5, aw, wr, "A40% + C15@1.5"))

# Sort by total R
combo_results.sort(key=lambda x: -x[0])

for tr, rd, top5, aw, wr, label in combo_results:
    print(f"  {label:>25s} {tr:+8.2f} {rd:+9.2f}R {top5:+9.2f}R {aw:+7.3f}R {wr:5.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# WINNER ANALYSIS: 2.5R LOCK @ 2.0R
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("DETAIL: 2.5R LOCK @ 2.0R — TRADE-LEVEL ANALYSIS (BEST STRATEGY)")
print(f"{'='*80}")

best_lock_r, best_floor_r = 2.5, 2.0
lock_rs = simulate_b(best_lock_r, best_floor_r)

lock_deltas = []
lock_actual = []
lock_sim = []
for i, t in enumerate(usable):
    delta = lock_rs[i] - t["actual_r"]
    lock_deltas.append(delta)
    lock_actual.append(t["actual_r"])
    lock_sim.append(lock_rs[i])

lock_deltas = np.array(lock_deltas)
lock_actual = np.array(lock_actual)
lock_sim = np.array(lock_sim)

print(f"\n  Barrier trade impact of {best_lock_r}R lock @ {best_floor_r}R floor:")
print(f"  Actual mean R: {lock_actual.mean():.4f}")
print(f"  Simulated mean R: {lock_sim.mean():.4f}")
print(f"  Mean change: {lock_deltas.mean():+.4f}R")
print(f"  Trades improved: {(lock_deltas > 0).sum()} / {len(lock_deltas)} ({(lock_deltas>0).mean()*100:.1f}%)")
print(f"  Trades harmed: {(lock_deltas < 0).sum()} / {len(lock_deltas)} ({(lock_deltas<0).mean()*100:.1f}%)")

print(f"\n  Trades harmed by lock (Δ < -0.2R):")
harmed = [(lock_deltas[i], lock_actual[i], lock_sim[i], usable[i]) for i in range(len(lock_deltas)) if lock_deltas[i] < -0.2]
harmed.sort(key=lambda x: x[0])
for d, a, s, t in harmed[:10]:
    print(f"    {t['asset']:>8s}: actual={a:+.2f}R → sim={s:+.2f}R (Δ={d:+.2f}R, peak_close={max(t['prices']):.2f}R)")

thresh_95 = np.percentile(lock_actual, 95)
top5_actual = [lock_actual[i] for i in range(len(lock_actual)) if lock_actual[i] >= thresh_95]
top5_sim = [lock_sim[i] for i in range(len(lock_sim)) if lock_actual[i] >= thresh_95]
if top5_actual:
    print(f"\n  Top 5% barrier trades (threshold: {thresh_95:.2f}R, n={len(top5_actual)}):")
    print(f"    Actual mean: {np.mean(top5_actual):.4f}R")
    print(f"    Lock mean: {np.mean(top5_sim):.4f}R")
    print(f"    Change: {np.mean(top5_sim) - np.mean(top5_actual):+.4f}R")
    tail_preserved = sum(1 for s, a in zip(top5_sim, top5_actual) if s >= a)
    print(f"    Trades preserved/improved: {tail_preserved}/{len(top5_actual)} ({tail_preserved/len(top5_actual)*100:.0f}%)")

print(f"\n  Asset breakdown:")
assets = sorted(set(t["asset"] for t in usable))
for asset in assets:
    idxs = [i for i, t in enumerate(usable) if t["asset"] == asset]
    if not idxs or len(idxs) < 5:
        continue
    a_r = np.array([lock_actual[i] for i in idxs])
    s_r = np.array([lock_sim[i] for i in idxs])
    d_r = s_r - a_r
    print(f"    {asset:>8s}: n={len(idxs):3d} | actual={a_r.mean():+.2f} → sim={s_r.mean():+.2f} (Δ={d_r.mean():+.2f}) | improved={(d_r>0).mean()*100:.0f}%")

print("\nDone.")
