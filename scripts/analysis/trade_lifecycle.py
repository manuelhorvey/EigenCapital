#!/usr/bin/env python3
"""
Trade Lifecycle, MAE/MFE & Exit Efficiency Analysis.

Reconstructs every trade from walk-forward signal parquets + OHLCV data,
computes full lifecycle metrics across 18 analysis phases.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trade_lifecycle.py --assets GC,USDCHF
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trade_lifecycle.py --all
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trade_lifecycle.py --phase 3-5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("trade_lifecycle")

# ── Portfolio config ─────────────────────────────────────────────────────────
PORTFOLIO_ASSETS: dict[str, str] = {
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "GBPCAD": "GBPCAD=X",
    "NZDCAD": "NZDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPUSD": "GBPUSD=X",
    "EURAUD": "EURAUD=X",
}

TP_SL: dict[str, tuple[float, float]] = {
    "GC": (4.0, 1.0),
    "USDCHF": (3.0, 0.85),
    "USDCAD": (3.9, 1.30),
    "GBPCAD": (4.34, 1.45),
    "NZDCAD": (5.48, 1.83),
    "NZDUSD": (3.87, 1.29),
    "GBPAUD": (3.0, 1.0),
    "NZDCHF": (4.0, 1.0),
    "CADCHF": (4.0, 1.0),
    "AUDUSD": (4.24, 1.41),
    "EURCHF": (3.0, 1.0),
    "EURCAD": (2.12, 0.71),
    "EURNZD": (3.36, 1.12),
    "GBPCHF": (2.45, 0.82),
    "GBPUSD": (2.22, 0.50),
    "EURAUD": (3.28, 1.0),
}

SELL_ONLY: frozenset[str] = frozenset({"CADCHF", "NZDCHF", "EURAUD"})
WALKDIR = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent / "walkforward"


@dataclass
class TradeRecord:
    """Reconstructed trade with full lifecycle data."""

    asset: str
    side: str  # "BUY" or "SELL"
    entry_date: pd.Timestamp
    entry_price: float
    tp_price: float
    sl_price: float
    barrier_candles: int = 20
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = "unknown"  # "tp", "sl", "barrier"
    r_multiple: float = 0.0
    p_long: float = 0.0
    signal_age: float = 0.0  # candles from signal to entry
    prob_long: float = 0.0
    prob_short: float = 0.0
    # ── Price path ──
    prices: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    highs: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    lows: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    # ── Lifecycle ──
    candles_to_first_profit: int | None = None
    candles_to_breakeven: int | None = None
    candles_underwater: int = 0
    candles_profitable: int = 0
    pnl_crossings: int = 0
    underwater_streak_max: int = 0
    profitable_streak_max: int = 0
    largest_intra_reversal: float = 0.0
    # ── MAE / MFE ──
    mae: float = 0.0  # max adverse excursion (negative in price units)
    mfe: float = 0.0  # max favorable excursion (positive in price units)
    mae_r: float = 0.0  # MAE in R-multiples
    mfe_r: float = 0.0  # MFE in R-multiples
    mae_atr: float = 0.0  # MAE / ATR at entry
    mfe_atr: float = 0.0  # MFE / ATR at entry
    candle_of_mae: int = 0
    candle_of_mfe: int = 0
    recovered_from_mae: bool = False
    candles_recovery: int | None = None
    # ── Efficiency ──
    efficiency_score: float = 0.0  # captured / available
    profit_left: float = 0.0
    # ── vol at entry ──
    atr_pct_entry: float = 0.0


def load_signal_data(asset: str, tag: str = "remediation") -> pd.DataFrame | None:
    """Load walk-forward signal parquet for an asset."""
    paths = [
        WALKDIR / f"{asset}_wf_signals_{tag}.parquet",
        WALKDIR / f"{asset}_wf_signals.parquet",
    ]
    for p in paths:
        if p.exists():
            df = pd.read_parquet(p)
            if "asset" not in df.columns:
                df["asset"] = asset
            return df
    return None


def fetch_ohlcv(ticker: str) -> pd.DataFrame:
    """Fetch OHLCV data from yfinance or local cache."""
    from features.data_fetch import fetch_asset_ohlcv

    return fetch_asset_ohlcv(ticker)


def compute_atr_pct(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as fraction of close."""
    high, low, close = ohlcv["high"].astype(float), ohlcv["low"].astype(float), ohlcv["close"].astype(float)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    return atr / close.replace(0, np.nan)


