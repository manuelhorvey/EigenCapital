#!/usr/bin/env python3
"""
Robustness grid + asset-level attribution for profit floor protection.

Loads all trades from trade_lifecycle_results.json, simulates the profit
floor lifecycle across a trigger×floor grid, and produces per-asset
attribution for the candidate configs.

Usage::

    python scripts/analysis/profit_floor_robustness.py

Output::

    Grid heatmap (total R delta) + asset-level attribution table
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


def get_prices(t):
    ps = t.get("prices", "")
    if not isinstance(ps, str):
        return []
    return [float(l.split()[1]) for l in ps.strip().split("\n") if l.strip() and "dtype:" not in l]


def compute_candle_r(prices, entry, risk, side):
    if risk == 0:
        return [0.0] * len(prices)
    mult = 1 if side == "BUY" else -1
    return [mult * (p - entry) / risk for p in prices]


def prepare_trades(trades):
    """Filter to trades with usable price data and precompute candle R-series."""
    usable = []
    for t in trades:
        prices = get_prices(t)
        if len(prices) < 2:
            continue
        entry = t["entry_price"]
        sl = t["sl_price"]
        risk = abs(entry - sl)
        side = t["side"]
        r_prices = compute_candle_r(prices, entry, risk, side)
        usable.append({
            "asset": t["asset"],
            "actual_r": t["r_multiple"],
            "exit_reason": t["exit_reason"],
            "r_prices": r_prices,
            "mfe_r": max(r_prices) if r_prices else 0,
            "candles": len(r_prices),
        })
    return usable


def simulate_profit_floor(trades, trigger_r, floor_r):
    """Simulate profit floor: track peak R, trigger, enforce floor."""
    result = np.empty(len(trades), dtype=float)
    improved = np.zeros(len(trades), dtype=bool)
    harmed = np.zeros(len(trades), dtype=bool)

    for i, t in enumerate(trades):
        r_prices = t["r_prices"]
        baseline_r = t["actual_r"]
        highest_r = -999.0
        triggered = False
        realised = baseline_r

        for r in r_prices:
            if r > highest_r:
                highest_r = r
            if not triggered and highest_r >= trigger_r:
                triggered = True
            if triggered and r < floor_r:
                realised = floor_r
                break

        result[i] = realised
        improved[i] = realised > baseline_r
        harmed[i] = realised < baseline_r

    return result, improved, harmed


# ── Load and prepare ─────────────────────────────────────────────────────────
usable = prepare_trades(all_trades)
baseline_r = np.array([t["actual_r"] for t in usable])

print(f"Total trades in dataset: {len(all_trades)}")
print(f"Trades with price data:  {len(usable)}")

# ── Grid: trigger × floor ────────────────────────────────────────────────────
triggers = [2.0, 2.25, 2.5, 2.75, 3.0]
floors = [1.25, 1.5, 1.75, 2.0, 2.25]

print(f"\n{'='*100}")
print("ROBUSTNESS GRID — TOTAL R DELTA (vs baseline)")
print("Each cell: Δ_R  |  improved/harmed  |  top5% change")
print(f"{'='*100}")

header = f"{'Trigger →':>10s}" + "".join(f"{f:>12.2f}" for f in floors)
print(f"\n{header}")
print(f"{'─'*len(header)}")

for tr in triggers:
    row = f"{tr:<5.2f}      "
    for fl in floors:
        sim_r, imp, harm = simulate_profit_floor(usable, tr, fl)
        delta = sim_r.sum() - baseline_r.sum()
        sorted_sim = np.sort(sim_r)
        sorted_base = np.sort(baseline_r)
        top5_sim = sorted_sim[int(len(sorted_sim) * 0.95):].sum()
        top5_base = sorted_base[int(len(sorted_base) * 0.95):].sum()
        top5_change = top5_sim - top5_base
        imp_ct = int(imp.sum())
        harm_ct = int(harm.sum())
        row += f"{delta:+7.1f} {imp_ct:>3d}/{harm_ct:<3d} T{top5_change:+4.1f}  "
    print(row)

# ── Best configs summary ─────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("TOP CONFIGS BY TOTAL R DELTA")
print(f"{'='*100}")
results = []
for tr in triggers:
    for fl in floors:
        sim_r, imp, harm = simulate_profit_floor(usable, tr, fl)
        delta = sim_r.sum() - baseline_r.sum()
        imp_ct = int(imp.sum())
        harm_ct = int(harm.sum())
        harm_ratio = harm_ct / max(imp_ct, 1)
        results.append((delta, harm_ratio, tr, fl, imp_ct, harm_ct))

results.sort(key=lambda x: x[0], reverse=True)
print(f"\n  {'Rank':>4s} {'Trigger':>8s} {'Floor':>6s} {'Δ_R':>9s} {'Imp':>5s} {'Harm':>6s} {'Ratio':>6s} {'Top5%':>10s}")
print(f"  {'─'*60}")
for rank, (delta, h_ratio, tr, fl, imp_ct, harm_ct) in enumerate(results[:10], 1):
    top5_base = np.sort(baseline_r)[int(len(baseline_r) * 0.95):].sum()
    sim_r, _, _ = simulate_profit_floor(usable, tr, fl)
    top5_sim = np.sort(sim_r)[int(len(sim_r) * 0.95):].sum()
    print(f"  {rank:>4d} {tr:>8.2f} {fl:>6.2f} {delta:+9.1f}R {imp_ct:>5d} {harm_ct:>6d} {h_ratio:>6.2f} {top5_sim - top5_base:+10.1f}R")

print(f"\n{'─'*60}")
print(f"  Baseline total R: {baseline_r.sum():+.1f}R")
print(f"  Baseline top5%:   {top5_base:+.1f}R")

# ── Asset-level attribution for best configs ─────────────────────────────────
print(f"\n{'='*100}")
print("ASSET-LEVEL ATTRIBUTION")
print(f"{'='*100}")

candidate_configs = [
    ("2.5/2.0 (production)", 2.5, 2.0),
    ("2.5/1.75", 2.5, 1.75),
    ("2.75/2.0", 2.75, 2.0),
    ("2.25/1.75", 2.25, 1.75),
]

assets_in_data = sorted(set(t["asset"] for t in usable))
n_assets = len(assets_in_data)

for label, tr, fl in candidate_configs:
    print(f"\n  {label}: trigger={tr}R, floor={fl}R")
    print(f"  {'─'*80}")
    print(f"  {'Asset':>20s} {'Count':>6s} {'Baseline_R':>11s} {'Sim_R':>8s} {'Δ_R':>9s} {'Δ%':>7s} {'Top5_Δ':>8s} {'Imp':>5s} {'Harm':>6s}")
    print(f"  {'─'*80}")

    asset_trades = defaultdict(list)
    for i, t in enumerate(usable):
        asset_trades[t["asset"]].append(i)

    total_delta = 0.0
    for asset in sorted(asset_trades):
        idx = asset_trades[asset]
        asset_baseline = baseline_r[idx]
        sim_r, imp, harm = simulate_profit_floor([usable[i] for i in idx], tr, fl)
        a_delta = sim_r.sum() - asset_baseline.sum()
        pct = a_delta / max(abs(asset_baseline.sum()), 1e-9) * 100
        top5_base_a = np.sort(asset_baseline)[int(len(asset_baseline) * 0.95):].sum() if len(asset_baseline) >= 20 else 0
        top5_sim_a = np.sort(sim_r)[int(len(sim_r) * 0.95):].sum() if len(sim_r) >= 20 else 0
        imp_ct = int(imp.sum())
        harm_ct = int(harm.sum())
        total_delta += a_delta
        print(f"  {asset:>20s} {len(idx):>6d} {asset_baseline.sum():+11.1f}R {sim_r.sum():+8.1f}R {a_delta:+9.1f}R {pct:+6.1f}% {top5_sim_a - top5_base_a:+8.1f}R {imp_ct:>5d} {harm_ct:>6d}")

    print(f"  {'─'*80}")
    print(f"  {'TOTAL':>20s} {len(usable):>6d} {baseline_r.sum():+11.1f}R {baseline_r.sum()+total_delta:+8.1f}R {total_delta:+9.1f}R")

# ── Harmed trades deep dive (2.5/2.0) ────────────────────────────────────────
print(f"\n{'='*100}")
print("HARMED TRADES DEEP DIVE (2.5R/2.0R)")
print(f"{'='*100}")

sim_r, imp, harm = simulate_profit_floor(usable, 2.5, 2.0)
harmed_idx = np.where(harm)[0]
if len(harmed_idx) > 0:
    harmed_by_asset = defaultdict(list)
    for i in harmed_idx:
        t = usable[i]
        harmed_by_asset[t["asset"]].append((t["actual_r"], t["mfe_r"], t["candles"]))
    print(f"\n  {'Asset':>20s} {'Count':>6s} {'Avg_baseline_R':>15s} {'Avg_MFE':>8s} {'Avg_candles':>11s} {'Avg_lost':>9s}")
    print(f"  {'─'*70}")
    for asset in sorted(harmed_by_asset):
        entries = harmed_by_asset[asset]
        avg_base = np.mean([e[0] for e in entries])
        avg_mfe = np.mean([e[1] for e in entries])
        avg_candles = np.mean([e[2] for e in entries])
        avg_lost = np.mean([e[0] - 2.0 for e in entries])  # capped at floor_r
        print(f"  {asset:>20s} {len(entries):>6d} {avg_base:>15.4f}R {avg_mfe:>8.2f}R {avg_candles:>11.1f} {avg_lost:>+9.4f}R")

# ── Win-rate preservation check ──────────────────────────────────────────────
print(f"\n{'='*100}")
print("WIN-RATE PRESERVATION (2.5R/2.0R)")
print(f"{'='*100}")
baseline_wr = (baseline_r > 0).mean() * 100
sim_wr = (sim_r > 0).mean() * 100
print(f"  Baseline WR: {baseline_wr:.2f}%")
print(f"  Sim WR:      {sim_wr:.2f}%")
print(f"  WR change:   {sim_wr - baseline_wr:+.2f}pp")

# Trades that flipped from loss to win
flipped_win = ((baseline_r <= 0) & (sim_r > 0)).sum()
flipped_loss = ((baseline_r > 0) & (sim_r <= 0)).sum()
print(f"  Flipped loss→win: {flipped_win}")
print(f"  Flipped win→loss: {flipped_loss}")
