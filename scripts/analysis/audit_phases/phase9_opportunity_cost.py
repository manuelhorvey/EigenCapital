"""Phase 9 — Opportunity Cost Analysis.

Evaluates every rejected signal (FLAT = no trade taken).
Reconstructs what would have happened if the signal was followed:
  - Would it have won or lost?
  - How much profit was missed?
  - How many losses were avoided?
  - Net filter contribution

This answers whether the gate architecture (sell_only, confidence threshold,
spread gate, etc.) improves or reduces expectancy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.audit.phase9_opportunity")

WALKDIR = Path(__file__).resolve().parent.parent.parent.parent / "walkforward"

from scripts.analysis.audit_phases.phase_data import PORTFOLIO_ASSETS, TP_SL, SELL_ONLY_ASSETS


def _compute_atr_pct(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    h = ohlcv["high"].astype(float)
    l = ohlcv["low"].astype(float)
    c = ohlcv["close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    return atr / c.replace(0, np.nan)


def _simulate_rejected_signal(sig: int, p_long: float, entry_price: float,
                               atr_pct: float, tp_mult: float, sl_mult: float,
                               exit_prices: np.ndarray, exit_highs: np.ndarray,
                               exit_lows: np.ndarray, barrier: int = 20) -> tuple[float, str]:
    """Simulate what would have happened if a FLAT signal was traded."""
    if sig == 0:
        return (0.0, "no_signal")

    sl_price = entry_price * (1 - sl_mult * atr_pct) if sig == 1 else entry_price * (1 + sl_mult * atr_pct)
    tp_price = entry_price * (1 + tp_mult * atr_pct) if sig == 1 else entry_price * (1 - tp_mult * atr_pct)
    risk_gap = abs(entry_price - sl_price)

    for j in range(min(len(exit_prices), barrier)):
        candle_high = exit_highs[j] if j < len(exit_highs) else exit_prices[j]
        candle_low = exit_lows[j] if j < len(exit_lows) else exit_prices[j]

        if sig == 1:
            if candle_high >= tp_price:
                return (tp_mult, "tp")
            if candle_low <= sl_price:
                return (-sl_mult, "sl")
        else:
            if candle_low <= tp_price:
                return (tp_mult, "tp")
            if candle_high >= sl_price:
                return (-sl_mult, "sl")

    exit_price = float(exit_prices[min(len(exit_prices) - 1, barrier - 1)])
    if sig == 1:
        r = (exit_price - entry_price) / risk_gap if risk_gap > 0 else 0
    else:
        r = (entry_price - exit_price) / risk_gap if risk_gap > 0 else 0
    return (r, "barrier")


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 9: Opportunity cost — reconstructing rejected signals")

    results: dict[str, Any] = {"per_asset": {}, "portfolio": {}}
    total_missed_profit = 0.0
    total_saved_losses = 0.0
    total_net_filter = 0.0
    total_rejected = 0

    for asset in sorted(PORTFOLIO_ASSETS.keys()):
        # Load signal parquet
        signal_paths = [
            WALKDIR / f"{asset}_wf_signals_remediation.parquet",
            WALKDIR / f"{asset}_wf_signals.parquet",
        ]
        signal_df = None
        for p in signal_paths:
            if p.exists():
                signal_df = pd.read_parquet(p)
                break

        if signal_df is None:
            continue

        # Load OHLCV
        ticker = PORTFOLIO_ASSETS[asset]
        try:
            from features.data_fetch import fetch_asset_ohlcv
            ohlcv = fetch_asset_ohlcv(ticker)
        except Exception:
            ohlcv = pd.DataFrame()
        if ohlcv.empty:
            continue

        ohlcv = ohlcv.copy()
        if hasattr(ohlcv.index, "tz") and ohlcv.index.tz is not None:
            ohlcv.index = ohlcv.index.tz_localize(None)
        ohlcv.index = pd.DatetimeIndex(ohlcv.index).normalize()

        atr_pct = _compute_atr_pct(ohlcv)
        tp_mult, sl_mult = TP_SL.get(asset, (2.0, 2.0))
        is_sell_only = asset in SELL_ONLY_ASSETS

        rejected_count = 0
        rejected_rs: list[float] = []
        rejected_reasons: list[str] = []

        for idx, row in signal_df.iterrows():
            sig = row["signal"]
            p_long = row.get("p_long", 0.5)
            if sig == 1 and is_sell_only:
                continue

            if sig != 0:
                continue

            rejected_count += 1
            sig_date = pd.Timestamp(idx)
            if hasattr(sig_date, "tz") and sig_date.tz is not None:
                sig_date = sig_date.tz_localize(None)
            sig_date = sig_date.normalize()

            if sig_date < ohlcv.index[0] or sig_date > ohlcv.index[-1]:
                continue
            entry_loc = ohlcv.index.get_indexer([sig_date], method="nearest")[0]
            if entry_loc < 0 or entry_loc >= len(ohlcv):
                continue

            entry_price = float(ohlcv.iloc[entry_loc]["close"])
            atr_entry = float(atr_pct.iloc[entry_loc]) if entry_loc < len(atr_pct) else 0.01
            atr_entry = max(atr_entry, 0.0005)

            barrier = 20
            end_loc = min(entry_loc + barrier + 1, len(ohlcv))
            path = ohlcv.iloc[entry_loc + 1: end_loc]

            if path.empty:
                continue

            exit_prices = path["close"].values
            exit_highs = path["high"].values
            exit_lows = path["low"].values

            # Determine what signal would have been (inverse of whatever the model said)
            # If p_long > 0.5, model wants BUY (signal=1). If p_long < 0.5, model wants SELL (signal=-1)
            # A FLAT signal means something filtered it. Let's simulate both directions.
            # Conservative: simulate the direction the model favored.
            sig_implied = 1 if p_long > 0.5 else -1

            r, reason = _simulate_rejected_signal(sig_implied, p_long, entry_price,
                                                    atr_entry, tp_mult, sl_mult,
                                                    exit_prices, exit_highs, exit_lows, barrier)
            rejected_rs.append(r)
            rejected_reasons.append(reason)

        if rejected_count == 0 or not rejected_rs:
            continue

        rej_arr = np.array(rejected_rs)
        missed_profit = float(rej_arr[rej_arr > 0].sum())
        saved_losses = abs(float(rej_arr[rej_arr < 0].sum()))
        net_filter = float(rej_arr.sum())

        total_missed_profit += missed_profit
        total_saved_losses += saved_losses
        total_net_filter += net_filter
        total_rejected += rejected_count

        unique_reasons, reason_counts = np.unique(rejected_reasons, return_counts=True)
        reason_dist = dict(zip(unique_reasons, reason_counts))

        results["per_asset"][asset] = {
            "n_rejected": rejected_count,
            "n_would_have_won": int((rej_arr > 0).sum()),
            "n_would_have_lost": int((rej_arr < 0).sum()),
            "missed_profit_r": round(missed_profit, 2),
            "saved_losses_r": round(saved_losses, 2),
            "net_filter_contribution_r": round(net_filter, 2),
            "avg_rejected_r": round(float(rej_arr.mean()), 4),
            "rejected_wr": round((rej_arr > 0).mean() * 100, 1),
            "reason_distribution": reason_dist,
        }

        logger.info("  %s: %d rejected, net filter = %.1fR (missed %.1fR / saved %.1fR)",
                     asset, rejected_count, net_filter, missed_profit, saved_losses)

    results["portfolio"] = {
        "n_total_rejected": total_rejected,
        "total_missed_profit_r": round(total_missed_profit, 2),
        "total_saved_losses_r": round(total_saved_losses, 2),
        "total_net_filter_contribution_r": round(total_net_filter, 2),
        "filter_verdict": "BENEFICIAL" if total_net_filter < 0 else "HARMFUL" if total_net_filter > 0 else "NEUTRAL",
    }

    return results