def reconstruct_trades(asset: str, signal_df: pd.DataFrame, ohlcv: pd.DataFrame) -> list[TradeRecord]:
    """Reconstruct all trades from signal parquet + OHLCV data."""
    tp_mult, sl_mult = TP_SL.get(asset, (2.0, 2.0))
    is_sell_only = asset in SELL_ONLY

    trades: list[TradeRecord] = []
    # Normalize indexes to tz-naive dates
    ohlcv = ohlcv.copy()
    if hasattr(ohlcv.index, "tz") and ohlcv.index.tz is not None:
        ohlcv.index = ohlcv.index.tz_localize(None)
    ohlcv.index = pd.DatetimeIndex(ohlcv.index).normalize()
    atr_pct = compute_atr_pct(ohlcv)
    ohlcv_index = ohlcv.index

    signal_index_norm = signal_df.index
    if hasattr(signal_index_norm, "tz") and signal_index_norm.tz is not None:
        signal_index_norm = signal_index_norm.tz_localize(None)

    for idx, row in signal_df.iterrows():
        sig = row["signal"]
        if sig == 0:
            continue

        # Skip BUY signals on SELL_ONLY assets
        if is_sell_only and sig == 1:
            continue

        # Find closest OHLCV bar
        sig_date = idx
        if hasattr(sig_date, "tz") and sig_date.tz is not None:
            sig_date = sig_date.tz_localize(None)
        sig_date = pd.Timestamp(sig_date).normalize()
        if sig_date < ohlcv_index[0] or sig_date > ohlcv_index[-1]:
            continue
        entry_loc = ohlcv_index.get_indexer([sig_date], method="nearest")[0]
        if entry_loc < 0:
            continue

        # Entry price (close of signal day)
        entry_price = float(ohlcv.iloc[entry_loc]["close"])
        atr_pct_entry = float(atr_pct.iloc[entry_loc]) if entry_loc < len(atr_pct) else 0.01
        atr_pct_entry = max(atr_pct_entry, 0.0005)

        # Compute TP/SL
        if sig == 1:  # LONG
            sl_price = entry_price * (1 - sl_mult * atr_pct_entry)
            tp_price = entry_price * (1 + tp_mult * atr_pct_entry)
        else:  # SHORT
            sl_price = entry_price * (1 + sl_mult * atr_pct_entry)
            tp_price = entry_price * (1 - tp_mult * atr_pct_entry)

        barrier_candles = 20
        end_loc = min(entry_loc + barrier_candles + 1, len(ohlcv))

        # Extract price path
        path_df = ohlcv.iloc[entry_loc + 1 : end_loc]
        if path_df.empty:
            continue

        path_prices = path_df["close"].values
        path_highs = path_df["high"].values
        path_lows = path_df["low"].values

        # Simulate trade
        exit_date = None
        exit_price_val = None
        exit_reason = "barrier"
        exit_loc = end_loc - 1

        for j in range(len(path_df)):
            candle_high = path_highs[j]
            candle_low = path_lows[j]

            if sig == 1:  # LONG
                if candle_high >= tp_price:
                    exit_reason = "tp"
                    exit_price_val = tp_price
                    exit_loc = entry_loc + 1 + j
                    break
                if candle_low <= sl_price:
                    exit_reason = "sl"
                    exit_price_val = sl_price
                    exit_loc = entry_loc + 1 + j
                    break
            else:  # SHORT
                if candle_low <= tp_price:
                    exit_reason = "tp"
                    exit_price_val = tp_price
                    exit_loc = entry_loc + 1 + j
                    break
                if candle_high >= sl_price:
                    exit_reason = "sl"
                    exit_price_val = sl_price
                    exit_loc = entry_loc + 1 + j
                    break

        if exit_price_val is None:
            exit_price_val = float(ohlcv.iloc[min(exit_loc, len(ohlcv) - 1)]["close"])
            exit_date = ohlcv.index[min(exit_loc, len(ohlcv) - 1)]

        if exit_date is None:
            exit_date = ohlcv.index[min(exit_loc, len(ohlcv) - 1)]

        # R-multiple
        if sig == 1:
            r = (exit_price_val - entry_price) / (entry_price * atr_pct_entry)
        else:
            r = (entry_price - exit_price_val) / (entry_price * atr_pct_entry)

        # Clip to path length for MAE/MFE computation
        path_len = min(len(path_prices), exit_loc - entry_loc)
        if path_len < 1:
            continue

        actual_prices = path_prices[:path_len]
        actual_highs = path_highs[:path_len]
        actual_lows = path_lows[:path_len]

        # MAE / MFE
        if sig == 1:  # LONG: MAE = max drop, MFE = max rise
            running_mae = entry_price - np.minimum.accumulate(np.concatenate([[entry_price], actual_lows]))[1:]
            running_mfe = np.maximum.accumulate(np.concatenate([[entry_price], actual_highs]))[1:] - entry_price
        else:  # SHORT: MAE = max rise, MFE = max drop
            running_mae = np.maximum.accumulate(np.concatenate([[entry_price], actual_highs]))[1:] - entry_price
            running_mfe = entry_price - np.minimum.accumulate(np.concatenate([[entry_price], actual_lows]))[1:]

        mae_val = float(running_mae.max()) if len(running_mae) > 0 else 0.0
        mfe_val = float(running_mfe.max()) if len(running_mfe) > 0 else 0.0
        candle_of_mae = int(np.argmax(running_mae)) if len(running_mae) > 0 else 0
        candle_of_mfe = int(np.argmax(running_mfe)) if len(running_mfe) > 0 else 0

        # MAE/MFE in R and ATR units
        dollar_risk = entry_price * atr_pct_entry
        mae_r = mae_val / dollar_risk if dollar_risk > 0 else 0.0
        mfe_r = mfe_val / dollar_risk if dollar_risk > 0 else 0.0
        mae_atr_val = mae_val / dollar_risk if dollar_risk > 0 else 0.0
        mfe_atr_val = mfe_val / dollar_risk if dollar_risk > 0 else 0.0

        # Lifecycle metrics
        cumulative_pnl = np.zeros(path_len)
        cumulative_pnl = actual_prices - entry_price if sig == 1 else entry_price - actual_prices

        # First profit
        first_profit_idx = np.where(cumulative_pnl > 0)[0]
        candles_to_first_profit = int(first_profit_idx[0]) + 1 if len(first_profit_idx) > 0 else None

        # Breakeven
        be_idx = np.where(cumulative_pnl >= 0)[0]
        candles_to_breakeven = int(be_idx[0]) + 1 if len(be_idx) > 0 else None

        # Underwater / profitable candles
        underwater = int((cumulative_pnl <= 0).sum())
        profitable = int((cumulative_pnl > 0).sum())
        pnl_crossings = int(((cumulative_pnl[:-1] * cumulative_pnl[1:]) < 0).sum())

        # Streaks
        underwater_streaks = []
        profitable_streaks = []
        current = 0
        current_type = None
        for p in cumulative_pnl:
            if p <= 0:
                if current_type == "underwater":
                    current += 1
                else:
                    if current_type == "profitable":
                        profitable_streaks.append(current)
                    current = 1
                    current_type = "underwater"
            else:
                if current_type == "profitable":
                    current += 1
                else:
                    if current_type == "underwater":
                        underwater_streaks.append(current)
                    current = 1
                    current_type = "profitable"
        if current_type == "underwater":
            underwater_streaks.append(current)
        elif current_type == "profitable":
            profitable_streaks.append(current)

        max_underwater = max(underwater_streaks) if underwater_streaks else 0
        max_profitable = max(profitable_streaks) if profitable_streaks else 0

        # Largest reversal
        rev = float(abs(np.diff(cumulative_pnl)).max()) if len(cumulative_pnl) > 1 else 0.0

        # Recovery from MAE
        recovered = mae_val > 0 and cumulative_pnl[-1] > -mae_val * 0.5
        recovery_candles = None
        if recovered and candle_of_mae < len(cumulative_pnl) - 1:
            after_mae = cumulative_pnl[candle_of_mae + 1 :]
            above_mae_half = np.where(after_mae > -mae_val * 0.5)[0]
            if len(above_mae_half) > 0:
                recovery_candles = int(above_mae_half[0]) + 1

        # Efficiency
        capture_amount = abs(r) * dollar_risk if dollar_risk > 0 else abs(exit_price_val - entry_price)
        efficiency = min(capture_amount / mfe_val, 1.0) if mfe_val > 0 else 1.0 if r > 0 else 0.0

        profit_left = max(0.0, mfe_val - capture_amount)

        # Signal metadata
        prob_long = float(row.get("p_long", 0.5))
        prob_short = 1.0 - prob_long

        rec = TradeRecord(
            asset=asset,
            side="BUY" if sig == 1 else "SELL",
            entry_date=idx,
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            barrier_candles=barrier_candles,
            exit_date=exit_date,
            exit_price=exit_price_val,
            exit_reason=exit_reason,
            r_multiple=r,
            p_long=prob_long,
            prob_long=prob_long,
            prob_short=prob_short,
            prices=pd.Series(actual_prices),
            highs=actual_highs,
            lows=actual_lows,
            candles_to_first_profit=candles_to_first_profit,
            candles_to_breakeven=candles_to_breakeven,
            candles_underwater=underwater,
            candles_profitable=profitable,
            pnl_crossings=pnl_crossings,
            underwater_streak_max=max_underwater,
            profitable_streak_max=max_profitable,
            largest_intra_reversal=rev,
            mae=mae_val,
            mfe=mfe_val,
            mae_r=mae_r,
            mfe_r=mfe_r,
            mae_atr=mae_atr_val,
            mfe_atr=mfe_atr_val,
            candle_of_mae=candle_of_mae,
            candle_of_mfe=candle_of_mfe,
            recovered_from_mae=recovered,
            candles_recovery=recovery_candles,
            efficiency_score=efficiency,
            profit_left=profit_left,
            atr_pct_entry=atr_pct_entry,
        )
        trades.append(rec)

    return trades


