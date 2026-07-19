#!/usr/bin/env python3
"""
Re-entry Policy Simulation Engine.

Reconstructs trade timelines from walk-forward signal parquets + OHLCV data
and simulates three position-entry policies:

  Policy A (baseline): max 1 position per asset, no same-side re-entry
  Policy B:            max 2 positions per asset, same-side re-entry (guarded: min_confidence=0.55, min_reentry_r=0.5)
  Policy C:            max 3 positions per asset, same-side re-entry (guarded)
  Policy D:            max 2 positions per asset, same-side re-entry (unguarded — matches live engine)

All policies enforce cross-side flipping (close existing, open opposite).
No production code is modified — this is a research-only analysis.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_simulation.py --all
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_simulation.py --assets GC,USDCHF
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from paper_trading.position.adaptive_exit import AdaptiveExitEngine, AdaptiveExitResult

sys.path.insert(0, Path(__file__).resolve().parent.parent.parent)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reentry_simulation")

# ── Reuse infrastructure from trade_lifecycle ─────────────────────────────
from scripts.analysis.trade_lifecycle import (
    PORTFOLIO_ASSETS,
    SELL_ONLY,
    TP_SL,
    WALKDIR,
    TradeRecord,
    compute_atr_pct,
    fetch_ohlcv,
    load_signal_data,
)

# ── Re-entry event record ─────────────────────────────────────────────────


@dataclass
class ReentryEvent:
    """A re-entry opportunity and whether the policy allowed it."""

    asset: str
    signal_date: str
    signal_side: str  # "BUY" / "SELL"
    p_long: float
    allowed: bool
    blocked_reason: str | None
    candidate_r: float
    candidate_exit_reason: str
    candidate_mfe_r: float
    existing_positions: int
    existing_side: str | None
    existing_r_since_entry: float  # MFE of oldest trade at this point
    policy: str  # "A" | "B" | "C"


# ── Policy parameters ─────────────────────────────────────────────────────


@dataclass
class ReentryPolicy:
    """Configuration for a re-entry policy simulation."""

    name: str = "B"
    max_positions: int = 2
    min_confidence: float = 0.55
    min_reentry_r: float = 0.5
    same_side_allowed: bool = True
    cross_side_allowed: bool = True
    require_independent_signal: bool = True
    min_bars_between_reentries: int = 3


POLICIES: dict[str, ReentryPolicy] = {
    "A": ReentryPolicy(
        name="A",
        max_positions=1,
        same_side_allowed=False,
        min_confidence=0.0,
        min_reentry_r=0.0,
    ),
    "B": ReentryPolicy(
        name="B",
        max_positions=2,
        same_side_allowed=True,
        min_confidence=0.55,
        min_reentry_r=0.5,
    ),
    "C": ReentryPolicy(
        name="C",
        max_positions=3,
        same_side_allowed=True,
        min_confidence=0.55,
        min_reentry_r=0.5,
    ),
    "D": ReentryPolicy(
        name="D",
        max_positions=2,
        same_side_allowed=True,
        min_confidence=0.0,
        min_reentry_r=0.0,
    ),
}


# ── Active position tracker ───────────────────────────────────────────────


@dataclass
class ActivePosition:
    """Tracks a single open position during simulation."""

    trade_idx: int
    side: str
    entry_date: datetime
    entry_price: float
    sl_price: float
    tp_price: float
    barrier_candles: int
    p_long: float
    atr_pct_entry: float
    exit_date: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    r_multiple: float | None = None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    efficiency_score: float = 0.0
    candles_open: int = 0
    effective_sl: float | None = None
    adaptive_engine: AdaptiveExitEngine | None = None


# ── Core policy simulation ────────────────────────────────────────────────


def _active_to_trade(asset: str, pos: ActivePosition) -> TradeRecord:
    """Convert an ActivePosition to a TradeRecord once closed."""
    return TradeRecord(
        asset=asset,
        side=pos.side,
        entry_date=pos.entry_date,
        entry_price=pos.entry_price,
        tp_price=pos.tp_price,
        sl_price=pos.sl_price,
        barrier_candles=pos.barrier_candles,
        exit_date=pos.exit_date or pos.entry_date,
        exit_price=pos.exit_price or pos.entry_price,
        exit_reason=pos.exit_reason or "barrier",
        r_multiple=pos.r_multiple or 0.0,
        p_long=pos.p_long,
        prob_long=pos.p_long,
        prob_short=1.0 - pos.p_long,
        mae_r=pos.mae_r,
        mfe_r=pos.mfe_r,
        atr_pct_entry=pos.atr_pct_entry,
    )


def simulate_one_asset(
    asset: str,
    signal_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    policy: ReentryPolicy,
    trailing: bool = False,
) -> tuple[list[TradeRecord], list[ReentryEvent]]:
    """Simulate a re-entry policy for one asset.

    Returns (all_trades, reentry_events).
    all_trades — every TradeRecord that would have been opened under this policy.
    reentry_events — every re-entry opportunity and whether it was blocked.
    """
    tp_mult, sl_mult = TP_SL.get(asset, (2.0, 2.0))
    is_sell_only = asset in SELL_ONLY

    # Prepare OHLCV — ensure tz-naive normalized dates
    ohlcv = ohlcv.copy()
    if hasattr(ohlcv.index, "tz") and ohlcv.index.tz is not None:
        ohlcv.index = ohlcv.index.tz_localize(None)
    ohlcv.index = pd.DatetimeIndex(ohlcv.index).normalize()
    atr_pct = compute_atr_pct(ohlcv)
    ohlcv_index = ohlcv.index

    # Normalise signal index to tz-naive
    signal_df = signal_df.copy()
    if hasattr(signal_df.index, "tz") and signal_df.index.tz is not None:
        signal_df.index = signal_df.index.tz_localize(None)
    signal_df.index = pd.DatetimeIndex(signal_df.index).normalize()

    active: list[ActivePosition] = []
    all_trades: list[TradeRecord] = []
    reentry_events: list[ReentryEvent] = []
    flat_days_cache: dict[str, int] = {}  # track last trade idx per side for spacing
    trade_counter = 0

    def _collect_closed(closed_list: list[ActivePosition]) -> None:
        """Convert closed positions to TradeRecords and add to all_trades."""
        for p in closed_list:
            all_trades.append(_active_to_trade(asset, p))

    check_exits_fn = _check_exits_trailing if trailing else _check_exits

    for idx, row in signal_df.iterrows():
        sig = int(row["signal"])
        sig_date = idx
        if sig == 0:
            closed = check_exits_fn(active, ohlcv, ohlcv_index, sig_date)
            _collect_closed(closed)
            continue

        if is_sell_only and sig == 1:
            continue

        side = "BUY" if sig == 1 else "SELL"

        if sig_date < ohlcv_index[0] or sig_date > ohlcv_index[-1]:
            continue
        entry_loc = ohlcv_index.get_indexer([sig_date], method="nearest")[0]
        if entry_loc < 0:
            continue

        entry_price = float(ohlcv.iloc[entry_loc]["close"])
        atr_pct_entry = float(atr_pct.iloc[entry_loc]) if entry_loc < len(atr_pct) else 0.01
        atr_pct_entry = max(atr_pct_entry, 0.0005)

        if sig == 1:
            sl_price = entry_price * (1 - sl_mult * atr_pct_entry)
            tp_price = entry_price * (1 + tp_mult * atr_pct_entry)
        else:
            sl_price = entry_price * (1 + sl_mult * atr_pct_entry)
            tp_price = entry_price * (1 - tp_mult * atr_pct_entry)

        barrier_candles = 20
        end_loc = min(entry_loc + barrier_candles + 1, len(ohlcv))
        path_df = ohlcv.iloc[entry_loc + 1 : end_loc]

        closed = check_exits_fn(active, ohlcv, ohlcv_index, sig_date)

        existing_side = active[0].side if active else None
        existing_count = len(active)
        p_long = float(row.get("p_long", 0.5))

        candidate_r, candidate_reason, candidate_mfe = _simulate_candidate_trade(
            sig,
            entry_price,
            sl_price,
            tp_price,
            entry_loc,
            end_loc,
            ohlcv,
            barrier_candles,
            atr_pct_entry,
        )

        existing_mfe_now = 0.0
        if active:
            existing_mfe_now = _compute_mfe_at_date(active[0], ohlcv, ohlcv_index, sig_date)

        can_enter = True
        blocked_reason = None

        if existing_side is not None and side != existing_side:
            if policy.cross_side_allowed:
                for pos in active:
                    _force_close_position(pos, ohlcv, ohlcv_index, sig_date)
                    all_trades.append(_active_to_trade(asset, pos))
                active.clear()
            else:
                can_enter = False
                blocked_reason = "cross_side_blocked"
        elif existing_side is not None and side == existing_side:
            if existing_count >= policy.max_positions:
                can_enter = False
                blocked_reason = f"max_positions_{policy.max_positions}"
            elif not policy.same_side_allowed:
                can_enter = False
                blocked_reason = "same_side_blocked"
            elif p_long < policy.min_confidence and side == "BUY":
                can_enter = False
                blocked_reason = "confidence_below_threshold"
            elif (1 - p_long) < policy.min_confidence and side == "SELL":
                can_enter = False
                blocked_reason = "confidence_below_threshold"
            elif existing_mfe_now < policy.min_reentry_r:
                can_enter = False
                blocked_reason = f"existing_mfe_{existing_mfe_now:.2f}_below_{policy.min_reentry_r}"

        reentry_events.append(
            ReentryEvent(
                asset=asset,
                signal_date=str(sig_date),
                signal_side=side,
                p_long=float(p_long),
                allowed=can_enter,
                blocked_reason=blocked_reason,
                candidate_r=candidate_r,
                candidate_exit_reason=candidate_reason,
                candidate_mfe_r=candidate_mfe,
                existing_positions=existing_count,
                existing_side=existing_side,
                existing_r_since_entry=existing_mfe_now,
                policy=policy.name,
            )
        )

        if not can_enter:
            continue

        trade_counter += 1
        pos = ActivePosition(
            trade_idx=trade_counter,
            side=side,
            entry_date=sig_date,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            barrier_candles=barrier_candles,
            p_long=p_long,
            atr_pct_entry=atr_pct_entry,
        )
        active.append(pos)
        if not path_df.empty:
            _update_position_metrics(pos, ohlcv, ohlcv_index, entry_loc, end_loc)

    # Close remaining active positions at end
    last_date = signal_df.index[-1] if len(signal_df.index) > 0 else ohlcv_index[-1]
    for pos in list(active):
        _force_close_position(pos, ohlcv, ohlcv_index, last_date)
        all_trades.append(_active_to_trade(asset, pos))
    active.clear()

    return all_trades, reentry_events


def _check_exits(
    active: list[ActivePosition],
    ohlcv: pd.DataFrame,
    ohlcv_index: pd.DatetimeIndex,
    current_date: pd.Timestamp,
) -> list[ActivePosition]:
    """Check and close any positions hit TP/SL or expired by current_date.
    Returns the list of closed positions."""
    current_ts = pd.Timestamp(current_date).tz_localize(None)
    closed: list[ActivePosition] = []
    to_remove = []
    for i, pos in enumerate(active):
        # Find price data between entry and current date to check TP/SL
        entry_ts = pd.Timestamp(pos.entry_date).tz_localize(None)
        entry_loc = ohlcv_index.get_indexer([entry_ts], method="nearest")[0]
        current_loc = ohlcv_index.get_indexer([current_ts], method="nearest")[0]
        if entry_loc >= 0 and current_loc > entry_loc:
            path_df = ohlcv.iloc[entry_loc + 1 : current_loc + 1]
            if not path_df.empty:
                for j in range(len(path_df)):
                    ch = float(path_df.iloc[j]["high"])
                    cl = float(path_df.iloc[j]["low"])
                    if pos.side == "BUY":
                        if ch >= pos.tp_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.tp_price
                            pos.exit_reason = "tp"
                            atr = max(pos.atr_pct_entry, 0.0005)
                            pos.r_multiple = (pos.exit_price - pos.entry_price) / (pos.entry_price * atr)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                        if cl <= pos.sl_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.sl_price
                            pos.exit_reason = "sl"
                            atr = max(pos.atr_pct_entry, 0.0005)
                            pos.r_multiple = (pos.exit_price - pos.entry_price) / (pos.entry_price * atr)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                    else:
                        if cl <= pos.tp_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.tp_price
                            pos.exit_reason = "tp"
                            atr = max(pos.atr_pct_entry, 0.0005)
                            pos.r_multiple = (pos.entry_price - pos.exit_price) / (pos.entry_price * atr)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                        if ch >= pos.sl_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.sl_price
                            pos.exit_reason = "sl"
                            atr = max(pos.atr_pct_entry, 0.0005)
                            pos.r_multiple = (pos.entry_price - pos.exit_price) / (pos.entry_price * atr)
                            closed.append(pos)
                            to_remove.append(i)
                            break

        # If not closed by TP/SL, check barrier expiry
        if i not in to_remove:
            candles_open = _candles_between(entry_ts, current_ts, ohlcv_index)
            if candles_open > pos.barrier_candles:
                _force_close_position(pos, ohlcv, ohlcv_index, current_ts)
                closed.append(pos)
                to_remove.append(i)

    for i in reversed(to_remove):
        active.pop(i)
    return closed


def _check_exits_trailing(
    active: list[ActivePosition],
    ohlcv: pd.DataFrame,
    ohlcv_index: pd.DatetimeIndex,
    current_date: pd.Timestamp,
    adaptive_config: dict | None = None,
) -> list[ActivePosition]:
    """Like _check_exits but integrates AdaptiveExitEngine trailing logic.

    Between each candle check, updates trailing SL via AdaptiveExitEngine.
    Trades close at adaptive trailing SL, not the fixed sl_price.
    """
    if adaptive_config is None:
        adaptive_config = {
            "be_lock_r": 0.5,
            "trail_activation_r": 0.8,
            "trail_retrace_pct": 0.50,
            "max_hold_candles": 20,
            "time_decay_start": 10,
        }
    current_ts = pd.Timestamp(current_date).tz_localize(None)
    closed: list[ActivePosition] = []
    to_remove = []
    for i, pos in enumerate(active):
        entry_ts = pd.Timestamp(pos.entry_date).tz_localize(None)
        entry_loc = ohlcv_index.get_indexer([entry_ts], method="nearest")[0]
        current_loc = ohlcv_index.get_indexer([current_ts], method="nearest")[0]

        # Initialise adaptive engine on first call
        if pos.adaptive_engine is None:
            pos.adaptive_engine = AdaptiveExitEngine()
        engine = pos.adaptive_engine
        vol = max(pos.atr_pct_entry, 0.0005)

        # Use effective_sl (possibly tightened by trailing), fall back to sl_price
        use_sl = pos.effective_sl if pos.effective_sl is not None else pos.sl_price

        if entry_loc >= 0 and current_loc > entry_loc:
            path_df = ohlcv.iloc[entry_loc + 1 : current_loc + 1]
            if not path_df.empty:
                for j in range(len(path_df)):
                    ch = float(path_df.iloc[j]["high"])
                    cl = float(path_df.iloc[j]["low"])
                    bars_open = j + 1

                    # 1. Check TP/SL first against the ADAPTIVE SL from BEFORE this candle
                    #    (the effective_sl was computed from previous candles' data)
                    if pos.side == "BUY":
                        if ch >= pos.tp_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.tp_price
                            pos.exit_reason = "tp"
                            pos.r_multiple = (pos.exit_price - pos.entry_price) / (pos.entry_price * vol)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                        if cl <= use_sl:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = max(cl, use_sl)
                            pos.exit_reason = "trailing_sl" if pos.effective_sl is not None else "sl"
                            pos.r_multiple = (pos.exit_price - pos.entry_price) / (pos.entry_price * vol)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                    else:
                        if cl <= pos.tp_price:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = pos.tp_price
                            pos.exit_reason = "tp"
                            pos.r_multiple = (pos.entry_price - pos.exit_price) / (pos.entry_price * vol)
                            closed.append(pos)
                            to_remove.append(i)
                            break
                        if ch >= use_sl:
                            pos.exit_date = ohlcv_index[min(entry_loc + 1 + j, len(ohlcv_index) - 1)]
                            pos.exit_price = min(ch, use_sl)
                            pos.exit_reason = "trailing_sl" if pos.effective_sl is not None else "sl"
                            pos.r_multiple = (pos.entry_price - pos.exit_price) / (pos.entry_price * vol)
                            closed.append(pos)
                            to_remove.append(i)
                            break

                    # 2. Position survived this candle — update adaptive exit for NEXT candle
                    if pos.side == "BUY":
                        engine.compute(
                            side="long",
                            entry_price=pos.entry_price,
                            current_price=ch,
                            current_sl=use_sl,
                            vol_at_entry=vol,
                            bars_since_entry=bars_open,
                            config=adaptive_config,
                        )
                    else:
                        engine.compute(
                            side="short",
                            entry_price=pos.entry_price,
                            current_price=cl,
                            current_sl=use_sl,
                            vol_at_entry=vol,
                            bars_since_entry=bars_open,
                            config=adaptive_config,
                        )

                    # Compute new effective SL for future candles
                    trail_sl = engine._best_price
                    if trail_sl is not None:
                        new_eff_sl = (
                            pos.entry_price * (1 + 0.5 * vol)
                            if pos.side == "BUY"
                            else pos.entry_price * (1 - 0.5 * vol)
                        )
                        if pos.side == "BUY" and engine._trail_activated and trail_sl > pos.entry_price:
                            retrace = trail_sl - adaptive_config.get("trail_retrace_pct", 0.50) * (
                                trail_sl - pos.entry_price
                            )
                            new_eff_sl = max(new_eff_sl, retrace)
                        elif pos.side == "SELL" and engine._trail_activated and trail_sl < pos.entry_price:
                            retrace = trail_sl + adaptive_config.get("trail_retrace_pct", 0.50) * (
                                pos.entry_price - trail_sl
                            )
                            new_eff_sl = min(new_eff_sl, retrace)
                        if engine._breakeven_activated:
                            be_sl = pos.entry_price
                            new_eff_sl = max(new_eff_sl, be_sl) if pos.side == "BUY" else min(new_eff_sl, be_sl)
                        if (pos.side == "BUY" and new_eff_sl > use_sl) or (pos.side == "SELL" and new_eff_sl < use_sl):
                            pos.effective_sl = new_eff_sl
                            use_sl = new_eff_sl

        # Barrier expiry (unchanged)
        if i not in to_remove:
            candles_open = _candles_between(entry_ts, current_ts, ohlcv_index)
            if candles_open > pos.barrier_candles:
                _force_close_position(pos, ohlcv, ohlcv_index, current_ts)
                closed.append(pos)
                to_remove.append(i)

    for i in reversed(to_remove):
        active.pop(i)
    return closed


def _candles_between(start: datetime | pd.Timestamp, end: pd.Timestamp | datetime, index: pd.DatetimeIndex) -> int:
    """Count trading days between two dates."""
    start_ts = pd.Timestamp(start).tz_localize(None)
    end_ts = pd.Timestamp(end).tz_localize(None)
    mask = (index >= start_ts) & (index <= end_ts)
    return int(mask.sum())


def _simulate_candidate_trade(
    sig: int,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    entry_loc: int,
    end_loc: int,
    ohlcv: pd.DataFrame,
    barrier_candles: int,
    atr_pct_entry: float,
) -> tuple[float, str, float]:
    """Simulate a trade to determine its R-multiple outcome and MFE."""
    path_df = ohlcv.iloc[entry_loc + 1 : end_loc]
    if path_df.empty:
        return 0.0, "barrier", 0.0

    path_highs = path_df["high"].values
    path_lows = path_df["low"].values

    max_mfe = 0.0
    for j in range(len(path_df)):
        candle_high = path_highs[j]
        candle_low = path_lows[j]

        if sig == 1:
            mfe = (candle_high - entry_price) / (entry_price * atr_pct_entry)
            if candle_high >= tp_price:
                r_tp = (tp_price - entry_price) / (entry_price * atr_pct_entry)
                return r_tp, "tp", max(mfe, r_tp)
            if candle_low <= sl_price:
                return (sl_price - entry_price) / (entry_price * atr_pct_entry), "sl", max(mfe, 0.0)
        else:
            mfe = (entry_price - candle_low) / (entry_price * atr_pct_entry)
            if candle_low <= tp_price:
                return (
                    (entry_price - tp_price) / (entry_price * atr_pct_entry),
                    "tp",
                    max(mfe, (entry_price - tp_price) / (entry_price * atr_pct_entry)),
                )
            if candle_high >= sl_price:
                return (entry_price - sl_price) / (entry_price * atr_pct_entry), "sl", max(mfe, 0.0)
        max_mfe = max(max_mfe, mfe)

    exit_price = float(ohlcv.iloc[min(end_loc - 1, len(ohlcv) - 1)]["close"])
    r = (
        (exit_price - entry_price) / (entry_price * atr_pct_entry)
        if sig == 1
        else (entry_price - exit_price) / (entry_price * atr_pct_entry)
    )
    return r, "barrier", max_mfe


def _compute_mfe_at_date(
    pos: ActivePosition,
    ohlcv: pd.DataFrame,
    ohlcv_index: pd.DatetimeIndex,
    date: pd.Timestamp | datetime,
) -> float:
    """Compute MFE (max favorable excursion) up to a given date."""
    date_ts = pd.Timestamp(date).tz_localize(None)
    entry_ts = pd.Timestamp(pos.entry_date).tz_localize(None)
    entry_loc = ohlcv_index.get_indexer([entry_ts], method="nearest")[0]
    date_loc = ohlcv_index.get_indexer([date_ts], method="nearest")[0]
    if entry_loc < 0 or date_loc <= entry_loc:
        return 0.0

    path_df = ohlcv.iloc[entry_loc + 1 : date_loc + 1]
    if path_df.empty:
        return 0.0

    if pos.side == "BUY":
        best = path_df["high"].max()
        return max(0.0, (best - pos.entry_price) / (pos.entry_price * max(pos.atr_pct_entry, 0.0005)))
    else:
        best = path_df["low"].min()
        return max(0.0, (pos.entry_price - best) / (pos.entry_price * max(pos.atr_pct_entry, 0.0005)))


def _update_position_metrics(
    pos: ActivePosition,
    ohlcv: pd.DataFrame,
    ohlcv_index: pd.DatetimeIndex,
    entry_loc: int,
    end_loc: int,
) -> None:
    """Pre-compute full-path metrics for a position (via integers, no timestamp issues)."""
    path_df = ohlcv.iloc[entry_loc + 1 : min(end_loc, len(ohlcv))]
    if path_df.empty:
        return

    path_highs = path_df["high"].values
    path_lows = path_df["low"].values
    atr = max(pos.atr_pct_entry, 0.0005)

    if pos.side == "BUY":
        pos.mfe_r = max(0.0, (path_highs.max() - pos.entry_price) / (pos.entry_price * atr))
        pos.mae_r = max(0.0, (pos.entry_price - path_lows.min()) / (pos.entry_price * atr))
    else:
        pos.mfe_r = max(0.0, (pos.entry_price - path_lows.min()) / (pos.entry_price * atr))
        pos.mae_r = max(0.0, (path_highs.max() - pos.entry_price) / (pos.entry_price * atr))


def _force_close_position(
    pos: ActivePosition,
    ohlcv: pd.DataFrame,
    ohlcv_index: pd.DatetimeIndex,
    exit_date: pd.Timestamp | datetime,
) -> None:
    """Force-close a position at a given date's close price."""
    exit_ts = pd.Timestamp(exit_date).tz_localize(None)
    exit_loc = ohlcv_index.get_indexer([exit_ts], method="nearest")[0]
    if exit_loc < 0 or exit_loc >= len(ohlcv):
        exit_loc = len(ohlcv) - 1
    pos.exit_date = ohlcv_index[exit_loc]
    pos.exit_price = float(ohlcv.iloc[exit_loc]["close"])
    atr = max(pos.atr_pct_entry, 0.0005)
    if pos.side == "BUY":
        pos.r_multiple = (pos.exit_price - pos.entry_price) / (pos.entry_price * atr)
    else:
        pos.r_multiple = (pos.entry_price - pos.exit_price) / (pos.entry_price * atr)
    pos.exit_reason = "barrier"


