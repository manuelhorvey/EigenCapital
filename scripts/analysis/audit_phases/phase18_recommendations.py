"""Phase 18 — Production Recommendations.

Aggregates all findings from Phases 1–17 and produces:
  - Classified recommendations (Alpha / Sigma / Info)
  - Impact estimates (total_R, Sharpe, max_dd, capital efficiency)
  - Confidence level
  - Implementation complexity
  - Prioritized list
"""

from __future__ import annotations

import logging
from typing import Any
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase18_recs")

RECOMMENDATION_WEIGHTS = {
    "impact_total_r": 0.25,
    "impact_sharpe": 0.20,
    "impact_max_dd": 0.15,
    "confidence": 0.15,
    "complexity_inverse": 0.15,
    "robustness": 0.10,
}


def _score_rec(rec: dict) -> float:
    """Score a recommendation for priority ranking (higher = better)."""
    score = 0.0
    score += rec.get("impact_total_r", 0) * RECOMMENDATION_WEIGHTS["impact_total_r"]
    score += rec.get("impact_sharpe", 0) * RECOMMENDATION_WEIGHTS["impact_sharpe"]
    score += (1 - rec.get("impact_max_dd", 0)) * RECOMMENDATION_WEIGHTS["impact_max_dd"]
    score += rec.get("confidence", 0.5) * RECOMMENDATION_WEIGHTS["confidence"]
    score += (1 - rec.get("complexity", 0.5)) * RECOMMENDATION_WEIGHTS["complexity_inverse"]
    score += rec.get("robustness", 0.5) * RECOMMENDATION_WEIGHTS["robustness"]
    return round(score, 4)


def run(all_phase_results: dict[str, Any]) -> dict[str, Any]:
    logger.info("Phase 18: Aggregating recommendations")

    recommendations: list[dict] = []

    # ── Phase 4/5: Time-based recommendations ──
    time_data = all_phase_results.get("phase4_5", {}).get("time_breakdown", {})
    concentration = all_phase_results.get("phase4_5", {}).get("concentration", {})
    _extract_time_recs(time_data, concentration, recommendations)

    # ── Phase 6: Holding period ──
    hp_data = all_phase_results.get("phase6", {})
    _extract_hp_recs(hp_data, recommendations)

    # ── Phase 7: Exit strategy ──
    exit_data = all_phase_results.get("phase7", {})
    _extract_exit_recs(exit_data, recommendations)

    # ── Phase 11: Overlap ──
    overlap_data = all_phase_results.get("phase11", {}).get("overlap", {})
    _extract_overlap_recs(overlap_data, recommendations)

    # ── Phase 17: Portfolio timing ──
    timing_data = all_phase_results.get("phase17", {})
    _extract_timing_recs(timing_data, recommendations)

    # ── Phase 9: Opportunity cost ──
    oc_data = all_phase_results.get("phase9", {})
    _extract_opportunity_recs(oc_data, recommendations)

    # ── Phase 8: Entry quality ──
    eq_data = all_phase_results.get("phase8", {}).get("portfolio", {})
    _extract_entry_recs(eq_data, recommendations)

    # ── Phase 14: Regime transitions ──
    regime_data = all_phase_results.get("phase14", {}).get("portfolio", {})
    if regime_data and "error" not in regime_data:
        _extract_regime_recs(regime_data, recommendations)

    # ── Phase 12: Risk of ruin ──
    ruin_data = all_phase_results.get("phase12", {})
    _extract_ruin_recs(ruin_data, recommendations)

    # Score and rank
    for rec in recommendations:
        rec["priority_score"] = _score_rec(rec)

    recommendations.sort(key=lambda r: r["priority_score"], reverse=True)

    # Apply priority rank
    for i, rec in enumerate(recommendations):
        rec["priority_rank"] = i + 1

    # Categorize
    alpha = [r for r in recommendations if r["type"] == "ALPHA"]
    sigma = [r for r in recommendations if r["type"] == "SIGMA"]
    info = [r for r in recommendations if r["type"] == "INFO"]

    return {
        "n_recommendations": len(recommendations),
        "n_alpha": len(alpha),
        "n_sigma": len(sigma),
        "n_info": len(info),
        "top_3": recommendations[:3],
        "recommendations": recommendations,
        "summary": f"{len(alpha)} Alpha (PnL), {len(sigma)} Sigma (risk), {len(info)} Info recommendations",
    }