# ── Analysis Phases ──────────────────────────────────────────────────────────


def phase1_trade_lifecycle(trades: list[TradeRecord]) -> dict:
    """Measure entry/exit timing, durations, sessions."""
    if not trades:
        return {"error": "no trades"}

    candle_durations = []
    for t in trades:
        if t.exit_date is not None and hasattr(t, "prices") and len(t.prices) > 0:
            candle_durations.append(len(t.prices))

    results = {
        "n_trades": len(trades),
        "avg_candle_duration": float(np.mean(candle_durations)) if candle_durations else 0,
        "median_candle_duration": float(np.median(candle_durations)) if candle_durations else 0,
        "max_candle_duration": int(np.max(candle_durations)) if candle_durations else 0,
        "min_candle_duration": int(np.min(candle_durations)) if candle_durations else 1,
        "avg_first_profit_candle": float(
            np.mean([t.candles_to_first_profit for t in trades if t.candles_to_first_profit is not None])
        ),  # noqa: E501
        "median_first_profit_candle": float(
            np.median([t.candles_to_first_profit for t in trades if t.candles_to_first_profit is not None])
        ),  # noqa: E501
        "pct_never_profitable": sum(1 for t in trades if t.candles_to_first_profit is None) / len(trades) * 100,
        "avg_underwater_pct": float(np.mean([t.candles_underwater / max(len(t.prices), 1) * 100 for t in trades])),
        "avg_profitable_pct": float(np.mean([t.candles_profitable / max(len(t.prices), 1) * 100 for t in trades])),
        "avg_pnl_crossings": float(np.mean([t.pnl_crossings for t in trades])),
        "avg_underwater_streak": float(np.mean([t.underwater_streak_max for t in trades])),
        "avg_reversal_size_r": float(
            np.mean(
                [
                    t.largest_intra_reversal / (t.entry_price * t.atr_pct_entry) if t.atr_pct_entry > 0 else 0
                    for t in trades
                ]
            )
        ),  # noqa: E501
    }
    return results