# ── Overlap analysis (Question 1) ─────────────────────────────────────────


def analyze_overlap_opportunities(
    asset: str,
    signal_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
) -> dict:
    """Analyze how frequently re-entry opportunities occur.

    Returns stats on: total signals, signals while position active,
    same-side overlaps, cross-side overlaps.
    """
    tp_mult, sl_mult = TP_SL.get(asset, (2.0, 2.0))
    is_sell_only = asset in SELL_ONLY

    ohlcv = ohlcv.copy()
    if hasattr(ohlcv.index, "tz") and ohlcv.index.tz is not None:
        ohlcv.index = ohlcv.index.tz_localize(None)
    ohlcv.index = pd.DatetimeIndex(ohlcv.index).normalize()
    atr_pct = compute_atr_pct(ohlcv)
    ohlcv_index = ohlcv.index

    signal_df = signal_df.copy()
    if hasattr(signal_df.index, "tz") and signal_df.index.tz is not None:
        signal_df.index = signal_df.index.tz_localize(None)
    signal_df.index = pd.DatetimeIndex(signal_df.index).normalize()

    active: list[ActivePosition] = []
    total_signals = 0
    signals_while_active = 0
    same_side_opportunities = 0
    cross_side_opportunities = 0
    profitable_reentry_candidates = 0
    losing_reentry_candidates = 0
    reentry_candidate_r: list[float] = []
    reentry_candidate_p_long: list[float] = []

    for idx, row in signal_df.iterrows():
        sig = int(row["signal"])
        sig_date = idx
        if sig == 0:
            _check_exits(active, ohlcv, ohlcv_index, sig_date)
            continue

        if is_sell_only and sig == 1:
            continue

        total_signals += 1
        side = "BUY" if sig == 1 else "SELL"

        _check_exits(active, ohlcv, ohlcv_index, sig_date)

        existing_side = active[0].side if active else None

        if existing_side is not None:
            signals_while_active += 1
            if side == existing_side:
                same_side_opportunities += 1
            else:
                cross_side_opportunities += 1

            # Simulate this candidate
            entry_loc = ohlcv_index.get_indexer([sig_date], method="nearest")[0]
            if entry_loc >= 0:
                entry_price = float(ohlcv.iloc[entry_loc]["close"])
                atr_pct_entry = float(atr_pct.iloc[entry_loc]) if entry_loc < len(atr_pct) else 0.01
                atr_pct_entry = max(atr_pct_entry, 0.0005)
                sl_p = (
                    entry_price * (1 - sl_mult * atr_pct_entry)
                    if sig == 1
                    else entry_price * (1 + sl_mult * atr_pct_entry)
                )
                tp_p = (
                    entry_price * (1 + tp_mult * atr_pct_entry)
                    if sig == 1
                    else entry_price * (1 - tp_mult * atr_pct_entry)
                )
                end_loc = min(entry_loc + 21, len(ohlcv))
                r, reason, mfe = _simulate_candidate_trade(
                    sig, entry_price, sl_p, tp_p, entry_loc, end_loc, ohlcv, 20, atr_pct_entry
                )
                reentry_candidate_r.append(r)
                reentry_candidate_p_long.append(float(row.get("p_long", 0.5)))
                if r > 0:
                    profitable_reentry_candidates += 1
                else:
                    losing_reentry_candidates += 1

        # Enter the trade (baseline — open it for the active tracking)
        if existing_side is None or side != existing_side:
            entry_loc = ohlcv_index.get_indexer([sig_date], method="nearest")[0]
            if entry_loc < 0:
                continue
            entry_price = float(ohlcv.iloc[entry_loc]["close"])
            atr_pct_entry = float(atr_pct.iloc[entry_loc]) if entry_loc < len(atr_pct) else 0.01
            atr_pct_entry = max(atr_pct_entry, 0.0005)
            sl_p = (
                entry_price * (1 - sl_mult * atr_pct_entry) if sig == 1 else entry_price * (1 + sl_mult * atr_pct_entry)
            )
            tp_p = (
                entry_price * (1 + tp_mult * atr_pct_entry) if sig == 1 else entry_price * (1 - tp_mult * atr_pct_entry)
            )
            pos = ActivePosition(
                trade_idx=len(active),
                side=side,
                entry_date=sig_date,
                entry_price=entry_price,
                sl_price=sl_p,
                tp_price=tp_p,
                barrier_candles=20,
                p_long=float(row.get("p_long", 0.5)),
                atr_pct_entry=atr_pct_entry,
            )

            # Check for cross-side flip
            if existing_side is not None and side != existing_side:
                for p in active:
                    _force_close_position(p, ohlcv, ohlcv_index, sig_date)
                active.clear()
            active.append(pos)

    return {
        "asset": asset,
        "total_signals": total_signals,
        "signals_while_active": signals_while_active,
        "same_side_opportunities": same_side_opportunities,
        "cross_side_opportunities": cross_side_opportunities,
        "reentry_fraction": signals_while_active / max(total_signals, 1),
        "profitable_reentry_candidates": profitable_reentry_candidates,
        "losing_reentry_candidates": losing_reentry_candidates,
        "reentry_candidate_win_rate": profitable_reentry_candidates
        / max(profitable_reentry_candidates + losing_reentry_candidates, 1),
        "avg_reentry_candidate_r": np.mean(reentry_candidate_r) if reentry_candidate_r else 0.0,
        "avg_reentry_candidate_p_long": np.mean(reentry_candidate_p_long) if reentry_candidate_p_long else 0.0,
    }


