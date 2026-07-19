#!/usr/bin/env python3
"""
Re-entry Policy Decision Report.

Per-asset deep dive, policy recommendation matrix, and
final printed recommendation for production deployment.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_report.py
"""

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(Path(__file__).resolve().parent, "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reentry_report")

RECOMMENDATION_MAP: dict[str, str] = {
    "strong_buy": "Allow 2-position re-entry (recommended)",
    "weak_buy": "Allow 2-position re-entry (monitor)",
    "neutral": "Allow 2-position re-entry (no adverse effect)",
    "weak_sell": "Restrict to 1 position (degrade risk)",
    "strong_sell": "Restrict to 1 position (confirmed degrade)",
}


def load_metrics(path: str = "/tmp/reentry_metrics.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_statistics(path: str = "/tmp/reentry_statistics.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_simulation(path: str = "/tmp/reentry_full_results.json") -> dict:
    with open(path) as f:
        return json.load(f)


def classify_asset(
    asset: str,
    r_a: float,
    r_b: float,
    n_a: int,
    n_b: int,
    degrade: bool,
) -> dict[str, Any]:
    """Classify an asset for re-entry policy recommendation."""
    delta_r = r_b - r_a
    r_ratio = r_b / max(abs(r_a), 1e-6) if abs(r_a) > 1e-6 else float("inf")

    if degrade and delta_r < 0:
        if delta_r < -5.0:
            rec = "strong_sell"
        else:
            rec = "weak_sell"
    elif delta_r > 10.0 and r_ratio > 1.5:
        rec = "strong_buy"
    elif delta_r > 2.0:
        rec = "weak_buy"
    elif delta_r > -2.0:
        rec = "neutral"
    elif delta_r > -5.0:
        rec = "weak_sell"
    else:
        rec = "strong_sell"

    return {
        "asset": asset,
        "r_a": round(r_a, 1),
        "r_b": round(r_b, 1),
        "delta_r": round(delta_r, 1),
        "r_ratio": round(r_ratio, 2),
        "n_a": n_a,
        "n_b": n_b,
        "recommendation": rec,
        "label": RECOMMENDATION_MAP[rec],
    }


def per_asset_deep_dive(
    data: dict,
    metrics: dict,
    degrade_assets: list[dict],
) -> list[dict[str, Any]]:
    """Build per-asset recommendation list."""
    asset_a = metrics.get("A", {}).get("asset_metrics", {})
    asset_b = metrics.get("B", {}).get("asset_metrics", {})

    degrade_set = {d["asset"] for d in degrade_assets}

    results = []
    for asset, m_a in asset_a.items():
        m_b = asset_b.get(asset, {})
        results.append(classify_asset(
            asset,
            m_a.get("total_r", 0),
            m_b.get("total_r", 0),
            m_a.get("n_trades", 0),
            m_b.get("n_trades", 0),
            asset in degrade_set,
        ))

    return sorted(results, key=lambda r: r["delta_r"], reverse=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Re-entry policy report")
    parser.add_argument("--metrics", default="/tmp/reentry_metrics.json")
    parser.add_argument("--statistics", default="/tmp/reentry_statistics.json")
    parser.add_argument("--simulation", default="/tmp/reentry_full_results.json")
    parser.add_argument("--output", default="/tmp/reentry_report.json")
    args = parser.parse_args()

    logger.info("Loading metrics from %s", args.metrics)
    metrics = load_metrics(args.metrics)
    logger.info("Loading statistics from %s", args.statistics)
    stats = load_statistics(args.statistics)
    logger.info("Loading simulation from %s", args.simulation)
    data = load_simulation(args.simulation)

    degrade_assets = stats.get("sensitivity", {}).get("degrade_assets", [])
    recommendations = per_asset_deep_dive(data, metrics, degrade_assets)

    decision_matrix = {
        "strong_buy": [r for r in recommendations if r["recommendation"] == "strong_buy"],
        "weak_buy": [r for r in recommendations if r["recommendation"] == "weak_buy"],
        "neutral": [r for r in recommendations if r["recommendation"] == "neutral"],
        "weak_sell": [r for r in recommendations if r["recommendation"] == "weak_sell"],
        "strong_sell": [r for r in recommendations if r["recommendation"] == "strong_sell"],
    }

    report = {
        "metadata": {
            "timestamp": str(pd.Timestamp.now()),
            "study": "reentry_policy_simulation",
            "policies": {"A": "1-position baseline", "B": "2-position re-entry", "C": "3-position re-entry"},
        },
        "portfolio_summary": {
            "Policy_A": {
                "total_r": metrics.get("A", {}).get("total_r", 0),
                "n_trades": metrics.get("A", {}).get("n_trades", 0),
                "sharpe": metrics.get("A", {}).get("sharpe", 0),
                "max_dd_r": metrics.get("A", {}).get("max_dd_r", 0),
                "psr": metrics.get("A", {}).get("psr", 0),
                "dsr": metrics.get("A", {}).get("dsr", 0),
            },
            "Policy_B": {
                "total_r": metrics.get("B", {}).get("total_r", 0),
                "n_trades": metrics.get("B", {}).get("n_trades", 0),
                "sharpe": metrics.get("B", {}).get("sharpe", 0),
                "max_dd_r": metrics.get("B", {}).get("max_dd_r", 0),
                "psr": metrics.get("B", {}).get("psr", 0),
                "dsr": metrics.get("B", {}).get("dsr", 0),
            },
            "Policy_C": {
                "total_r": metrics.get("C", {}).get("total_r", 0),
                "n_trades": metrics.get("C", {}).get("n_trades", 0),
                "sharpe": metrics.get("C", {}).get("sharpe", 0),
                "max_dd_r": metrics.get("C", {}).get("max_dd_r", 0),
                "psr": metrics.get("C", {}).get("psr", 0),
                "dsr": metrics.get("C", {}).get("dsr", 0),
            },
            "delta_B_minus_A": {
                "total_r": round(
                    metrics.get("B", {}).get("total_r", 0) - metrics.get("A", {}).get("total_r", 0), 1
                ),
                "sharpe": round(
                    metrics.get("B", {}).get("sharpe", 0) - metrics.get("A", {}).get("sharpe", 0), 4
                ),
                "max_dd": round(
                    metrics.get("B", {}).get("max_dd_r", 0) - metrics.get("A", {}).get("max_dd_r", 0), 1
                ),
            },
        },
        "bootstrap_validation": stats.get("bootstrap", {}),
        "monte_carlo_validation": stats.get("monte_carlo", {}),
        "regime_analysis": stats.get("regime", {}),
        "max_positions_sweep": stats.get("max_positions_sweep", {}),
        "per_asset_recommendations": recommendations,
        "decision_matrix": {k: [r["asset"] for r in v] for k, v in decision_matrix.items()},
        "final_recommendation": _produce_recommendation(recommendations, metrics, stats, degrade_assets),
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        logger.info("Report saved to %s", args.output)

    _print_report(report)
    return report


def _produce_recommendation(
    recommendations: list[dict],
    metrics: dict,
    stats: dict,
    degrade_assets: list[dict],
) -> dict[str, Any]:
    n_strong_buy = sum(1 for r in recommendations if r["recommendation"] == "strong_buy")
    n_weak_buy = sum(1 for r in recommendations if r["recommendation"] == "weak_buy")
    n_neutral = sum(1 for r in recommendations if r["recommendation"] == "neutral")
    n_weak_sell = sum(1 for r in recommendations if r["recommendation"] == "weak_sell")
    n_strong_sell = sum(1 for r in recommendations if r["recommendation"] == "strong_sell")

    bs = stats.get("bootstrap", {}).get("A_vs_B", {})
    mc = stats.get("monte_carlo", {}).get("Policy_B", {})

    if n_strong_sell > 2:
        decision = "CAUTIOUS"
        summary = "Too many assets degrade under re-entry. Recommend per-asset opt-in."
    elif n_strong_sell == 0 and n_weak_sell <= 2 and bs.get("pct_improve", 0) > 95:
        decision = "APPROVED"
        summary = "Strong statistical evidence supports portfolio-wide re-entry."
    elif n_weak_sell <= 4 and bs.get("pct_improve", 0) > 90:
        decision = "APPROVED_WITH_EXCEPTIONS"
        summary = "Approve re-entry with per-asset opt-out for degrading assets."
    else:
        decision = "MONITOR"
        summary = "Insufficient evidence or excessive degrade risk."

    return {
        "decision": decision,
        "summary": summary,
        "n_recommendations": {
            "strong_buy": n_strong_buy,
            "weak_buy": n_weak_buy,
            "neutral": n_neutral,
            "weak_sell": n_weak_sell,
            "strong_sell": n_strong_sell,
        },
        "key_evidence": {
            "bootstrap_p_improve_pct": round(bs.get("pct_improve", 0), 1),
            "bootstrap_delta_r": round(bs.get("delta_r_mean", 0), 1),
            "bootstrap_delta_sharpe_ci": bs.get("delta_sharpe_ci_95", [0, 0]),
            "monte_carlo_p_positive": round(mc.get("p_positive", 0), 1),
            "monte_carlo_mean_final_r": round(mc.get("mean_final_r", 0), 1),
            "monte_carlo_mean_max_dd": round(mc.get("mean_max_dd", 0), 1),
            "n_degrade_assets": len(degrade_assets),
        },
    }


def _print_report(report: dict) -> None:
    print("\n" + "=" * 70)
    print("RE-ENTRY POLICY DECISION REPORT")
    print("=" * 70)

    ps = report["portfolio_summary"]
    print("\n--- Portfolio Summary ---")
    print(f"  Policy A (1-pos): R={ps['Policy_A']['total_r']:+.1f}, Sharpe={ps['Policy_A']['sharpe']:.4f}, DD={ps['Policy_A']['max_dd_r']:.1f}R")
    print(f"  Policy B (2-pos): R={ps['Policy_B']['total_r']:+.1f}, Sharpe={ps['Policy_B']['sharpe']:.4f}, DD={ps['Policy_B']['max_dd_r']:.1f}R")
    print(f"  Policy C (3-pos): R={ps['Policy_C']['total_r']:+.1f}, Sharpe={ps['Policy_C']['sharpe']:.4f}, DD={ps['Policy_C']['max_dd_r']:.1f}R")
    d = ps["delta_B_minus_A"]
    print(f"  ΔB-A: R={d['total_r']:+.1f}, Sharpe={d['sharpe']:+.4f}, DD={d['max_dd']:+.1f}R")

    fr = report["final_recommendation"]
    print(f"\n--- Decision: {fr['decision']} ---")
    print(f"  {fr['summary']}")
    print(f"  Bootstrap P(improve): {fr['key_evidence']['bootstrap_p_improve_pct']:.1f}%")
    print(f"  Monte Carlo P(positive): {fr['key_evidence']['monte_carlo_p_positive']:.1f}%")
    print(f"  Degrading assets: {fr['key_evidence']['n_degrade_assets']}")

    print("\n--- Per-Asset Recommendations ---")
    print(f"{'Asset':<10} {'R_A':>7} {'R_B':>7} {'ΔR':>7} {'Ratio':>6} {'Rec':<25}")
    print("-" * 65)
    for r in report["per_asset_recommendations"]:
        rec_short = r["recommendation"].replace("strong_buy", "STRONG BUY").replace("weak_buy", "WEAK BUY").replace("neutral", "NEUTRAL").replace("weak_sell", "WEAK SELL").replace("strong_sell", "STR SELL")
        print(f"{r['asset']:<10} {r['r_a']:>+7.1f} {r['r_b']:>+7.1f} {r['delta_r']:>+7.1f} {r['r_ratio']:>6.1f} {rec_short:<25}")

    print("\n--- Decision Matrix ---")
    dm = report["decision_matrix"]
    for cat, assets in dm.items():
        if assets:
            print(f"  {cat.replace('_', ' ').title():<20}: {', '.join(assets)}")


if __name__ == "__main__":
    main()