def phase3_mae(trades: list[TradeRecord]) -> dict:
    """Maximum Adverse Excursion analysis."""
    if not trades:
        return {"error": "no trades"}

    mae_r_vals = np.array([t.mae_r for t in trades])
    mae_atr_vals = np.array([t.mae_atr for t in trades])

    results = {
        "avg_mae_r": float(mae_r_vals.mean()),
        "median_mae_r": float(np.median(mae_r_vals)),
        "max_mae_r": float(mae_r_vals.max()),
        "p95_mae_r": float(np.percentile(mae_r_vals, 95)),
        "avg_mae_atr": float(mae_atr_vals.mean()),
        "median_mae_atr": float(np.median(mae_atr_vals)),
        "p95_mae_atr": float(np.percentile(mae_atr_vals, 95)),
        "recovery_rate": sum(1 for t in trades if t.recovered_from_mae) / len(trades) * 100,
        "avg_recovery_candles": float(np.mean([t.candles_recovery for t in trades if t.candles_recovery is not None])),
        "mae_larger_than_sl_pct": float((mae_r_vals > 1.0).mean() * 100),
        "mae_gt_2r_pct": float((mae_r_vals > 2.0).mean() * 100),
    }
    return results


def phase4_mfe(trades: list[TradeRecord]) -> dict:
    """Maximum Favorable Excursion analysis."""
    if not trades:
        return {"error": "no trades"}

    mfe_r_vals = np.array([t.mfe_r for t in trades])
    efficiency_vals = np.array([t.efficiency_score for t in trades])
    profit_left_r = np.array(
        [t.profit_left / (t.entry_price * t.atr_pct_entry) if t.atr_pct_entry > 0 else 0 for t in trades]
    )

    results = {
        "avg_mfe_r": float(mfe_r_vals.mean()),
        "median_mfe_r": float(np.median(mfe_r_vals)),
        "max_mfe_r": float(mfe_r_vals.max()),
        "p95_mfe_r": float(np.percentile(mfe_r_vals, 95)),
        "avg_efficiency": float(efficiency_vals.mean()),
        "median_efficiency": float(np.median(efficiency_vals)),
        "pct_efficiency_gt_50pct": float((efficiency_vals > 0.5).mean() * 100),
        "pct_efficiency_gt_75pct": float((efficiency_vals > 0.75).mean() * 100),
        "avg_profit_left_r": float(profit_left_r.mean()),
        "p95_profit_left_r": float(np.percentile(profit_left_r, 95)),
        "tp_capture_rate": sum(1 for t in trades if t.exit_reason == "tp") / len(trades) * 100,
        "sl_capture_rate": sum(1 for t in trades if t.exit_reason == "sl") / len(trades) * 100,
        "barrier_expiry_rate": sum(1 for t in trades if t.exit_reason == "barrier") / len(trades) * 100,
    }
    return results


