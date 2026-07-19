"""Phase 8 — Entry Quality Analysis.

For each trade, measures entry quality using:
  - Distance from local 10-bar high/low (as % of ATR)
  - Entry ATR position (vol percentile vs recent history)
  - Trend alignment (entry direction vs 20-bar MA slope)
  - Immediate adverse excursion (first-candle MAE)
  - Entry timing quality (early/late relative to signal trigger)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase8_entry")

WALKDIR = None  # Will be set in run()


def compute_entry_quality(trades_map: dict[str, list[dict]], ohlcv_map: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Compute entry quality metrics for every trade."""
    results: dict[str, Any] = {"per_asset": {}, "portfolio": {}}
    all_mae_per_bar: list[float] = []
    all_first_candle_mae: list[float] = []
    all_trend_alignment: list[bool] = []

    for asset, trades in trades_map.items():
        ohlcv = ohlcv_map.get(asset)
        if ohlcv is None or ohlcv.empty:
            logger.warning("  No OHLCV for %s — skipping entry quality", asset)
            continue

        asset_metrics = _asset_entry_quality(asset, trades, ohlcv)
        if asset_metrics:
            for t in asset_metrics.get("trades", []):
                all_mae_per_bar.append(t.get("mae_per_bar", 0))
                all_first_candle_mae.append(t.get("first_candle_mae_r", 0))
                all_trend_alignment.append(t.get("trend_aligned", False))
            results["per_asset"][asset] = asset_metrics

    # Portfolio aggregate
    results["portfolio"] = {
        "n_trades": len(all_mae_per_bar),
        "avg_mae_per_bar_r": round(float(np.mean(all_mae_per_bar)), 4) if all_mae_per_bar else 0.0,
        "avg_first_candle_mae_r": round(float(np.mean(all_first_candle_mae)), 4) if all_first_candle_mae else 0.0,
        "pct_trend_aligned": round(sum(all_trend_alignment) / max(len(all_trend_alignment), 1) * 100, 1),
        "entries_against_trend": sum(1 for a in all_trend_alignment if not a),
    }

    return results


