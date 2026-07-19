"""Phase 13 — Sensitivity Analysis.

Perturbs key parameters and measures the impact on portfolio performance:
  - SL multiplier (0.5×, 0.75×, 1.0×, 1.25×, 1.5× current)
  - TP multiplier (0.5×, 0.75×, 1.0×, 1.25×, 1.5× current)
  - Confidence threshold (±0.05, ±0.10 from current 0.45)
  - Position size (±20%, ±50%)
  - Exit strategy (on/off for each gate)
  - Session filter (remove worst session)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase13_sensitivity")

PERTURBATIONS = {
    "sl_mult": [0.5, 0.75, 1.0, 1.25, 1.5],
    "tp_mult": [0.5, 0.75, 1.0, 1.25, 1.5],
    "confidence_threshold": [0.35, 0.40, 0.45, 0.50, 0.55],
    "position_size_factor": [0.5, 0.8, 1.0, 1.2, 1.5],
}


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 13: Sensitivity analysis")

    def _sharpe_safe(arr):
        if len(arr) < 2:
            return 0.0
        s = float(arr.std())
        return round(float(arr.mean() / s), 4) if s > 0 else 0.0

    all_rs = np.array([t["r_multiple"] for ts in trades_map.values() for t in ts])
    baseline_total_r = float(all_rs.sum())
    baseline_sharpe = _sharpe_safe(all_rs)

    results: dict[str, Any] = {
        "baseline": {"total_r": round(baseline_total_r, 2), "sharpe": round(baseline_sharpe, 4)},
        "perturbations": {},
    }

    # 1. SL multiplier sweep (approximate: scale SL in the realized R)
    sl_results = []
    for mult in PERTURBATIONS["sl_mult"]:
        rs = []
        for ts in trades_map.values():
            for t in ts:
                r = t["r_multiple"]
                if r >= 0:
                    rs.append(r)
                else:
                    rs.append(r * mult / 1.0)
        arr = np.array(rs)
        sl_results.append({
            "multiplier": mult,
            "total_r": round(float(arr.sum()), 2),
            "sharpe": _sharpe_safe(arr),
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })
    results["perturbations"]["sl_mult"] = sl_results

    # 2. TP multiplier sweep (scale positive R)
    tp_results = []
    for mult in PERTURBATIONS["tp_mult"]:
        rs = []
        for ts in trades_map.values():
            for t in ts:
                r = t["r_multiple"]
                if r > 0:
                    rs.append(r * mult / 1.0)
                else:
                    rs.append(r)
        arr = np.array(rs)
        tp_results.append({
            "multiplier": mult,
            "total_r": round(float(arr.sum()), 2),
            "sharpe": _sharpe_safe(arr),
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })
    results["perturbations"]["tp_mult"] = tp_results

    # 3. Confidence threshold sweep (filter out low-confidence trades)
    conf_results = []
    for thresh in PERTURBATIONS["confidence_threshold"]:
        rs = []
        for ts in trades_map.values():
            for t in ts:
                prob_long = t.get("prob_long", 0.5)
                prob_short = t.get("prob_short", 0.5)
                max_prob = max(prob_long, prob_short)
                if max_prob >= thresh:
                    rs.append(t["r_multiple"])
                else:
                    rs.append(0.0)  # FLAT
        arr = np.array(rs)
        conf_results.append({
            "threshold": thresh,
            "n_trades": int((arr != 0).sum()),
            "total_r": round(float(arr.sum()), 2),
            "sharpe": _sharpe_safe(arr),
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })
    results["perturbations"]["confidence_threshold"] = conf_results

    # 4. Position size
    pos_results = []
    for factor in PERTURBATIONS["position_size_factor"]:
        rs = all_rs * factor
        arr = np.array(rs)
        pos_results.append({
            "factor": factor,
            "total_r": round(float(arr.sum()), 2),
            "sharpe": _sharpe_safe(arr),
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })
    results["perturbations"]["position_size"] = pos_results

    # 5. Session filter (remove worst session)
    session_results = _session_filter(trades_map, baseline_total_r)
    results["perturbations"]["session_filter"] = session_results

    return results


def _session_filter(trades_map: dict[str, list[dict]], baseline_total_r: float) -> list[dict]:
    from collections import defaultdict
    results = []

    # Find worst session portfolio-wide
    session_rs: dict[str, list[float]] = defaultdict(list)
    for ts in trades_map.values():
        for t in ts:
            session = t.get("entry_session", "unknown")
            session_rs[session].append(t["r_multiple"])

    session_avg = {s: float(np.mean(rs)) for s, rs in session_rs.items() if rs}
    worst_session = min(session_avg, key=session_avg.get) if session_avg else None

    # Calculate what happens if we remove the worst session
    if worst_session:
        rs_after = []
        for ts in trades_map.values():
            for t in ts:
                if t.get("entry_session", "unknown") != worst_session:
                    rs_after.append(t["r_multiple"])
        arr = np.array(rs_after)
        results.append({
            "removed_session": worst_session,
            "n_removed": int((sum(1 for ts in trades_map.values() for t in ts if t.get("entry_session") == worst_session))),
            "total_r_after": round(float(arr.sum()), 2),
            "sharpe_after": round(float(arr.mean() / arr.std()), 4) if arr.std() > 0 else 0.0,
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })

    # Also test each session removal independently
    for session in sorted(session_avg.keys()):
        rs_after = []
        removed = 0
        for ts in trades_map.values():
            for t in ts:
                if t.get("entry_session", "unknown") != session:
                    rs_after.append(t["r_multiple"])
                else:
                    removed += 1
        if removed < 10:
            continue
        arr = np.array(rs_after)
        results.append({
            "removed_session": session,
            "n_removed": removed,
            "total_r_after": round(float(arr.sum()), 2),
            "delta_r": round(float(arr.sum() - baseline_total_r), 2),
        })

    return results