def _extract_time_recs(time_data: dict, concentration: dict, recs: list):
    if not time_data or "error" in time_data:
        return
    summary = time_data.get("summary", {})
    for dim, data in summary.items():
        worst = data.get("worst", [])
        if worst and worst[0]["expectancy"] < -0.01:
            recs.append({
                "title": f"Filter worst {dim}: {worst[0]['period']}",
                "type": "SIGMA",
                "description": f"Removing trades during {worst[0]['period']} (expectancy={worst[0]['expectancy']:.4f}, "
                               f"loss={worst[0]['total_r']:.1f}R) could reduce drawdown.",
                "impact_total_r": 0.05,
                "impact_sharpe": 0.15,
                "impact_max_dd": 0.20,
                "confidence": 0.4,
                "complexity": 0.2,
                "robustness": 0.3,
            })

    if concentration:
        gini = concentration.get("global_gini", 0)
        if gini > 0.5:
            recs.append({
                "title": "Profit concentration is high (Gini={:.2f})".format(gini),
                "type": "INFO",
                "description": f"Gini={gini:.2f} indicates profits are concentrated. "
                               f"Top 3 periods drive {concentration.get('hourly', {}).get('pct_profit_from_top3', 0)}% of profit.",
                "impact_total_r": 0.0,
                "impact_sharpe": 0.0,
                "impact_max_dd": 0.0,
                "confidence": 0.9,
                "complexity": 0.0,
                "robustness": 0.9,
            })


def _extract_hp_recs(hp_data: dict, recs: list):
    optimal = hp_data.get("optimal", {})
    if optimal:
        baseline = hp_data.get("baseline", {})
        best_candles = optimal.get("max_candles", 0)
        best_sharpe = optimal.get("sharpe", 0)

        recs.append({
            "title": f"Optimal holding period: {best_candles} candles",
            "type": "ALPHA",
            "description": f"Holding for {best_candles} candles maximizes Sharpe ({best_sharpe:.2f}) vs "
                           f"current barrier ({baseline.get('sharpe', 0):.2f}).",
            "impact_total_r": 0.10,
            "impact_sharpe": 0.30,
            "impact_max_dd": 0.10,
            "confidence": 0.5,
            "complexity": 0.3,
            "robustness": 0.4,
        })

        # Per-asset optimal holding periods
        per_asset = hp_data.get("per_asset", {})
        varying = [(a, d.get("best_max_candles", 0)) for a, d in per_asset.items()
                   if d.get("best_max_candles", 0) != best_candles and d.get("best_data", {}).get("n_trades", 0) > 10]
        if varying:
            recs.append({
                "title": f"{len(varying)} assets need individual holding periods",
                "type": "ALPHA",
                "description": f"Assets {', '.join(a for a, _ in varying[:5])} have optimal holding periods "
                               f"different from portfolio optimum ({best_candles}).",
                "impact_total_r": 0.08,
                "impact_sharpe": 0.10,
                "impact_max_dd": 0.05,
                "confidence": 0.4,
                "complexity": 0.4,
                "robustness": 0.3,
            })


def _extract_exit_recs(exit_data: dict, recs: list):
    strategies = exit_data.get("strategies", {})
    ranking_sharpe = exit_data.get("ranking", {}).get("by_sharpe", [])
    ranking_total_r = exit_data.get("ranking", {}).get("by_total_r", [])

    if ranking_sharpe:
        top_sharpe = ranking_sharpe[0]
        baseline_sharpe = next((s for s in ranking_sharpe if s["name"] == "fixed_barriers"), None)

        if top_sharpe and top_sharpe["name"] != "fixed_barriers":
            delta_sharpe = top_sharpe["sharpe"] - (baseline_sharpe["sharpe"] if baseline_sharpe else 0)
            recs.append({
                "title": f"Deploy exit strategy: {top_sharpe['name']}",
                "type": "ALPHA",
                "description": f"Sharpe improves from {baseline_sharpe['sharpe'] if baseline_sharpe else 0:.2f} "
                               f"to {top_sharpe['sharpe']:.2f} using {top_sharpe['name']}. "
                               f"Total R={top_sharpe['total_r']:.1f}, max_dd={top_sharpe['max_dd_r']:.1f}R.",
                "impact_total_r": 0.30,
                "impact_sharpe": 0.50,
                "impact_max_dd": 0.20,
                "confidence": 0.6,
                "complexity": 0.5,
                "robustness": 0.5,
            })

    # Per-asset best exit strategies
    per_asset = exit_data.get("per_asset", {})
    if per_asset:
        recs.append({
            "title": f"Deploy per-asset exit strategies ({len(per_asset)} assets)",
            "type": "ALPHA",
            "description": "Each asset may have a different optimal exit strategy. "
                           "Simulation data available for per-asset tuning.",
            "impact_total_r": 0.20,
            "impact_sharpe": 0.30,
            "impact_max_dd": 0.15,
            "confidence": 0.5,
            "complexity": 0.6,
            "robustness": 0.4,
        })


def _extract_overlap_recs(overlap_data: dict, recs: list):
    if not overlap_data or "error" in overlap_data:
        return
    max_concurrent = overlap_data.get("max_concurrent_positions", 0)
    if max_concurrent >= 8:
        recs.append({
            "title": f"Reduce max concurrent positions ({max_concurrent})",
            "type": "SIGMA",
            "description": f"Portfolio reached {max_concurrent} simultaneous positions. "
                           f"Over-concentration amplifies drawdown during correlated moves.",
            "impact_total_r": 0.0,
            "impact_sharpe": 0.10,
            "impact_max_dd": 0.25,
            "confidence": 0.7,
            "complexity": 0.3,
            "robustness": 0.6,
        })

    cluster_count = overlap_data.get("n_correlated_entry_hours", 0)
    if cluster_count > 10:
        recs.append({
            "title": f"{cluster_count} correlated entry clusters found",
            "type": "INFO",
            "description": f"{cluster_count} instances where 3+ assets entered within the same hour. "
                           f"Staggered entries could reduce clustering.",
            "impact_total_r": 0.0,
            "impact_sharpe": 0.05,
            "impact_max_dd": 0.10,
            "confidence": 0.6,
            "complexity": 0.4,
            "robustness": 0.5,
        })


