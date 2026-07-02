"""Phase 4 — Time-Based Profitability Analysis.

Determines when the trading system actually earns money.
For every asset and for the portfolio, analyzes profitability by:
  - Hour of day (UTC)
  - Trading session (Sydney/Tokyo/London/NY + overlaps)
  - Day of week
  - Week of month
  - Month of year (seasonality)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
from scipy import stats as sp_stats

logger = logging.getLogger("eigencapital.audit.phase4_time")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_mean(arr: list[float]) -> float:
    return float(np.mean(arr)) if arr else 0.0


def _safe_median(arr: list[float]) -> float:
    return float(np.median(arr)) if arr else 0.0


def _total_r(arr: list[float]) -> float:
    return float(np.sum(arr))


def _win_rate(arr: list[float]) -> float:
    if not arr:
        return 0.0
    return sum(1 for r in arr if r > 0) / len(arr) * 100


def _profit_factor(arr: list[float]) -> float:
    wins = sum(r for r in arr if r > 0)
    losses = abs(sum(r for r in arr if r < 0))
    return wins / losses if losses > 0 else float("inf") if wins > 0 else 0.0


def _expectancy(arr: list[float]) -> float:
    return float(np.mean(arr)) if arr else 0.0


def _sharpe(arr: list[float]) -> float:
    if len(arr) < 2:
        return 0.0
    a = np.array(arr)
    return float(a.mean() / a.std()) if a.std() > 0 else 0.0


def _max_dd(arr: list[float]) -> float:
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def _period_stats(rs: list[float]) -> dict[str, Any]:
    return {
        "n_trades": len(rs),
        "total_r": round(_total_r(rs), 2),
        "avg_r": round(_safe_mean(rs), 4),
        "median_r": round(_safe_median(rs), 4),
        "win_rate": round(_win_rate(rs), 2),
        "profit_factor": round(_profit_factor(rs), 4),
        "expectancy": round(_expectancy(rs), 4),
        "sharpe": round(_sharpe(rs), 4),
        "max_dd_r": round(_max_dd(rs), 2),
        "std_r": round(float(np.std(rs)), 4) if rs else 0.0,
    }


def _binomial_test(period_wr: float, period_n: int, global_wr: float) -> float:
    """p-value that period WR differs from global WR (two-sided binomial test)."""
    if period_n < 5:
        return 1.0
    p = global_wr / 100.0
    k = int(period_wr / 100.0 * period_n)
    pval = sp_stats.binomtest(k, period_n, p, alternative="two-sided").pvalue
    return float(pval)


# ── Aggregation ──────────────────────────────────────────────────────────────


def compute_time_breakdown(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Run full time-based profitability analysis across all time dimensions.

    Returns nested dict with portfolio-level + per-asset breakdowns for each
    time dimension: hourly, session, session_overlap, dow, week_of_month, month.
    """
    results: dict[str, Any] = {}
    dimensions = ["hourly", "session", "session_overlap", "dow", "week_of_month", "month"]

    for dim in dimensions:
        key_map = _dimension_key_map(dim)
        results[dim] = _analyze_dimension(trades_map, key_map)

        # Statistical significance
        global_rs = [t["r_multiple"] for ts in trades_map.values() for t in ts]
        global_wr = _win_rate(global_rs)
        results[dim]["global_win_rate"] = round(global_wr, 2)
        for period_label, period_data in results[dim].get("periods", {}).items():
            if period_data["n_trades"] >= 5:
                pval = _binomial_test(period_data["win_rate"], period_data["n_trades"], global_wr)
                period_data["p_value"] = round(pval, 4)
                period_data["significant_at_5pct"] = pval < 0.05
            else:
                period_data["p_value"] = 1.0
                period_data["significant_at_5pct"] = False

    # Best / worst periods per dimension
    results["summary"] = _summarize_best_worst(results, dimensions)
    return results


def _dimension_key_map(dim: str) -> str:
    """Return the trade dict field name for this dimension."""
    mapping = {
        "hourly": "entry_hour_utc",
        "session": "entry_session",
        "session_overlap": "entry_session_overlap",
        "dow": "entry_dow",
        "week_of_month": "entry_week_of_month",
        "month": "entry_month",
    }
    return mapping.get(dim, dim)


