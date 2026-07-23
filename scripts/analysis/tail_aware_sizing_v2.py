#!/usr/bin/env python3
"""
Tail-Aware Position Sizing Backtest — v2.

Uses conditional tail rates (asset_group × confidence_bucket × implied_r)
from the earlier research findings rather than unconditional per-asset rates.

Score = AssetGroupConfFactor × ImpliedRFactor

Three portfolios:
  Baseline:  1×
  Moderate:  0.75×–1.5×
  Aggressive: 0.5×–2.0×
"""

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

from datetime import datetime
def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

for t in all_trades:
    t["_entry_dt"] = parse_dt(t["entry_date"])
all_trades.sort(key=lambda t: t["_entry_dt"])

# ── Asset groups ─────────────────────────────────────────────────────────────
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

# ── Conditional tail rates from prior research ───────────────────────────────
# Format: (group, conf_bucket) -> top5%_rate
# These are the empirical rates from tail_predictor_research.py
CONDITIONAL_TAIL_RATES = {
    ("COMMODITY", "moderate"): 24.59,   # conf [0.5, 0.8)
    ("COMMODITY", "high"):     23.47,   # conf [0.8, 0.9)
    ("COMMODITY", "very_high"): 13.49,  # conf [0.9, 1.0)
    ("EQUITY", "moderate"):     4.48,
    ("EQUITY", "high"):        12.21,
    ("EQUITY", "very_high"):   14.62,
    ("FX-MAJOR", "moderate"):  3.26,
    ("FX-MAJOR", "high"):      7.56,
    ("FX-MAJOR", "very_high"): 11.76,
    ("FX-CHF", "moderate"):    1.39,   # from the multivariate table
    ("FX-CHF", "high"):        1.70,
    ("FX-CHF", "very_high"):   1.95,
    ("FX-CROSS", "moderate"):  1.60,
    ("FX-CROSS", "high"):      1.75,
    ("FX-CROSS", "very_high"): 1.32,
    ("CRYPTO", "moderate"):    0.00,
    ("CRYPTO", "high"):        0.00,
    ("CRYPTO", "very_high"):   0.00,
}

BASE_TAIL_RATE = 5.0  # global unconditional

def get_conditional_factor(group, conf):
    if conf < 0.8:
        bucket = "moderate"
    elif conf < 0.9:
        bucket = "high"
    else:
        bucket = "very_high"
    rate = CONDITIONAL_TAIL_RATES.get((group, bucket), BASE_TAIL_RATE)
    return max(0.2, rate / BASE_TAIL_RATE)

# ── Extract features ────────────────────────────────────────────────────────
all_features = []
for t in all_trades:
    side = t["side"]
    prob_long = t.get("prob_long", 0.5)
    prob_short = t.get("prob_short", 0.5)
    trade_confidence = prob_long if side == "BUY" else prob_short
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    implied_r = abs(entry - tp) / abs(entry - sl) if abs(entry - sl) > 1e-10 else 0
    group = asset_to_group.get(t["asset"], "FX-CROSS")
    all_features.append({
        "trade_confidence": trade_confidence,
        "implied_r": implied_r,
        "group": group,
        "asset": t["asset"],
    })

# ── Tail Opportunity Score ──────────────────────────────────────────────────
def compute_score(feat):
    af = get_conditional_factor(feat["group"], feat["trade_confidence"])
    ir = feat["implied_r"]
    if ir >= 8.0:
        ir_factor = 2.5
    elif ir >= 4.0:
        ir_factor = 2.0
    elif ir >= 3.5:
        ir_factor = 1.5
    elif ir >= 3.0:
        ir_factor = 1.0
    else:
        ir_factor = 0.7
    return af * ir_factor

scores = np.array([compute_score(f) for f in all_features])

print("Conditional Tail Factors (asset_group × confidence):")
for (group, bucket), rate in sorted(CONDITIONAL_TAIL_RATES.items()):
    factor = rate / BASE_TAIL_RATE
    print(f"  {group+':':15s} conf {bucket:10s}: {rate:5.1f}%  →  factor={factor:.2f}x")