# ── Multi-asset runner ────────────────────────────────────────────────────


def run_all_assets(
    asset_names: list[str],
    policies: list[str] | None = None,
    tag: str = "remediation",
    trailing: bool = False,
) -> dict[str, Any]:
    """Run re-entry simulation across all requested assets."""
    if policies is None:
        policies = ["A", "B", "C"]

    results: dict[str, Any] = {
        "config": {
            "assets": asset_names,
            "policies": policies,
            "tag": tag,
            "timestamp": str(pd.Timestamp.now()),
            "trailing": trailing,
        },
        "overlap": {},
        "policies": {p: {"trades": {}, "events": {}} for p in policies},
        "summary": {},
    }

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

        # Overlap analysis
        overlap = analyze_overlap_opportunities(asset, signal_df, ohlcv)
        results["overlap"][asset] = overlap

        # Policy simulation
        for p_name in policies:
            policy = POLICIES.get(p_name)
            if policy is None:
                logger.warning("  Unknown policy: %s", p_name)
                continue
            logger.info("  Simulating policy %s...", p_name)
            trades, events = simulate_one_asset(asset, signal_df, ohlcv, policy, trailing=trailing)
            results["policies"][p_name]["trades"][asset] = trades
            results["policies"][p_name]["events"][asset] = events
            logger.info("    Policy %s: %d trades, %d events", p_name, len(trades), len(events))

    return results


