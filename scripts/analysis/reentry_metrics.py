#!/usr/bin/env python3
"""
Re-Entry Policy Metrics Computation.

Reads the re-entry simulation output and computes all requested
performance, risk, and trade statistics for each policy.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_metrics.py \
        --input /tmp/reentry_full_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import OrderedDict
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from eigencapital.domain.value_objects.statistical_metrics import (
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
)

logger = logging.getLogger("reentry_metrics")

R_FREE = 0.0  # risk-free rate in R-space


# ── Helpers ───────────────────────────────────────────────────────────────


def _safe(val: Any, default: float = 0.0) -> float:
    """Return float or default."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return float(val)


def _compute_sharpe(returns: np.ndarray, rfr: float = R_FREE) -> float:
    """Compute annualized-like Sharpe from R-series (no annualization needed)."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float((np.mean(returns) - rfr) / np.std(returns))


def _compute_sortino(returns: np.ndarray, rfr: float = R_FREE) -> float:
    """Sortino ratio using downside deviation only."""
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < rfr]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0 if np.mean(returns) <= rfr else 999.0
    return float((np.mean(returns) - rfr) / np.std(downside))


def _compute_max_dd(equity: np.ndarray) -> float:
    """Maximum drawdown from peak."""
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    return float(np.max(dd))


def _compute_profit_factor(gross_profit: float, gross_loss: float) -> float:
    if gross_loss >= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / abs(gross_loss)


def _ulcer_index(equity: np.ndarray) -> float:
    """Ulcer Index — sqrt(mean(squared_drawdown))."""
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd_pct = (peak - equity) / peak
    return float(np.sqrt(np.mean(dd_pct ** 2)))


# ── Core metrics ──────────────────────────────────────────────────────────


def compute_asset_metrics(trades_list: list[dict]) -> dict:
    """Compute all performance/trade metrics for a list of trade dicts."""
    if not trades_list:
        return {"n_trades": 0, "total_r": 0.0, "error": "no_trades"}

    r_values = np.array([_safe(t.get("r_multiple", 0)) for t in trades_list])
    win_mask = r_values > 0
    loss_mask = r_values <= 0

    n = len(r_values)
    total_r = float(r_values.sum())
    gross_profit = float(r_values[win_mask].sum()) if win_mask.any() else 0.0
    gross_loss = float(r_values[loss_mask].sum()) if loss_mask.any() else 0.0
    win_rate = float(win_mask.mean())
    avg_win = float(r_values[win_mask].mean()) if win_mask.any() else 0.0
    avg_loss = float(r_values[loss_mask].mean()) if loss_mask.any() else 0.0
    expectancy = float(r_values.mean())
    profit_factor = _compute_profit_factor(gross_profit, gross_loss)

    # Consecutive wins/losses
    signs = (r_values > 0).astype(int)
    runs = np.diff(np.concatenate(([0], signs, [0])))
    run_starts = np.where(runs == 1)[0]
    run_ends = np.where(runs == -1)[0]
    run_lengths = run_ends - run_starts
    max_consec_win = int(run_lengths[signs[run_starts] == 1].max()) if len(run_lengths) > 0 and (signs[run_starts] == 1).any() else 0
    max_consec_loss = int(run_lengths[signs[run_starts] == 0].max()) if len(run_lengths) > 0 and (signs[run_starts] == 0).any() else 0

    # Duration
    durations = []
    for t in trades_list:
        entry = t.get("entry_date")
        exit_ = t.get("exit_date")
        if entry and exit_:
            try:
                d = (pd.Timestamp(exit_) - pd.Timestamp(entry)).days
                durations.append(max(d, 0))
            except (ValueError, TypeError):
                pass
    avg_duration = float(np.mean(durations)) if durations else 0.0

    # Equity curve (cumulative R)
    equity = np.cumsum(r_values)
    max_dd = _compute_max_dd(equity)
    sharpe = _compute_sharpe(r_values)
    sortino = _compute_sortino(r_values)
    ulcer = _ulcer_index(equity)
    recovery = total_r / max_dd if max_dd > 0 else 999.0
    calmar = total_r / max_dd if max_dd > 0 else 999.0

    # Profitability buckets
    r_buckets = {
        "gt_3r": int((r_values > 3).sum()),
        "gt_2r": int((r_values > 2).sum()),
        "gt_1r": int((r_values > 1).sum()),
        "lt_neg1": int((r_values < -1).sum()),
        "lt_neg2": int((r_values < -2).sum()),
        "lt_neg3": int((r_values < -3).sum()),
    }

    return {
        "n_trades": n,
        "total_r": round(total_r, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 3),
        "win_rate": round(win_rate * 100, 1),
        "loss_rate": round((1 - win_rate) * 100, 1),
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(avg_loss, 3),
        "expectancy_r": round(expectancy, 4),
        "total_r_per_trade": round(total_r / n, 3),
        "max_consec_win": max_consec_win,
        "max_consec_loss": max_consec_loss,
        "avg_duration_days": round(avg_duration, 1),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "max_dd_r": round(max_dd, 2),
        "recovery_factor": round(recovery, 3),
        "ulcer_index": round(ulcer, 4),
        "r_buckets": r_buckets,
        "pct_profitable": round(win_rate * 100, 1),
    }


def compute_portfolio_metrics(policy_data: dict) -> dict:
    """Compute portfolio-level metrics from all assets under one policy."""
    all_metrics = []
    all_r: list[float] = []
    all_trade_records: list[dict] = []

    for asset, trades in policy_data.get("trades", {}).items():
        trade_dicts = []
        for t in trades:
            if hasattr(t, "__dataclass_fields__"):
                d = {f: getattr(t, f) for f in t.__dataclass_fields__}
            elif isinstance(t, dict):
                d = t
            else:
                d = {"r_multiple": 0}
            trade_dicts.append(d)
        all_trade_records.extend(trade_dicts)
        metrics = compute_asset_metrics(trade_dicts)
        metrics["asset"] = asset
        all_metrics.append(metrics)
        all_r.extend([_safe(t.get("r_multiple", 0)) for t in trade_dicts])

    if not all_r:
        return {"n_assets": 0, "n_trades": 0, "total_r": 0.0}

    r_arr = np.array(all_r)
    total_r = float(r_arr.sum())
    sharpe = _compute_sharpe(r_arr)
    sortino = _compute_sortino(r_arr)
    equity = np.cumsum(r_arr)
    max_dd = _compute_max_dd(equity)
    ulcer = _ulcer_index(equity)
    recovery = total_r / max_dd if max_dd > 0 else 999.0
    calmar = total_r / max_dd if max_dd > 0 else 999.0
    win_rate = float((r_arr > 0).mean())

    # PSR/DSR
    n_obs = len(r_arr)
    psr = probabilistic_sharpe_ratio(sharpe, n_obs)
    dsr = deflated_sharpe_ratio(sharpe, n_obs, num_trials=len(all_metrics))

    # Re-entry stats — only count events where existing_positions > 0
    events = policy_data.get("events", {})
    reentry_allowed = []
    reentry_blocked = []
    for asset, evts in events.items():
        for e in evts:
            if hasattr(e, "__dataclass_fields__"):
                e_dict = {f: getattr(e, f) for f in e.__dataclass_fields__}
            elif isinstance(e, dict):
                e_dict = e
            else:
                continue
            # Only count events where a position was already open
            if e_dict.get("existing_positions", 0) == 0:
                continue
            if e_dict.get("allowed", False):
                reentry_allowed.append(e_dict.get("candidate_r", 0))
            else:
                reentry_blocked.append(e_dict.get("candidate_r", 0))

    reentry_metrics = {}
    if reentry_allowed:
        reentry_metrics["n_reentries"] = len(reentry_allowed)
        reentry_metrics["profitable_reentries"] = int(sum(1 for r in reentry_allowed if r > 0))
        reentry_metrics["losing_reentries"] = int(sum(1 for r in reentry_allowed if r <= 0))
        reentry_metrics["reentry_win_rate"] = round(
            sum(1 for r in reentry_allowed if r > 0) / len(reentry_allowed) * 100, 1
        )
        reentry_metrics["avg_reentry_r"] = round(np.mean(reentry_allowed), 3)
        reentry_metrics["reentry_total_r"] = round(sum(reentry_allowed), 2)
    else:
        reentry_metrics = {
            "n_reentries": 0, "profitable_reentries": 0, "losing_reentries": 0,
            "reentry_win_rate": 0.0, "avg_reentry_r": 0.0, "reentry_total_r": 0.0,
        }

    blocked_r = reentry_blocked
    reentry_metrics["blocked_n"] = len(blocked_r)
    reentry_metrics["blocked_avg_r"] = round(np.mean(blocked_r), 3) if blocked_r else 0.0
    reentry_metrics["blocked_total_r"] = round(sum(blocked_r), 2) if blocked_r else 0.0

    return {
        "n_assets": len(all_metrics),
        "n_trades": len(all_r),
        "total_r": round(total_r, 2),
        "gross_profit": round(float(r_arr[r_arr > 0].sum()), 2),
        "gross_loss": round(float(r_arr[r_arr <= 0].sum()), 2),
        "profit_factor": _compute_profit_factor(float(r_arr[r_arr > 0].sum()), float(r_arr[r_arr <= 0].sum())),
        "win_rate": round(win_rate * 100, 1),
        "avg_r": round(float(r_arr.mean()), 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "max_dd_r": round(max_dd, 2),
        "recovery_factor": round(recovery, 3),
        "ulcer_index": round(ulcer, 4),
        "psr": round(psr, 4),
        "dsr": round(dsr, 4),
        "asset_metrics": {m["asset"]: m for m in all_metrics},
        "reentry_stats": reentry_metrics,
    }


# ── Comparison ────────────────────────────────────────────────────────────


def compare_policies(results: dict) -> dict:
    """Compare all policies and compute deltas."""
    policies = results.get("policies", {})
    comparison = {}

    for p_name, p_data in policies.items():
        comparison[p_name] = compute_portfolio_metrics(p_data)

    # Delta: B - A, C - A, C - B
    for p_pair in [("B", "A"), ("C", "A"), ("C", "B")]:
        p1, p2 = p_pair
        if p1 in comparison and p2 in comparison:
            key = f"delta_{p1}_minus_{p2}"
            comparison[key] = {
                "total_r": round(comparison[p1]["total_r"] - comparison[p2]["total_r"], 2),
                "n_trades": comparison[p1]["n_trades"] - comparison[p2]["n_trades"],
                "sharpe": round(comparison[p1]["sharpe"] - comparison[p2]["sharpe"], 3),
                "max_dd_r": round(comparison[p1]["max_dd_r"] - comparison[p2]["max_dd_r"], 2),
                "win_rate": round(comparison[p1]["win_rate"] - comparison[p2]["win_rate"], 1),
            }

    return comparison


# ── Main ──────────────────────────────────────────────────────────────────


def print_comparison(comparison: dict) -> None:
    """Print formatted comparison table."""
    policies = [k for k in comparison.keys() if k in ("A", "B", "C")]

    print("\n" + "=" * 80)
    print("RE-ENTRY POLICY COMPARISON — Portfolio-Level")
    print("=" * 80)

    headers = ["Metric", *[f"Policy {p}" for p in policies]]
    rows = [
        ("Total R", [comparison[p].get("total_r", "?") for p in policies]),
        ("N Trades", [comparison[p].get("n_trades", "?") for p in policies]),
        ("Win Rate %", [comparison[p].get("win_rate", "?") for p in policies]),
        ("Sharpe", [comparison[p].get("sharpe", "?") for p in policies]),
        ("Sortino", [comparison[p].get("sortino", "?") for p in policies]),
        ("Calmar", [comparison[p].get("calmar", "?") for p in policies]),
        ("Max DD (R)", [comparison[p].get("max_dd_r", "?") for p in policies]),
        ("Recovery", [comparison[p].get("recovery_factor", "?") for p in policies]),
        ("Profit Factor", [comparison[p].get("profit_factor", "?") for p in policies]),
        ("PSR", [comparison[p].get("psr", "?") for p in policies]),
        ("DSR", [comparison[p].get("dsr", "?") for p in policies]),
    ]

    print(f"\n{'Metric':<20} {' | '.join(f'{h:>12}' for h in headers[1:])}")
    print("-" * 80)
    for name, vals in rows:
        vals_str = " | ".join(f"{str(v):>12}" for v in vals)
        print(f"{name:<20} {vals_str}")

    # Delta rows
    for key in ["delta_B_minus_A", "delta_C_minus_A", "delta_C_minus_B"]:
        if key in comparison:
            d = comparison[key]
            print(f"\n  {key}: ΔR={d['total_r']:+.1f}, Δtrades={d['n_trades']:+d}, ΔSharpe={d['sharpe']:+.3f}, ΔDD={d['max_dd_r']:+.2f}R")

    # Re-entry stats
    print("\n" + "-" * 80)
    print("RE-ENTRY STATISTICS")
    print("-" * 80)
    for p in policies:
        rs = comparison[p].get("reentry_stats", {})
        print(f"\n  Policy {p}:")
        print(f"    Re-entries:         {rs.get('n_reentries', 0)}")
        print(f"    Profitable:         {rs.get('profitable_reentries', 0)} ({rs.get('reentry_win_rate', 0)}%)")
        print(f"    Avg re-entry R:     {rs.get('avg_reentry_r', 0):+.3f}")
        print(f"    Re-entry total R:   {rs.get('reentry_total_r', 0):+.2f}")
        print(f"    Blocked (count):    {rs.get('blocked_n', 0)}")
        print(f"    Blocked avg R:      {rs.get('blocked_avg_r', 0):+.3f}")
        print(f"    Blocked total R:    {rs.get('blocked_total_r', 0):+.2f}")

    # Per-asset detail
    print("\n" + "-" * 80)
    print("PER-ASSET COMPARISON")
    print("-" * 80)
    assets = sorted(comparison["A"].get("asset_metrics", {}).keys())
    print(f"{'Asset':<10} {'Trades_A':>8} {'R_A':>8} {'Trades_B':>8} {'R_B':>8} {'ΔR_B-A':>8} {'Trades_C':>8} {'R_C':>8} {'ΔR_C-A':>8}")  # noqa: E501
    print("-" * 80)
    for a in assets:
        m_a = comparison["A"]["asset_metrics"].get(a, {})
        m_b = comparison["B"]["asset_metrics"].get(a, {})
        m_c = comparison["C"]["asset_metrics"].get(a, {})
        ta = m_a.get("n_trades", 0)
        ra = m_a.get("total_r", 0)
        tb = m_b.get("n_trades", 0)
        rb = m_b.get("total_r", 0)
        tc = m_c.get("n_trades", 0)
        rc = m_c.get("total_r", 0)
        dr_ba = rb - ra
        dr_ca = rc - ra
        print(f"{a:<10} {ta:>8} {ra:>+8.1f} {tb:>8} {rb:>+8.1f} {dr_ba:>+8.1f} {tc:>8} {rc:>+8.1f} {dr_ca:>+8.1f}")


def main():
    parser = argparse.ArgumentParser(description="Compute re-entry policy metrics")
    parser.add_argument("--input", default="/tmp/reentry_full_results.json", help="Path to simulation results")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    with open(args.input) as f:
        results = json.load(f)

    comparison = compare_policies(results)
    print_comparison(comparison)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(comparison, f, indent=2, default=str)
        logger.info("Metrics saved to %s", args.output)

    return comparison


if __name__ == "__main__":
    main()
