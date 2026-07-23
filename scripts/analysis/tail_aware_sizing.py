#!/usr/bin/env python3
"""
Tail-Aware Position Sizing Backtest.

Implements the Tail Opportunity Score as a deterministic overlay:
  Score = AssetTailFactor × ImpliedRFactor × ConfidenceFactor

Three portfolios compared:
  Baseline:      1× risk on every trade
  Moderate:      0.75×–1.5× based on score
  Aggressive:    0.50×–2.0× based on score

NOTE: AssetTailFactors are computed from the full dataset (research-mode).
A production implementation would use expanding windows.
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

# Sort by entry date for chronological simulation
def parse_dt(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

for t in all_trades:
    t["_entry_dt"] = parse_dt(t["entry_date"])

all_trades.sort(key=lambda t: t["_entry_dt"])

# ── 1. Build entry-time features ────────────────────────────────────────────
def extract_features(t):
    side = t["side"]
    prob_long = t.get("prob_long", 0.5)
    prob_short = t.get("prob_short", 0.5)
    trade_confidence = prob_long if side == "BUY" else prob_short
    prob_gap = abs(prob_long - prob_short)
    entry = t["entry_price"]
    sl = t["sl_price"]
    tp = t["tp_price"]
    implied_r = abs(entry - tp) / abs(entry - sl) if abs(entry - sl) > 1e-10 else 0
    atr = t.get("atr_pct_entry", 0.01)
    return {
        "trade_confidence": trade_confidence,
        "implied_r": implied_r,
        "atr_pct_entry": atr,
        "asset": t["asset"],
        "side": side,
    }

all_features = [extract_features(t) for t in all_trades]
for i, t in enumerate(all_trades):
    t["_feat"] = all_features[i]

# ── 2. Asset tail factors (from full dataset empirical rates) ────────────────
# Group assets by their observed top-5% rate
assets = sorted(set(t["asset"] for t in all_trades))

top5_rate_by_asset = {}
for asset in assets:
    at = [t for t in all_trades if t["asset"] == asset]
    n = len(at)
    n_top5 = sum(1 for t in at if t["r_multiple"] >= np.percentile(
        np.array([x["r_multiple"] for x in at]), 95))
    top5_rate_by_asset[asset] = n_top5 / n * 100

base_rate = np.mean([t["r_multiple"] > 0 for t in all_trades]) * 100  # not used

# Compute asset tail factor as lift over global top-5% rate
global_top5_rate = 5.0  # by definition
asset_tail_factor = {}
for asset, rate in top5_rate_by_asset.items():
    # Cap at sensible values
    asset_tail_factor[asset] = max(0.3, min(5.0, rate / global_top5_rate))

print("Asset Tail Factors (lift over global 5% base rate):")
for asset, f in sorted(asset_tail_factor.items(), key=lambda x: -x[1]):
    print(f"  {asset:>8s}: {f:.2f}x (empirical top-5% rate: {top5_rate_by_asset[asset]:.1f}%)")

# ── 3. Tail Opportunity Score function ───────────────────────────────────────
def compute_score(feat):
    af = asset_tail_factor.get(feat["asset"], 1.0)
    # Implied R factor: higher implied R → more opportunity
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
    
    # Confidence factor
    c = feat["trade_confidence"]
    # For GC: moderate confidence is better (inverse U)
    if feat["asset"] == "GC":
        if 0.5 <= c < 0.8:
            c_factor = 2.0
        elif c >= 0.8:
            c_factor = 1.2
        else:
            c_factor = 0.5
    else:
        if c >= 0.9:
            c_factor = 1.5
        elif c >= 0.8:
            c_factor = 1.2
        elif c >= 0.6:
            c_factor = 1.0
        else:
            c_factor = 0.7
    
    score = af * ir_factor * c_factor
    return score

# ── 4. Compute scores for all trades ────────────────────────────────────────
scores = np.array([compute_score(f) for f in all_features])

# Score statistics
score_pcts = {p: v for p, v in zip([10, 25, 50, 75, 90, 95, 99], np.percentile(scores, [10, 25, 50, 75, 90, 95, 99]))}
print(f"\nTail Opportunity Score distribution:")
for p in [10, 25, 50, 75, 90, 95, 99]:
    print(f"  P{p:2d}: {score_pcts[p]:.2f}")
print(f"  Min: {scores.min():.2f}  Max: {scores.max():.2f}")

# ── 5. Simulate portfolios ──────────────────────────────────────────────────
def simulate(risk_multiplier_func, label):
    """risk_multiplier_func: score -> multiplier"""
    equity = 500.0
    equity_curve = [equity]
    trades_taken = 0
    trade_r_list = []
    for i, t in enumerate(all_trades):
        r = t["r_multiple"]
        score = scores[i]
        mult = risk_multiplier_func(score)
        # Apply multiplier to R
        adj_r = r * mult
        equity *= (1 + adj_r * 0.01)  # assuming 1% risk per R
        trade_r_list.append(adj_r)
        equity_curve.append(equity)
        trades_taken += 1
    
    r_arr = np.array(trade_r_list)
    total_r = r_arr.sum()
    final_equity = equity
    total_return = (final_equity / 500.0 - 1) * 100
    mean_r = r_arr.mean()
    std_r = r_arr.std() if r_arr.std() > 0 else 1e-10
    sharpe = mean_r / std_r
    wins = r_arr[r_arr > 0]
    losses = r_arr[r_arr <= 0]
    wr = len(wins) / len(r_arr) * 100
    pf = abs(wins.sum() / losses.sum()) if losses.sum() != 0 else float("inf")
    downside = r_arr[r_arr < 0]
    sortino = mean_r / (downside.std() if len(downside) > 0 and downside.std() > 0 else 1e-10)
    
    # Max drawdown (equity curve)
    ec = np.array(equity_curve)
    peak = np.maximum.accumulate(ec)
    dd_pct = (ec - peak) / peak * 100
    max_dd = abs(dd_pct.min())
    
    # CAGR
    n_days = (all_trades[-1]["_entry_dt"] - all_trades[0]["_entry_dt"]).days
    years = max(1, n_days / 365.25)
    cagr = (final_equity / 500.0) ** (1 / years) - 1
    
    # Calmar
    calmar = cagr / (max_dd / 100) if max_dd > 0 else 0
    
    # Profit velocity (R/day)
    total_days = sum(
        len(t.get("prices", "").split("\n")) if isinstance(t.get("prices", ""), str) 
        else (len(t.get("prices", [])) if isinstance(t.get("prices", []), list) else 1)
        for t in all_trades
    )
    profit_velocity = total_r / max(1, total_days)
    
    return {
        "label": label,
        "trades": trades_taken,
        "final_equity": final_equity,
        "total_return_pct": total_return,
        "cagr_pct": cagr * 100,
        "total_r": total_r,
        "mean_r": mean_r,
        "std_r": std_r,
        "sharpe": sharpe,
        "sortino": sortino,
        "win_rate": wr,
        "profit_factor": pf,
        "max_dd_pct": max_dd,
        "calmar": calmar,
        "profit_velocity_r_per_day": profit_velocity,
    }

# Baseline: constant 1x
baseline = simulate(lambda s: 1.0, "Baseline (1×)")

# Moderate: score-based, clamped [0.75, 1.5]
def moderate_mult(s):
    if s >= 10:
        return 1.5
    elif s >= 5:
        return 1.25
    elif s >= 2:
        return 1.0
    else:
        return 0.75

moderate = simulate(moderate_mult, "Moderate (0.75×–1.5×)")

# Aggressive: wider range [0.5, 2.0]
def aggressive_mult(s):
    if s >= 10:
        return 2.0
    elif s >= 7:
        return 1.5
    elif s >= 4:
        return 1.25
    elif s >= 2:
        return 1.0
    else:
        return 0.5

aggressive = simulate(aggressive_mult, "Aggressive (0.5×–2.0×)")

# ── 6. Report ───────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TAIL-AWARE POSITION SIZING BACKTEST")
print("=" * 80)
print(f"Starting capital: $500.00")
print(f"Period: {all_trades[0]['_entry_dt'].date()} → {all_trades[-1]['_entry_dt'].date()} "
      f"({(all_trades[-1]['_entry_dt'] - all_trades[0]['_entry_dt']).days} days)")
print(f"Total trades: {N}")
print()

results = [baseline, moderate, aggressive]

header = f"{'Strategy':<25s} {'FinalEq':>10s} {'Return':>8s} {'CAGR':>8s} {'Sharpe':>8s} {'Sortino':>8s} {'WR':>6s} {'PF':>8s} {'MaxDD':>8s} {'Calmar':>8s} {'Vel(R/d)':>9s}"
print(header)
print("-" * len(header))
for r in results:
    print(f"{r['label']:<25s} ${r['final_equity']:>7.2f} {r['total_return_pct']:>7.2f}% "
          f"{r['cagr_pct']:>7.2f}% {r['sharpe']:>7.3f} {r['sortino']:>7.3f} "
          f"{r['win_rate']:>5.1f}% {r['profit_factor']:>7.3f} {r['max_dd_pct']:>7.2f}% "
          f"{r['calmar']:>7.3f} {r['profit_velocity_r_per_day']:>8.4f}")

# ── 7. Trade-level comparison: which trades get upsized/downsized ────────────
print("\n" + "=" * 80)
print("SIZING DECISION DISTRIBUTION")
print("=" * 80)

# Moderate sizing
mod_mults = np.array([moderate_mult(s) for s in scores])
agg_mults = np.array([aggressive_mult(s) for s in scores])

for label, mults in [("Moderate", mod_mults), ("Aggressive", agg_mults)]:
    print(f"\n  {label}:")
    for mult in sorted(set(mults)):
        n = (mults == mult).sum()
        pct = n / N * 100
        subset_r = r_vals[mults == mult]
        top5 = sum(1 for r in subset_r if r >= np.percentile(r_vals, 95))
        top5_pct = top5 / len(subset_r) * 100 if len(subset_r) > 0 else 0
        n_wins = (subset_r > 0).sum()
        wr_sub = n_wins / len(subset_r) * 100 if len(subset_r) > 0 else 0
        print(f"    {mult:.2f}x: n={n:5d} ({pct:5.1f}%) | avg_R={subset_r.mean():+.4f} | "
              f"WR={wr_sub:.1f}% | top5%_rate={top5_pct:.1f}%")

# ── 8. Score bucket analysis ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SCORE BUCKET PERFORMANCE")
print("=" * 80)

buckets = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 7), (7, 10), (10, 999)]
for lo, hi in buckets:
    mask = (scores >= lo) & (scores < hi)
    n = mask.sum()
    if n == 0:
        continue
    subset_r = r_vals[mask]
    n_top5 = sum(1 for r in subset_r if r >= np.percentile(r_vals, 95))
    print(f"  Score [{lo:3.0f}, {hi:3.0f}): n={n:5d} | avg_R={subset_r.mean():+.4f} | "
          f"WR={(subset_r>0).mean()*100:.1f}% | top5%_rate={n_top5/n*100:.1f}% | "
          f"total_R={subset_r.sum():+.2f}")

# ── 9. Top-5% capture by strategy ──────────────────────────────────────────
print("\n" + "=" * 80)
print("TOP-5% TRADE CAPTURE (do we size up on the right trades?)")
print("=" * 80)

top5_th = np.percentile(r_vals, 95)
is_top5 = r_vals >= top5_th
n_top5 = is_top5.sum()

print(f"  Top-5% threshold: {top5_th:.4f}R")
print(f"  Top-5% trades: {n_top5}")

for label, mults in [("Baseline (1×)", np.ones(N)), ("Moderate", mod_mults), ("Aggressive", agg_mults)]:
    avg_mult_on_top5 = mults[is_top5].mean()
    avg_mult_on_normal = mults[~is_top5].mean()
    top5_contribution = (r_vals * mults)[is_top5].sum()
    total_contribution = (r_vals * mults).sum()
    top5_share = top5_contribution / total_contribution * 100 if total_contribution != 0 else 0
    print(f"  {label:<25s}: avg_mult on top5={avg_mult_on_top5:.3f}x | "
          f"avg_mult on normal={avg_mult_on_normal:.3f}x | "
          f"top5 share of PnL={top5_share:.1f}%")

print("\nDone.")