score_pcts = {p: v for p, v in zip([10, 25, 50, 75, 90, 95, 99],
                                     np.percentile(scores, [10, 25, 50, 75, 90, 95, 99]))}
print(f"\nScore distribution:")
for p in [10, 25, 50, 75, 90, 95, 99]:
    print(f"  P{p:2d}: {score_pcts[p]:.2f}")
print(f"  Min: {scores.min():.2f}  Max: {scores.max():.2f}")

# ── Portfolio simulation ────────────────────────────────────────────────────
def simulate(risk_mult_func, label):
    equity = 500.0
    ec = [equity]
    adj_rs = []
    for i, t in enumerate(all_trades):
        r = t["r_multiple"]
        mult = risk_mult_func(scores[i])
        adj_r = r * mult
        equity *= (1 + adj_r * 0.01)
        adj_rs.append(adj_r)
        ec.append(equity)
    
    r_arr = np.array(adj_rs)
    total_r = r_arr.sum()
    mean_r = r_arr.mean()
    std_r = r_arr.std() if r_arr.std() > 0 else 1e-10
    sharpe = mean_r / std_r
    wins = r_arr[r_arr > 0]
    losses = r_arr[r_arr <= 0]
    wr = len(wins) / len(r_arr) * 100
    pf = abs(wins.sum() / losses.sum()) if losses.sum() != 0 else float("inf")
    downside = r_arr[r_arr < 0]
    sortino = mean_r / (downside.std() if len(downside) > 0 and downside.std() > 0 else 1e-10)
    
    ec_arr = np.array(ec)
    peak = np.maximum.accumulate(ec_arr)
    dd_pct = (ec_arr - peak) / peak * 100
    max_dd = abs(dd_pct.min())
    
    n_days = (all_trades[-1]["_entry_dt"] - all_trades[0]["_entry_dt"]).days
    years = max(1, n_days / 365.25)
    final_eq = ec[-1]
    cagr = (final_eq / 500.0) ** (1 / years) - 1
    calmar = cagr / (max_dd / 100) if max_dd > 0 else 0
    
    return {
        "label": label,
        "final_eq": final_eq,
        "return_pct": (final_eq / 500.0 - 1) * 100,
        "cagr_pct": cagr * 100,
        "total_r": total_r,
        "mean_r": mean_r,
        "sharpe": sharpe,
        "sortino": sortino,
        "wr": wr,
        "pf": pf,
        "max_dd_pct": max_dd,
        "calmar": calmar,
    }

baseline = simulate(lambda s: 1.0, "Baseline (1×)")

def moderate_mult(s):
    if s >= 4.0: return 1.75
    if s >= 3.0: return 1.50
    if s >= 2.0: return 1.25
    if s >= 1.5: return 1.0
    return 0.75

moderate = simulate(moderate_mult, "Moderate (0.75×–1.75×)")

def aggressive_mult(s):
    if s >= 4.0: return 2.5
    if s >= 3.0: return 2.0
    if s >= 2.0: return 1.5
    if s >= 1.5: return 1.0
    return 0.5

aggressive = simulate(aggressive_mult, "Aggressive (0.5×–2.5×)")

# ── Report ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TAIL-AWARE POSITION SIZING BACKTEST v2")
print("=" * 80)
print(f"Period: {all_trades[0]['_entry_dt'].date()} → {all_trades[-1]['_entry_dt'].date()}")
print(f"Trades: {N}")
print()

header = (f"{'Strategy':<25s} {'FinalEq':>10s} {'Return':>9s} {'CAGR':>8s} "
          f"{'Sharpe':>8s} {'Sortino':>8s} {'WR':>5s} {'PF':>7s} "
          f"{'MaxDD':>7s} {'Calmar':>8s}")
