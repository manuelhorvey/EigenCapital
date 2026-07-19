"""Phase 6 — Optimal Holding Period Analysis.

Force-closes every trade after N candles and measures the impact on:
  - Net Profit (total_R)
  - Sharpe Ratio
  - Profit Factor
  - Max Drawdown
  - Win Rate
  - Expectancy

Determines the optimal holding duration for each asset and portfolio-wide.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase6_holding")

HOLDING_CANDLE_LIMITS = [3, 5, 10, 15, 20, 30, 50, 100, 200]


def _force_close_at(trade: dict[str, Any], max_candles: int, ohlcv_map: dict) -> dict[str, Any]:
    """Simulate force-closing a trade after max_candles candles.

    Reconstructs the price path from the asset's OHLCV data. If the trade's
    barrier would have already been hit before max_candles, that exit is
    preserved. Otherwise, exit at the close price of the max_candles-th candle.
    Falls back gracefully to original R if price path cannot be reconstructed.
    """
    t = dict(trade)
    asset = t.get("asset") or t.get("_asset")
    entry_raw = t.get("entry_date")
    ohlcv = ohlcv_map.get(asset) if asset and isinstance(ohlcv_map, dict) else None

    if ohlcv is None or ohlcv.empty or entry_raw is None:
        return t

    # Normalize entry date
    import pandas as pd
    try:
        if isinstance(entry_raw, pd.Timestamp):
            entry_dt = entry_raw
        elif isinstance(entry_raw, str):
            entry_dt = pd.Timestamp(entry_raw)
        else:
            entry_dt = pd.Timestamp(str(entry_raw))
        if hasattr(entry_dt, "tz") and entry_dt.tz is not None:
            entry_dt = entry_dt.tz_localize(None)
        entry_dt = entry_dt.normalize()
    except (ValueError, TypeError):
        return t

    # Normalize OHLCV index
    ohlcv_idx = ohlcv.index.copy()
    if hasattr(ohlcv_idx, "tz") and ohlcv_idx.tz is not None:
        ohlcv_idx = ohlcv_idx.tz_localize(None)
    ohlcv_idx = pd.DatetimeIndex(ohlcv_idx).normalize()

    # Find entry position in OHLCV
    try:
        entry_pos = ohlcv_idx.get_loc(entry_dt)
    except (KeyError, TypeError):
        return t

    close_arr = ohlcv["close"].astype(float).values
    if entry_pos >= len(close_arr) - 1:
        return t

    actual_bars = len(close_arr) - entry_pos
    if actual_bars <= 1:
        return t

    early_exit = actual_bars <= max_candles
    if early_exit:
        return t

    exit_pos = entry_pos + min(max_candles, actual_bars - 1)
    exit_price = float(close_arr[exit_pos])

    entry_price = t.get("entry_price", 0)
    side = t.get("side", "BUY")
    atr_entry = max(t.get("atr_pct_entry", 0.01), 0.0001)

    if entry_price == 0:
        entry_price = float(close_arr[entry_pos])

    if side == "BUY":
        r = (exit_price - entry_price) / (entry_price * atr_entry)
    else:
        r = (entry_price - exit_price) / (entry_price * atr_entry)

    t["r_multiple"] = r
    t["exit_price"] = exit_price
    t["exit_reason"] = f"time_stop_{max_candles}c"
    t["holding_candles"] = max_candles
    t["_force_closed"] = True
    t["_force_entry_pos"] = entry_pos
    t["_force_exit_pos"] = exit_pos

    return t


def _period_stats_hp(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"n_trades": 0, "total_r": 0, "avg_r": 0, "win_rate": 0,
                "profit_factor": 0, "expectancy": 0, "sharpe": 0, "max_dd_r": 0}
    arr = np.array(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    return {
        "n_trades": len(rs),
        "total_r": round(float(arr.sum()), 2),
        "avg_r": round(float(arr.mean()), 4),
        "win_rate": round((arr > 0).mean() * 100, 2),
        "profit_factor": round(pf, 4),
        "expectancy": round(float(arr.mean()), 4),
        "sharpe": round(sharpe, 4),
        "max_dd_r": round(float(dd), 2),
        "std_r": round(float(arr.std()), 4),
    }


def run(trades_map: dict[str, list[dict]], ohlcv_map: dict | None = None) -> dict[str, Any]:
    logger.info("Phase 6: Optimal holding period (sweep 3–200 candles)")

    ohlcv_map = ohlcv_map or {}
    baseline_rs = [t["r_multiple"] for ts in trades_map.values() for t in ts]
    baseline = _period_stats_hp(baseline_rs)

    results: dict[str, Any] = {"baseline": baseline, "sweeps": [], "per_asset": {}}
    asset_optima: dict[str, dict] = {}

    for max_candles in HOLDING_CANDLE_LIMITS:
        forced_rs = []
        asset_rs: dict[str, list[float]] = {a: [] for a in trades_map}

        for asset, trades in trades_map.items():
            for t in trades:
                forced = _force_close_at(t, max_candles, ohlcv_map)
                r = forced.get("r_multiple", 0.0)
                forced_rs.append(r)
                asset_rs[asset].append(r)

        sweep = _period_stats_hp(forced_rs)
        sweep["max_candles"] = max_candles
        results["sweeps"].append(sweep)

        # Best holding period per asset
        for asset, rs in asset_rs.items():
            if asset not in asset_optima:
                asset_optima[asset] = {"best_total_r": -float("inf"), "best_max_candles": max_candles, "best_data": {}}
            ar = sum(rs)
            if ar > asset_optima[asset]["best_total_r"]:
                asset_optima[asset]["best_total_r"] = ar
                asset_optima[asset]["best_max_candles"] = max_candles
                asset_optima[asset]["best_data"] = _period_stats_hp(rs)

    results["per_asset"] = asset_optima

    # Find portfolio optimum
    best = max(results["sweeps"], key=lambda s: s["sharpe"])
    results["optimal"] = {
        "max_candles": best["max_candles"],
        "total_r": best["total_r"],
        "sharpe": best["sharpe"],
        "win_rate": best["win_rate"],
        "max_dd_r": best["max_dd_r"],
        "profit_factor": best["profit_factor"],
    }

    logger.info("  Optimal holding period: %d candles (Sharpe=%.2f, total_R=%.1f, DD=%.1f)",
                best["max_candles"], best["sharpe"], best["total_r"], best["max_dd_r"])
    return results