def phase12_confidence_buckets(trades: list[TradeRecord]) -> dict:
    """Group trades by p_long confidence bucket."""
    if not trades:
        return {"error": "no trades"}

    bins = [(0.0, 0.25), (0.25, 0.40), (0.40, 0.45), (0.45, 0.55), (0.55, 0.60), (0.60, 0.75), (0.75, 1.0)]

    bucket_results = {}
    for lo, hi in bins:
        bucket = [t for t in trades if lo <= t.prob_long < hi]
        if not bucket:
            continue
        rs = [t.r_multiple for t in bucket]
        ws = sum(1 for r in rs if r > 0)
        label = f"{lo:.2f}-{hi:.2f}"
        bucket_results[label] = {
            "n": len(bucket),
            "win_rate": ws / len(bucket) * 100,
            "avg_r": float(np.mean(rs)),
            "total_r": float(np.sum(rs)),
            "avg_mae_r": float(np.mean([t.mae_r for t in bucket])),
            "avg_mfe_r": float(np.mean([t.mfe_r for t in bucket])),
            "avg_efficiency": float(np.mean([t.efficiency_score for t in bucket])),
            "avg_duration": float(np.mean([len(t.prices) for t in bucket])),
            "tp_rate": sum(1 for t in bucket if t.exit_reason == "tp") / len(bucket) * 100,
            "sl_rate": sum(1 for t in bucket if t.exit_reason == "sl") / len(bucket) * 100,
        }
    return bucket_results