print(header)
print("-" * 85)
for r in [baseline, moderate, aggressive]:
    print(f"{r['label']:<25s} ${r['final_eq']:>8.2f} {r['return_pct']:>8.2f}% "
          f"{r['cagr_pct']:>7.2f}% {r['sharpe']:>7.3f} {r['sortino']:>7.3f} "
          f"{r['wr']:>5.1f}% {r['pf']:>7.3f} {r['max_dd_pct']:>6.2f}% "
          f"{r['calmar']:>8.3f}")

# Rel vs baseline
print(f"\n  Improvement vs Baseline:")
b = baseline
for r in [moderate, aggressive]:
    print(f"  {r['label']:<25s}: CAGR Δ={r['cagr_pct']-b['cagr_pct']:+7.2f}pp  "
          f"Sharpe Δ={r['sharpe']-b['sharpe']:+7.3f}  "
          f"MaxDD Δ={r['max_dd_pct']-b['max_dd_pct']:+7.2f}pp  "
          f"Calmar Δ={r['calmar']-b['calmar']:+7.3f}")

# ── Sizing distribution ─────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SIZING DECISION DISTRIBUTION")
print("=" * 80)

for label, mult_func in [("Moderate", moderate_mult), ("Aggressive", aggressive_mult)]:
    mults = np.array([mult_func(s) for s in scores])
    print(f"\n  {label}:")
    for mult in sorted(set(mults)):
        n = (mults == mult).sum()
        pct = n / N * 100
        r_sub = r_vals[mults == mult]
        top5_th = np.percentile(r_vals, 95)
        top5_n = (r_sub >= top5_th).sum()
        print(f"    {mult:.2f}x: n={n:5d} ({pct:5.1f}%) | avg_R={r_sub.mean():+.4f} | "
              f"top5%_rate={top5_n/len(r_sub)*100:.1f}%")

# ── Top-5% capture ──────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TOP-5% CAPTURE: ARE WE UPSIZING THE RIGHT TRADES?")
print("=" * 80)

top5_th = np.percentile(r_vals, 95)
is_top5 = r_vals >= top5_th

for label, mult_func in [("Baseline", lambda s: 1.0), ("Moderate", moderate_mult), ("Aggressive", aggressive_mult)]:
    mults = np.array([mult_func(s) for s in scores])
    avg_top5 = mults[is_top5].mean()
    avg_normal = mults[~is_top5].mean()
    top5_r = (r_vals * mults)[is_top5].sum()
    total_r = (r_vals * mults).sum()
    share = top5_r / total_r * 100 if total_r != 0 else 0
    # Fraction of top-5% trades that get upsized (mult > 1)
    upsized_top5 = (mults[is_top5] > 1.0).mean() * 100
    downsized_top5 = (mults[is_top5] < 1.0).mean() * 100
    print(f"  {label:<15s}: avg_mult(top5)={avg_top5:.3f}x avg_mult(normal)={avg_normal:.3f}x | "
          f"top5_share={share:.1f}% | upsized={upsized_top5:.1f}% downsized={downsized_top5:.1f}%")

# ── Win/loss asymmetry ──────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("WIN/LOSS ASYMMETRY BY SCORE")
print("=" * 80)

buckets = [(0, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 4), (4, 999)]
for lo, hi in buckets:
    mask = (scores >= lo) & (scores < hi)
    n = mask.sum()
    if n == 0:
        continue
    r_sub = r_vals[mask]
    wins = r_sub[r_sub > 0]
    losses = r_sub[r_sub <= 0]
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    top5_n = (r_sub >= top5_th).sum()
    print(f"  Score [{lo:3.0f}, {hi:3.0f}): n={n:5d} | avg_R={r_sub.mean():+.4f} | "
          f"avg_win={avg_win:+.4f} | avg_loss={avg_loss:+.4f} | "
          f"WR={(r_sub>0).mean()*100:.1f}% | top5%={top5_n/n*100:.1f}%")

print("\nDone.")