def _analyze_dimension(trades_map: dict[str, list[dict]], key: str) -> dict:
    """Group all trades by a temporal key and compute per-period stats."""
    period_buckets: dict[str, list[float]] = defaultdict(list)
    asset_period: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for asset, trades in trades_map.items():
        for t in trades:
            period_val = str(t.get(key, "unknown"))
            r = t.get("r_multiple", 0.0)
            period_buckets[period_val].append(r)
            asset_period[asset][period_val].append(r)

    periods = {}
    for period_label in sorted(period_buckets.keys(), key=_sort_key):
        rs = period_buckets[period_label]
        periods[period_label] = _period_stats(rs)

    per_asset = {}
    for asset in sorted(asset_period.keys()):
        per_asset[asset] = {}
        for period_label in sorted(asset_period[asset].keys(), key=_sort_key):
            rs = asset_period[asset][period_label]
            per_asset[asset][period_label] = _period_stats(rs)

    return {"periods": periods, "per_asset": per_asset}


def _sort_key(label: str) -> tuple:
    """Sort temporal keys in logical order."""
    try:
        return (0, int(label))
    except ValueError:
        pass
    order = {
        "sydney": 1, "tokyo": 2, "london": 3, "new_york": 4,
        "sydney_tokyo": 5, "tokyo_london": 6, "london_ny": 7, "ny_close": 8, "off_hours": 9, "unknown": 99,
        "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 7,
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
    }
    return (1, order.get(label, 99))


def _summarize_best_worst(time_data: dict, dimensions: list[str]) -> dict:
    summary = {}
    for dim in dimensions:
        periods = time_data[dim].get("periods", {})
        if not periods:
            continue
        sorted_periods = sorted(periods.items(), key=lambda x: x[1].get("expectancy", 0))
        worst = sorted_periods[:3] if len(sorted_periods) >= 3 else sorted_periods
        best = sorted_periods[-3:] if len(sorted_periods) >= 3 else sorted_periods
        best.reverse()
        summary[dim] = {
            "best": [{"period": p[0], "expectancy": p[1].get("expectancy", 0),
                       "total_r": p[1].get("total_r", 0), "n": p[1].get("n_trades", 0)} for p in best],
            "worst": [{"period": p[0], "expectancy": p[1].get("expectancy", 0),
                        "total_r": p[1].get("total_r", 0), "n": p[1].get("n_trades", 0)} for p in worst],
        }
    return summary


# ── Per-dimension convenience helpers ─────────────────────────────────────────


def best_hours(trades_map: dict[str, list[dict]], top_n: int = 3) -> list[dict]:
    """Return the top-N most profitable hours by expectancy."""
    key = _dimension_key_map("hourly")
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            h = t.get(key, -1)
            if h >= 0:
                buckets[int(h)].append(t.get("r_multiple", 0.0))
    sorted_h = sorted(buckets.items(), key=lambda x: _safe_mean(x[1]), reverse=True)
    return [{"hour": h, "n": len(rs), "avg_r": round(_safe_mean(rs), 4), "wr": round(_win_rate(rs), 1), "total_r": round(_total_r(rs), 2)} for h, rs in sorted_h[:top_n]]


def worst_hours(trades_map: dict[str, list[dict]], bottom_n: int = 3) -> list[dict]:
    key = _dimension_key_map("hourly")
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            h = t.get(key, -1)
            if h >= 0:
                buckets[int(h)].append(t.get("r_multiple", 0.0))
    sorted_h = sorted(buckets.items(), key=lambda x: _safe_mean(x[1]))
    return [{"hour": h, "n": len(rs), "avg_r": round(_safe_mean(rs), 4), "wr": round(_win_rate(rs), 1), "total_r": round(_total_r(rs), 2)} for h, rs in sorted_h[:bottom_n]]


