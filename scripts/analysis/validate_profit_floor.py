#!/usr/bin/env python3
"""
Replay validation: profit floor protection vs baseline.

Loads all trades from trade_lifecycle_results.json, simulates the profit
floor lifecycle (ACTIVE → PROFIT_LOCKED → LOCK_EXIT) on each trade's
candle-level price series, and compares aggregate metrics.

Usage::

    python scripts/analysis/validate_profit_floor.py

Output::

    Trade count: N
    Baseline vs Profit Floor (2.5R trigger, 2.0R floor):
    ...
"""

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


# ── Prepare usable trades (those with price data) ─────────────────────────────
usable = []
for t in all_trades:
    prices = get_prices(t)
    if len(prices) < 2:
        continue
    entry = t["entry_price"]
    sl = t["sl_price"]
    risk = abs(entry - sl)
    side = t["side"]
    r_prices = compute_candle_r(prices, entry, risk, side)
    usable.append({
        "actual_r": t["r_multiple"],
        "exit_reason": t["exit_reason"],
        "r_prices": r_prices,
        "mfe_r": max(r_prices) if r_prices else 0,
        "candles": len(r_prices),
    })

print(f"Total trades in dataset: {len(all_trades)}")
print(f"Trades with price data:  {len(usable)}")


def simulate_profit_floor(trades, trigger_r=2.5, floor_r=2.0):
    """Simulate profit floor protection on a list of trade dicts.

    Returns an array of realized R-multiples under the policy.
    """
    result = []
    for t in trades:
        r_prices = t["r_prices"]
        realised = t["actual_r"]
        highest_r = -999.0
        triggered = False

        for r in r_prices:
            if r > highest_r:
                highest_r = r

            if not triggered and highest_r >= trigger_r:
                triggered = True

            if triggered and r < floor_r:
                realised = floor_r
                break

        result.append(realised)
    return np.array(result)


# ── Baseline: actual realized R ──────────────────────────────────────────────
baseline_r = np.array([t["actual_r"] for t in usable])

# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT: PROFIT FLOOR PROTECTION
# ══════════════════════════════════════════════════════════════════════════════
configs = [
    ("1.5R trigger, 1.2R floor", 1.5, 1.2),
    ("2.0R trigger, 1.5R floor", 2.0, 1.5),
    ("2.5R trigger, 1.5R floor", 2.5, 1.5),
    ("2.5R trigger, 2.0R floor", 2.5, 2.0),
    ("3.0R trigger, 2.0R floor", 3.0, 2.0),
    ("3.0R trigger, 2.5R floor", 3.0, 2.5),
]

print(f"\n{'='*80}")
print("PROFIT FLOOR PROTECTION — REPLAY VALIDATION")
print(f"{'='*80}")
print(f"\n  {'Config':>30s} {'Baseline_R':>10s} {'Sim_R':>8s} {'Δ_R':>9s} "
      f"{'Top5_contrib':>14s} {'AvgWin':>8s} {'WR':>6s} "
      f"{'Improved':>9s} {'Harmed':>7s}")
print(f"  {'-'*105}")

for label, trigger_r, floor_r in configs:
    sim_r = simulate_profit_floor(usable, trigger_r, floor_r)

    total_r = sim_r.sum()
    baseline_total = baseline_r.sum()
    r_diff = total_r - baseline_total

    sorted_sim = np.sort(sim_r)
    top5_contrib = sorted_sim[int(len(sorted_sim) * 0.95):].sum()
    avg_win = sim_r[sim_r > 0].mean() if (sim_r > 0).any() else 0.0
    wr = (sim_r > 0).mean() * 100

    improved = int((sim_r > baseline_r).sum())
    harmed = int((sim_r < baseline_r).sum())

    print(f"  {label:>30s} {baseline_total:+10.2f} {total_r:+8.2f} {r_diff:+9.2f}R "
          f"{top5_contrib:+14.2f}R {avg_win:+8.3f}R {wr:6.2f}% "
          f"{improved:>9d} {harmed:>7d}")

# ══════════════════════════════════════════════════════════════════════════════
# DETAILED ANALYSIS: 2.5R/2.0R (production config)
# ══════════════════════════════════════════════════════════════════════════════
pro_trigger = 2.5
pro_floor = 2.0
pro_sim = simulate_profit_floor(usable, pro_trigger, pro_floor)
pro_diff = pro_sim - baseline_r

# Which trades get improved?
improved_idx = np.where(pro_sim > baseline_r)[0]
harmed_idx = np.where(pro_sim < baseline_r)[0]

print(f"\n{'='*80}")
print(f"DETAILED: {pro_trigger}R trigger, {pro_floor}R floor")
print(f"{'='*80}")
print(f"  Total trades:              {len(usable)}")
print(f"  Improved:                  {len(improved_idx)} ({len(improved_idx)/len(usable)*100:.1f}%)")
print(f"  Harmed:                    {len(harmed_idx)} ({len(harmed_idx)/len(usable)*100:.1f}%)")
print(f"  Unchanged:                 {len(usable) - len(improved_idx) - len(harmed_idx)}")
print(f"  Baseline total R:          {baseline_r.sum():+.2f}")
print(f"  Simulated total R:         {pro_sim.sum():+.2f}")
print(f"  Delta:                     {pro_sim.sum() - baseline_r.sum():+.2f}R")
print(f"  Baseline expectancy:       {baseline_r.mean():+.4f}R")
print(f"  Simulated expectancy:      {pro_sim.mean():+.4f}R")
print(f"  Baseline top-5% contrib:   {np.sort(baseline_r)[int(len(baseline_r)*0.95):].sum():+.2f}R")
print(f"  Simulated top-5% contrib:  {sorted_sim[int(len(sorted_sim)*0.95):].sum():+.2f}R")

if len(improved_idx) > 0:
    print(f"\n  Improved trades — avg baseline R: {baseline_r[improved_idx].mean():+.4f}")
    print(f"  Improved trades — avg sim R:      {pro_sim[improved_idx].mean():+.4f}")
    print(f"  Improved trades — avg gain:        {pro_diff[improved_idx].mean():+.4f}R")
    gains = pro_sim[improved_idx] - baseline_r[improved_idx]
    print(f"  Minimal saved on any improved:     {gains.min():+.4f}R")

if len(harmed_idx) > 0:
    print(f"\n  Harmed trades — avg baseline R:    {baseline_r[harmed_idx].mean():+.4f}")
    print(f"  Harmed trades — avg sim R:         {pro_sim[harmed_idx].mean():+.4f}")
    print(f"  Harmed trades — avg loss:          {pro_diff[harmed_idx].mean():+.4f}R")
    losses = baseline_r[harmed_idx] - pro_sim[harmed_idx]
    print(f"  Max R lost on any harmed:          {losses.max():+.4f}R")
