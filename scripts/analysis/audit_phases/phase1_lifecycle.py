"""Phase 1 — Enhanced Trade Lifecycle Report.

Builds on the existing trade_lifecycle.py analysis with additional metrics:
  - Time-to-TP distribution
  - Time-to-SL distribution
  - Time-to-peak-MFE
  - Time-from-peak-MFE-to-exit
  - Portfolio-level aggregation with percentiles
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.audit.phase1_lifecycle")


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 1: Enhanced lifecycle report")

    all_rs = []
    all_durations = []
    all_efficiencies = []
    all_mae_r = []
    all_mfe_r = []
    time_to_tp: list[int] = []
    time_to_sl: list[int] = []
    time_to_peak_mfe: list[int] = []
    time_from_peak_to_exit: list[int] = []
    candles_to_first_profit: list[int] = []

    for asset, trades in trades_map.items():
        for t in trades:
            r = t.get("r_multiple", 0.0)
            all_rs.append(r)

            prices = t.get("prices", [])
            duration = len(prices) if hasattr(prices, "__len__") else 1
            all_durations.append(duration)
            all_efficiencies.append(t.get("efficiency_score", 0))
            all_mae_r.append(t.get("mae_r", 0))
            all_mfe_r.append(t.get("mfe_r", 0))

            if t.get("exit_reason") == "tp":
                time_to_tp.append(duration)
            if t.get("exit_reason") == "sl":
                time_to_sl.append(duration)

            candle_of_mfe = t.get("candle_of_mfe", 0)
            time_to_peak_mfe.append(candle_of_mfe)
            time_from_peak_to_exit.append(max(0, duration - candle_of_mfe - 1))

            fp = t.get("candles_to_first_profit")
            if fp is not None:
                candles_to_first_profit.append(fp)

    arr_rs = np.array(all_rs)

    def _pctile(vals, p):
        return float(np.percentile(vals, p)) if vals else 0.0

    def _stats(arr):
        return {
            "mean": round(float(np.mean(arr)), 2) if len(arr) > 0 else 0,
            "median": round(float(np.median(arr)), 2) if len(arr) > 0 else 0,
            "p25": round(_pctile(arr, 25), 2),
            "p75": round(_pctile(arr, 75), 2),
            "p95": round(_pctile(arr, 95), 2),
            "min": round(float(np.min(arr)), 2) if len(arr) > 0 else 0,
            "max": round(float(np.max(arr)), 2) if len(arr) > 0 else 0,
            "std": round(float(np.std(arr)), 2) if len(arr) > 0 else 0,
        }

    return {
        "portfolio": {
            "n_trades": len(all_rs),
            "total_r": round(float(arr_rs.sum()), 2),
            "win_rate": round((arr_rs > 0).mean() * 100, 1),
            "avg_r": round(float(arr_rs.mean()), 4),
            "median_r": round(float(np.median(arr_rs)), 4),
            "sharpe": round(float(arr_rs.mean() / arr_rs.std()), 4) if arr_rs.std() > 0 else 0.0,
        },
        "duration_candles": _stats(all_durations),
        "efficiency": _stats(all_efficiencies),
        "mae_r": _stats(all_mae_r),
        "mfe_r": _stats(all_mfe_r),
        "time_to_tp": _stats(time_to_tp) if time_to_tp else {},
        "time_to_sl": _stats(time_to_sl) if time_to_sl else {},
        "time_to_peak_mfe": _stats(time_to_peak_mfe),
        "time_from_peak_mfe_to_exit": _stats(time_from_peak_to_exit),
        "candles_to_first_profit": _stats(candles_to_first_profit) if candles_to_first_profit else {},
    }