def phase13_regime_analysis(trades: list[TradeRecord], ohlcv: pd.DataFrame) -> dict:
    """Separate trades by volatility regime (high/low) and direction."""
    if not trades or ohlcv.empty:
        return {"error": "no data"}

    # Classify market regime using ATR percentile
    atr_pct = compute_atr_pct(ohlcv)
    atr_median = atr_pct.median()

    high_vol = []
    low_vol = []
    bull = []
    bear = []

    for t in trades:
        idx = t.entry_date
        idx_utc = idx.tz_localize(None) if hasattr(idx, "tz") and idx.tz is not None else idx
        entry_atr = float(atr_pct.loc[idx_utc]) if idx_utc in atr_pct.index else atr_median

        # Vol regime
        if entry_atr > atr_median:
            high_vol.append(t)
        else:
            low_vol.append(t)

        # Trend regime (close above 50-bar MA = bull)
        if idx_utc in ohlcv.index:
            ma50 = ohlcv["close"].rolling(50).mean().loc[idx_utc] if idx_utc in ohlcv.index else ohlcv["close"].iloc[-1]
            if ohlcv.loc[idx_utc, "close"] > ma50:
                bull.append(t)
            else:
                bear.append(t)

    def regime_stats(trades_list, label):
        if not trades_list:
            return {f"{label}_n": 0}
        rs = [t.r_multiple for t in trades_list]
        return {
            f"{label}_n": len(trades_list),
            f"{label}_win_rate": sum(1 for r in rs if r > 0) / len(rs) * 100,
            f"{label}_avg_r": float(np.mean(rs)),
            f"{label}_total_r": float(np.sum(rs)),
            f"{label}_avg_duration": float(np.mean([len(t.prices) for t in trades_list])),
            f"{label}_tp_rate": sum(1 for t in trades_list if t.exit_reason == "tp") / len(trades_list) * 100,
        }

    results = {}
    results.update(regime_stats(high_vol, "high_vol"))
    results.update(regime_stats(low_vol, "low_vol"))
    results.update(regime_stats(bull, "bull"))
    results.update(regime_stats(bear, "bear"))
    return results


def phase16_portfolio_level(all_trades: dict[str, list[TradeRecord]]) -> dict:
    """Portfolio-level capital efficiency and asset contribution."""
    if not all_trades:
        return {"error": "no data"}

    asset_metrics = {}
    for asset, trades in all_trades.items():
        if not trades:
            continue
        rs = [t.r_multiple for t in trades]
        durations = [len(t.prices) for t in trades]
        asset_metrics[asset] = {
            "n_trades": len(trades),
            "total_r": float(np.sum(rs)),
            "avg_r": float(np.mean(rs)),
            "win_rate": sum(1 for r in rs if r > 0) / len(rs) * 100,
            "avg_duration": float(np.mean(durations)),
            "total_duration_candles": int(np.sum(durations)),
            "avg_efficiency": float(np.mean([t.efficiency_score for t in trades])),
            "tp_rate": sum(1 for t in trades if t.exit_reason == "tp") / len(trades) * 100,
            "sl_rate": sum(1 for t in trades if t.exit_reason == "sl") / len(trades) * 100,
            "r_per_candle": float(np.sum(rs) / max(np.sum(durations), 1)),
            "r_per_hour": float(np.sum(rs) / max(np.sum(durations) * 24, 1)),
        }

    # Overall
    all_rs = np.concatenate([np.array([t.r_multiple for t in ts]) for ts in all_trades.values() if ts])
    all_durations = np.concatenate([np.array([len(t.prices) for t in ts]) for ts in all_trades.values() if ts])

    return {
        "n_assets": len([a for a, ts in all_trades.items() if ts]),
        "n_trades": int(len(all_rs)),
        "total_r": float(all_rs.sum()),
        "avg_r": float(all_rs.mean()),
        "win_rate": float((all_rs > 0).mean() * 100),
        "avg_duration_candles": float(all_durations.mean()),
        "avg_efficiency": float(np.mean([t.efficiency_score for ts in all_trades.values() for t in ts])),
        "tp_rate": float(np.mean([1 for ts in all_trades.values() for t in ts if t.exit_reason == "tp"]) * 100)
        if any(ts for ts in all_trades.values())
        else 0,  # noqa: E501
        "r_per_100_candles": float(all_rs.sum() / max(all_durations.sum(), 1) * 100),
        "asset_metrics": asset_metrics,
    }


