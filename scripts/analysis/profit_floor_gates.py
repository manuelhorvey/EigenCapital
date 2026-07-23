#!/usr/bin/env python3
"""
Three-gate validation for profit floor protection.

Gate 1: Walk-forward validation (4 expanding windows)
Gate 2: Drawdown impact (equity curve comparison)
Gate 3: Monte Carlo reshuffle (10,000 simulations)

Usage::

    python scripts/analysis/profit_floor_gates.py

Output::

    Console tables for each gate + JSON results cache
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
TRIGGER_R = 2.5
FLOOR_R = 2.0

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
            "entry_date": t.get("entry_date", ""),
            "side": t["side"],
        })
    return usable


def simulate_profit_floor(trades, trigger_r, floor_r):
    result = np.empty(len(trades), dtype=float)
    improved = np.zeros(len(trades), dtype=bool)
    harmed = np.zeros(len(trades), dtype=bool)
    triggered_mask = np.zeros(len(trades), dtype=bool)
    floor_hit_mask = np.zeros(len(trades), dtype=bool)

    for i, t in enumerate(trades):
        r_prices = t["r_prices"]
        baseline_r = t["actual_r"]
        highest_r = -999.0
        triggered = False
        floor_hit = False
        realised = baseline_r

        for r in r_prices:
            if r > highest_r:
                highest_r = r
            if not triggered and highest_r >= trigger_r:
                triggered = True
            if triggered and r < floor_r:
                realised = floor_r
                floor_hit = True
                break

        result[i] = realised
        improved[i] = realised > baseline_r
        harmed[i] = realised < baseline_r
        triggered_mask[i] = triggered
        floor_hit_mask[i] = floor_hit

    return result, improved, harmed, triggered_mask, floor_hit_mask


def equity_curve_from_rs(rs, initial_capital=1000.0):
    """Convert R-multiple series to equity curve (1R = 1% risk)."""
    equity = np.full(len(rs) + 1, initial_capital, dtype=float)
    for i, r in enumerate(rs):
        risk_amount = equity[i] * 0.01
        equity[i + 1] = equity[i] + risk_amount * r
    return equity


def compute_drawdowns(equity):
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    return dd


# ── Load and prepare ─────────────────────────────────────────────────────────
usable = prepare_trades(all_trades)

# Sort by entry_date for walk-forward
usable.sort(key=lambda t: t.get("entry_date", ""))

print(f"Total trades: {len(all_trades)}")
print(f"Usable trades: {len(usable)}")
print(f"Date range: {usable[0]['entry_date'][:10]} to {usable[-1]['entry_date'][:10]}")

baseline_r = np.array([t["actual_r"] for t in usable])
sim_r_base, imp_base, harm_base, trig_base, floor_base = simulate_profit_floor(usable, TRIGGER_R, FLOOR_R)

# ══════════════════════════════════════════════════════════════════════════════
# GATE 1: WALK-FORWARD VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
# Data spans Aug 2024 - Jun 2026 (~22mo). Use 4 expanding windows.
# Each window: train on earlier period, test on later period.
# Since this is not a model retraining scenario, "train" = compute baseline,
# "test" = measure out-of-sample improvement. The profit floor rule is fixed.
print(f"\n{'='*100}")
print("GATE 1: WALK-FORWARD VALIDATION")
print(f"{'='*100}")

# Split dates (roughly 3-month test periods)
all_dates = sorted(set(t["entry_date"][:10] for t in usable))
split_points = [
    ("2025-03-01", "P1: train→2025-02, test 2025-03→2025-05"),
    ("2025-06-01", "P2: train→2025-05, test 2025-06→2025-08"),
    ("2025-09-01", "P3: train→2025-08, test 2025-09→2025-11"),
    ("2025-12-01", "P4: train→2025-11, test 2025-12→2026-06"),
]

print(f"\n  {'Window':>25s} {'Test_ct':>7s} {'Base_R':>8s} {'Sim_R':>8s} {'Δ_R':>8s} {'Δ_exp':>8s} {'WRΔ':>6s} {'Top5_Δ':>8s} {'Imp/Harm':>9s} {'Floor%':>7s}")
print(f"  {'─'*105}")

wf_results = []
for test_start, label in split_points:
    train_trades = [t for t in usable if t["entry_date"][:10] < test_start]
    test_trades = [t for t in usable if t["entry_date"][:10] >= test_start]

    if len(test_trades) < 50:
        continue

    test_base = np.array([t["actual_r"] for t in test_trades])
    test_sim, test_imp, test_harm, _, test_floor_hit = simulate_profit_floor(test_trades, TRIGGER_R, FLOOR_R)

    delta = test_sim.sum() - test_base.sum()
    delta_exp = test_sim.mean() - test_base.mean()
    wr_delta = (test_sim > 0).mean() * 100 - (test_base > 0).mean() * 100

    test_sorted = np.sort(test_sim)
    test_base_sorted = np.sort(test_base)
    top5_sim = test_sorted[int(len(test_sorted) * 0.95):].sum() if len(test_sorted) >= 20 else 0
    top5_base = test_base_sorted[int(len(test_base_sorted) * 0.95):].sum() if len(test_base_sorted) >= 20 else 0
    top5_delta = top5_sim - top5_base

    floor_pct = test_floor_hit.mean() * 100
    imp_ct = int(test_imp.sum())
    harm_ct = int(test_harm.sum())

    wf_results.append({
        "label": label,
        "n": len(test_trades),
        "delta_r": delta,
        "delta_exp": delta_exp,
        "wr_delta": wr_delta,
        "top5_delta": top5_delta,
        "imp": imp_ct,
        "harm": harm_ct,
        "floor_pct": floor_pct,
    })

    print(f"  {label:>25s} {len(test_trades):>7d} {test_base.sum():+8.1f}R {test_sim.sum():+8.1f}R {delta:+8.1f}R {delta_exp:+8.4f}R {wr_delta:+5.2f}% {top5_delta:+8.1f}R {imp_ct:>3d}/{harm_ct:<3d}  {floor_pct:>5.1f}%")

# Summary
positive_windows = sum(1 for r in wf_results if r["delta_r"] > 0)
total_r_delta = sum(r["delta_r"] for r in wf_results)
total_test_ct = sum(r["n"] for r in wf_results)
print(f"\n  Summary: {positive_windows}/{len(wf_results)} windows positive, total ΔR = {total_r_delta:+.1f}R")
print(f"  Floor hit rate: avg {np.mean([r['floor_pct'] for r in wf_results]):.1f}% of test trades")

# ══════════════════════════════════════════════════════════════════════════════
# GATE 2: DRAWDOWN IMPACT
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("GATE 2: DRAWDOWN IMPACT")
print(f"{'='*100}")

baseline_eq = equity_curve_from_rs(baseline_r)
sim_eq = equity_curve_from_rs(sim_r_base)

baseline_dd = compute_drawdowns(baseline_eq)
sim_dd = compute_drawdowns(sim_eq)

base_max_dd = np.min(baseline_dd)
sim_max_dd = np.min(sim_dd)

# Recovery time: bars to return to previous peak after max DD
def recovery_time(equity, dd_series):
    trough_idx = np.argmin(dd_series)
    if trough_idx == 0:
        return 0
    pre_peak = np.max(equity[:trough_idx])
    for i in range(trough_idx, len(equity)):
        if equity[i] >= pre_peak:
            return i - trough_idx
    return len(equity) - trough_idx

base_rec = recovery_time(baseline_eq, baseline_dd)
sim_rec = recovery_time(sim_eq, sim_dd)

# Longest drawdown (consecutive negative DD days)
def longest_dd_streak(dd_series):
    streak = 0
    max_streak = 0
    for d in dd_series[1:]:
        if d < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak

base_dd_streak = longest_dd_streak(baseline_dd)
sim_dd_streak = longest_dd_streak(sim_dd)

# Consecutive losses
def consec_losses(rs):
    streak = 0
    max_streak = 0
    for r in rs:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak

base_consec = consec_losses(baseline_r)
sim_consec = consec_losses(sim_r_base)

# Worst month (rolling 21 trades)
def worst_rolling_sum(rs, window=21):
    if len(rs) < window:
        return rs.sum()
    rolling = np.convolve(rs, np.ones(window), mode='valid')
    return np.min(rolling)

base_worst_mo = worst_rolling_sum(baseline_r)
sim_worst_mo = worst_rolling_sum(sim_r_base)

print(f"\n  {'Metric':>30s} {'Baseline':>12s} {'ProfitFloor':>12s} {'Δ':>10s}")
print(f"  {'─'*66}")
print(f"  {'Max DD':>30s} {base_max_dd:>11.2f}% {sim_max_dd:>11.2f}% {sim_max_dd - base_max_dd:+10.2f}%")
print(f"  {'Recovery (trades)':>30s} {base_rec:>12d} {sim_rec:>12d} {sim_rec - base_rec:+10d}")
print(f"  {'Longest DD streak':>30s} {base_dd_streak:>12d} {sim_dd_streak:>12d} {sim_dd_streak - base_dd_streak:+10d}")
print(f"  {'Max consecutive losses':>30s} {base_consec:>12d} {sim_consec:>12d} {sim_consec - base_consec:+10d}")
print(f"  {'Worst 21-trade period':>30s} {base_worst_mo:>+11.2f}R {sim_worst_mo:>+11.2f}R {sim_worst_mo - base_worst_mo:+10.2f}R")
print(f"  {'Final equity ($1k start)':>30s} {baseline_eq[-1]:>11.2f} {sim_eq[-1]:>11.2f} {sim_eq[-1] - baseline_eq[-1]:+10.2f}")
print(f"  {'Sharpe (R/trade)':>30s} {baseline_r.mean()/max(baseline_r.std(),1e-9):>11.4f} {sim_r_base.mean()/max(sim_r_base.std(),1e-9):>11.4f}")

# ══════════════════════════════════════════════════════════════════════════════
# GATE 3: MONTE CARLO RESHUFFLE
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("GATE 3: MONTE CARLO RESHUFFLE (10,000 simulations)")
print(f"{'='*100}")

N_SIM = 10_000
rng = np.random.default_rng(42)

base_cum_ends = np.empty(N_SIM)
sim_cum_ends = np.empty(N_SIM)
base_max_dds = np.empty(N_SIM)
sim_max_dds = np.empty(N_SIM)
base_worst_months = np.empty(N_SIM)
sim_worst_months = np.empty(N_SIM)

for n in range(N_SIM):
    perm = rng.permutation(len(baseline_r))

    base_cum = np.cumsum(baseline_r[perm])
    sim_cum = np.cumsum(sim_r_base[perm])

    base_cum_ends[n] = base_cum[-1]
    sim_cum_ends[n] = sim_cum[-1]

    base_peak = np.maximum.accumulate(base_cum)
    sim_peak = np.maximum.accumulate(sim_cum)
    base_dd = base_cum - base_peak
    sim_dd = sim_cum - sim_peak
    base_max_dds[n] = np.min(base_dd)
    sim_max_dds[n] = np.min(sim_dd)

    base_worst_months[n] = np.min(np.convolve(baseline_r[perm], np.ones(21), mode='valid'))
    sim_worst_months[n] = np.min(np.convolve(sim_r_base[perm], np.ones(21), mode='valid'))

print(f"\n  {'Metric':>35s} {'Baseline':>14s} {'ProfitFloor':>14s} {'Δ':>10s} {'Better%':>8s}")
print(f"  {'─'*83}")
print(f"\n  ── Median ──")
print(f"  {'Median cum R':>35s} {np.median(base_cum_ends):>+10.2f}R {np.median(sim_cum_ends):>+10.2f}R {np.median(sim_cum_ends) - np.median(base_cum_ends):+8.2f}R {(np.median(sim_cum_ends) > np.median(base_cum_ends))*100:>7.0f}%")
print(f"  {'Median max DD':>35s} {np.median(base_max_dds):>+10.2f}R {np.median(sim_max_dds):>+10.2f}R {np.median(sim_max_dds) - np.median(base_max_dds):+8.2f}R {(np.median(sim_max_dds) > np.median(base_max_dds))*100:>7.0f}%")

print(f"\n  ── 5th percentile (worst case) ──")
print(f"  {'P5 cum R':>35s} {np.percentile(base_cum_ends, 5):>+10.2f}R {np.percentile(sim_cum_ends, 5):>+10.2f}R {np.percentile(sim_cum_ends, 5) - np.percentile(base_cum_ends, 5):+8.2f}R {(np.percentile(sim_cum_ends, 5) > np.percentile(base_cum_ends, 5))*100:>7.0f}%")
print(f"  {'P5 max DD':>35s} {np.percentile(base_max_dds, 5):>+10.2f}R {np.percentile(sim_max_dds, 5):>+10.2f}R {np.percentile(sim_max_dds, 5) - np.percentile(base_max_dds, 5):+8.2f}R {(np.percentile(sim_max_dds, 5) > np.percentile(base_max_dds, 5))*100:>7.0f}%")
print(f"  {'P5 worst 21-trade':>35s} {np.percentile(base_worst_months, 5):>+10.2f}R {np.percentile(sim_worst_months, 5):>+10.2f}R {np.percentile(sim_worst_months, 5) - np.percentile(base_worst_months, 5):+8.2f}R")

print(f"\n  ── 95th percentile (best case) ──")
print(f"  {'P95 cum R':>35s} {np.percentile(base_cum_ends, 95):>+10.2f}R {np.percentile(sim_cum_ends, 95):>+10.2f}R {np.percentile(sim_cum_ends, 95) - np.percentile(base_cum_ends, 95):+8.2f}R")
print(f"  {'P95 max DD':>35s} {np.percentile(base_max_dds, 95):>+10.2f}R {np.percentile(sim_max_dds, 95):>+10.2f}R {np.percentile(sim_max_dds, 95) - np.percentile(base_max_dds, 95):+8.2f}R")

print(f"\n  ── Downside tail probability ──")
ruin_base = (base_max_dds < -100).mean() * 100
ruin_sim = (sim_max_dds < -100).mean() * 100
print(f"  {'P(max DD < -100R) baseline':>35s} {ruin_base:.1f}%")
print(f"  {'P(max DD < -100R) profit floor':>35s} {ruin_sim:.1f}%")
# P(cum R < 0) — probability of losing money
neg_base = (base_cum_ends < 0).mean() * 100
neg_sim = (sim_cum_ends < 0).mean() * 100
print(f"  {'P(final R < 0) baseline':>35s} {neg_base:.1f}%")
print(f"  {'P(final R < 0) profit floor':>35s} {neg_sim:.1f}%")
# DD vs baseline: how often is profit floor DD less bad?
dd_better = (sim_max_dds > base_max_dds).mean() * 100
print(f"  {'DD improved vs baseline':>35s} {dd_better:.1f}%")

# ── State transition audit ────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("STATE TRANSITION AUDIT")
print(f"{'='*100}")

n_trig = int(trig_base.sum())
n_floor = int(floor_base.sum())
n_tp = int((trig_base & ~floor_base).sum())

print(f"\n  {'Metric':>40s} {'Value':>10s}")
print(f"  {'─'*52}")
print(f"  {'Trades entering PROFIT_PROTECTED':>40s} {n_trig:>10d}")
print(f"  {'Trades hitting floor (LOCK_EXIT)':>40s} {n_floor:>10d}")
print(f"  {'Trades continuing to TP/exit':>40s} {n_tp:>10d}")
print(f"  {'Floor hit rate (% of protected)':>40s} {n_floor/max(n_trig,1)*100:>9.1f}%")
print(f"  {'Median trigger MFE':>40s} {np.median([t['mfe_r'] for i,t in enumerate(usable) if trig_base[i]]):>9.2f}R")
print(f"  {'Mean trigger MFE':>40s} {np.mean([t['mfe_r'] for i,t in enumerate(usable) if trig_base[i]]):>9.2f}R")
print(f"  {'Mean candles at entry':>40s} {np.mean([t['candles'] for i,t in enumerate(usable) if trig_base[i]]):>9.1f}")
