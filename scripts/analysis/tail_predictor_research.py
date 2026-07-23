#!/usr/bin/env python3
"""
Tail Predictor Research: Can we identify top-decile/percentile trades 
using only information available at entry time?

Features available at entry:
  - asset, side
  - p_long / prob_long / prob_short (model confidence)
  - signal_age
  - barrier_candles (preconfigured)
  - atr_pct_entry (volatility regime)
  - tp_price, sl_price ratio (implied R)
  - entry_price level

We create binary targets:
  - is_top_1pct  (R >= 4.00)
  - is_top_5pct  (R >= 3.36)
  - is_top_10pct (R >= 2.45)
  - is_positive  (R > 0)

Then compare feature distributions and report separability.
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

# Define thresholds from the data
order = np.argsort(r_vals)[::-1]
def threshold_for_pct(pct):
    n = max(1, int(N * pct / 100))
    return r_vals[order[n-1]]

pct1_th = threshold_for_pct(1)
pct5_th = threshold_for_pct(5)
pct10_th = threshold_for_pct(10)
pct20_th = threshold_for_pct(20)

print(f"Top 1% threshold:  R >= {pct1_th:+.4f}")
print(f"Top 5% threshold:  R >= {pct5_th:+.4f}")
print(f"Top 10% threshold: R >= {pct10_th:+.4f}")
print(f"Top 20% threshold: R >= {pct20_th:+.4f}")
print(f"Positive threshold: R > 0.0 ({r_vals[r_vals > 0].shape[0]} trades)")
print(f"Total trades: {N}")

# ── Build entry-time feature vectors ─────────────────────────────────────────
# Available at entry time only:
#   asset, side, entry_price, tp_price, sl_price,
#   p_long, prob_long, prob_short, signal_age,
#   barrier_candles, atr_pct_entry

features = {}
for t in all_trades:
    uid = id(t)
    # Model confidence: use the probability in the direction of the trade
    side = t["side"]
    prob_long = t.get("prob_long", 0.5)
    prob_short = t.get("prob_short", 0.5)
    # Confidence in trade direction
    if side == "BUY":
        trade_confidence = prob_long
    else:
        trade_confidence = prob_short
    
    # Probability gap: how much conviction vs the alternative
    prob_gap = abs(prob_long - prob_short)
    
    # Implied R (from SL/TP)
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    atr = t.get("atr_pct_entry", 0.01)
    if atr > 0:
        implied_r = abs(entry - tp) / (abs(entry - sl) * 1.0) if sl != entry else 0
    else:
        implied_r = 0
    
    features[uid] = {
        "asset": t["asset"],
        "side": side,
        "trade_confidence": trade_confidence,
        "prob_gap": prob_gap,
        "prob_long": prob_long,
        "prob_short": prob_short,
        "signal_age": t.get("signal_age", 0),
        "barrier_candles": t.get("barrier_candles", 20),
        "atr_pct_entry": atr,
        "implied_r": implied_r,
    }

# ── Targets ──────────────────────────────────────────────────────────────────
targets = {}
for t in all_trades:
    uid = id(t)
    r = t["r_multiple"]
    targets[uid] = {
        "r": r,
        "is_top_1pct": r >= pct1_th,
        "is_top_5pct": r >= pct5_th,
        "is_top_10pct": r >= pct10_th,
        "is_positive": r > 0,
    }

# ── Feature analysis by target ───────────────────────────────────────────────
print("\n" + "=" * 80)
print("FEATURE SEPARABILITY ANALYSIS")
print("=" * 80)

feature_names = ["trade_confidence", "prob_gap", "signal_age", "implied_r", "atr_pct_entry"]
target_names = ["is_top_1pct", "is_top_5pct", "is_top_10pct", "is_positive"]

for target_name in target_names:
    print(f"\n── Target: {target_name} ──")
    yes_group = []
    no_group = []
    for t in all_trades:
        uid = id(t)
        if targets[uid][target_name]:
            yes_group.append(features[uid])
        else:
            no_group.append(features[uid])
    
    n_yes = len(yes_group)
    n_no = len(no_group)
    print(f"  Yes: {n_yes:5d} ({n_yes/N*100:.1f}%)  No: {n_no:5d} ({n_no/N*100:.1f}%)")
    
    for feat in feature_names:
        y_vals = np.array([f[feat] for f in yes_group])
        n_vals = np.array([f[feat] for f in no_group])
        if len(y_vals) == 0 or len(n_vals) == 0:
            continue
        y_mean = y_vals.mean()
        n_mean = n_vals.mean()
        diff = y_mean - n_mean
        # Effect size (Cohen's d approximation)
        pooled_std = np.sqrt((y_vals.var() + n_vals.var()) / 2)
        cohens_d = diff / pooled_std if pooled_std > 0 else 0
        
        # Percentile comparison
        print(f"  {feat:25s}: Yes mean={y_mean:8.4f} | No mean={n_mean:8.4f} | Δ={diff:+8.4f} | d={cohens_d:+7.3f}")
        # Show selected percentiles only for interesting features
        if abs(cohens_d) > 0.1:
            for p in [10, 25, 50, 75, 90]:
                yp = np.percentile(y_vals, p)
                np_ = np.percentile(n_vals, p)
                print(f"    P{p:2d}: Yes={yp:8.4f}  No={np_:8.4f}")

# ── Asset-level tail concentration ───────────────────────────────────────────
print("\n" + "=" * 80)
print("ASSET-LEVEL TAIL CONCENTRATION")
print("=" * 80)

assets = sorted(set(t["asset"] for t in all_trades))

print(f"\n  {'Asset':>8s} {'N':>6s} {'Top1%N':>6s} {'Top5%N':>6s} {'Top10%N':>7s} {'Top1%R':>8s} {'Top5%R':>8s} {'Top10%R':>9s} {'TailR/AssetR':>12s}")
print(f"  {'-'*80}")

for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    r_a = np.array([t["r_multiple"] for t in at], dtype=float)
    total_r = r_a.sum()
    
    order_a = np.argsort(r_a)[::-1]
    
    for pct, label in [(1, "1%"), (5, "5%"), (10, "10%")]:
        n_top = max(1, int(n * pct / 100))
        top_r = r_a[order_a[:n_top]].sum()
        if pct == 1:
            n1, top1_r = n_top, top_r
        elif pct == 5:
            n5, top5_r = n_top, top_r
        else:
            n10, top10_r = n_top, top_r
    
    tail_share = top5_r / total_r * 100 if total_r != 0 else 0
    print(f"  {asset:>8s} {n:6d} {n1:6d} {n5:6d} {n10:7d} {top1_r:+8.2f} {top5_r:+8.2f} {top10_r:+9.2f} {tail_share:10.1f}% {'(tail-dependent)' if tail_share > 150 else '(robust)' if tail_share < 50 else ''}")

# ── Side analysis ────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SIDE AS A PREDICTOR OF TAIL")
print("=" * 80)

for target_name in ["is_top_5pct", "is_top_10pct"]:
    print(f"\n── {target_name} ──")
    for side in ["BUY", "SELL"]:
        side_trades = [t for t in all_trades if t["side"] == side]
        n_side = len(side_trades)
        n_tail = sum(1 for t in side_trades if targets[id(t)][target_name])
        tail_pct = n_tail / n_side * 100 if n_side > 0 else 0
        avg_r = np.mean([t["r_multiple"] for t in side_trades])
        print(f"  {side:5s}: {n_side:5d} trades, {n_tail:4d} tail ({tail_pct:.1f}%), avg_R={avg_r:+.4f}")

# ── Confidence bucket analysis ───────────────────────────────────────────────
print("\n" + "=" * 80)
print("CONFIDENCE AS A PREDICTOR (trade_confidence buckets)")
print("=" * 80)

buckets = [(0.0, 0.25), (0.25, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.75), (0.75, 0.85), (0.85, 1.0)]
for lo, hi in buckets:
    bucket = [t for t in all_trades if lo <= features[id(t)]["trade_confidence"] < hi]
    if not bucket:
        continue
    n_b = len(bucket)
    r_b = np.array([t["r_multiple"] for t in bucket])
    n_top5 = sum(1 for t in bucket if targets[id(t)]["is_top_5pct"])
    n_top10 = sum(1 for t in bucket if targets[id(t)]["is_top_10pct"])
    print(f"  [{lo:.2f}, {hi:.2f}): n={n_b:5d} | avg_R={r_b.mean():+.4f} | WR={(r_b>0).mean()*100:.1f}% "
          f"| top5%_rate={n_top5/n_b*100:.2f}% | top10%_rate={n_top10/n_b*100:.2f}%")

# ── Implied R analysis ───────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("IMPLIED R (TP/SL ratio) AS A PREDICTOR OF TAIL")
print("=" * 80)

implied_r_vals = np.array([features[id(t)]["implied_r"] for t in all_trades])
for pct in [5, 10, 20, 50, 80, 90, 95]:
    th = np.percentile(implied_r_vals, pct)
    high_ir = [t for t in all_trades if features[id(t)]["implied_r"] >= th]
    low_ir = [t for t in all_trades if features[id(t)]["implied_r"] < th]
    n_high = len(high_ir)
    n_low = len(low_ir)
    r_high = np.array([t["r_multiple"] for t in high_ir])
    r_low = np.array([t["r_multiple"] for t in low_ir])
    top5_high = sum(1 for t in high_ir if targets[id(t)]["is_top_5pct"])
    top5_low = sum(1 for t in low_ir if targets[id(t)]["is_top_5pct"])
    print(f"  ImpliedR >= P{pct} ({th:.2f}): n={n_high:5d} | avg_R={r_high.mean():+.4f} | "
          f"top5%_rate={top5_high/n_high*100:.2f}%")
    print(f"  ImpliedR <  P{pct} ({th:.2f}): n={n_low:5d} | avg_R={r_low.mean():+.4f} | "
          f"top5%_rate={top5_low/n_low*100:.2f}%")

# ── Volatility (ATR) analysis ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("VOLATILITY AT ENTRY (ATR%) AS A PREDICTOR")
print("=" * 80)

atr_vals = np.array([features[id(t)]["atr_pct_entry"] for t in all_trades])
for pct in [10, 25, 50, 75, 90]:
    th = np.percentile(atr_vals, pct)
    high_atr = [t for t in all_trades if features[id(t)]["atr_pct_entry"] >= th]
    low_atr = [t for t in all_trades if features[id(t)]["atr_pct_entry"] < th]
    r_high = np.array([t["r_multiple"] for t in high_atr])
    r_low = np.array([t["r_multiple"] for t in low_atr])
    top5_high = sum(1 for t in high_atr if targets[id(t)]["is_top_5pct"])
    print(f"  ATR >= P{pct:2d} ({th:.4f}): n={len(high_atr):5d} | avg_R={r_high.mean():+.4f} | "
          f"top5%_rate={top5_high/len(high_atr)*100:.2f}%")
    print(f"  ATR <  P{pct:2d} ({th:.4f}): n={len(low_atr):5d} | avg_R={r_low.mean():+.4f} | "
          f"top5%_rate={top5_high/len(high_atr)*100:.2f}%" if False else "")

# ── Multivariate: Top-5% rate by confidence + asset type ─────────────────────
print("\n" + "=" * 80)
print("MULTIVARIATE: TOP-5% RATE BY CONFIDENCE x ASSET GROUP")
print("=" * 80)

# Asset groups
groups = {
    "FX-MAJOR": ["AUDUSD", "GBPUSD", "USDJPY", "USDCAD", "NZDUSD"],
    "FX-CHF": ["USDCHF", "EURCHF", "GBPCHF", "CADCHF", "NZDCHF"],
    "FX-CROSS": ["EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "AUDJPY", "NZDJPY", "EURAUD"],
    "EQUITY": ["^DJI"],
    "COMMODITY": ["GC"],
    "CRYPTO": ["BTCUSD"],
}

for group_name, group_assets in groups.items():
    print(f"\n  ── {group_name} ──")
    for lo, hi in [(0.0, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.0)]:
        bucket = [t for t in all_trades 
                  if t["asset"] in group_assets
                  and lo <= features[id(t)]["trade_confidence"] < hi]
        if not bucket:
            continue
        n_b = len(bucket)
        r_b = np.array([t["r_multiple"] for t in bucket])
        n_top5 = sum(1 for t in bucket if targets[id(t)]["is_top_5pct"])
        n_wins = sum(1 for t in bucket if t["r_multiple"] > 0)
        print(f"    conf [{lo:.1f}, {hi:.1f}): n={n_b:4d} | avg_R={r_b.mean():+.4f} | "
              f"WR={n_wins/n_b*100:.1f}% | top5%={n_top5/n_b*100:.2f}%")

# ── Summary: Best single-feature rules for tail capture ──────────────────────
print("\n" + "=" * 80)
print("BEST SINGLE-FEATURE RULES FOR TAIL CAPTURE")
print("=" * 80)

print("\n  Evaluating threshold rules for top-5% capture...\n")

for feat in feature_names + ["implied_r"]:
    all_feat = np.array([features[id(t)][feat] for t in all_trades])
    best_f1 = 0
    best_th = 0
    best_results = {}
    
    # Try percentiles as thresholds
    for p in range(5, 100, 5):
        th = np.percentile(all_feat, p)
        predicted = (all_feat >= th).astype(int)
        actual = np.array([targets[id(t)]["is_top_5pct"] for t in all_trades], dtype=int)
        
        tp = (predicted & actual).sum()
        fp = (predicted & ~actual).sum()
        fn = (~predicted & actual).sum()
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        lift = precision / (actual.sum() / len(actual)) if (actual.sum() / len(actual)) > 0 else 0
        
        if f1 > best_f1:
            best_f1 = f1
            best_th = th
            best_results = {
                "threshold": th,
                "pctile": p,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "lift": lift,
                "n_predicted": tp + fp,
                "n_correct": tp,
                "n_total_tail": tp + fn,
            }
    
    if best_results["n_predicted"] > 0:
        print(f"  {feat:25s}: threshold >= P{best_results['pctile']:2d} ({best_results['threshold']:.4f}) | "
              f"precision={best_results['precision']:.3f} | recall={best_results['recall']:.3f} | "
              f"F1={best_results['f1']:.3f} | lift={best_results['lift']:.2f}x | "
              f"captures {best_results['n_correct']}/{best_results['n_total_tail']} tail trades")

print("\nDone.")
