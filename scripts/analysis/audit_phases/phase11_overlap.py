"""Phase 11 — Trade Overlap & Correlation Analysis.

Evaluates:
  - Simultaneous open positions over time (portfolio clustering)
  - Correlated entries (same hour/session across assets)
  - Correlated exits (same exit date/reason across assets)
  - Drawdown concentration (which assets drive the worst drawdowns)
  - Sector/region clustering of positions
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase11_overlap")

REGION_MAP: dict[str, str] = {
    "AUDUSD": "commodity_aud", "USDCAD": "commodity_cad", "NZDCAD": "nzd",
    "NZDUSD": "nzd", "GBPAUD": "gbp", "GBPCAD": "gbp", "GBPCHF": "gbp",
    "GBPUSD": "gbp", "EURCAD": "eur", "EURCHF": "eur", "EURNZD": "eur",
    "EURAUD": "eur", "CADCHF": "chf", "NZDCHF": "nzd", "USDCHF": "chf",
    "GC": "commodity_metal",
}


def _to_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00").split("+")[0].split(".")[0])
        except (ValueError, TypeError):
            return None
    return None


def compute_overlap(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Analyze simultaneous open positions and correlated exits.

    Reconstructs a timeline of open positions by sorting all trades by entry_date,
    tracking which assets are simultaneously open at each point in time.
    """
    all_events: list[dict] = []
    for asset, trades in trades_map.items():
        for t in trades:
            entry_dt = _to_dt(t.get("entry_date"))
            exit_dt = _to_dt(t.get("exit_date"))
            if entry_dt is None:
                continue
            r_mult = t.get("r_multiple", 0.0)
            all_events.append({
                "type": "entry", "asset": asset, "ts": entry_dt,
                "r": r_mult, "region": REGION_MAP.get(asset, "other"),
                "side": t.get("side", "?"),
            })
            if exit_dt is not None:
                all_events.append({
                    "type": "exit", "asset": asset, "ts": exit_dt,
                    "r": r_mult, "region": REGION_MAP.get(asset, "other"),
                    "side": t.get("side", "?"),
                })

    if not all_events:
        return {"error": "no events"}

    all_events.sort(key=lambda e: e["ts"])

    # Simulate portfolio state
    open_positions: dict[str, dict] = {}
    overlap_timeline: list[dict] = []
    region_positions: dict[str, int] = defaultdict(int)
    max_concurrent = 0
    max_concurrent_ts = None
    max_concurrent_assets: list[str] = []

    # Track exits that happen within the same timestamp (correlated exits)
    exit_clusters: list[dict] = []
    current_exit_cluster: dict | None = None

    for event in all_events:
        asset = event["asset"]
        ts = event["ts"]

        if event["type"] == "entry":
            open_positions[asset] = event
            region_positions[event["region"]] += 1
            n_curr = len(open_positions)
            if n_curr > max_concurrent:
                max_concurrent = n_curr
                max_concurrent_ts = ts
                max_concurrent_assets = list(open_positions.keys())
            overlap_timeline.append({"ts": ts.isoformat(), "n_open": n_curr, "assets": list(open_positions.keys())})

            # Check for same-hour entries (correlated entries)
            # Handled in cluster analysis below

        elif event["type"] == "exit":
            if asset in open_positions:
                del open_positions[asset]
                region_positions[event["region"]] = max(0, region_positions[event["region"]] - 1)

            # Cluster exits by same date
            if current_exit_cluster is None:
                current_exit_cluster = {"ts": ts.isoformat(), "assets": [asset], "count": 1}
            elif abs((ts - datetime.fromisoformat(current_exit_cluster["ts"])).total_seconds()) < 86400:
                current_exit_cluster["assets"].append(asset)
                current_exit_cluster["count"] += 1
            else:
                if current_exit_cluster["count"] >= 2:
                    exit_clusters.append(current_exit_cluster)
                current_exit_cluster = {"ts": ts.isoformat(), "assets": [asset], "count": 1}

    if current_exit_cluster and current_exit_cluster["count"] >= 2:
        exit_clusters.append(current_exit_cluster)

    # Correlated entry analysis: trades entering within same hour across assets
    entry_hour_clusters: dict[str, list[str]] = defaultdict(list)
    for t_entry in [e for e in all_events if e["type"] == "entry"]:
        hour_key = t_entry["ts"].strftime("%Y-%m-%d %H")
        entry_hour_clusters[hour_key].append(t_entry["asset"])

    multi_entry_hours = {k: v for k, v in entry_hour_clusters.items() if len(v) >= 3}
    multi_entry_hours_list = [{"hour": k, "assets": v, "count": len(v)} for k, v in
                              sorted(multi_entry_hours.items(), key=lambda x: len(x[1]), reverse=True)]

    # Region concentration during overlap peaks
    peak_region: dict[str, int] = defaultdict(int)
    for a in max_concurrent_assets:
        peak_region[REGION_MAP.get(a, "other")] += 1

    return {
        "max_concurrent_positions": max_concurrent,
        "max_concurrent_timestamp": max_concurrent_ts.isoformat() if max_concurrent_ts else None,
        "max_concurrent_assets": max_concurrent_assets,
        "peak_region_concentration": dict(peak_region),
        "correlated_exit_clusters": [
            {"ts": c["ts"], "n_assets": c["count"], "assets": c["assets"]}
            for c in exit_clusters[:20]
        ],
        "correlated_entry_hours": multi_entry_hours_list[:20],
        "n_correlated_entry_hours": len(multi_entry_hours),
        "avg_concurrent": round(float(np.mean([e["n_open"] for e in overlap_timeline])), 2),
        "pct_time_zero_positions": round(
            sum(1 for e in overlap_timeline if e["n_open"] == 0) / max(len(overlap_timeline), 1) * 100, 1
        ),
        "pct_time_high_concentration": round(
            sum(1 for e in overlap_timeline if e["n_open"] >= 5) / max(len(overlap_timeline), 1) * 100, 1
        ),
    }


def compute_correlation_matrix(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    """Compute pairwise trade entry correlation between assets.

    Uses co-occurrence of entry events within a 1-hour window.
    Returns correlation matrix and cluster assignments.
    """
    assets = sorted(trades_map.keys())
    n = len(assets)
    if n < 2:
        return {"error": "need at least 2 assets"}

    # Build entry hour signatures
    entry_signatures: dict[str, set[str]] = {}
    for asset, trades in trades_map.items():
        sig: set[str] = set()
        for t in trades:
            dt = _to_dt(t.get("entry_date"))
            if dt is not None:
                sig.add(dt.strftime("%Y-%m-%d %H"))
        entry_signatures[asset] = sig

    corr_matrix: dict[str, dict[str, float]] = {}
    for a1 in assets:
        corr_matrix[a1] = {}
        s1 = entry_signatures[a1]
        if not s1:
            continue
        for a2 in assets:
            if a1 == a2:
                corr_matrix[a1][a2] = 1.0
                continue
            s2 = entry_signatures[a2]
            if not s2:
                corr_matrix[a1][a2] = 0.0
                continue
            intersection = len(s1 & s2)
            union = len(s1 | s2)
            corr_matrix[a1][a2] = round(intersection / max(union, 1), 4)

    return corr_matrix


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 11: Trade overlap & correlation")

    overlap = compute_overlap(trades_map)
    corr_matrix = compute_correlation_matrix(trades_map)

    return {
        "overlap": overlap,
        "correlation_matrix": corr_matrix,
    }
