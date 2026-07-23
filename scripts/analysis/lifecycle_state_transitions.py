#!/usr/bin/env python3
"""
Dynamic Stop Geometry by Lifecycle State.

Not: "Can we avoid fast SL?"
But: "Can we improve the stop policy after entry?"

Core question: is survival to candle N informative?
If a trade survives 3 candles, does its win rate improve?
If so, a "survival bonus" (wider stop) could be activated post-candle-3.

A. Survival-conditioned win rates: P(win | survive to candle N)
B. Exit reason distribution by survival time
C. Trade-off: what happens if we widen SL only after candle 3?
D. Per-asset lifecycle state machines
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

N = len(all_trades)

def get_dur(t):
    ps = t.get("prices", "")
    if isinstance(ps, str):
        return len([l for l in ps.strip().split("\n") if "dtype:" not in l and l.strip()])
    return 0

def is_win(t):
    return t["exit_reason"] in ("tp", "barrier") or t["r_multiple"] > 0


# ═════════════════════════════════════════════════════════════════════════════
# A. SURVIVAL-CONDITIONED WIN RATES
# ═════════════════════════════════════════════════════════════════════════════
print(f"Total trades: {N}")
print(f"\n{'='*80}")
print("A. WIN RATE CONDITIONAL ON SURVIVAL TO CANDLE N")
print(f"{'='*80}")

# Build survival-to-candle-N win rates
print(f"\n  {'Candle':>7s} {'N':>6s} {'Win%':>7s} {'WR_chg':>8s} {'AvgR':>8s} {'MedR':>8s} {'FastSL%':>9s} {'TP%':>6s} {'Barrier%':>10s}")
print(f"  {'-'*65}")

# Overall unconditional
all_r = np.array([t["r_multiple"] for t in all_trades])
all_win = np.array([is_win(t) for t in all_trades])
print(f"  {'All':>7s} {N:6d} {all_win.mean()*100:6.1f}% {'':>8s} {all_r.mean():+8.4f} {np.median(all_r):+8.4f} "
      f"{(sum(1 for t in all_trades if get_dur(t)<=3 and t['exit_reason']=='sl')/N*100):7.1f}% "
      f"{(sum(1 for t in all_trades if t['exit_reason']=='tp')/N*100):5.1f}% "
      f"{(sum(1 for t in all_trades if t['exit_reason']=='barrier')/N*100):8.1f}%")

for candle_n in [1, 2, 3, 4, 5, 6, 7, 10, 15, 20]:
    survived = [t for t in all_trades if get_dur(t) > candle_n]
    if not survived:
        continue
    n = len(survived)
    r_vals = np.array([t["r_multiple"] for t in survived])
    win_pct = np.mean([is_win(t) for t in survived]) * 100
    fast_sl = sum(1 for t in survived if t["exit_reason"] == "sl" and get_dur(t) <= 3) / n * 100
    tp_pct = sum(1 for t in survived if t["exit_reason"] == "tp") / n * 100
    barrier_pct = sum(1 for t in survived if t["exit_reason"] == "barrier") / n * 100
    wr_chg = all_win.mean() * 100
    
    print(f"  >{candle_n:3d}{'c':>3s} {n:6d} {win_pct:6.1f}% {win_pct-wr_chg:+7.1f}%  {r_vals.mean():+8.4f} {np.median(r_vals):+8.4f} "
          f"{fast_sl:7.1f}% {tp_pct:5.1f}% {barrier_pct:8.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# B. EXIT REASON DISTRIBUTION BY SURVIVAL TIME
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("B. EXIT REASON DISTRIBUTION BY SURVIVAL TIME")
print(f"{'='*80}")

# For each candle, what fraction of trades that reach that candle
# eventually exit via each reason?
print(f"\n  {'Candle':>7s} {'N_alive':>8s} {'→SL':>8s} {'→TP':>8s} {'→Barrier':>8s} {'Attrition':>10s}")
print(f"  {'-'*55}")

for candle_n in range(0, 21):
    alive = [t for t in all_trades if get_dur(t) >= candle_n]
    if not alive:
        continue
    n = len(alive)
    
    # Of those alive at candle N, what will they eventually become?
    future_sl = sum(1 for t in alive if t["exit_reason"] == "sl") / n * 100
    future_tp = sum(1 for t in alive if t["exit_reason"] == "tp") / n * 100
    future_barrier = sum(1 for t in alive if t["exit_reason"] == "barrier") / n * 100
    
    # How many die AT this candle?
    die_here = sum(1 for t in all_trades if get_dur(t) == candle_n)
    pct_attrition = die_here / n * 100 if n > 0 else 0
    
    print(f"  {candle_n:4d}{'c':>3s} {n:7d}  {future_sl:6.1f}% {future_tp:6.1f}% {future_barrier:8.1f}% {pct_attrition:8.1f}%")

# ═════════════════════════════════════════════════════════════════════════════
# C. COUNTERFACTUAL: SURVIVAL BONUS (widen SL after candle 3)
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("C. COUNTERFACTUAL: WIDEN SL ONLY AFTER SURVIVAL")
print(f"{'='*80}")

# For fast-SL trades that die at candle 2 or 3:
# if SL had been 1.5x wider starting at candle 2, would they have survived
# long enough to become winners?
#
# Use MAE_R as a proxy: what MAE did they ultimately experience?
# If the trade died at candle 2 with MAE_R = 0.8, that means price moved
# 0.8R against before exiting. With 1.5x SL, the stop would have been
# 50% further, potentially keeping them alive.

fast_sl_trades = [t for t in all_trades if get_dur(t) <= 3 and t['exit_reason'] == 'sl']
print(f"\n  Fast-SL trades used for widening analysis: {len(fast_sl_trades)}")

ts = fast_sl_trades
mae_rs = np.array([t.get("mae_r", 0) for t in ts])

for factor in [1.5, 2.0, 2.5]:
    saved = (mae_rs < factor).mean() * 100
    would_still_die = (mae_rs >= factor).mean() * 100
    print(f"  {factor:.1f}× SL: would save {saved:.1f}% of fast-SL, {would_still_die:.1f}% still die")

# For survivors: how many only survived because SL was tight enough
# that MAE didn't exceed it?
survs = [t for t in all_trades if t['exit_reason'] in ('tp', 'barrier')]
surv_mae = np.array([t.get("mae_r", 0) for t in survs])
would_have_died = (surv_mae >= 1.0).mean() * 100
barely_survived = ((surv_mae >= 0.8) & (surv_mae < 1.0)).mean() * 100
print(f"  Survivors: {would_have_died:.1f}% would have died at current SL (MAE ≥ 1.0R)")
print(f"  Survivors: {barely_survived:.1f}% barely survived (0.8 ≤ MAE < 1.0)")

# More detailed: what happens if we widen only from candle 3 onward?
# We need per-candle MAE data. Use MAE at candle_of_mae as proxy.
print(f"\n  Conditional stop widening simulation:")
for sl_adj in [1.25, 1.5, 1.75, 2.0, 2.5]:
    # Current: SL = X ATR
    # After candle 3: SL = X * sl_adj ATR
    # Calculate: how many fast-SL die AFTER candle 3 that wouldn't have?
    # (None, since fast-SL dies before candle 3 by definition)
    # More useful: for trades that die at candle 3+ (medium SL),
    # how many would be saved?
    medium_sl = [t for t in all_trades if t["exit_reason"] == "sl" and get_dur(t) > 3 and get_dur(t) <= 10]
    if not medium_sl:
        continue
    mae_rs = np.array([t.get("mae_r", 0) for t in medium_sl])
    saved = (mae_rs < sl_adj).mean() * 100
    net_chg = saved * abs(np.median(mae_rs)) - (100-saved) * 0.5  # rough estimate
    print(f"    After-c3 SL ×{sl_adj:.2f}: saves {saved:.1f}% of medium-SL trades (died c4-10)")

# ═════════════════════════════════════════════════════════════════════════════
# D. PER-ASSET LIFECYCLE STATE MACHINES
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("D. PER-ASSET LIFECYCLE PROFILES")
print(f"{'='*80}")

# For each asset, compute the lifecycle distribution as a state machine:
# P(enter) → P(fast_SL | enter) → P(survive_3c | enter) → P(TP|survive) → P(barrier|survive)

ASSET_GROUPS = {
    "FX-MAJOR":  ["AUDUSD", "GBPUSD", "USDJPY", "USDCAD", "NZDUSD"],
    "FX-CHF":    ["USDCHF", "EURCHF", "GBPCHF", "CADCHF", "NZDCHF"],
    "FX-CROSS":  ["EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "AUDJPY", "NZDJPY", "EURAUD"],
    "EQUITY":    ["^DJI"],
    "COMMODITY": ["GC"],
    "CRYPTO":    ["BTCUSD"],
}

assets = sorted(set(t["asset"] for t in all_trades))

print(f"\n  {'Asset':>8s} {'N':>5s} {'P(fastSL)':>10s} {'P(medSL)':>10s} {'P(TP)':>7s} {'P(barrier)':>10s} {'WR|>3c':>8s} {'E[R|>3c]':>9s} {'Lifecycle':>15s}")
print(f"  {'-'*90}")

for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    if n < 20:
        continue
    
    fast = sum(1 for t in at if get_dur(t) <= 3 and t["exit_reason"] == "sl")
    med_sl = sum(1 for t in at if get_dur(t) > 3 and t["exit_reason"] == "sl")
    tp = sum(1 for t in at if t["exit_reason"] == "tp")
    barrier = sum(1 for t in at if t["exit_reason"] == "barrier")
    
    # Conditional: survived > 3c
    survived_3c = [t for t in at if get_dur(t) > 3]
    if survived_3c:
        wr_surv = np.mean([is_win(t) for t in survived_3c]) * 100
        er_surv = np.mean([t["r_multiple"] for t in survived_3c])
    else:
        wr_surv = 0
        er_surv = 0
    
    # Lifecycle archetype
    fast_pct = fast / n * 100
    barrier_pct = barrier / n * 100
    tp_pct = tp / n * 100
    
    if barrier_pct > 30 and fast_pct < 25:
        archetype = "BARRIER"
    elif tp_pct > 25:
        archetype = "TAIL"
    elif fast_pct > 55:
        archetype = "HIGH-FAIL"
    elif barrier_pct > 20 and fast_pct < 35:
        archetype = "MIXED-BARR"
    elif tp_pct > 20:
        archetype = "TAIL-MIXED"
    else:
        archetype = "BALANCED"
    
    print(f"  {asset:>8s} {n:5d} {fast/n*100:8.1f}% {med_sl/n*100:8.1f}% {tp/n*100:6.1f}% "
          f"{barrier/n*100:8.1f}% {wr_surv:6.1f}% {er_surv:+8.4f} {archetype:>15s}")

# Archetype summary
print(f"\n  Archetype summary:")
archetypes = defaultdict(list)
for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    if n < 20: continue
    fast_pct = sum(1 for t in at if get_dur(t) <= 3 and t["exit_reason"] == "sl") / n * 100
    barrier_pct = sum(1 for t in at if t["exit_reason"] == "barrier") / n * 100
    tp_pct = sum(1 for t in at if t["exit_reason"] == "tp") / n * 100
    if barrier_pct > 20:
        archetypes["BARRIER-DOMINANT"].append(asset)
    if tp_pct > 20:
        archetypes["TAIL-DOMINANT"].append(asset)
    if fast_pct > 50:
        archetypes["HIGH-FAILURE"].append(asset)

for arch, assets_list in archetypes.items():
    print(f"    {arch:20s}: {', '.join(assets_list)}")

# ═════════════════════════════════════════════════════════════════════════════
# E. DECISION RULE: IF SURVIVED → HIGHER WIN RATE → TIGHTER RISK?
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("E. STATE-DEPENDENT RISK: INVERSE QUESTION")
print(f"{'='*80}")

# Counter-intuitive: maybe survivors should have TIGHTER risk management,
# because they have more to protect?
# If a trade has survived 10 candles, its equity is at stake.
# Should we tighten the stop to protect gains?

# For barrier trades: how much profit is given back after peak?
print(f"\n  Profit erosion in barrier trades:")
barrier_trades = [t for t in all_trades if t["exit_reason"] == "barrier"]
if barrier_trades:
    pct_erosion = []
    for t in barrier_trades:
        mfe = t.get("mfe_r", 0)
        r = t["r_multiple"]
        if mfe > 0 and r > 0:
            erosion = (mfe - r) / mfe * 100  # % of peak profit lost
            pct_erosion.append(erosion)
    if pct_erosion:
        pe = np.array(pct_erosion)
        print(f"  Mean profit erosion (peak to exit): {pe.mean():.1f}%")
        print(f"  Median: {np.median(pe):.1f}%")
        for p in [10, 25, 50, 75, 90]:
            print(f"    P{p}: {np.percentile(pe, p):.1f}% of peak profit lost")

# For TP trades: how much gain was captured?
print(f"\n  Profit capture in TP trades:")
tp_trades = [t for t in all_trades if t["exit_reason"] == "tp"]
if tp_trades:
    capture = []
    for t in tp_trades:
        mfe = t.get("mfe_r", 0)
        r = t["r_multiple"]
        if mfe > 0 and r > 0:
            cap = r / mfe * 100
            capture.append(cap)
    if capture:
        cap_arr = np.array(capture)
        print(f"  Mean TP capture (peak captured): {cap_arr.mean():.1f}%")
        print(f"  Median: {np.median(cap_arr):.1f}%")
        # How many TP trades would have done better with trailing?
        left_on_table = []
        for t in tp_trades:
            mfe = t.get("mfe_r", 0)
            r = t["r_multiple"]
            profit_left = t.get("profit_left", 0)
            if mfe > r and mfe > 0:
                left = (mfe - r) / mfe * 100
                left_on_table.append(left)
        if left_on_table:
            lo = np.array(left_on_table)
            print(f"  Trades where MFE > exit: {len(lo)}/{len(tp_trades)} ({len(lo)/len(tp_trades)*100:.1f}%)")
            print(f"  Mean profit left on table: {lo.mean():.1f}%")
            print(f"  Median: {np.median(lo):.1f}%")

print("\nDone.")
