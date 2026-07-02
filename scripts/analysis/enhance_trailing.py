#!/usr/bin/env python3
"""Simulate enhanced trailing and scale-out exit strategies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"

ASSET_CONFIG = {
    a: {"trail_activation_r": 0.8, "trail_retrace_pct": 0.50, "be_lock_r": 0.5}
    for a in ["GC", "USDCHF", "USDCAD", "GBPCAD", "NZDCAD", "NZDCHF", "CADCHF",
              "EURCHF", "EURCAD", "GBPUSD"]
}
for a in ["NZDUSD", "GBPAUD", "AUDUSD", "EURNZD", "GBPCHF", "EURAUD"]:
    ASSET_CONFIG[a] = {"trail_activation_r": 0.5, "trail_retrace_pct": 0.50, "be_lock_r": 0.5}


# ── Exit simulators ──────────────────────────────────────────────────────────

def fixed_barriers(t, _a):
    return t.get("r_multiple", 0.0)


def current_live(t, a):
    orig = t.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = t.get("mfe_r", 0.0)
    cfg = ASSET_CONFIG.get(a, ASSET_CONFIG["GBPUSD"])
    if mfe < cfg["be_lock_r"] or t.get("exit_reason") == "tp":
        return orig
    if mfe >= cfg["trail_activation_r"]:
        return max(mfe * (1.0 - cfg["trail_retrace_pct"]), 0.0)
    if mfe >= cfg["be_lock_r"]:
        return 0.0
    return orig


def scale_trail(t, _a, scale_pct=0.5, scale_r=1.0, trail_retrace=0.33, act_r=0.5):
    """Scale out `scale_pct` at `scale_r` R, trail remainder at `trail_retrace`."""
    orig = t.get("r_multiple", 0.0)
    mfe = t.get("mfe_r", 0.0)
    if orig >= 0:
        return orig
    if mfe < 0.5 or t.get("exit_reason") == "tp":
        return orig

    captured = scale_pct * (scale_r if mfe >= scale_r else mfe)
    rem = 1.0 - scale_pct

    if mfe >= act_r:
        trail = mfe * (1.0 - trail_retrace)
        captured += rem * max(trail, 0)
    elif mfe >= 0.5:
        pass
    return max(captured, 0)


def three_tier(t, _a):
    """33% at 0.5R + 33% at 1.0R + 34% trail at 40% retrace."""
    orig = t.get("r_multiple", 0.0)
    mfe = t.get("mfe_r", 0.0)
    if orig >= 0:
        return orig
    if mfe < 0.5 or t.get("exit_reason") == "tp":
        return orig

    captured = 0.33 * min(mfe, 0.5)
    captured += 0.33 * (1.0 if mfe >= 1.0 else mfe)
    rem = 0.34
    if mfe >= 0.8:
        captured += rem * max(mfe * 0.6, 0)
    elif mfe >= 0.5:
        pass
    return max(captured, 0)


def tighten_trail(t, _a):
    """Trail tightens with MFE: 60% retrace at 0.5-1R, 45% at 1-2R, 30% at 2+R."""
    orig = t.get("r_multiple", 0.0)
    mfe = t.get("mfe_r", 0.0)
    if orig >= 0:
        return orig
    if mfe < 0.5 or t.get("exit_reason") == "tp":
        return orig
    retrace = 0.30 if mfe >= 2.0 else (0.45 if mfe >= 1.0 else 0.60)
    return max(mfe * (1.0 - retrace), 0)


def double_scale_trail(t, _a):
    """25% at 0.5R + 25% at 1.0R + 50% trail at 33%."""
    orig = t.get("r_multiple", 0.0)
    mfe = t.get("mfe_r", 0.0)
    if orig >= 0:
        return orig
    if mfe < 0.5 or t.get("exit_reason") == "tp":
        return orig

    captured = 0.25 * min(mfe, 0.5)
    captured += 0.25 * (1.0 if mfe >= 1.0 else mfe)
    rem = 0.50
    if mfe >= 0.8:
        captured += rem * max(mfe * 0.67, 0)
    elif mfe >= 0.5:
        pass
    return max(captured, 0)


# ── Engine ───────────────────────────────────────────────────────────────────

STRATEGIES = [
    ("Fixed barriers (baseline)", fixed_barriers),
    ("Current live (50% trail, per-asset)", current_live),
    ("Scale 50%@1R + trail 33%", lambda t, a: scale_trail(t, a)),
    ("Scale 50%@1R + trail 50%", lambda t, a: scale_trail(t, a, trail_retrace=0.50)),
    ("Three-tier: 33%@0.5R + 33%@1R + trail 40%", three_tier),
    ("Tighten trail (60/45/30% retrace)", tighten_trail),
    ("Scale 25%@0.5R + 25%@1R + trail 33%", double_scale_trail),
]


def test(name, fn, trades):
    rs = [fn(t, t["_asset"]) for t in trades]
    arr = np.array(rs)
    n = len(arr)
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 and n > 1 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    wr = (arr > 0).mean() * 100
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else (float("inf") if len(wins) > 0 else 0.0)
    sortino = float(arr.mean() / arr[arr < 0].std()) if len(arr[arr < 0]) > 1 and arr[arr < 0].std() > 0 else 0.0
    return {"name": name, "total_r": round(float(arr.sum()), 2), "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4), "wr": round(wr, 1), "max_dd_r": round(dd, 2), "pf": round(pf, 4)}


def bootstrap_delta(trades, fn_a, fn_b, n_iter=1000):
    """Fraction of resamples where fn_a > fn_b."""
    base = np.array([fn_b(t, t["_asset"]) for t in trades])
    improved = 0
    n = len(trades)
    for _ in range(n_iter):
        idx = np.random.randint(0, n, n)
        a_r = np.array([fn_a(trades[i], trades[i]["_asset"]) for i in idx])
        b_r = base[idx]
        if a_r.sum() > b_r.sum():
            improved += 1
    return improved / n_iter


def main():
    with open(TRADE_PATH) as f:
        data = json.load(f)

    trades = []
    for asset, ts in data["_trades"].items():
        for t in ts:
            t["_asset"] = asset
            trades.append(t)

    print(f"\n{'=' * 72}")
    print(f"  ENHANCED TRAILING & SCALE-OUT SIMULATION")
    print(f"  {len(trades)} trades, {len(data['_trades'])} assets")
    print(f"{'=' * 72}")

    results = [test(n, fn, trades) for n, fn in STRATEGIES]

    sep = "  " + "─" * 38 + " " + "─" * 10 + " " + "─" * 8 + " " + "─" * 8 + " " + "─" * 6 + " " + "─" * 10 + " " + "─" * 8
    hdr = f"  {'Strategy':<38s} {'Total R':>10s} {'Sharpe':>8s} {'Sortino':>8s} {'WR':>6s} {'Max DD':>10s} {'PF':>8s}"

    print(f"\n{hdr}")
    print(sep)

    baseline_r = results[0]["total_r"]
    current_r = results[1]["total_r"]
    best_r = max(r["total_r"] for r in results[2:])

    for r in results:
        marker = ""
        if r["name"] == results[0]["name"]:
            marker = " (baseline)"
        elif r["name"] == results[1]["name"]:
            marker = " (current)"
        elif r["total_r"] >= best_r - 0.01:
            marker = " ★ BEST"
        print(f"  {r['name']:<38s} {r['total_r']:>10.2f} {r['sharpe']:>8.4f} {r['sortino']:>8.4f} {r['wr']:>5.1f}% {r['max_dd_r']:>10.2f} {r['pf']:>8.4f}{marker}")

    print(sep)

    # Best strategy details
    best_entry = results[2:][results[2:].index(max(results[2:], key=lambda r: r["total_r"]))]
    best_fn = next(fn for n, fn in STRATEGIES if n == best_entry["name"])

    current_rs = np.array([current_live(t, t["_asset"]) for t in trades])
    best_rs = np.array([best_fn(t, t["_asset"]) for t in trades])
    delta = best_rs - current_rs

    print(f"\n  Delta analysis: {best_entry['name']} vs current live")
    print(f"  Trades improved: {(delta > 0).sum()} ({(delta > 0).mean() * 100:.1f}%)")
    print(f"  Trades harmed:   {(delta < 0).sum()} ({(delta < 0).mean() * 100:.1f}%)")
    print(f"  Total delta R:   {delta.sum():+.2f}")
    print(f"  Avg improvement per improved trade: {delta[delta > 0].mean():.4f}R")
    print(f"  Avg harm per harmed trade:           {delta[delta < 0].mean():.4f}R")

    # Bootstrap
    print(f"\n  Bootstrap: P(best > current)")
    win_pct = bootstrap_delta(trades, best_fn, current_live, n_iter=2000)
    if win_pct >= 0.95:
        print(f"  {win_pct*100:.1f}% -> SIGNIFICANT (p < 0.05)")
    else:
        print(f"  {win_pct*100:.1f}%")

    # Per-asset breakdown
    print(f"\n  Per-asset: {best_entry['name']}")
    print(f"  {'Asset':<10s} {'Trades':>7s} {'Live R':>10s} {'New R':>10s} {'ΔR':>10s}")
    print(f"  {'─' * 10} {'─' * 7} {'─' * 10} {'─' * 10} {'─' * 10}")
    for asset in sorted(data["_trades"].keys()):
        ts = data["_trades"][asset]
        lrs = [current_live(t, asset) for t in ts]
        brs = [best_fn(t, asset) for t in ts]
        lr = sum(lrs)
        br = sum(brs)
        print(f"  {asset:<10s} {len(ts):>7d} {lr:>10.2f} {br:>10.2f} {br - lr:>+10.2f}")

    # ── Gini coefficient for benefit concentration ──
    gains = delta[delta > 0]
    if len(gains) > 1:
        sg = np.sort(gains)
        n = len(sg)
        l = np.arange(1, n + 1)
        gini = (2 * (l * sg).sum() - n * sg.sum()) / (n * sg.sum())
        print(f"\n  Benefit concentration (Gini): {gini:.3f}")
        top10 = int(n * 0.1)
        top_frac = sg[-top10:].sum() / sg.sum() if top10 > 0 else 0
        print(f"  Top 10% of improved trades account for {top_frac*100:.1f}% of improvement")


if __name__ == "__main__":
    main()