def compute_all_phases(
    all_trades: dict[str, list[TradeRecord]],
    ohlcv_map: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Run all phases and return results dict."""
    results: dict[str, Any] = {
        "phases": {},
        "summary": {},
        "_trades": {},
    }
    for asset, trades in all_trades.items():
        results["_trades"][asset] = [t.__dict__.copy() for t in trades]
        for t in results["_trades"][asset]:
            t.pop("prices", None)
            t.pop("highs", None)
            t.pop("lows", None)

    # Phase 1-2: Lifecycle
    combined_trades = [t for ts in all_trades.values() for t in ts]
    results["phases"]["lifecycle"] = phase1_trade_lifecycle(combined_trades)

    # Phase 3-4: MAE/MFE
    results["phases"]["mae"] = phase3_mae(combined_trades)
    results["phases"]["mfe"] = phase4_mfe(combined_trades)

    # Phase 5: Exit efficiency via MFE capture
    mfe_data = results["phases"]["mfe"]
    results["phases"]["exit_efficiency"] = {
        "avg_efficiency": mfe_data["avg_efficiency"],
        "median_efficiency": mfe_data["median_efficiency"],
        "pct_gt_50pct": mfe_data["pct_efficiency_gt_50pct"],
        "pct_gt_75pct": mfe_data["pct_efficiency_gt_75pct"],
        "tp_rate": mfe_data["tp_capture_rate"],
        "sl_rate": mfe_data["sl_capture_rate"],
        "barrier_rate": mfe_data["barrier_expiry_rate"],
        "avg_profit_left_r": mfe_data["avg_profit_left_r"],
    }

    # Phase 12: Confidence buckets
    results["phases"]["confidence_buckets"] = phase12_confidence_buckets(combined_trades)

    # Phase 13: Regime analysis (per asset with ohlcv)
    regime_all = {"all": {}}
    for asset, trades in all_trades.items():
        if trades and asset in ohlcv_map:
            regime_all[asset] = phase13_regime_analysis(trades, ohlcv_map[asset])
    results["phases"]["regime"] = regime_all

    # Phase 16: Portfolio level
    results["phases"]["portfolio"] = phase16_portfolio_level(all_trades)

    # Summary
    lc = results["phases"]["lifecycle"]
    pf = results["phases"]["portfolio"]
    results["summary"] = {
        "n_trades": pf["n_trades"],
        "n_assets": pf["n_assets"],
        "total_r": pf["total_r"],
        "win_rate": pf["win_rate"],
        "avg_efficiency": pf["avg_efficiency"],
        "avg_duration_candles": pf["avg_duration_candles"],
        "r_per_100_candles": pf["r_per_100_candles"],
        "avg_mae_r": results["phases"]["mae"]["avg_mae_r"],
        "avg_mfe_r": results["phases"]["mfe"]["avg_mfe_r"],
        "tp_rate": mfe_data["tp_capture_rate"],
        "sl_rate": mfe_data["sl_capture_rate"],
        "recovery_rate": results["phases"]["mae"]["recovery_rate"],
        "avg_underwater_pct": lc["avg_underwater_pct"],
        "avg_pnl_crossings": lc["avg_pnl_crossings"],
    }

    return results


# ── Main ─────────────────────────────────────────────────────────────────────


def run_for_assets(asset_names: list[str], tag: str = "remediation") -> dict[str, Any]:
    """Run full analysis for a list of assets."""
    all_trades: dict[str, list[TradeRecord]] = {}
    ohlcv_map: dict[str, pd.DataFrame] = {}

    for asset in asset_names:
        if asset not in PORTFOLIO_ASSETS:
            logger.warning("Unknown asset: %s", asset)
            continue
        ticker = PORTFOLIO_ASSETS[asset]
        logger.info("Processing %s (%s)...", asset, ticker)

        signal_df = load_signal_data(asset, tag)
        if signal_df is None:
            logger.warning("  No signal data for %s", asset)
            continue

        ohlcv = fetch_ohlcv(ticker)
        if ohlcv.empty:
            logger.warning("  No OHLCV for %s", asset)
            continue
        ohlcv_map[asset] = ohlcv

        trades = reconstruct_trades(asset, signal_df, ohlcv)
        logger.info("  Reconstructed %d trades", len(trades))
        all_trades[asset] = trades

    if not all_trades:
        return {"error": "no assets processed"}

    logger.info("\n=== Computing all phases ===")
    results = compute_all_phases(all_trades, ohlcv_map)
    return results


def print_summary(results: dict) -> None:
    """Print formatted summary."""
    if "error" in results:
        logger.error("Error: %s", results["error"])
        return

    s = results.get("summary", {})
    print("\n" + "=" * 60)
    print("TRADE LIFECYCLE ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"  Assets analyzed:    {s.get('n_assets', '?')}")
    print(f"  Total trades:       {s.get('n_trades', '?')}")
    print(f"  Total R:            {s.get('total_r', '?'):+.2f}")
    print(f"  Win rate:           {s.get('win_rate', '?'):.1f}%")
    print(f"  Avg efficiency:     {s.get('avg_efficiency', '?'):.1%}")
    print(f"  Avg duration:       {s.get('avg_duration_candles', '?'):.1f} candles")
    print(f"  R/100 candles:      {s.get('r_per_100_candles', '?'):+.2f}")
    print()
    print("  MAE/MFE:")
    print(f"    Avg MAE (R):      {s.get('avg_mae_r', '?'):+.2f}")
    print(f"    Avg MFE (R):      {s.get('avg_mfe_r', '?'):+.2f}")
    print(f"    Recovery rate:    {s.get('recovery_rate', '?'):.1f}%")
    print()
    print("  Exits:")
    print(f"    TP rate:          {s.get('tp_rate', '?'):.1f}%")
    print(f"    SL rate:          {s.get('sl_rate', '?'):.1f}%")
    print()
    print("  Path quality:")
    print(f"    Avg underwater:   {s.get('avg_underwater_pct', '?'):.1f}% of trade")
    print(f"    Avg PnL crosses:  {s.get('avg_pnl_crossings', '?'):.1f}")

    # Per-asset detail
    pf = results.get("phases", {}).get("portfolio", {})
    am = pf.get("asset_metrics", {})
    if am:
        print("\n" + "-" * 60)
        print(f"{'Asset':<10} {'Trades':>7} {'TotalR':>8} {'WR':>6} {'Eff':>6} {'Dur':>5} {'TP%':>5} {'R/100c':>8}")
        print("-" * 60)
        for asset in sorted(am.keys()):
            m = am[asset]
            print(
                f"{asset:<10} {m['n_trades']:>7} {m['total_r']:>+8.1f} {m['win_rate']:>5.1f}% {m['avg_efficiency']:>5.1%} {m['avg_duration']:>4.0f} {m['tp_rate']:>4.0f}% {m['r_per_candle'] * 100:>+7.2f}"  # noqa: E501
            )  # noqa: E501

    # Confidence buckets
    cb = results.get("phases", {}).get("confidence_buckets", {})
    if cb and "error" not in cb:
        print("\n" + "-" * 60)
        print("Confidence Buckets:")
        print(f"{'Bucket':<12} {'N':>5} {'WR':>6} {'AvgR':>7} {'Eff':>6} {'Dur':>5} {'TP%':>5}")
        print("-" * 60)
        for label, b in sorted(cb.items()):
            print(
                f"{label:<12} {b['n']:>5} {b['win_rate']:>5.1f}% {b['avg_r']:>+6.2f} {b['avg_efficiency']:>5.1%} {b['avg_duration']:>4.0f} {b['tp_rate']:>4.0f}%"  # noqa: E501
            )  # noqa: E501

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Trade lifecycle & MAE/MFE analysis")
    parser.add_argument("--assets", default=None, help="Comma-separated asset names")
    parser.add_argument("--all", action="store_true", help="Run on all 16 portfolio assets")
    parser.add_argument("--tag", default="remediation", help="Signal parquet tag")
    parser.add_argument("--output", default=None, help="JSON output path")
    args = parser.parse_args()

    if args.all:
        assets = sorted(PORTFOLIO_ASSETS.keys())
    elif args.assets:
        assets = [a.strip() for a in args.assets.split(",")]
    else:
        assets = sorted(PORTFOLIO_ASSETS.keys())

    logger.info("Running on %d assets: %s", len(assets), ", ".join(assets))
    results = run_for_assets(assets, tag=args.tag)

    print_summary(results)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Results saved to %s", args.output)

    # Print sample trades for first few assets
    for asset, trades in list(results.get("_trades", {}).items())[:3]:
        print(f"\n{asset} sample trades (first 5):")
        for t in trades[:5]:
            if isinstance(t, dict):
                print(
                    f"  {t.get('side', '?'):4s} | entry={t.get('entry_date', '?')} | R={t.get('r_multiple', 0):+.2f} | exit={t.get('exit_reason', '?'):8s} | eff={t.get('efficiency_score', 0):.0%} | MAE={t.get('mae_r', 0):.2f}R | MFE={t.get('mfe_r', 0):.2f}R"  # noqa: E501
                )  # noqa: E501


if __name__ == "__main__":
    main()