def session_summary(trades_map: dict[str, list[dict]]) -> dict:
    """Return per-session performance summary."""
    key = _dimension_key_map("session")
    buckets: dict[str, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            s = t.get(key, "unknown")
            buckets[s].append(t.get("r_multiple", 0.0))
    return {s: _period_stats(rs) for s, rs in sorted(buckets.items(), key=lambda x: _sort_key(x[0]))}


def dow_summary(trades_map: dict[str, list[dict]]) -> dict:
    """Return per-day-of-week performance summary."""
    key = _dimension_key_map("dow")
    buckets: dict[str, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            d = t.get(key, "unknown")
            buckets[d].append(t.get("r_multiple", 0.0))
    return {d: _period_stats(rs) for d, rs in sorted(buckets.items(), key=lambda x: _sort_key(x[0]))}


def monthly_summary(trades_map: dict[str, list[dict]]) -> dict:
    """Return per-month performance summary."""
    key = _dimension_key_map("month")
    buckets: dict[str, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            m = t.get(key, "unknown")
            buckets[m].append(t.get("r_multiple", 0.0))
    return {m: _period_stats(rs) for m, rs in sorted(buckets.items(), key=lambda x: _sort_key(x[0]))}


# ── Phase 5: Profit Concentration ─────────────────────────────────────────────


def compute_concentration(trades_map: dict[str, list[dict]], time_data: dict) -> dict[str, Any]:
    """Phase 5 — Profit concentration analysis.

    Determines what percentage of total profits/losses are generated during
    each time period. Computes Gini coefficient and top-N concentration.
    """
    all_rs = [t["r_multiple"] for ts in trades_map.values() for t in ts]
    total_profit = sum(r for r in all_rs if r > 0)
    total_loss = abs(sum(r for r in all_rs if r < 0))

    dims = ["hourly", "session", "session_overlap", "dow", "month"]
    concentration: dict = {}

    for dim in dims:
        periods = time_data[dim].get("periods", {})
        if not periods:
            continue
        dim_c = _dim_concentration(periods, total_profit, total_loss, dim)
        concentration[dim] = dim_c

    # Global Gini
    concentration["global_gini"] = round(_gini_coefficient(sorted(all_rs)), 4)
    concentration["total_profit_r"] = round(total_profit, 2)
    concentration["total_loss_r"] = round(total_loss, 2)

    return concentration


def _dim_concentration(periods: dict, total_profit: float, total_loss: float, dim: str) -> dict:
    profit_shares = []
    loss_shares = []
    trade_shares = []

    for label, data in periods.items():
        n = data.get("n_trades", 0)
        tr = data.get("total_r", 0.0)
        profit_share = max(tr, 0) / total_profit * 100 if total_profit > 0 else 0
        loss_share = abs(min(tr, 0)) / total_loss * 100 if total_loss > 0 else 0
        profit_shares.append((label, round(profit_share, 2), n))
        loss_shares.append((label, round(loss_share, 2), n))

    # Top 3 by profit share
    top_profit = sorted(profit_shares, key=lambda x: x[1], reverse=True)[:5]
    top_loss = sorted(loss_shares, key=lambda x: x[1], reverse=True)[:5]

    # Concentration: what % of total profit comes from top 3 periods
    pct_from_top3_profit = sum(p[1] for p in top_profit[:3])
    pct_from_top3_loss = sum(p[1] for p in top_loss[:3])

    return {
        "top_profit_periods": [{"period": p[0], "profit_share_pct": p[1], "n_trades": p[2]} for p in top_profit],
        "top_loss_periods": [{"period": p[0], "loss_share_pct": p[1], "n_trades": p[2]} for p in top_loss],
        "pct_profit_from_top3": round(pct_from_top3_profit, 2),
        "pct_loss_from_top3": round(pct_from_top3_loss, 2),
    }


def _gini_coefficient(sorted_vals: list[float]) -> float:
    """Compute Gini coefficient of R-multiples."""
    if not sorted_vals or sum(sorted_vals) == 0:
        return 0.0
    n = len(sorted_vals)
    cumsum = np.cumsum(sorted(sorted_vals))
    return float((2 * np.sum(cumsum) / n / np.sum(sorted_vals)) - (n + 1) / n)


# ── Main ─────────────────────────────────────────────────────────────────────


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 4–5: Time-based profitability + concentration")
    time_data = compute_time_breakdown(trades_map)
    concentration = compute_concentration(trades_map, time_data)
    return {"time_breakdown": time_data, "concentration": concentration}
