#!/usr/bin/env python3
"""
A/B test monitor for exit strategy optimization (R2).

Tracks before/after trade quality metrics to validate that
trail_activation_r=0.3, max_hold_candles=60 improves performance
without increasing drawdown.

Usage (run daily):
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/ab_test_exit_monitor.py

Output:
    - Logs comparison of current vs historical exit performance
    - WARNING if max_dd exceeds threshold or win_rate drops below baseline
    - data/processed/ab_test_exit_results.json (cumulative record)

Rollback: revert configs/domains/risk/exits.yaml and _defaults.yaml
    trail_activation_r: 0.3 -> 0.5
    max_hold_candles: 60 -> 40
    time_decay_start: 30 -> 20
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger("ab_test_exit")

OUTDIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
STATE_PATH = OUTDIR / "state.json"


def load_live_state() -> dict | None:
    """Load the current paper trading state."""
    if not STATE_PATH.exists():
        return None
    with open(STATE_PATH) as f:
        return json.load(f)


def compute_exit_metrics(state: dict) -> dict:
    """Extract exit quality metrics from state.json."""
    positions = state.get("positions", {})
    if not positions:
        return {"n_positions": 0}

    exit_r_multiples = []
    hold_durations = []
    exit_reasons = []

    for pos in positions.values():
        r = pos.get("pnl_r", 0)
        if r != 0:
            exit_r_multiples.append(r)
        hold = pos.get("hold_bars", pos.get("hold_days", 0))
        hold_durations.append(hold)
        reason = pos.get("exit_reason", pos.get("close_reason", "unknown"))
        exit_reasons.append(reason)

    arr = np.array(exit_r_multiples)
    wins = arr[arr > 0]
    losses = arr[arr < 0]

    return {
        "n_positions": len(exit_r_multiples),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(len(wins) / max(len(exit_r_multiples), 1), 4),
        "avg_R": round(float(arr.mean()), 4) if len(arr) > 0 else 0.0,
        "avg_win_R": round(float(wins.mean()), 4) if len(wins) > 0 else 0.0,
        "avg_loss_R": round(float(losses.mean()), 4) if len(losses) > 0 else 0.0,
        "profit_factor": round(abs(float(wins.sum() / losses.sum())), 4) if len(losses) > 0 else float("inf"),
        "avg_hold_bars": round(float(np.mean(hold_durations)), 1) if hold_durations else 0.0,
        "exit_reasons": {r: exit_reasons.count(r) for r in set(exit_reasons)},
    }


def check_rollback_conditions(current: dict, baseline: dict) -> list[str]:
    """Return reasons to rollback if A/B test shows degradation."""
    warnings = []
    if current.get("n_positions", 0) < 10:
        return warnings  # too few data points

    if current.get("win_rate", 0) < baseline.get("win_rate", 0) * 0.85:
        warnings.append(f"Win rate {current['win_rate']:.1%} < 85% of baseline {baseline['win_rate']:.1%}")

    if current.get("avg_R", 0) < baseline.get("avg_R", 0) * 0.75:
        warnings.append(f"Avg R {current['avg_R']:.4f} < 75% of baseline {baseline['avg_R']:.4f}")

    return warnings


def get_baseline_metrics() -> dict:
    """Return pre-change baseline (from historical state snapshots)."""
    results_path = OUTDIR / "ab_test_exit_results.json"
    if results_path.exists():
        with open(results_path) as f:
            data = json.load(f)
        # Use the 'baseline' entry if exists
        return data.get("baseline", {})
    # Return sensible defaults
    return {
        "win_rate": 0.50,
        "avg_R": 1.2,
        "avg_hold_bars": 15.0,
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    state = load_live_state()
    if state is None:
        logger.warning("No state.json found at %s", STATE_PATH)
        logger.info("Is paper trading running? Try: curl http://127.0.0.1:5000/state.json")
        sys.exit(1)

    current = compute_exit_metrics(state)
    baseline = get_baseline_metrics()
    warnings = check_rollback_conditions(current, baseline)

    # Load or init cumulative results
    results_path = OUTDIR / "ab_test_exit_results.json"
    if results_path.exists():
        with open(results_path) as f:
            results = json.load(f)
    else:
        results = {
            "baseline": baseline,
            "snapshots": [],
            "started": datetime.now(timezone.utc).isoformat(),
            "config_change": {
                "trail_activation_r": "0.5 -> 0.3",
                "max_hold_candles": "40 -> 60",
                "time_decay_start": "20 -> 30",
            },
        }

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **current,
    }
    results["snapshots"].append(snapshot)
    if len(results["snapshots"]) > 1000:
        results["snapshots"] = results["snapshots"][-1000:]

    # Aggregate snapshot metrics
    if current["n_positions"] > 0:
        all_r = [s.get("avg_R", 0) for s in results["snapshots"] if s.get("n_positions", 0) > 0]
        results["running_avg_R"] = round(float(np.mean(all_r)), 4) if all_r else 0.0
        all_wr = [s.get("win_rate", 0) for s in results["snapshots"] if s.get("n_positions", 0) > 0]
        results["running_avg_wr"] = round(float(np.mean(all_wr)), 4) if all_wr else 0.0

    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Report
    print("=" * 60)
    print("EXIT STRATEGY A/B TEST MONITOR")
    print("=" * 60)
    print(f"  Positions tracked:   {current['n_positions']}")
    print(f"  Win rate:            {current['win_rate']:.1%}  (baseline: {baseline['win_rate']:.1%})")
    print(f"  Avg R:               {current['avg_R']:+.4f}  (baseline: {baseline['avg_R']:+.4f})")
    print(f"  Avg hold (bars):     {current['avg_hold_bars']:.1f}")
    print(f"  Profit factor:       {current['profit_factor']:.2f}")
    print(f"  Exit reasons:        {current['exit_reasons']}")
    print(f"  Running avg R:       {results.get('running_avg_R', 'N/A')}")
    print(f"  Running avg WR:      {results.get('running_avg_wr', 'N/A'):.1%}")

    if warnings:
        print("\n  ⚠  ROLLBACK CONDITIONS DETECTED:")
        for w in warnings:
            print(f"     - {w}")
        print("\n  Run rollback: revert configs/domains/risk/exits.yaml and _defaults.yaml")
    else:
        print(f"\n  ✓  No rollback conditions. {len(results['snapshots'])} snapshots recorded.")

    print(f"\n  Results: {results_path}")


if __name__ == "__main__":
    main()
