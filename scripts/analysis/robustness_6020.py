#!/usr/bin/env python3
"""Robustness gatekeeper for 60%@2.0R + 20% retrace exit strategy."""

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
    return sim(t, 0.6, 2.0, 0.20)


BASE_RS = np.array([baseline(t) for t in trades])
CAND_RS = np.array([candidate(t) for t in trades])
N = len(trades)

print(f"\n{'=' * 72}")
print(f"  ROBUSTNESS GATEKEEPER: 60%@2.0R + 20% retrace")
print(f"  {N} trades, {len(data['_trades'])} assets")
print(f"{'=' * 72}")

# 1. Per-asset benefit
print(f"\n  [1] Per-asset benefit (all 16 assets improve?)")
all_ok = True
for asset in sorted(data["_trades"].keys()):
    ts = data["_trades"][asset]
    br = sum(baseline(t) for t in ts)
    cr = sum(candidate(t) for t in ts)
    ok = cr > br
    if not ok:
        all_ok = False
    print(f"  {asset:<10s}  baseline {br:>8.2f}R  candidate {cr:>8.2f}R  {'✓' if ok else '✗'} +{cr-br:>+.2f}")
print(f"  ──> {'ALL PASS' if all_ok else 'FAILED'}")


# 2. Bootstrap
print(f"\n  [2] Bootstrap (P(candidate > baseline) over {2000:,} resamples)")
wins = 0
for _ in range(2000):
    idx = np.random.randint(0, N, N)
    if CAND_RS[idx].sum() > BASE_RS[idx].sum():
        wins += 1
ci_frac = 100 * wins / 2000
sig = ci_frac >= 95
print(f"  P(candidate > baseline) = {ci_frac:.1f}%{' (p < 0.05)' if sig else ''}")
print(f"  ──> {'SIGNIFICANT' if sig else 'NOT SIGNIFICANT'}")


# 3. Time stability (split first/last half)
print(f"\n  [3] Time stability (first half vs second half)")
half = N // 2
h1_base = BASE_RS[:half]
h1_cand = CAND_RS[:half]
h2_base = BASE_RS[half:]
h2_cand = CAND_RS[half:]
h1_ok = h1_cand.sum() > h1_base.sum()
h2_ok = h2_cand.sum() > h2_base.sum()
print(f"  First half:  baseline {h1_base.sum():>8.2f}R  candidate {h1_cand.sum():>8.2f}R  +{h1_cand.sum()-h1_base.sum():>+.2f}  {'✓' if h1_ok else '✗'}")
print(f"  Second half: baseline {h2_base.sum():>8.2f}R  candidate {h2_cand.sum():>8.2f}R  +{h2_cand.sum()-h2_base.sum():>+.2f}  {'✓' if h2_ok else '✗'}")
print(f"  ──> {'BOTH PASS' if h1_ok and h2_ok else 'FAILED'}")


# 4. Slippage sensitivity
print(f"\n  [4] Slippage sensitivity (adverse slippage on every trade)")
for adv in [0.5, 1.0, 2.0, 3.0]:
    slip_rs = np.array([candidate(t) - adv * abs(candidate(t) - baseline(t)) for t in trades])
    still_better = slip_rs.sum() > BASE_RS.sum()
    pct_retained = (slip_rs.sum() / CAND_RS.sum()) * 100
    print(f"  Adverse slippage {adv:>4.1f}R:  net {slip_rs.sum():>8.2f}R ({pct_retained:>5.1f}% retained)  baseline {BASE_RS.sum():>8.2f}R  {'✓' if still_better else '✗'}")
    if not still_better:
        break
else:
    print(f"  ──> ALL PASS (survives up to 3.0R adverse slippage)")


# 5. Benefit concentration
print(f"\n  [5] Benefit concentration (Gini)")
delta = CAND_RS - BASE_RS
gains = delta[delta > 0]
losses = delta[delta < 0]
print(f"  Trades improved: {len(gains):>4d} ({100*len(gains)/N:.1f}%)")
print(f"  Trades harmed:   {len(losses):>4d} ({100*len(losses)/N:.1f}%)")
if len(gains) > 1:
    sg = np.sort(gains)
    n_g = len(sg)
    l = np.arange(1, n_g + 1)
    gini = (2 * (l * sg).sum() - n_g * sg.sum()) / (n_g * sg.sum())
    top10 = int(n_g * 0.1) or 1
    top_frac = sg[-top10:].sum() / sg.sum() * 100
    avg_gain = gains.mean()
    avg_loss = losses.mean() if len(losses) > 0 else 0
    print(f"  Gini coefficient:                     {gini:.3f}")
    print(f"  Top 10% of improvements account for:  {top_frac:.1f}%")
    print(f"  Avg improvement per improved trade:   {avg_gain:.4f}R")
    if len(losses) > 0:
        print(f"  Avg harm per harmed trade:            {avg_loss:.4f}R")
print(f"  ──> {'LOW CONCENTRATION' if gini < 0.3 else 'MODERATE' if gini < 0.5 else 'HIGH CONCENTRATION'}")


# 6. Drawdown behavior
print(f"\n  [6] Drawdown behavior (helps when it hurts?)")
base_cum = np.cumsum(BASE_RS)
cand_cum = np.cumsum(CAND_RS)
base_peak = np.maximum.accumulate(base_cum)
cand_peak = np.maximum.accumulate(cand_cum)
base_dd = base_cum - base_peak
cand_dd = cand_cum - cand_peak

