"""Phase 17 — Portfolio Timing Analysis.

For every asset, determines which sessions/hours/DOW are profitable.
Identifies:
  - Which assets should only trade during certain sessions
  - Which assets perform best during each session
  - Which assets should avoid Asian/London/NY hours
  - Whether some assets are consistently profitable only during session overlaps

Produces per-asset trading calendar recommendations.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase17_timing")

SESSION_LABELS = ["sydney", "tokyo", "london", "new_york",
                  "sydney_tokyo", "tokyo_london", "london_ny", "ny_close"]
DOW_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
HOUR_RANGE = list(range(24))


def _safe_mean(x):
    return float(np.mean(x)) if len(x) > 0 else 0.0


def _win_rate(x):
    return sum(1 for r in x if r > 0) / len(x) * 100 if len(x) > 0 else 0.0


def compute_per_asset_session_matrix(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Build a matrix of (asset × session) performance.

    Returns for each asset the session-level stats and a recommendation.
    """
    matrix: dict[str, dict] = {}

    for asset, trades in trades_map.items():
        session_buckets: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            s = t.get("entry_session", "unknown")
            session_buckets[s].append(t.get("r_multiple", 0.0))

        asset_data = {}
        for session in SESSION_LABELS:
            rs = session_buckets.get(session, [])
            if rs:
                asset_data[session] = {
                    "n": len(rs),
                    "total_r": round(float(np.sum(rs)), 2),
                    "avg_r": round(_safe_mean(rs), 4),
                    "wr": round(_win_rate(rs), 1),
                    "sharpe": round(float(np.mean(rs) / max(np.std(rs), 1e-9)), 4) if len(rs) > 1 else 0.0,
                }

        # Best and worst sessions
        if asset_data:
            sorted_sessions = sorted(asset_data.items(), key=lambda x: x[1]["avg_r"], reverse=True)
            asset_data["best_session"] = sorted_sessions[0][0] if sorted_sessions else None
            asset_data["worst_session"] = sorted_sessions[-1][0] if sorted_sessions else None
            asset_data["recommendation"] = _recommend_session(asset_data, asset)
        else:
            asset_data["best_session"] = None
            asset_data["worst_session"] = None
            asset_data["recommendation"] = "insufficient_data"

        matrix[asset] = asset_data

    return matrix


def _recommend_session(asset_data: dict, asset: str) -> str:
    """Generate a trading calendar recommendation per asset."""
    session_metrics = {k: v for k, v in asset_data.items() if k in SESSION_LABELS}
    if not session_metrics:
        return "all_sessions"

    positive = {s: d for s, d in session_metrics.items() if d.get("avg_r", 0) > 0 and d.get("n", 0) >= 3}
    negative = {s: d for s, d in session_metrics.items() if d.get("avg_r", 0) <= 0 and d.get("n", 0) >= 3}

    pct_positive = len(positive) / max(len(session_metrics), 1) * 100

    if pct_positive >= 80:
        return "trade_all_sessions"
    elif pct_positive >= 50:
        neg_list = ", ".join(sorted(negative.keys()))
        return f"avoid_{neg_list}" if neg_list else "trade_all_sessions"
    elif len(positive) > 0:
        pos_list = ", ".join(sorted(positive.keys()))
        return f"trade_only_{pos_list}"
    else:
        return "review_asset"


def compute_per_asset_hour_matrix(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Hour-level profitability per asset."""
    matrix: dict[str, dict] = {}

    for asset, trades in trades_map.items():
        hour_buckets: dict[int, list[float]] = defaultdict(list)
        for t in trades:
            h = t.get("entry_hour_utc", -1)
            if h >= 0:
                hour_buckets[int(h)].append(t.get("r_multiple", 0.0))

        hour_data = {}
        for h in HOUR_RANGE:
            rs = hour_buckets.get(h, [])
            if rs:
                hour_data[str(h)] = {
                    "n": len(rs),
                    "total_r": round(float(np.sum(rs)), 2),
                    "avg_r": round(_safe_mean(rs), 4),
                    "wr": round(_win_rate(rs), 1),
                }

        if hour_data:
            sorted_hours = sorted(hour_data.items(), key=lambda x: x[1]["avg_r"], reverse=True)
            matrix[asset] = {
                "hours": hour_data,
                "best_hours": [{"hour": h, "avg_r": d["avg_r"], "n": d["n"]} for h, d in sorted_hours[:3]],
                "worst_hours": [{"hour": h, "avg_r": d["avg_r"], "n": d["n"]} for h, d in sorted_hours[-3:]],
            }

    return matrix


def compute_per_asset_dow_matrix(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Day-of-week profitability per asset."""
    matrix: dict[str, dict] = {}

    for asset, trades in trades_map.items():
        dow_buckets: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            d = t.get("entry_dow", "unknown")
            dow_buckets[d].append(t.get("r_multiple", 0.0))

        dow_data = {}
        for day in DOW_LABELS:
            rs = dow_buckets.get(day, [])
            if rs:
                dow_data[day] = {
                    "n": len(rs),
                    "total_r": round(float(np.sum(rs)), 2),
                    "avg_r": round(_safe_mean(rs), 4),
                    "wr": round(_win_rate(rs), 1),
                }

        if dow_data:
            matrix[asset] = dow_data

    return matrix


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 17: Portfolio timing analysis")

    session_matrix = compute_per_asset_session_matrix(trades_map)
    hour_matrix = compute_per_asset_hour_matrix(trades_map)
    dow_matrix = compute_per_asset_dow_matrix(trades_map)

    # Portfolio-level summary: which sessions are most/least profitable overall
    session_pool: dict[str, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            s = t.get("entry_session", "unknown")
            session_pool[s].append(t.get("r_multiple", 0.0))

    portfolio_session = {}
    for s in SESSION_LABELS:
        rs = session_pool.get(s, [])
        if rs:
            portfolio_session[s] = {
                "n": len(rs),
                "total_r": round(float(np.sum(rs)), 2),
                "avg_r": round(_safe_mean(rs), 4),
                "wr": round(_win_rate(rs), 1),
                "share_of_portfolio_pct": round(len(rs) / max(sum(len(v) for v in session_pool.values()), 1) * 100, 1),
            }

    return {
        "per_asset_session": session_matrix,
        "per_asset_hour": hour_matrix,
        "per_asset_dow": dow_matrix,
        "portfolio_session_summary": portfolio_session,
        "assets_that_need_restricted_sessions": [
            a for a, d in session_matrix.items()
            if isinstance(d.get("recommendation"), str) and d["recommendation"].startswith("avoid_")
        ],
        "assets_that_need_review": [
            a for a, d in session_matrix.items()
            if d.get("recommendation") == "review_asset"
        ],
    }