def _extract_timing_recs(timing_data: dict, recs: list):
    restricted = timing_data.get("assets_that_need_restricted_sessions", [])
    review = timing_data.get("assets_that_need_review", [])

    if restricted:
        recs.append({
            "title": f"Restrict {len(restricted)} assets to profitable sessions",
            "type": "ALPHA",
            "description": f"Assets {', '.join(restricted[:5])} lose money in certain sessions. "
                           f"Restricting trading windows could improve risk-adjusted returns.",
            "impact_total_r": 0.10,
            "impact_sharpe": 0.15,
            "impact_max_dd": 0.10,
            "confidence": 0.5,
            "complexity": 0.3,
            "robustness": 0.4,
        })

    if review:
        recs.append({
            "title": f"Review {len(review)} assets with poor session performance",
            "type": "SIGMA",
            "description": f"Assets {', '.join(review[:3])} show negative expectancy across all sessions.",
            "impact_total_r": 0.05,
            "impact_sharpe": 0.10,
            "impact_max_dd": 0.10,
            "confidence": 0.4,
            "complexity": 0.2,
            "robustness": 0.3,
        })


def _extract_opportunity_recs(oc_data: dict, recs: list):
    portfolio = oc_data.get("portfolio", {})
    verdict = portfolio.get("filter_verdict", "")
    net = portfolio.get("total_net_filter_contribution_r", 0)

    if verdict == "BENEFICIAL":
        recs.append({
            "title": f"Filters saved {abs(net):.1f}R (net beneficial)",
            "type": "INFO",
            "description": f"Gate architecture saved {abs(net):.1f}R by rejecting unprofitable signals.",
            "impact_total_r": 0.0,
            "impact_sharpe": 0.0,
            "impact_max_dd": 0.0,
            "confidence": 0.8,
            "complexity": 0.0,
            "robustness": 0.9,
        })
    elif verdict == "HARMFUL":
        recs.append({
            "title": f"Filters destroyed {net:.1f}R (net harmful)",
            "type": "ALPHA",
            "description": f"Current gate filters reject profitable signals. Net filter contribution is {net:.1f}R.",
            "impact_total_r": 0.15,
            "impact_sharpe": 0.10,
            "impact_max_dd": 0.0,
            "confidence": 0.6,
            "complexity": 0.3,
            "robustness": 0.5,
        })


def _extract_entry_recs(eq_data: dict, recs: list):
    if not eq_data or "error" in eq_data:
        return
    pct_aligned = eq_data.get("pct_trend_aligned", 0)
    entries_against = eq_data.get("entries_against_trend", 0)

    if pct_aligned < 50:
        recs.append({
            "title": f"Only {pct_aligned:.0f}% of entries are trend-aligned",
            "type": "SIGMA",
            "description": f"{entries_against} trades entered against the dominant trend. "
                           f"Trend-filtered entries could improve win rate.",
            "impact_total_r": 0.05,
            "impact_sharpe": 0.08,
            "impact_max_dd": 0.05,
            "confidence": 0.3,
            "complexity": 0.3,
            "robustness": 0.3,
        })


def _extract_regime_recs(regime_data: dict, recs: list):
    pct_worse = regime_data.get("pct_assets_worse_post_transition", 0)
    if pct_worse > 50:
        recs.append({
            "title": f"Regime transitions degrade performance ({pct_worse:.0f}% assets worse)",
            "type": "SIGMA",
            "description": "Performance drops after regime transitions for most assets. "
                           "Consider regime-adaptive exits or post-transition cooldown.",
            "impact_total_r": 0.05,
            "impact_sharpe": 0.10,
            "impact_max_dd": 0.10,
            "confidence": 0.4,
            "complexity": 0.5,
            "robustness": 0.3,
        })


def _extract_ruin_recs(ruin_data: dict, recs: list):
    if not ruin_data or "error" in ruin_data:
        return
    dd_risk = ruin_data.get("drawdown_risk", {})
    p95_dd = dd_risk.get("p95_max_dd_pct", 0)
    worst_dd = dd_risk.get("worst_max_dd_pct", 0)
    verdict = ruin_data.get("verdict", "")

    if verdict == "HIGH_RISK":
        recs.append({
            "title": f"High risk of ruin (p95 DD={p95_dd:.1f}%)",
            "type": "SIGMA",
            "description": f"95th-percentile max drawdown is {p95_dd:.1f}%. Reduce position sizing or add circuit breaker.",
            "impact_total_r": -0.05,
            "impact_sharpe": 0.10,
            "impact_max_dd": 0.30,
            "confidence": 0.7,
            "complexity": 0.3,
            "robustness": 0.7,
        })