# ── Main ──────────────────────────────────────────────────────────────────


def print_overlap_summary(results: dict) -> None:
    """Print overlap analysis summary."""
    overlap = results.get("overlap", {})
    print("\n" + "=" * 70)
    print("RE-ENTRY OPPORTUNITY ANALYSIS (Question 1)")
    print("=" * 70)
    print(
        f"{'Asset':<10} {'Total Sig':>9} {'While Active':>12} {'SameSide':>9} {'CrossSide':>10} {'Reentry%':>9} {'CandidateWR':>12} {'Avg CandR':>10}"
    )
    print("-" * 70)
    total_sig = 0
    total_active = 0
    for asset in sorted(overlap.keys()):
        o = overlap[asset]
        total_sig += o["total_signals"]
        total_active += o["signals_while_active"]
        print(
            f"{asset:<10} {o['total_signals']:>9} {o['signals_while_active']:>12} "
            f"{o['same_side_opportunities']:>9} {o['cross_side_opportunities']:>10} "
            f"{o['reentry_fraction']:>8.1%} {o['reentry_candidate_win_rate']:>11.1%} "
            f"{o['avg_reentry_candidate_r']:>+9.2f}"
        )
    print("-" * 70)
    print(f"{'TOTAL':<10} {total_sig:>9} {total_active:>12}")
    print(f"  Overall reentry fraction: {total_active / max(total_sig, 1):.1%}")
    print()