def _asset_entry_quality(asset: str, trades: list[dict], ohlcv: pd.DataFrame) -> dict:
    """Entry quality for a single asset's trades."""
    if ohlcv.empty:
        return {}

    ohlcv_index = ohlcv.index
    if hasattr(ohlcv_index, "tz") and ohlcv_index.tz is not None:
        ohlcv_index = ohlcv_index.tz_localize(None)

    close = ohlcv["close"].astype(float)
    high = ohlcv["high"].astype(float)
    low = ohlcv["low"].astype(float)

    # Precompute rolling metrics
    atr_series = _compute_atr(ohlcv)
    ma20 = close.rolling(20).mean()
    ma20_slope = ma20.diff(5) / ma20.shift(5) * 100  # slope over 5 bars
    local_high_10 = high.rolling(10).max()
    local_low_10 = low.rolling(10).min()

    trade_metrics = []
    for t in trades:
        entry_dt = t.get("entry_date")
        if entry_dt is None:
            continue
        try:
            if isinstance(entry_dt, pd.Timestamp):
                dt = entry_dt
            elif isinstance(entry_dt, str):
                dt = pd.Timestamp(entry_dt)
            else:
                continue
        except (ValueError, TypeError):
            continue

        if hasattr(dt, "tz") and dt.tz is not None:
            dt = dt.tz_localize(None)
        dt = pd.Timestamp(dt).normalize()

        if dt not in ohlcv_index:
            loc = ohlcv_index.get_indexer([dt], method="nearest")[0]
            if loc < 0:
                continue
            dt = ohlcv_index[loc]

        loc = ohlcv_index.get_loc(dt)
        entry_price = float(close.iloc[loc])
        atr_val = float(atr_series.iloc[loc]) if loc < len(atr_series) else 0.01
        side = t.get("side", "BUY")

        # Distance from local high/low in ATR units
        local_high_val = float(local_high_10.iloc[loc]) if loc < len(local_high_10) else entry_price
        local_low_val = float(local_low_10.iloc[loc]) if loc < len(local_low_10) else entry_price
        dist_from_high = abs(entry_price - local_high_val) / max(atr_val * entry_price, 0.0001)
        dist_from_low = abs(entry_price - local_low_val) / max(atr_val * entry_price, 0.0001)

        # ATR percentile (vol regime)
        atr_percentile = float((atr_series < atr_val).mean() * 100) if len(atr_series) > 0 else 50.0

        # Trend alignment
        slope_val = float(ma20_slope.iloc[loc]) if loc < len(ma20_slope) else 0.0
        trend_bullish = slope_val > 0
        trend_aligned = (side == "BUY" and trend_bullish) or (side == "SELL" and not trend_bullish)

        # Immediate adverse excursion (first candle MAE)
        if hasattr(t.get("prices"), "__len__"):
            prices = t["prices"]
            if len(prices) > 1:
                if side == "BUY":
                    first_move = float(prices[0]) - entry_price if hasattr(prices, "__getitem__") else 0
                else:
                    first_move = entry_price - float(prices[0]) if hasattr(prices, "__getitem__") else 0
                first_candle_mae_r = abs(min(first_move, 0)) / max(atr_val * entry_price, 0.0001)
            else:
                first_candle_mae_r = 0.0
        else:
            first_candle_mae_r = 0.0

        # MAE per bar
        mae = t.get("mae_r", 0.0)
        duration = max(len(t.get("prices", [])), 1)
        mae_per_bar = mae / duration

        trade_metrics.append({
            "side": side,
            "entry_price": entry_price,
            "dist_from_high_atr": round(dist_from_high, 4),
            "dist_from_low_atr": round(dist_from_low, 4),
            "atr_percentile": round(atr_percentile, 1),
            "ma20_slope_pct": round(slope_val, 4),
            "trend_aligned": trend_aligned,
            "first_candle_mae_r": round(first_candle_mae_r, 4),
            "mae_per_bar": round(mae_per_bar, 4),
            "r": round(t.get("r_multiple", 0), 4),
        })

    if not trade_metrics:
        return {}

    aligned = [m for m in trade_metrics if m["trend_aligned"]]
    misaligned = [m for m in trade_metrics if not m["trend_aligned"]]

    return {
        "n_trades": len(trade_metrics),
        "avg_dist_from_high_atr": round(float(np.mean([m["dist_from_high_atr"] for m in trade_metrics])), 4),
        "avg_dist_from_low_atr": round(float(np.mean([m["dist_from_low_atr"] for m in trade_metrics])), 4),
        "avg_atr_percentile_at_entry": round(float(np.mean([m["atr_percentile"] for m in trade_metrics])), 1),
        "pct_trend_aligned": round(len(aligned) / len(trade_metrics) * 100, 1),
        "avg_first_candle_mae_r": round(float(np.mean([m["first_candle_mae_r"] for m in trade_metrics])), 4),
        "avg_mae_per_bar_r": round(float(np.mean([m["mae_per_bar"] for m in trade_metrics])), 4),
        "trend_aligned_avg_r": round(float(np.mean([m["r"] for m in aligned])), 4) if aligned else 0,
        "trend_misaligned_avg_r": round(float(np.mean([m["r"] for m in misaligned])), 4) if misaligned else 0,
        "n_misaligned": len(misaligned),
        "trades": trade_metrics,
    }


def _compute_atr(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    h = ohlcv["high"].astype(float)
    l = ohlcv["low"].astype(float)
    c = ohlcv["close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    return atr / c.replace(0, np.nan)


def run(trades_map: dict[str, list[dict]], ohlcv_map: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    logger.info("Phase 8: Entry quality analysis")
    if ohlcv_map is None:
        logger.warning("  No OHLCV map provided — cannot compute entry quality")
        return {"error": "no_ohlcv"}
    return compute_entry_quality(trades_map, ohlcv_map)
