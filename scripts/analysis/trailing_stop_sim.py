#!/usr/bin/env python3
"""
Trailing stop simulation from trade lifecycle data.
Tests multiple trailing stop rules against all 16 assets.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trailing_stop_sim.py
"""

import json
import sys
from pathlib import Path


def simulate_trailing(
    trades: list[dict],
    retrace_pct: float = 0.50,
    require_min_mfe: float = 0.5,
) -> tuple[float, float, int]:
    """
    Simulate trailing stop on reconstructed trades.
    For each trade where MFE >= min_mfe: if price retraced by retrace_pct from
    peak MFE, exit at the retracement level instead of SL.
    Returns (improvement_r, new_total_r, n_saved).
    """
    original_r = sum(t["r_multiple"] for t in trades)
    new_r = 0.0
    n_saved = 0

    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)
        abs(t.get("sl_price", 0) - t.get("entry_price", 0)) / max(
            abs(t.get("sl_price", 0) - t.get("entry_price", 0)), 1e-10
        )

        if orig >= 0:
            # Winner — leave as-is (trailing might reduce profit; we're conservative)
            new_r += orig
            continue

        if mfe_r < require_min_mfe:
            new_r += orig
            continue

        exit_r = t.get("exit_reason", "")
        if exit_r == "tp":
            new_r += orig
            continue

        # Simulate: exit at (1 - retrace_pct) * MFE
        captured = mfe_r * (1.0 - retrace_pct)

        # SL in R units
        if "sl_price" in t and "entry_price" in t:
            sl_mult = abs(t["sl_price"] - t["entry_price"])
            atr_entry = t.get("atr_pct_entry", 0.01)
            entry_px = t["entry_price"]
            sl_mult / (atr_entry * entry_px) if atr_entry > 0 and entry_px > 0 else abs(sl_mult)
        else:
            pass

        new_r += captured
        if captured > 0:
            n_saved += 1

    return new_r - original_r, new_r, n_saved


CAVEAT = (
    "\n*** CAVEAT: This simulation uses realized (post-hoc) MFE to determine\n"
    "*** trailing stop placement. In live trading, the ultimate MFE is\n"
    "*** unknown when setting the trail. This represents an UPPER BOUND\n"
    "*** on trailing stop performance. Real results will be lower because\n"
    "*** the trail level is set from the running peak, not the ultimate peak.\n"
    "*** See audit finding C8/H9 in AGENTS.md for methodology discussion.\n"
)


def simulate_trailing_running_peak(
    trades: list[dict],
    retrace_pct: float = 0.50,
    require_min_mfe: float = 0.5,
    running_factor: float = 0.5,
) -> tuple[float, float, int]:
    """Conservative bound: trail from the running (candle-by-candle) peak MFE,
    not the ultimate peak. running_factor is the assumed fraction of ultimate
    MFE that has been achieved when the trail is set (default 0.5 — midpoint
    between entry and peak). Produces a lower/realistic bound.
    """
    original_r = sum(t["r_multiple"] for t in trades)
    new_r = 0.0
    n_saved = 0

    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)

        if orig >= 0:
            # Winners: leave as-is (running-peak trail might reduce profit)
            new_r += orig
            continue
        if mfe_r < require_min_mfe:
            new_r += orig
            continue
        if t.get("exit_reason", "") == "tp":
            new_r += orig
            continue

        # Conservative: trail set partway into the trade (not at ultimate peak)
        captured = mfe_r * running_factor * (1.0 - retrace_pct)
        new_r += captured
        if captured > 0:
            n_saved += 1

    return new_r - original_r, new_r, n_saved


