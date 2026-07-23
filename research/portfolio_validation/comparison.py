"""Scenario comparison — statistical tests between A/B/C results."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats as sp_stats


def compare_portfolios(
    results_a: dict[str, Any],
    results_b: dict[str, Any],
    results_c: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare portfolio metrics across scenarios.

    Args:
        results_a: Scenario A results.
        results_b: Scenario B results.
        results_c: Optional Scenario C results.

    Returns:
        Dict of comparison metrics with paired statistical tests.
    """
    assets_a = {r["asset"]: r for r in results_a.get("asset_results", [])}
    assets_b = {r["asset"]: r for r in results_b.get("asset_results", [])}

    comparison: dict[str, Any] = {}
    common_assets = set(assets_a.keys()) & set(assets_b.keys())

    # Per-metric paired comparison
    for metric in ["sharpe", "ece", "cal_inversion_rate", "brier"]:
        vals_a = []
        vals_b = []
        for asset in sorted(common_assets):
            va = assets_a[asset].get(metric)
            vb = assets_b[asset].get(metric)
            if va is not None and vb is not None:
                vals_a.append(va)
                vals_b.append(vb)

        if len(vals_a) < 3 or len(vals_b) < 3:
            comparison[metric] = {
                "mean_a": float(np.mean(vals_a)) if vals_a else 0,
                "mean_b": float(np.mean(vals_b)) if vals_b else 0,
                "paired_t_p": None,
                "wilcoxon_p": None,
                "n_assets": len(vals_a),
                "verdict": "Insufficient data",
            }
            continue

        t_stat, t_p = sp_stats.ttest_rel(vals_a, vals_b)
        w_stat, w_p = sp_stats.wilcoxon(
            vals_a, vals_b, alternative="two-sided",
        )

        mean_a = float(np.mean(vals_a))
        mean_b = float(np.mean(vals_b))
        delta = mean_b - mean_a

        if metric == "ece":
            improvement = -delta  # negative delta is improvement
            verdict = (
                "Significant improvement" if t_p < 0.05 and improvement > 0
                else "Significant degradation" if t_p < 0.05 and improvement < 0
                else "No significant difference"
            )
        elif metric == "sharpe":
            verdict = (
                "Significant improvement" if t_p < 0.05 and delta > 0
                else "Significant degradation" if t_p < 0.05 and delta < 0
                else "No significant difference"
            )
        else:
            verdict = (
                "Significant difference" if t_p < 0.05
                else "No significant difference"
            )

        comparison[metric] = {
            "mean_a": round(mean_a, 4),
            "mean_b": round(mean_b, 4),
            "delta": round(delta, 4),
            "delta_pct": f"{delta / max(abs(mean_a), 1e-8) * 100:+.1f}%",
            "paired_t_p": round(t_p, 4) if not np.isnan(t_p) else None,
            "wilcoxon_p": round(w_p, 4) if not np.isnan(w_p) else None,
            "n_assets": len(vals_a),
            "verdict": verdict,
        }

    # Additional behavioral comparisons
    comparison["behavioral"] = _compare_behavioral(assets_a, assets_b, common_assets)

    if results_c:
        comparison["scenario_c"] = _summarize_c(results_c)

    return comparison


def _compare_behavioral(
    assets_a: dict[str, Any],
    assets_b: dict[str, Any],
    common: set[str],
) -> dict[str, Any]:
    """Compare behavioral characteristics across scenarios."""
    flips_a = sum(
        1 for a in common
        if assets_a[a].get("cal_inversion_rate", 0) > 0.5
    )
    flips_b = sum(
        1 for a in common
        if assets_b[a].get("cal_inversion_rate", 0) > 0.5
    )

    sell_pct_a = np.mean([assets_a[a].get("sell_pct", 0) for a in common])
    sell_pct_b = np.mean([assets_b[a].get("sell_pct", 0) for a in common])

    return {
        "calibration_flips_a": flips_a,
        "calibration_flips_b": flips_b,
        "avg_sell_pct_a": round(float(sell_pct_a), 4),
        "avg_sell_pct_b": round(float(sell_pct_b), 4),
    }


def _summarize_c(results_c: dict[str, Any]) -> dict[str, Any]:
    """Extract key metrics from Scenario C."""
    pm = results_c.get("portfolio_metrics", {})
    return {
        "portfolio_sharpe": pm.get("portfolio_sharpe"),
        "portfolio_ece": pm.get("portfolio_ece"),
        "n_assets": pm.get("n_assets"),
    }
