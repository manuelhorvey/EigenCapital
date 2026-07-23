#!/usr/bin/env python3
"""
Tail-Aware Position Sizing Backtest — v3.

Uses the empirical conditional top-5% rate directly as the score.
Score = P(top5 | asset_group, confidence_bucket) × ImpliedRFactor

No product of factors — the conditional rate IS the signal.
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

ASSET_GROUPS = {
    "FX-MAJOR":  ["AUDUSD", "GBPUSD", "USDJPY", "USDCAD", "NZDUSD"],
    "FX-CHF":    ["USDCHF", "EURCHF", "GBPCHF", "CADCHF", "NZDCHF"],
    "FX-CROSS":  ["EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "AUDJPY", "NZDJPY", "EURAUD"],
    "EQUITY":    ["^DJI"],
    "COMMODITY": ["GC"],
    "CRYPTO":    ["BTCUSD"],
}
asset_to_group = {}
for g, assets in ASSET_GROUPS.items():
    for a in assets:
        asset_to_group[a] = g

# Empirical conditional top-5% rates from earlier research
COND_RATES = {
    ("COMMODITY", "lo"): 24.59,
    ("COMMODITY", "hi"): 13.49,
    ("EQUITY", "lo"): 4.48,
    ("EQUITY", "hi"): 14.62,
    ("FX-MAJOR", "lo"): 3.26,
    ("FX-MAJOR", "hi"): 11.76,
    ("FX-CHF", "lo"): 1.39,
    ("FX-CHF", "hi"): 1.95,
    ("FX-CROSS", "lo"): 1.60,
    ("FX-CROSS", "hi"): 1.32,
    ("CRYPTO", "lo"): 0.0,
    ("CRYPTO", "hi"): 0.0,
}

def get_cond_rate(group, conf):
    bucket = "hi" if conf >= 0.8 else "lo"
    return COND_RATES.get((group, bucket), 5.0)

# Score = conditional top-5% rate × implied R factor
scores = []
for t in all_trades:
    side = t["side"]
    prob_long = t.get("prob_long", 0.5)
    prob_short = t.get("prob_short", 0.5)
    conf = prob_long if side == "BUY" else prob_short
    group = asset_to_group.get(t["asset"], "FX-CROSS")
    cond_rate = get_cond_rate(group, conf)
    
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    implied_r = abs(entry - tp) / abs(entry - sl) if abs(entry - sl) > 1e-10 else 0
    
    # Implied R factor: higher → more room for tail
    if implied_r >= 8.0: ir_f = 1.5
    elif implied_r >= 4.0: ir_f = 1.3
    elif implied_r >= 3.5: ir_f = 1.15
    elif implied_r >= 3.0: ir_f = 1.0
    else: ir_f = 0.85
    
    # Also factor in which bucket the asset falls into:
    # robust (<50% tailR/assetR), moderate (50-150%), tail-dependent (>150%)
    # From earlier analysis:
    # Robust: BTCUSD, CADCHF, EURAUD, EURCHF, EURNZD, GBPAUD, GBPCHF, NZDCAD, NZDCHF, NZDJPY, USDCHF
    # Moderate: AUDJPY, AUDUSD, EURCAD, GBPUSD, ^DJI
    # Tail-dependent: GBPCAD, GBPJPY, GC, NZDUSD, USDCAD, USDJPY
    robust = {"BTCUSD", "CADCHF", "EURAUD", "EURCHF", "EURNZD", "GBPAUD", "GBPCHF", "NZDCAD", "NZDCHF", "NZDJPY", "USDCHF"}
    tail_dep = {"GBPCAD", "GBPJPY", "GC", "NZDUSD", "USDCAD", "USDJPY"}
    asset_type_factor = 1.0
    if t["asset"] in robust:
        asset_type_factor = 0.85  # these get consistent but smaller R
    elif t["asset"] in tail_dep:
        asset_type_factor = 1.2   # these get rare large moves
    
    score = cond_rate * ir_f * asset_type_factor
    scores.append(score)

scores = np.array(scores)

for p in [10, 25, 50, 75, 90, 95, 99]:
    print(f"  Score P{p:2d}: {np.percentile(scores, p):.2f}")
print(f"  Min: {scores.min():.2f}  Max: {scores.max():.2f}")

# ── Simulation ──────────────────────────────────────────────────────────────
def simulate(mult_func, label):
    eq = 500.0; ec = [eq]; adj = []
    for i, t in enumerate(all_trades):
        r = t["r_multiple"]
        m = mult_func(scores[i])
        a = r * m
        eq *= (1 + a * 0.01); adj.append(a); ec.append(eq)
    ra = np.array(adj)
    mean_r, std_r = ra.mean(), ra.std()
    std_r = std_r if std_r > 0 else 1e-10
    sharpe = mean_r / std_r
    w = ra[ra > 0]; l_ = ra[ra <= 0]
    wr = len(w)/len(ra)*100; pf = abs(w.sum()/l_.sum()) if l_.sum()!=0 else float("inf")
    ds = ra[ra < 0]; sortino = mean_r/(ds.std() if len(ds)>0 and ds.std()>0 else 1e-10)
    ea = np.array(ec); pk = np.maximum.accumulate(ea)
    dd = (ea - pk) / pk * 100; mdd = abs(dd.min())
    yrs = max(1, (all_trades[-1]["_entry_dt"] - all_trades[0]["_entry_dt"]).days / 365.25)
    cagr = (ec[-1]/500.0)**(1/yrs)-1
    return {"label":label, "final":ec[-1], "ret":(ec[-1]/500-1)*100, "cagr":cagr*100,
            "sharpe":sharpe, "sortino":sortino, "wr":wr, "pf":pf, "mdd":mdd, "calmar":cagr/(mdd/100) if mdd>0 else 0}

def mult_base(s): return 1.0
def mult_mod(s):
    if s >= 20: return 1.75
    if s >= 10: return 1.50
    if s >= 5:  return 1.25
    if s >= 3:  return 1.0
    return 0.75
def mult_agg(s):
    if s >= 20: return 2.50
    if s >= 10: return 2.00
    if s >= 5:  return 1.50
    if s >= 3:  return 1.0
    return 0.50

base = simulate(mult_base, "Baseline (1×)")
mod = simulate(mult_mod, "Moderate (0.75×–1.75×)")
agg = simulate(mult_agg, "Aggressive (0.5×–2.5×)")

print(f"\n{'Strategy':<25s} {'FinalEq':>10s} {'Return':>9s} {'CAGR':>8s} {'Sharpe':>8s} "
      f"{'Sortino':>8s} {'WR':>5s} {'PF':>7s} {'MaxDD':>7s} {'Calmar':>9s}")
print("-"*95)
for r in [base, mod, agg]:
    print(f"{r['label']:<25s} ${r['final']:>8.2f} {r['ret']:>8.2f}% {r['cagr']:>7.2f}% "
          f"{r['sharpe']:>7.4f} {r['sortino']:>7.4f} {r['wr']:>4.1f}% {r['pf']:>7.4f} "
          f"{r['mdd']:>6.2f}% {r['calmar']:>9.3f}")

# Improvement
for r in [mod, agg]:
    print(f"  {r['label']:<25s}: CAGR Δ={r['cagr']-base['cagr']:+8.2f}pp  "
          f"Sharpe Δ={r['sharpe']-base['sharpe']:+8.4f}  "
          f"MaxDD Δ={r['mdd']-base['mdd']:+8.2f}pp  "
          f"Calmar Δ={r['calmar']-base['calmar']:+8.3f}")

# ── Score analysis ──────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"SCORE BUCKET PERFORMANCE")
print(f"{'='*80}")
buckets = [(0, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 999)]
for lo, hi in buckets:
    m = (scores >= lo) & (scores < hi); n = m.sum()
    if n == 0: continue
    rs = r_vals[m]; top5 = (rs >= np.percentile(r_vals, 95)).sum()
    wins = rs[rs > 0]; losses = rs[rs <= 0]
    print(f"  [{lo:3.0f},{hi:3.0f}): n={n:5d} | avg_R={rs.mean():+.4f} | "
          f"WR={len(wins)/n*100:.1f}% | PF={abs(wins.sum()/losses.sum()) if losses.sum()!=0 else float('inf'):.3f} | "
          f"top5%={top5/n*100:.1f}%")

# ── Sizing distribution ─────────────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"SIZING DISTRIBUTION")
print(f"{'='*80}")
for label, mf in [("Moderate", mult_mod), ("Aggressive", mult_agg)]:
    ms = np.array([mf(s) for s in scores])
    print(f"\n  {label}:")
    for m in sorted(set(ms)):
        n = (ms == m).sum(); r_sub = r_vals[ms == m]
        t5 = (r_sub >= np.percentile(r_vals, 95)).sum()
        print(f"    {m:.2f}x: n={n:5d} ({n/N*100:.1f}%) | avg_R={r_sub.mean():+.4f} | top5%={t5/n*100:.1f}%")

# ── Top-5% capture ──────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("TOP-5% CAPTURE")
print(f"{'='*80}")
t5_th = np.percentile(r_vals, 95); is_t5 = r_vals >= t5_th
for label, mf in [("Baseline", lambda s:1.0), ("Moderate", mult_mod), ("Aggressive", mult_agg)]:
    ms = np.array([mf(s) for s in scores])
    a5 = ms[is_t5].mean(); an = ms[~is_t5].mean()
    up5 = (ms[is_t5] > 1.0).mean()*100; dn5 = (ms[is_t5] < 1.0).mean()*100
    t5c = (r_vals*ms)[is_t5].sum(); tc = (r_vals*ms).sum()
    print(f"  {label:<15s}: mult(top5)={a5:.3f}x mult(normal)={an:.3f}x | "
          f"upsized={up5:.1f}% downsized={dn5:.1f}% | top5_share={t5c/tc*100:.1f}%")

print("\nDone.")
