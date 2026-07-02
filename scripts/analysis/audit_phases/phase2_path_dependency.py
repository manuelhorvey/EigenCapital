"""Phase 2 — Path Dependency Analysis.

Reconstructs path quality from existing trade-level metrics (price path is
not stored in the serialized JSON, so we use MAE/MFE/underwater/profitable
data already computed during trade lifecycle reconstruction).

Key metrics from existing TradeRecord fields:
  - candles_underwater / candles_profitable: % of time in each state
  - pnl_crossings: zero-crossings
  - underwater_streak_max / profitable_streak_max: longest streaks
  - largest_intra_reversal: biggest single-candle swing
  - recovered_from_mae: whether price recovered after MAE
  - mae_r / mfe_r: adverse/favorable excursion
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase2_path")


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 2: Path dependency analysis")

    all_metrics: dict[str, list[dict]] = {}
    all_underwater_pct: list[float] = []
    all_profitable_pct: list[float] = []
    all_crossings: list[int] = []
    all_reversals: list[float] = []
    all_recovery_rates: list[bool] = []
    all_mae_r: list[float] = []
    all_mfe_r: list[float] = []

    for asset, trades in trades_map.items():
        asset_metrics = []
        for t in trades:
            duration = max(len(t.get("prices", [])), 1)
            if not hasattr(t.get("prices"), "__len__"):
                duration = max(t.get("candles_underwater", 0) + t.get("candles_profitable", 0), 1)
            underwater = t.get("candles_underwater", 0)
            profitable = t.get("candles_profitable", 0)
            total = underwater + profitable
            pct_underwater = underwater / max(total, 1) * 100
            pct_profitable = profitable / max(total, 1) * 100
            crossings = t.get("pnl_crossings", 0)
            reversal_r = t.get("largest_intra_reversal", 0) / max(
                t.get("entry_price", 1) * max(t.get("atr_pct_entry", 0.01), 0.0001), 0.0001
            )
            recovered = t.get("recovered_from_mae", False)
            mae_r = t.get("mae_r", 0.0)
            mfe_r = t.get("mfe_r", 0.0)

            metrics = {
                "pct_underwater": round(pct_underwater, 1),
                "pct_profitable": round(pct_profitable, 1),
                "zero_crossings": crossings,
                "underwater_streak_max": t.get("underwater_streak_max", 0),
                "profitable_streak_max": t.get("profitable_streak_max", 0),
                "largest_reversal_r": round(reversal_r, 4),
                "recovered_from_mae": recovered,
                "mae_r": round(mae_r, 4),
                "mfe_r": round(mfe_r, 4),
            }
            asset_metrics.append(metrics)

            all_underwater_pct.append(pct_underwater)
            all_profitable_pct.append(pct_profitable)
            all_crossings.append(crossings)
            all_reversals.append(reversal_r)
            all_recovery_rates.append(recovered)
            all_mae_r.append(mae_r)
            all_mfe_r.append(mfe_r)

        if asset_metrics:
            all_metrics[asset] = asset_metrics

    if not all_underwater_pct:
        return {"error": "no data"}

    recovery_bool = [bool(r) for r in all_recovery_rates]
    profitable_with_adverse_count = sum(
        1 for ts in trades_map.values()
        for t in ts
        if t.get("r_multiple", 0) > 0
        and int(t.get("candles_underwater", 0)) > 0
    )
    profitable_count = sum(
        1 for ts in trades_map.values()
        for t in ts
        if t.get("r_multiple", 0) > 0
    )

    def _flat_metrics(key):
        return [m[key] for ms in all_metrics.values() for m in ms]

    return {
        "portfolio": {
            "n_trades": len(all_underwater_pct),
            "avg_pct_underwater": round(float(np.mean(all_underwater_pct)), 1),
            "avg_pct_profitable": round(float(np.mean(all_profitable_pct)), 1),
            "avg_zero_crossings": round(float(np.mean(all_crossings)), 2),
            "avg_largest_reversal_r": round(float(np.mean(all_reversals)), 4),
            "recovery_rate": round(
                sum(recovery_bool) / max(len(recovery_bool), 1) * 100, 1
            ),
            "avg_mae_r": round(float(np.mean(all_mae_r)), 4),
            "avg_mfe_r": round(float(np.mean(all_mfe_r)), 4),
            "pct_profitable_with_adverse_first": round(
                profitable_with_adverse_count / max(profitable_count, 1) * 100, 1
            ),
            "avg_underwater_streak": round(float(np.mean(_flat_metrics("underwater_streak_max"))), 1),
            "avg_profitable_streak": round(float(np.mean(_flat_metrics("profitable_streak_max"))), 1),
        },
    }