def print_policy_comparison(results: dict) -> None:
    """Print per-asset policy comparison."""
    print("=" * 70)
    print("POLICY COMPARISON — Per-Asset Totals")
    print("=" * 70)

    for p_name in ["A", "B", "C", "D"]:
        if p_name not in results["policies"]:
            continue
        trades_by_asset = results["policies"][p_name]["trades"]
        events_by_asset = results["policies"][p_name]["events"]
        total_trades = sum(len(t) for t in trades_by_asset.values())
        total_r = sum(
            sum(ti.get("r_multiple", 0) if isinstance(ti, dict) else getattr(ti, "r_multiple", 0) for ti in t)
            for t in trades_by_asset.values()
        )
        n_events = sum(len(e) for e in events_by_asset.values())
        allowed = sum(1 for el in events_by_asset.values() for e in el if e.allowed)
        blocked = n_events - allowed

        policy = [v for k, v in POLICIES.items() if v.name == p_name][0]
        desc = ""
        if p_name == "D":
            desc = " (no guards — matches live engine)"
        print(
            f"\n  Policy {p_name}{desc}: {total_trades} trades, {total_r:+.1f}R total, {n_events} events ({allowed} allowed, {blocked} blocked)"
        )

    policies_in_results = [p for p in ["A", "B", "C", "D"] if p in results["policies"]]
    print()
    header = f"{'Asset':<10}"
    for p in policies_in_results:
        header += f" {'Trades_' + p:>8} {'R_' + p:>8}"
    print(header)
    print("-" * (10 + len(policies_in_results) * 17))
    for asset in sorted(results.get("overlap", {}).keys()):
        line = f"{asset:<10}"
        for p in policies_in_results:
            trades = len(results["policies"][p]["trades"].get(asset, []))
            r = sum(t.r_multiple or 0 for t in results["policies"][p]["trades"].get(asset, []))
            line += f" {trades:>8} {r:>+8.1f}"
        print(line)