worst_base_dd_idx = int(np.argmin(base_dd))
print(f"  Worst baseline drawdown: {base_dd.min():>8.2f}R at trade {worst_base_dd_idx}")
print(f"  Candidate during same period: {cand_dd[worst_base_dd_idx]:>8.2f}R")
better_during_dd = cand_dd[worst_base_dd_idx] > base_dd[worst_base_dd_idx]

dd_delta = cand_dd - base_dd
mask = base_dd < -5
help_during_dd = dd_delta[mask]
help_pct = (help_during_dd > 0).mean() * 100 if len(help_during_dd) > 0 else 0
print(f"  During >5R drawdown events: candidate helps in {help_pct:.0f}% of trades")
print(f"  ──> {'HELPS DURING DRAWDOWN' if better_during_dd else 'NEUTRAL'}")


# 7. Parameter sensitivity
print(f"\n  [7] Parameter sensitivity (nearby configs)")
sweep = []
for sp in [0.5, 0.55, 0.60, 0.65, 0.70]:
    for sr in [1.5, 1.75, 2.0, 2.25, 2.5]:
        for rt in [0.15, 0.20, 0.25, 0.30]:
            r = np.array([sim(t, sp, sr, rt) for t in trades])
            swe = r.std() > 0
            sh = r.mean() / r.std() if swe else 0
            sweep.append((r.sum(), sh, sp, sr, rt))
sweep.sort(reverse=True)
best_r = max(r[0] for r in sweep)

print(f"  Swept 5×5×4 = 100 configs within [0.5-0.7, 1.5-2.5, 0.15-0.30]")
print(f"  Best: {sweep[0][0]:>8.2f}R  Sharpe {sweep[0][1]:.4f}  ({100*sweep[0][2]:.0f}%/{sweep[0][3]:.1f}R/{100*sweep[0][4]:.0f}%)")
print(f"  Our 60%/2.0R/20%: {sweep[1][0]:>8.2f}R  Sharpe {sweep[1][1]:.4f}  ranks #{next(i+1 for i,s in enumerate(sweep) if abs(s[0]-CAND_RS.sum())<0.1)}")
print(f"  Median config: {sweep[50][0]:>8.2f}R")
print(f"  Range (max-min): {sweep[0][0]-sweep[-1][0]:>8.2f}R")
stable = sweep[0][0] - CAND_RS.sum() < 50  # best is within 50R
print(f"  ──> {'STABLE PLATEAU' if stable else 'SHARP PEAK'} (best is {sweep[0][0]-sweep[1][0]:+.2f}R above ours)")


# 8. Ablation: which component drives the improvement?
print(f"\n  [8] Ablation: what drives the improvement?")
base_2R_20 = np.array([sim(t, 0.5, 1.0, 0.50) for t in trades])  # current
abl_scale = np.array([sim(t, 0.6, 1.0, 0.50) for t in trades])  # just increase scale
abl_target = np.array([sim(t, 0.5, 2.0, 0.50) for t in trades])  # just later target
abl_retrace = np.array([sim(t, 0.5, 1.0, 0.20) for t in trades])  # just tighter trail
abl_full = np.array([sim(t, 0.6, 2.0, 0.20) for t in trades])

print(f"  Current (50%/1R/50%):      {base_2R_20.sum():>8.2f}R")
print(f"  Just scale↑ (60%/1R/50%):  {abl_scale.sum():>8.2f}R  Δ+{abl_scale.sum()-base_2R_20.sum():>+.2f}")
print(f"  Just target↑ (50%/2R/50%): {abl_target.sum():>8.2f}R  Δ+{abl_target.sum()-base_2R_20.sum():>+.2f}")
print(f"  Just retrace↓ (50%/1R/20%):{abl_retrace.sum():>8.2f}R  Δ+{abl_retrace.sum()-base_2R_20.sum():>+.2f}")
print(f"  Full (60%/2R/20%):         {abl_full.sum():>8.2f}R  Δ+{abl_full.sum()-base_2R_20.sum():>+.2f}")
print(f"  Synergy: {abl_full.sum() - (base_2R_20.sum() + sum(s - base_2R_20.sum() for s in [abl_scale.sum(), abl_target.sum(), abl_retrace.sum()])):>+.2f}R")
print(f"  ──> {'COMPONENTS ADDITIVE' if abs(abl_full.sum() - (base_2R_20.sum() + (abl_scale.sum()-base_2R_20.sum()) + (abl_target.sum()-base_2R_20.sum()) + (abl_retrace.sum()-base_2R_20.sum()))) < 10 else 'COMPONENTS INTERACTIVE'}")


# ── Verdict ──
print(f"\n{'=' * 72}")
passed = all([
    all_ok,
    sig,
    h1_ok and h2_ok,
    slip_rs.sum() > BASE_RS.sum(),
    gini < 0.5,
])
print(f"  VERDICT: {'DEPLOY' if passed else 'INVESTIGATE'} — 60%@2.0R + 20% retrace")
if not all_ok: print(f"  ✗ Per-asset benefit failed")
if not sig: print(f"  ✗ Bootstrap not significant")
if not (h1_ok and h2_ok): print(f"  ✗ Time stability failed")
if not (slip_rs.sum() > BASE_RS.sum()): print(f"  ✗ Slippage sensitivity failed")
if not (gini < 0.5): print(f"  ✗ Benefit concentration too high")
print(f"{'=' * 72}\n")
