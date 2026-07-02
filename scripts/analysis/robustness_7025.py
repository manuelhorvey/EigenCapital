#!/usr/bin/env python3
"""Robustness gatekeeper for the optimal config: 70%@2.5R + 15% retrace."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"

with open(TRADE_PATH) as f:
    data = json.load(f)

trades = []
for asset, ts in data["_trades"].items():
    for t in ts:
        t["_asset"] = asset
        trades.append(t)


def sim(t, scale_pct, scale_r, trail_retrace):
    orig = t.get("r_multiple", 0.0)
    mfe = t.get("mfe_r", 0.0)
    if orig >= 0:
        return orig
    if mfe < 0.5 or t.get("exit_reason") == "tp":
        return orig
    captured = scale_pct * (scale_r if mfe >= scale_r else mfe)
    rem = 1.0 - scale_pct
    if mfe >= 0.8:
        captured += rem * max(mfe * (1.0 - trail_retrace), 0)
    return max(captured, 0)


def baseline(t):
    return sim(t, 0.5, 1.0, 0.50)


def candidate(t):
    return sim(t, 0.7, 2.5, 0.15)


P_OPT = {"scale_pct": 0.7, "scale_r": 2.5, "trail_retrace": 0.15}
P_REF = {"scale_pct": 0.5, "scale_r": 1.0, "trail_retrace": 0.50}
P_USER = {"scale_pct": 0.5, "scale_r": 1.0, "trail_retrace": 0.33}
P_6020 = {"scale_pct": 0.6, "scale_r": 2.0, "trail_retrace": 0.20}

BASE_RS = np.array([baseline(t) for t in trades])
CAND_RS = np.array([candidate(t) for t in trades])
N = len(trades)

print(f"\n{'=' * 72}")
print(f"  ROBUSTNESS GATEKEEPER: 70%@2.5R + 15% retrace (optimum)")
print(f"  {N} trades, {len(data['_trades'])} assets")
print(f"  vs baseline 50%/1R/50%: {CAND_RS.sum() - BASE_RS.sum():+.2f}R")
print(f"{'=' * 72}")

# 1. Per-asset
print(f"\n  [1] Per-asset benefit")
all_ok = True
for asset in sorted(data["_trades"].keys()):
    ts = data["_trades"][asset]
    br = sum(baseline(t) for t in ts)
    cr = sum(candidate(t) for t in ts)
    ok = cr > br
    if not ok:
        all_ok = False
    print(f"  {asset:<10s}  +{cr-br:>+7.2f}R  {'✓' if ok else '✗'}")
print(f"  ──> {'ALL 16 ASSETS POSITIVE' if all_ok else 'FAILED'}")

# 2. Bootstrap
print(f"\n  [2] Bootstrap (P(candidate > baseline) over 10,000 resamples)")
wins = 0
for _ in range(10000):
    idx = np.random.randint(0, N, N)
    if CAND_RS[idx].sum() > BASE_RS[idx].sum():
        wins += 1
ci_frac = 100 * wins / 10000
sig = ci_frac >= 95
print(f"  P = {ci_frac:.1f}%{' (p < 0.0001)' if wins == 10000 else ''}")
print(f"  ──> {'SIGNIFICANT' if sig else 'NOT SIGNIFICANT'}")

# 3. Time stability
print(f"\n  [3] Time stability")
half = N // 2
h1_ok = CAND_RS[:half].sum() > BASE_RS[:half].sum()
h2_ok = CAND_RS[half:].sum() > BASE_RS[half:].sum()
print(f"  First half:  +{CAND_RS[:half].sum()-BASE_RS[:half].sum():>+.2f}R  {'✓' if h1_ok else '✗'}")
print(f"  Second half: +{CAND_RS[half:].sum()-BASE_RS[half:].sum():>+.2f}R  {'✓' if h2_ok else '✗'}")
print(f"  ──> {'BOTH PASS' if h1_ok and h2_ok else 'FAILED'}")

# 4a. Slippage sensitivity
print(f"\n  [4a] Slippage sensitivity (adverse per trade)")
slip_pass = True
for adv in [0.5, 1.0, 2.0, 3.0]:
    slip_rs = CAND_RS - adv * np.maximum(CAND_RS - BASE_RS, 0)
    ok = slip_rs.sum() > BASE_RS.sum()
    pct = slip_rs.sum() / CAND_RS.sum() * 100
    print(f"  {adv:>4.1f}R adverse:  net {slip_rs.sum():>+8.2f}R ({pct:.1f}% retained)  {'✓' if ok else '✗'}")
    if not ok:
        slip_pass = False
        break
print(f"  ──> {'PASS' if slip_pass else f'FAILS at {adv}R'}")

# 4b. Realistic slippage (stochastic)
print(f"  [4b] Stochastic slippage (1000 sims, ~0.15R mean adverse)")
slip_dist = np.abs(np.random.normal(0, 0.15, (1000, N)))
slip_results = []
for s in slip_dist:
    sr = CAND_RS - s
    slip_results.append(sr.sum() - BASE_RS.sum())
arr = np.array(slip_results)
p_positive = (arr > 0).mean()
print(f"  Mean net improvement after slippage: {arr.mean():>+.2f}R")
print(f"  P(still > baseline): {p_positive*100:.1f}%")
print(f"  ──> {'ROBUST' if p_positive > 0.95 else 'FRAGILE'}")

# 5. Benefit concentration
print(f"\n  [5] Benefit concentration")
delta = CAND_RS - BASE_RS
gains = delta[delta > 0]
losses = delta[delta < 0]
print(f"  Trades improved: {len(gains):>4d} ({100*len(gains)/N:.1f}%)")
print(f"  Trades harmed:   {len(losses):>4d} ({100*len(losses)/N:.1f}%)")
if len(gains) > 1:
    sg = np.sort(gains)
    n_g = len(sg)
    gini = (2 * (np.arange(1, n_g + 1) * sg).sum() - n_g * sg.sum()) / (n_g * sg.sum())
    top10 = int(n_g * 0.1) or 1
    top_frac = sg[-top10:].sum() / sg.sum() * 100
    print(f"  Gini: {gini:.3f}   Top 10%: {top_frac:.1f}%")
    print(f"  Avg improv/improved trade: {gains.mean():.4f}R")
if len(losses) > 0:
    print(f"  Avg harm/harmed trade: {losses.mean():.4f}R")
print(f"  ──> {'LOW' if gini < 0.3 else 'MODERATE' if gini < 0.5 else 'HIGH'}")

# 6. Drawdown
print(f"\n  [6] Drawdown behavior")
base_cum = np.cumsum(BASE_RS)
cand_cum = np.cumsum(CAND_RS)
base_dd = base_cum - np.maximum.accumulate(base_cum)
cand_dd = cand_cum - np.maximum.accumulate(cand_cum)
worst_idx = int(np.argmin(base_dd))
print(f"  Worst baseline DD: {base_dd.min():>7.2f}R (trade {worst_idx})")
print(f"  Candidate same period: {cand_dd[worst_idx]:>7.2f}R")
mask = base_dd < -5
if mask.any():
    help_pct = ((cand_dd[mask] - base_dd[mask]) > 0).mean() * 100
    print(f"  During >5R DD: helps in {help_pct:.0f}% of trades")
print(f"  ──> {'HELPS' if cand_dd[worst_idx] > base_dd[worst_idx] else 'NEUTRAL/HURTS'}")

# 7. Robustness variant test
print(f"\n  [7] Robustness of neighbouring configs")
sweep = []
for sp in [0.65, 0.70, 0.75]:
    for sr in [2.0, 2.5, 3.0]:
        for rt in [0.10, 0.15, 0.20]:
            r = np.array([sim(t, sp, sr, rt) for t in trades])
            sh = r.mean() / r.std() if r.std() > 0 else 0
            sweep.append((r.sum(), sh, sp, sr, rt))
sweep.sort(reverse=True)
best_r = sweep[0][0]
our_rank = next(i for i, s in enumerate(sweep) if abs(s[0] - CAND_RS.sum()) < 0.1)
mean_r = np.mean([s[0] for s in sweep])
std_r = np.std([s[0] for s in sweep])
print(f"  {len(sweep)} configs in [0.65-0.75, 2.0-3.0, 0.10-0.20]")
print(f"  Ours ranks #{our_rank+1}  Best: {best_r:.2f}R (Sh {sweep[0][1]:.4f})")
print(f"  Mean: {mean_r:.2f}R  σ: {std_r:.2f}R")
print(f"  Worst in set: {sweep[-1][0]:.2f}R")
print(f"  ──> {'STABLE' if our_rank < len(sweep) * 0.3 else 'PERIPHERAL'}")

# 8. Ablation
print(f"\n  [8] Ablation")
abl_70_1_50 = np.array([sim(t, 0.7, 1.0, 0.50) for t in trades])
abl_50_25_50 = np.array([sim(t, 0.5, 2.5, 0.50) for t in trades])
abl_50_1_15 = np.array([sim(t, 0.5, 1.0, 0.15) for t in trades])
print(f"  Baseline (50%/1R/50%):          {BASE_RS.sum():>8.2f}R")
print(f"  Just scale↑ (70%/1R/50%):       {abl_70_1_50.sum():>8.2f}R  +{abl_70_1_50.sum()-BASE_RS.sum():>+.2f}")
print(f"  Just target↑ (50%/2.5R/50%):    {abl_50_25_50.sum():>8.2f}R  +{abl_50_25_50.sum()-BASE_RS.sum():>+.2f}")
print(f"  Just retrace↓ (50%/1R/15%):     {abl_50_1_15.sum():>8.2f}R  +{abl_50_1_15.sum()-BASE_RS.sum():>+.2f}")
print(f"  Full (70%/2.5R/15%):            {CAND_RS.sum():>8.2f}R  +{CAND_RS.sum()-BASE_RS.sum():>+.2f}")
synergy = CAND_RS.sum() - (BASE_RS.sum() + (abl_70_1_50.sum()-BASE_RS.sum()) + (abl_50_25_50.sum()-BASE_RS.sum()) + (abl_50_1_15.sum()-BASE_RS.sum()))
print(f"  Synergy: {synergy:+.2f}R  ──> {'ADDITIVE' if abs(synergy) < 20 else 'INTERACTIVE'}")

# 9. Comparison table
print(f"\n  [9] Config comparison")
for name, cfg in [("Current live", P_REF), ("User proposal", P_USER), ("60/20 find", P_6020), ("Optimum", P_OPT)]:
    r = np.array([sim(t, cfg['scale_pct'], cfg['scale_r'], cfg['trail_retrace']) for t in trades])
    sh = r.mean() / r.std() if r.std() > 0 else 0
    wr = (r > 0).mean() * 100
    cum = np.cumsum(r)
    dd = (cum - np.maximum.accumulate(cum)).min()
    print(f"  {name:<20s}  {r.sum():>8.2f}R  {sh:.4f} Sh  {wr:.0f}% WR  {dd:.1f} DD")

# ── Verdict ──
print(f"\n{'=' * 72}")
p1 = all_ok
p2 = sig
p3 = h1_ok and h2_ok
p4 = slip_pass and p_positive > 0.95
p5 = gini < 0.5
p6 = cand_dd[worst_idx] > base_dd[worst_idx]
passed = all([p1, p2, p3, p4, p5, p6])
print(f"  VERDICT: {'DEPLOY' if passed else 'INVESTIGATE'}")
for name, ok in [("Per-asset", p1), ("Bootstrap", p2), ("Time stability", p3),
                  ("Slippage", p4), ("Concentration", p5), ("Drawdown", p6)]:
    print(f"  {'✓' if ok else '✗'} {name}")
print(f"{'=' * 72}\n")