def main():
    print(CAVEAT)
    path = Path("data/processed/trade_data/trade_lifecycle_results.json")
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    all_trades = data.get("_trades", {})

    results = {}
    for retrace in [0.33, 0.50, 0.67, 0.75]:
        print(f"\n{'=' * 70}")
        print(f"TRAILING STOP: exit at {(1 - retrace) * 100:.0f}% of MFE (retrace {retrace * 100:.0f}%)")
        print(f"{'=' * 70}")
        print(f"{'Asset':<10} {'Orig R':>8} {'New R':>8} {'ΔR':>8} {'Saved':>6} {'WR':>6} {'NWR':>6}")
        print("-" * 55)
        for asset in sorted(all_trades.keys()):
            trades = all_trades[asset]
            if not trades:
                continue
            orig_r = sum(t["r_multiple"] for t in trades)
            wr = sum(1 for t in trades if t["r_multiple"] > 0) / len(trades) * 100

            delta, new_r, n_saved = simulate_trailing(trades, retrace_pct=retrace)
            nwr = sum(1 for t in trades if t["r_multiple"] > 0) / len(trades) * 100

            print(f"{asset:<10} {orig_r:>+8.1f} {new_r:>+8.1f} {delta:>+8.1f} {n_saved:>5d}  {wr:>5.1f}% {nwr:>5.1f}%")
            results[(asset, retrace)] = {"orig_r": orig_r, "new_r": new_r, "delta": delta, "n_saved": n_saved}

        # Portfolio total
        all_orig = sum(sum(t["r_multiple"] for t in trades) for trades in all_trades.values())
        all_new = 0.0
        all_saved = 0
        for asset, trades in all_trades.items():
            d, n, s = simulate_trailing(trades, retrace_pct=retrace)
            all_new += n
            all_saved += s
        print("-" * 55)
        print(f"{'PORTFOLIO':<10} {all_orig:>+8.1f} {all_new:>+8.1f} {all_new - all_orig:>+8.1f} {all_saved:>5d}")

        # Conservative bound: running-peak trail
        cons_orig = 0.0
        cons_new = 0.0
        cons_saved = 0
        for asset, trades in all_trades.items():
            d, n, s = simulate_trailing_running_peak(trades, retrace_pct=retrace)
            cons_orig += sum(t["r_multiple"] for t in trades)
            cons_new += n
            cons_saved += s
        print(f"{'  (running-peak)':<10} {cons_orig:>+8.1f} {cons_new:>+8.1f} {cons_new - cons_orig:>+8.1f} {cons_saved:>5d}")
        print("  ^ Conservative bound: trail from running peak, not ultimate MFE")

    # Per-asset recommendation table — both upper and conservative bound
    print(f"\n{'=' * 70}")
    print("ASSET RECOMMENDATIONS (50% retracement trailing stop)")
    print("                       Upper-bound = perfect MFE; Conservative = running peak")
    print(f"{'=' * 70}")
    print(f"{'Asset':<10} {'Orig':>8} {'Trail_UB':>9} {'Trail_RP':>9} {'Status':>10}")
    print("-" * 55)
    for asset in sorted(all_trades.keys()):
        trades = all_trades[asset]
        if not trades:
            continue
        orig_r = sum(t["r_multiple"] for t in trades)
        _, ub_new, _ = simulate_trailing(trades, retrace_pct=0.50)
        _, rp_new, _ = simulate_trailing_running_peak(trades, retrace_pct=0.50)
        status = "keep" if rp_new >= 0 else "remove"
        print(
            f"{asset:<10} {orig_r:>+8.1f} {ub_new:>+9.1f} {rp_new:>+9.1f} {status:>10}"
        )

    # Sensitivity analysis for the worst assets
    print(f"\n{'=' * 70}")
    print("SENSITIVITY — retrace % sweep on losing assets")
    print(f"{'=' * 70}")
    losers = [a for a in sorted(all_trades.keys()) if sum(t["r_multiple"] for t in all_trades[a]) < 0]
    print(f"{'Asset':<10} {'33%':>8} {'50%':>8} {'67%':>8} {'75%':>8}")
    print("-" * 45)
    for asset in losers:
        trades = all_trades[asset]
        if not trades:
            continue
        vals = []
        for rp in [0.33, 0.50, 0.67, 0.75]:
            _, new_r, _ = simulate_trailing(trades, retrace_pct=rp)
            vals.append(new_r)
        print(f"{asset:<10} {vals[0]:>+8.1f} {vals[1]:>+8.1f} {vals[2]:>+8.1f} {vals[3]:>+8.1f}")

    # Profit lock only (breakeven after MFE>=1R)
    print(f"\n{'=' * 70}")
    print("BREAKEVEN LOCK ONLY: move SL to entry when MFE >= 1.0R")
    print(f"{'=' * 70}")
    print(f"{'Asset':<10} {'Orig R':>8} {'BE Lock':>8} {'ΔR':>8}")
    print("-" * 40)
    for asset in sorted(all_trades.keys()):
        trades = all_trades[asset]
        if not trades:
            continue
        orig_r = sum(t["r_multiple"] for t in trades)
        new_r = 0.0
        saved = 0
        for t in trades:
            orig = t["r_multiple"]
            mfe_r = t.get("mfe_r", 0.0)
            if orig < 0 and mfe_r >= 1.0:
                # Exit at breakeven (0.0R)
                new_r += 0.0
                if orig < 0:
                    saved += 1
            else:
                new_r += orig
        delta = new_r - orig_r
        print(f"{asset:<10} {orig_r:>+8.1f} {new_r:>+8.1f} {delta:>+8.1f}")


if __name__ == "__main__":
    main()
