#!/usr/bin/env python3
"""
Structural Fast-SL Decomposition.

Not prediction — mechanics.
Why does a trade hit SL in 3 candles?

A. SL Distance (ATR-scaled) → fast-SL probability curve
B. TP/SL geometry: implied_r, SL ATR, TP ATR
C. Volatility regime: high/low/expanding/contracting at entry
D. First 3 candle MAE/MFE path comparison
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

def get_dur(t):
    ps = t.get("prices", "")
    if isinstance(ps, str):
        return len([l for l in ps.strip().split("\n") if "dtype:" not in l and l.strip()])
    return 0

def is_fast_sl(t):
    return t["exit_reason"] == "sl" and get_dur(t) <= 3

def parse_prices(t):
    """Return close price list."""
    ps = t.get("prices", "")
    if not isinstance(ps, str) or not ps.strip():
        return []
    lines = [l.strip() for l in ps.strip().split("\n") if l.strip() and "dtype:" not in l]
    prices = []
    for line in lines:
        parts = line.split(",")
        try:
            prices.append(float(parts[0]))
        except:
            prices.append(np.nan)
    return prices

# Pre-classify
fast_sl = []
fast_sl_assets = defaultdict(list)
survivors_by_exit = defaultdict(list)
all_non_fast = []
all_others = []

for t in all_trades:
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    risk = abs(entry - sl)
    reward = abs(entry - tp)
    atr = t.get("atr_pct_entry", 0.01)
    
    side = t["side"]
    conf = t.get("prob_long" if side == "BUY" else "prob_short", 0.5)
    gap = abs(t.get("prob_long", 0.5) - t.get("prob_short", 0.5))
    implied_r = reward / risk if risk > 0 else 0
    
    sl_atr = risk / (atr * entry) if atr * entry > 0 else 0
    tp_atr = reward / (atr * entry) if atr * entry > 0 else 0
    
    meta = {
        "asset": t["asset"],
        "side": side,
        "conf": conf,
        "gap": gap,
        "sl_atr": sl_atr,
        "tp_atr": tp_atr,
        "implied_r": implied_r,
        "atr": atr,
        "r": t["r_multiple"],
        "exit_reason": t["exit_reason"],
        "t": t,
    }
    
    if is_fast_sl(t):
        fast_sl.append(meta)
        fast_sl_assets[t["asset"]].append(meta)
        all_others.append(meta)
    else:
        all_non_fast.append(meta)
        survivors_by_exit[t["exit_reason"]].append(meta)
        all_others.append(meta)

print(f"Fast SL: {len(fast_sl)} / {N} ({len(fast_sl)/N*100:.1f}%)")
print(f"Non-fast: {len(all_non_fast)}")

# ═════════════════════════════════════════════════════════════════════════════
# A. SL DISTANCE (ATR-SCALED) → FAST-SL PROBABILITY
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("A. SL DISTANCE IN ATR → FAST-SL PROBABILITY CURVE")
print(f"{'='*80}")

bins = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 999.0]
print(f"\n  {'SL ATR bin':>15s} {'N':>6s} {'FastSL':>7s} {'FastSL%':>8s} {'AvgR':>8s} {'MedR':>8s}")
print(f"  {'-'*55}")
for i in range(len(bins)-1):
    lo, hi = bins[i], bins[i+1]
    in_bin = [t for t in all_others if lo <= t["sl_atr"] < hi]
    if not in_bin:
        continue
    n = len(in_bin)
    fs = sum(1 for t in in_bin if t["exit_reason"] == "sl" and get_dur(t["t"]) <= 3)
    r_vals = np.array([t["r"] for t in in_bin])
    print(f"  [{lo:5.1f}, {hi:5.1f}) {n:5d}  {fs:5d}   {fs/n*100:5.1f}%  {r_vals.mean():+7.4f}  {np.median(r_vals):+7.4f}")

# ═════════════════════════════════════════════════════════════════════════════
# B. TP/SL GEOMETRY
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("B. TP/SL GEOMETRY — 2D HEATMAP")
print(f"{'='*80}")

print(f"\n  fast-SL rate by (TP ATR bin × SL ATR bin):")
print(f"  {'':>10s}", end="")
for tp_lo, tp_hi in [(0,2),(2,4),(4,6),(6,10),(10,50)]:
    print(f"  TP[{tp_lo:.0f},{tp_hi:.0f})", end="")
print()

for sl_lo, sl_hi in [(0,1),(1,2),(2,3),(3,5),(5,20)]:
    print(f"  SL[{sl_lo:.0f},{sl_hi:.0f})", end="")
    for tp_lo, tp_hi in [(0,2),(2,4),(4,6),(6,10),(10,50)]:
        in_cell = [t for t in all_others 
                   if sl_lo <= t["sl_atr"] < sl_hi 
                   and tp_lo <= t["tp_atr"] < tp_hi]
        if not in_cell:
            print(f"  {'':>10s}", end="")
            continue
        fs = sum(1 for t in in_cell if t["exit_reason"] == "sl" and get_dur(t["t"]) <= 3)
        pct = fs / len(in_cell) * 100
        avg_r = np.mean([t["r"] for t in in_cell])
        print(f"  {pct:>4.0f}%|{avg_r:+.2f}", end="")
    print()

# ═════════════════════════════════════════════════════════════════════════════
# C. VOLATILITY REGIME
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("C. VOLATILITY REGIME AT ENTRY")
print(f"{'='*80}")

# We need historical ATR to detect expansion/contraction
# Using atr_pct_entry as current ATR, we'd need prior ATR for context
# For now, use ATR percentiles:

all_atrs = np.array([t["atr"] for t in all_others])
atr_p25, atr_p50, atr_p75 = np.percentile(all_atrs, [25, 50, 75])

print(f"\n  ATR percentiles (all trades): P25={atr_p25:.4f} P50={atr_p50:.4f} P75={atr_p75:.4f}")

for label, lo, hi in [("Low ATR (<P25)", 0, atr_p25),
                      ("Medium ATR (P25-P75)", atr_p25, atr_p75),
                      ("High ATR (>P75)", atr_p75, 999)]:
    in_bin = [t for t in all_others if lo <= t["atr"] < hi]
    if not in_bin:
        continue
    n = len(in_bin)
    fs = sum(1 for t in in_bin if t["exit_reason"] == "sl" and get_dur(t["t"]) <= 3)
    r_vals = np.array([t["r"] for t in in_bin])
    print(f"  {label:30s}: n={n:5d} | fast_sl={fs/n*100:5.1f}% | avgR={r_vals.mean():+.4f} | medR={np.median(r_vals):+.4f}")

# Asset-level volatility regime × fast SL
print(f"\n  Per-asset: Fast-SL rate by ATR quartile:")
for asset in sorted(set(t["asset"] for t in all_others)):
    at = [t for t in all_others if t["asset"] == asset]
    if len(at) < 30:
        continue
    asset_atrs = np.array([t["atr"] for t in at])
    a_p25, a_p75 = np.percentile(asset_atrs, [25, 75])
    low = [t for t in at if t["atr"] <= a_p25]
    high = [t for t in at if t["atr"] >= a_p75]
    
    def fast_pct(group):
        n = len(group)
        if n == 0: return 0, 0
        fs = sum(1 for t in group if t["exit_reason"] == "sl" and get_dur(t["t"]) <= 3)
        return n, fs/n*100
    
    n_low, pct_low = fast_pct(low)
    n_high, pct_high = fast_pct(high)
    overall_pct = sum(1 for t in at if t["exit_reason"] == "sl" and get_dur(t["t"]) <= 3) / len(at) * 100
    delta = pct_high - pct_low
    
    bar = "▲" if delta > 5 else ("▼" if delta < -5 else "—")
    print(f"  {asset:>8s}: n={len(at):4d} | overall={overall_pct:5.1f}% | "
          f"lowATR={pct_low:5.1f}% | highATR={pct_high:5.1f}% | Δ={delta:+5.1f}% {bar}")

# ═════════════════════════════════════════════════════════════════════════════
# D. MAE/MFE COMPARISON
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("D. MAE/MFE COMPARISON (per-trade summary metrics)")
print(f"{'='*80}")

# mae_r / mfe_r are stored as positive magnitudes relative to risk
print(f"\n  {'':>12s} {'N':>6s} {'MAE_R':>8s} {'MFE_R':>8s} {'MAE_Pip':>10s} {'MFE_Pip':>10s} {'C_MAE':>7s} {'C_MFE':>7s}")
print(f"  {'-'*68}")

for label, group in [("Fast-SL", fast_sl), ("Survivors", all_non_fast)]:
    ts = [m["t"] for m in group]
    mae_r = np.array([t.get("mae_r", 0) for t in ts])
    mfe_r = np.array([t.get("mfe_r", 0) for t in ts])
    mae = np.array([t.get("mae", 0) for t in ts])
    mfe = np.array([t.get("mfe", 0) for t in ts])
    c_mae = np.array([t.get("candle_of_mae", 0) for t in ts])
    c_mfe = np.array([t.get("candle_of_mfe", 0) for t in ts])
    print(f"  {label:12s} {len(ts):6d} {mae_r.mean():+8.4f} {mfe_r.mean():+8.4f} "
          f"{mae.mean():+10.4f} {mfe.mean():+10.4f} {c_mae.mean():7.1f} {c_mfe.mean():7.1f}")
    for p in [25, 50, 75]:
        print(f"  {'P'+str(p):>12s} {'':>6s} {np.percentile(mae_r,p):+8.4f} {np.percentile(mfe_r,p):+8.4f} "
              f"{np.percentile(mae,p):+10.4f} {np.percentile(mfe,p):+10.4f} "
              f"{np.percentile(c_mae,p):7.1f} {np.percentile(c_mfe,p):7.1f}")

# When does MAE peak?
print(f"\n  MAE/MFE timing:")
for label, group in [("Fast-SL", fast_sl), ("Survivors", all_non_fast)]:
    ts = [m["t"] for m in group]
    c_mae = np.array([t.get("candle_of_mae", 0) for t in ts])
    c_mfe = np.array([t.get("candle_of_mfe", 0) for t in ts])
    print(f"  {label:12s} MAE@candle {c_mae.mean():.1f}±{c_mae.std():.1f}, "
          f"MFE@candle {c_mfe.mean():.1f}±{c_mfe.std():.1f}")

# MAE_R vs MFE_R scatter — key insight: ratio
for label, group in [("Fast-SL", fast_sl), ("Survivors", all_non_fast)]:
    ts = [m["t"] for m in group]
    ratios = []
    for t in ts:
        mr = t.get("mae_r", 0)
        mfr = t.get("mfe_r", 0)
        if mfr > 0 and mr > 0:
            ratios.append(mr / mfr)
    r_arr = np.array(ratios)
    if len(r_arr) > 0:
        print(f"  {label:12s} MAE/MFE ratio: mean={r_arr.mean():.2f} median={np.median(r_arr):.2f}")

# ═════════════════════════════════════════════════════════════════════════════
# E. COUNTERFACTUAL: WHAT IF WE WIDENED THE SL?
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("E. COUNTERFACTUAL: SL WIDENING ANALYSIS")
print(f"{'='*80}")

# For fast-SL trades, what SL distance would have been needed
# to survive candle 3? Use MAE (max adverse excursion) as the
# fraction of SL consumed.
mae_consumption = []
for meta in fast_sl:
    t = meta["t"]
    mae_r_val = t.get("mae_r", 0)
    # mae_r_val is stored as positive magnitude
    pct_consumed = abs(mae_r_val) * 100
    mae_consumption.append(pct_consumed)

if mae_consumption:
    mc = np.array(mae_consumption)
    print(f"\n  MAE as % of SL distance consumed (fast-SL trades):")
    for p in [10, 25, 50, 75, 90, 95, 99]:
        print(f"    P{p:2d}: {np.percentile(mc, p):.1f}% of SL consumed (MAE_R = {np.percentile(mc, p)/100:.2f}R)")
    
    # Reverse: what fraction could have survived with wider SL?
    for factor in [1.5, 2.0, 3.0, 5.0]:
        survived = (mc < (100 * factor)).mean() * 100
        print(f"  Would survive with {factor:.1f}x SL: {survived:.1f}%")
    
    # And for comparison, what about survivors?
    surv_consumption = []
    for meta in all_non_fast:
        t = meta["t"]
        mae_r_val = t.get("mae_r", 0)
        pct = abs(mae_r_val) * 100
        surv_consumption.append(pct)
    sc = np.array(surv_consumption)
    print(f"\n  Comparison — MAE as % of SL distance (survivors):")
    for p in [10, 25, 50, 75, 90, 95, 99]:
        print(f"    P{p:2d}: {np.percentile(sc, p):.1f}% of SL consumed (MAE_R = {np.percentile(sc, p)/100:.2f}R)")
    
    # How many survivors would have died with a tighter SL?
    for factor in [0.5, 0.75, 0.875, 0.95]:
        would_die = (sc >= (100 * factor)).mean() * 100
        print(f"  Would have died with {factor:.2f}x current SL: {would_die:.1f}% of survivors")

print("\nDone.")