def main():
    parser = argparse.ArgumentParser(description="Re-entry policy simulation")
    parser.add_argument("--assets", default=None, help="Comma-separated asset names")
    parser.add_argument("--all", action="store_true", help="Run on all portfolio assets")
    parser.add_argument("--tag", default="remediation", help="Signal parquet tag")
    parser.add_argument("--policies", default="A,B,C", help="Policies to simulate")
    parser.add_argument("--output", default=None, help="JSON output path")
    parser.add_argument(
        "--trailing", action="store_true", help="Use production adaptive trailing exits instead of fixed TP/SL"
    )
    args = parser.parse_args()

    if args.all:
        assets = sorted(PORTFOLIO_ASSETS.keys())
    elif args.assets:
        assets = [a.strip() for a in args.assets.split(",")]
    else:
        assets = sorted(PORTFOLIO_ASSETS.keys())

    policies = [p.strip() for p in args.policies.split(",")]
    logger.info("Running on %d assets with policies %s (trailing=%s)", len(assets), policies, args.trailing)
    results = run_all_assets(assets, policies, tag=args.tag, trailing=args.trailing)

    print_overlap_summary(results)
    print_policy_comparison(results)

    if args.output:
        # Convert dataclasses to dicts for JSON serialization
        serializable = _make_serializable(results)
        with open(args.output, "w") as f:
            json.dump(serializable, f, indent=2, cls=EigenCapitalJSONEncoder)
        logger.info("Results saved to %s", args.output)

    return results


def _make_serializable(obj):
    """Convert dataclasses and non-serializable types for JSON output."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif hasattr(obj, "__dataclass_fields__"):
        d = {}
        for field_name in obj.__dataclass_fields__:
            val = getattr(obj, field_name)
            if isinstance(val, (datetime, pd.Timestamp)):
                d[field_name] = str(val)
            elif isinstance(val, np.floating):
                d[field_name] = float(val)
            elif isinstance(val, np.integer):
                d[field_name] = int(val)
            else:
                d[field_name] = _make_serializable(val)
        return d
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, (datetime, pd.Timestamp)):
        return str(obj)
    return obj


if __name__ == "__main__":
    main()
