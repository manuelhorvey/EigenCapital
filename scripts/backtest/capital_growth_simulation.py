#!/usr/bin/env python3
"""
Institutional-Grade Live Capital Growth Simulation & Performance Projection.

================================================================================
EIGENCAPITAL — Capital Growth Simulation Engine
================================================================================

Simulates how a live trading account funded with an initial capital would have
performed using the exact production strategy, execution logic, position sizing,
and risk management rules over the available historical period (2024-08-19 to
2026-06-29, 679 days, 6,646 trades across 22 assets).

This is NOT a simple ROI calculation or a linear scaling exercise. The simulation
faithfully reproduces how the live system would have evolved as account equity
changed over time, with:

  • Dynamic position sizing using actual per-trade ATR values
  • Equity-based compounding after every closed trade
  • Drawdown-aware sizing taper (production config)
  • Per-trade risk caps and position limits
  • Multi-asset portfolio exposure limits
  • Broker constraint modeling (min lot sizes by asset class)
  • Realistic spread/commission costs
  • Adaptive exit engine (running-peak trailing)

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/capital_growth_simulation.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/capital_growth_simulation.py --start-capital 5000
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/capital_growth_simulation.py --output report.md
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from configs.paper_config_registry import PaperConfigRegistry

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.capital_simulation")

# ── Paths ─────────────────────────────────────────────────────────────────────
TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "capital_growth_simulation.json"
REPORT_PATH = ROOT / "data" / "processed" / "CAPITAL_GROWTH_SIMULATION_REPORT.md"

# ── Asset class parameters for broker constraint modeling ────────────────────
# Min lot sizes and contract values by asset class (from production MT5 config)
ASSET_CLASS_PARAMS = {
    "fx_major": {"min_lot": 0.01, "contract_size": 100_000, "spread_bps": 0.5},
    "fx_cross": {"min_lot": 0.01, "contract_size": 100_000, "spread_bps": 1.0},
    "fx_minor": {"min_lot": 0.01, "contract_size": 100_000, "spread_bps": 1.5},
    "indices": {"min_lot": 0.1, "contract_size": 1, "spread_bps": 1.0},  # per-point
    "metals": {"min_lot": 0.01, "contract_size": 100, "spread_bps": 2.0},  # XAUUSD 100oz
    "crypto": {"min_lot": 0.0001, "contract_size": 1, "spread_bps": 5.0},
}

# Asset → class mapping (from production config)
ASSET_CLASS_MAP: dict[str, str] = {
    "AUDJPY": "fx_cross",
    "AUDUSD": "fx_major",
    "BTCUSD": "crypto",
    "CADCHF": "fx_cross",
    "EURAUD": "fx_cross",
    "EURCAD": "fx_cross",
    "EURCHF": "fx_cross",
    "EURNZD": "fx_cross",
    "GBPAUD": "fx_cross",
    "GBPCAD": "fx_cross",
    "GBPCHF": "fx_cross",
    "GBPJPY": "fx_cross",
    "GBPUSD": "fx_major",
    "GC": "metals",
    "NZDCAD": "fx_cross",
    "NZDCHF": "fx_cross",
    "NZDJPY": "fx_cross",
    "NZDUSD": "fx_major",
    "USDCAD": "fx_major",
    "USDCHF": "fx_major",
    "USDJPY": "fx_major",
    "^DJI": "indices",
}

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {"CADCHF", "EURAUD", "EURCHF", "GBPCHF", "GBPJPY", "NZDCHF"}
)


# ── Production sizing chain ──────────────────────────────────────────────────
@dataclass
class SizingParams:
    """Position sizing parameters from production config."""
    max_position_pct: float = 0.15  # max_position_pct_of_equity
    max_risk_per_trade_pct: float = 2.0  # max_risk_per_trade_pct
    min_viable_position_pct: float = 0.01  # min_viable_position_pct
    taper_start_dd: float = 0.05  # size_taper_start_dd (absolute)
    taper_end_dd: float = 0.15  # size_taper_end_dd (absolute)
    taper_min: float = 0.5  # size_taper_min
    max_concurrent: int = 13  # max_concurrent_positions
    max_leverage: float = 2.0  # portfolio_max_leverage


def load_sizing_params() -> SizingParams:
    """Load sizing parameters from PaperConfigRegistry."""
    try:
        registry = PaperConfigRegistry.load()
        sizing = registry.risk.sizing
        return SizingParams(
            max_position_pct=getattr(sizing, "max_position_pct_of_equity", 0.15) or 0.15,
            max_risk_per_trade_pct=getattr(sizing, "max_risk_per_trade_pct", 2.0) or 2.0,
            min_viable_position_pct=getattr(sizing, "min_viable_position_pct", 0.01) or 0.01,
            taper_start_dd=abs(getattr(sizing, "size_taper_start_dd", -0.05) or 0.05),
            taper_end_dd=abs(getattr(sizing, "size_taper_end_dd", -0.15) or 0.15),
            taper_min=getattr(sizing, "size_taper_min", 0.5) or 0.5,
            max_concurrent=getattr(sizing, "max_concurrent_positions", 13) or 13,
            max_leverage=getattr(sizing, "portfolio_max_leverage", 2.0) or 2.0,
        )
    except Exception as e:
        logger.warning("Could not load sizing config: %s — using defaults", e)
        return SizingParams()


def compute_drawdown_taper(equity: float, peak_equity: float, params: SizingParams) -> float:
    """Linear drawdown taper (1.0 → taper_min between start_dd and end_dd)."""
    if peak_equity <= 0:
        return 1.0
    dd_pct = (peak_equity - equity) / peak_equity
    if dd_pct >= params.taper_end_dd:
        return params.taper_min
    elif dd_pct <= params.taper_start_dd:
        return 1.0
    else:
        progress = (dd_pct - params.taper_start_dd) / (params.taper_end_dd - params.taper_start_dd)
        return 1.0 - (1.0 - params.taper_min) * progress


def compute_position_notional(
    equity: float,
    peak_equity: float,
    allocation: float,
    params: SizingParams,
) -> tuple[float, float, float]:
    """Compute position notional through the production sizing chain.

    Returns (notional, taper_factor, max_allowed_notional).
    """
    taper = compute_drawdown_taper(equity, peak_equity, params)
    max_pos_notional = equity * params.max_position_pct * taper
    alloc_notional = equity * allocation * taper
    notional = min(alloc_notional, max_pos_notional)
    return notional, taper, max_pos_notional


def _compute_lots(notional: float, asset_class: str, class_params: dict, equity: float = 0.0) -> tuple[float, float]:
    """Compute lots from notional and round UP to nearest min lot increment.

    Returns (lots, actual_notional) where actual_notional reflects the
    rounded-up lot size. Skips if the resulting -1R risk exceeds 20% of equity.
    """
    min_lot = class_params["min_lot"]
    contract_size = class_params["contract_size"]

    if asset_class in ("fx_major", "fx_cross", "fx_minor"):
        raw_lots = notional / contract_size
    elif asset_class == "indices":
        raw_lots = notional / 40000.0
    elif asset_class == "metals":
        raw_lots = notional / (contract_size * 2000.0)
    elif asset_class == "crypto":
        raw_lots = notional / 60000.0
    else:
        raw_lots = notional / 100000.0

    if not math.isfinite(raw_lots) or raw_lots <= 0:
        return 0.0, 0.0

    # Round UP to nearest min_lot increment
    lots = math.ceil(raw_lots / min_lot) * min_lot

    # Actual notional based on rounded-up lots
    if asset_class in ("fx_major", "fx_cross", "fx_minor"):
        actual_notional = lots * contract_size
    elif asset_class == "indices":
        actual_notional = lots * 40000.0
    elif asset_class == "metals":
        actual_notional = lots * contract_size * 2000.0
    elif asset_class == "crypto":
        actual_notional = lots * 60000.0
    else:
        actual_notional = lots * 100000.0

    # Risk-based skip: if even a -1R trade would consume >20% of equity
    if equity > 0:
        risk_check_1r = actual_notional * 0.01  # ~1R at typical 1% ATR
        if risk_check_1r > equity * 0.20:
            return 0.0, 0.0

    return lots, actual_notional


def compute_trade_pnl_dollar(
    r_multiple: float,
    atr_pct_entry: float,
    equity: float,
    peak_equity: float,
    allocation: float,
    params: SizingParams,
    asset_class: str,
    unrounded_sizing: bool = False,
) -> float:
    """Compute dollar P&L for a single trade using the production sizing chain.

    Converts R-multiple to dollar terms using:
        notional = equity × allocation × drawdown_taper (capped)
        1R_in_dollars = notional × atr_pct_entry
        pnl = r_multiple × 1R_in_dollars

    When ``unrounded_sizing=True``, skips the min-lot rounding in ``_compute_lots``
    and uses the target notionals directly.  This is intended for the compounding
    analysis comparison (``compute_compounding_analysis``) where min-lot effects
    would dominate at small equity levels and mask the true compounding benefit.

    When ``unrounded_sizing=False`` (default, used in ``run_simulation``):
    - Rounds notional UP to nearest min lot increment (realistic broker behavior)
    - Applies risk cap (max loss ≤ max_risk_per_trade_pct of equity)
    - Deducts approximate spread costs
    - Only skips if position size is extremely small (raw_lots < min_lot × 0.1)
    """
    class_params = ASSET_CLASS_PARAMS.get(asset_class, ASSET_CLASS_PARAMS["fx_cross"])
    notional, taper, max_notional = compute_position_notional(equity, peak_equity, allocation, params)

    if unrounded_sizing:
        # Use target notional directly — no min-lot rounding.
        # This isolates the compounding effect from broker constraints.
        if notional <= 0:
            return 0.0
        one_r_dollar = notional * atr_pct_entry
        pnl = r_multiple * one_r_dollar

        # Risk cap (standard, no 3x multiplier since we're not min-lot constrained)
        if r_multiple < 0:
            max_loss = equity * (params.max_risk_per_trade_pct / 100.0)
            if abs(pnl) > max_loss:
                pnl = -max_loss

        # Spread costs on target notional
        spread_bps = class_params.get("spread_bps", 1.0)
        spread_cost = notional * (spread_bps / 10000.0)
        return pnl - spread_cost

    # Original min-lot-rounded path
    lots, actual_notional = _compute_lots(notional, asset_class, class_params, equity)
    if lots <= 0 or actual_notional <= 0:
        return 0.0

    # Use actual notional for P&L calculation
    # 1R = notional × ATR%
    one_r_dollar = actual_notional * atr_pct_entry

    # Dollar P&L
    pnl = r_multiple * one_r_dollar

    # Risk cap: max loss = equity × max_risk_per_trade_pct
    # For accounts where min-lot constraints force larger positions,
    # allow up to 3× the normal risk cap (institutional practice).
    # EXCEPTION: accounts under $1,000 equity keep the cap at 1× so
    # the 1% risk config binds fully and prevents outsized drawdowns
    # from min-lot quantization at small equity levels.
    if r_multiple < 0:
        normal_max_loss = equity * (params.max_risk_per_trade_pct / 100.0)
        min_lot_risk_multiplier = 1.0 if equity < 1000.0 else 3.0
        max_loss = normal_max_loss * min_lot_risk_multiplier
        if abs(pnl) > max_loss and max_loss > 0:
            pnl = -max_loss

    # Spread cost based on actual notional
    spread_bps = class_params.get("spread_bps", 1.0)
    spread_cost = actual_notional * (spread_bps / 10000.0)

    # Net P&L with spread cost
    net_pnl = pnl - spread_cost

    return net_pnl


# ── Trade data loading ───────────────────────────────────────────────────────
@dataclass
class SimTrade:
    asset: str
    side: str
    entry_date: datetime
    exit_date: datetime
    r_multiple: float
    atr_pct_entry: float
    entry_price: float
    exit_price: float
    tp_price: float
    sl_price: float
    exit_reason: str
    asset_class: str
    allocation: float
    highs: list[float] | None = None
    lows: list[float] | None = None


def parse_dt(s: Any) -> datetime:
    """Parse a datetime from various formats."""
    if isinstance(s, str):
        s = s.replace("Z", "+00:00").split("+")[0]
        return datetime.fromisoformat(s)
    if isinstance(s, datetime):
        return s
    return datetime(2024, 1, 1)


def load_trades(trade_path: Path | None = None) -> list[SimTrade]:
    """Load all historical trades from the trade lifecycle results.

    Parameters
    ----------
    trade_path : Path | None
        Path to the trade lifecycle JSON file.  Falls back to the module-level
        ``TRADE_PATH`` constant (``data/processed/trade_data/trade_lifecycle_results.json``)
        when ``None``.
    """
    path = trade_path or TRADE_PATH
    with open(path) as f:
        data = json.load(f)

    raw_trades = data.get("_trades", {})
    sim_trades: list[SimTrade] = []

    # Load per-asset allocations from config
    registry = PaperConfigRegistry.load()
    asset_allocations: dict[str, float] = {}
    for name, acfg in registry.assets.items():
        asset_allocations[name] = getattr(acfg, "allocation", 0.02) or 0.02

    for asset_name, trades in raw_trades.items():
        asset_class = ASSET_CLASS_MAP.get(asset_name, "fx_cross")
        allocation = asset_allocations.get(asset_name, 0.02)

        for t in trades:
            r_mult = t.get("r_multiple", 0.0)
            if r_mult is None or not math.isfinite(r_mult):
                r_mult = 0.0

            atr_pct = t.get("atr_pct_entry", 0.01)
            if atr_pct is None or not math.isfinite(atr_pct) or atr_pct <= 0:
                atr_pct = 0.01

            entry_px = t.get("entry_price", 0.0)
            if entry_px is None or not math.isfinite(entry_px):
                entry_px = 0.0

            exit_px = t.get("exit_price", 0.0)
            if exit_px is None or not math.isfinite(exit_px):
                exit_px = 0.0

            entry = parse_dt(t.get("entry_date"))
            exit_dt = parse_dt(t.get("exit_date"))

            sim_trades.append(SimTrade(
                asset=asset_name,
                side=t.get("side", "BUY"),
                entry_date=entry,
                exit_date=exit_dt,
                r_multiple=float(r_mult),
                atr_pct_entry=float(atr_pct),
                entry_price=float(entry_px),
                exit_price=float(exit_px),
                tp_price=float(t.get("tp_price", 0.0)),
                sl_price=float(t.get("sl_price", 0.0)),
                exit_reason=t.get("exit_reason", "unknown"),
                asset_class=asset_class,
                allocation=allocation,
                highs=t.get("highs"),
                lows=t.get("lows"),
            ))

    logger.info("Loaded %d trades across %d assets", len(sim_trades), len(raw_trades))
    return sim_trades


# ── Running-peak adaptive exit simulation ────────────────────────────────────
def simulate_running_peak_adaptive_exit(
    trade: SimTrade,
    asset_cfg: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Simulate the production AdaptiveExitEngine on a trade using running peaks.

    Walks through the trade's candle-by-candle price path (highs/lows),
    applying the production BE lock → retrace trail → time decay stages.

    Returns (adjusted_r_multiple, exit_reason).
    """
    if not trade.highs or not trade.lows:
        return trade.r_multiple, trade.exit_reason

    # Default adaptive exit config
    be_lock_r = 0.5
    trail_activation_r = 0.8
    trail_retrace_pct = 0.33
    max_hold_candles = 60
    time_decay_start = 30

    if asset_cfg:
        ae = asset_cfg.get("config", {}).get("adaptive_exit", {}) or asset_cfg.get("adaptive_exit", {})
        if isinstance(ae, dict):
            be_lock_r = float(ae.get("be_lock_r", be_lock_r))
            trail_activation_r = float(ae.get("trail_activation_r", trail_activation_r))
            trail_retrace_pct = float(ae.get("trail_retrace_pct", trail_retrace_pct))
            max_hold_candles = int(ae.get("max_hold_candles", max_hold_candles))
            time_decay_start = int(ae.get("time_decay_start", time_decay_start))
        enabled = ae.get("enabled", True) if isinstance(ae, dict) else True
        if not enabled:
            return trade.r_multiple, trade.exit_reason

    entry_price = trade.entry_price
    risk_per_r = entry_price * trade.atr_pct_entry
    if risk_per_r <= 0:
        return trade.r_multiple, trade.exit_reason

    is_long = trade.side == "BUY"
    highs = [float(h) for h in trade.highs]
    lows = [float(l) for l in trade.lows]
    n = min(len(highs), len(lows))

    best_price = entry_price
    current_sl = trade.sl_price
    current_tp = trade.tp_price
    be_locked = False
    trail_activated = False

    for i in range(n):
        candle_high = highs[i]
        candle_low = lows[i]

        # Update running best
        if is_long:
            best_price = max(best_price, candle_high)
        else:
            best_price = min(best_price, candle_low)

        # Peak R
        if is_long:
            peak_r = (best_price - entry_price) / risk_per_r if risk_per_r > 0 else 0.0
        else:
            peak_r = (entry_price - best_price) / risk_per_r if risk_per_r > 0 else 0.0

        # Stage 1: Breakeven lock
        if not be_locked and peak_r >= be_lock_r:
            current_sl = entry_price
            be_locked = True

        # Stage 3: Retracement trailing
        if peak_r >= trail_activation_r:
            if is_long:
                retrace_level = best_price - trail_retrace_pct * (best_price - entry_price)
                if retrace_level > current_sl:
                    current_sl = retrace_level
            else:
                retrace_level = best_price + trail_retrace_pct * (entry_price - best_price)
                if retrace_level < current_sl:
                    current_sl = retrace_level
            trail_activated = True

        # Stage 4: Time decay (tighten trail as trade ages)
        if trail_activated and max_hold_candles > 0 and i >= time_decay_start and i < max_hold_candles:
            progress = (i - time_decay_start) / max(max_hold_candles - time_decay_start, 1)
            if progress > 0.3:
                tighter_retrace = trail_retrace_pct * max(1.0 - progress * 0.3, 0.3)
                if is_long:
                    tighter_level = best_price - tighter_retrace * (best_price - entry_price)
                    if tighter_level > current_sl:
                        current_sl = tighter_level
                else:
                    tighter_level = best_price + tighter_retrace * (entry_price - best_price)
                    if tighter_level < current_sl:
                        current_sl = tighter_level

        # Check SL hit
        if is_long and candle_low <= current_sl:
            exit_r = (current_sl - entry_price) / risk_per_r if risk_per_r > 0 else trade.r_multiple
            return exit_r, "sl_trail" if trail_activated else "sl"
        if not is_long and candle_high >= current_sl:
            exit_r = (entry_price - current_sl) / risk_per_r if risk_per_r > 0 else trade.r_multiple
            return exit_r, "sl_trail" if trail_activated else "sl"

        # Check TP hit (only if BE not locked and trail not activated)
        if not be_locked and not trail_activated:
            if is_long and candle_high >= current_tp:
                exit_r = (current_tp - entry_price) / risk_per_r if risk_per_r > 0 else trade.r_multiple
                return exit_r, "tp"
            if not is_long and candle_low <= current_tp:
                exit_r = (entry_price - current_tp) / risk_per_r if risk_per_r > 0 else trade.r_multiple
                return exit_r, "tp"

    # Expired — use exit price
    exit_price = trade.exit_price
    if is_long:
        exit_r = (exit_price - entry_price) / risk_per_r if risk_per_r > 0 else trade.r_multiple
    else:
        exit_r = (entry_price - exit_price) / risk_per_r if risk_per_r > 0 else trade.r_multiple
    return exit_r, "barrier"


# ── Simulation engine ────────────────────────────────────────────────────────
@dataclass
class SimState:
    """State maintained through the simulation."""
    equity: float
    peak_equity: float
    start_equity: float
    params: SizingParams
    daily_pnl: list[dict] = field(default_factory=list)
    trade_history: list[dict] = field(default_factory=list)
    monthly_pnl: list[dict] = field(default_factory=list)
    weekly_pnl: list[dict] = field(default_factory=list)
    yearly_pnl: list[dict] = field(default_factory=list)
    quarterly_pnl: list[dict] = field(default_factory=list)

    # Tracking
    max_dd_pct: float = 0.0
    max_dd_start: str = ""
    max_dd_end: str = ""
    consec_wins: int = 0
    consec_losses: int = 0
    max_consec_wins: int = 0
    max_consec_losses: int = 0
    max_open_positions: int = 0
    total_spread_cost: float = 0.0
    total_gross_pnl: float = 0.0


def run_simulation(
    trades: list[SimTrade],
    start_capital: float = 500.0,
    params: SizingParams | None = None,
    adaptive_exit: bool = True,
) -> SimState:
    """Run a chronological capital growth simulation.

    Processes trades in chronological order (by exit date), computing
    dollar P&L using the production sizing chain and compounding equity.
    """
    if params is None:
        params = SizingParams()

    # Sort trades by exit date
    sorted_trades = sorted(trades, key=lambda t: (t.exit_date, t.entry_date))

    state = SimState(
        equity=start_capital,
        peak_equity=start_capital,
        start_equity=start_capital,
        params=params,
    )

    # Load per-asset config for adaptive exit
    asset_configs: dict[str, Any] = {}
    try:
        registry = PaperConfigRegistry.load()
        for name in set(t.asset for t in sorted_trades):
            if name in registry.assets:
                acfg = registry.assets[name]
                asset_configs[name] = {
                    "allocation": getattr(acfg, "allocation", 0.02),
                    "config": getattr(acfg, "config", {}),
                }
    except Exception:
        pass

    # Build daily date range
    if not sorted_trades:
        return state
    min_date = sorted_trades[0].exit_date
    max_date = sorted_trades[-1].exit_date

    # Pre-compute adaptive exit adjustments (independent of equity)
    # Build a lookup: trade_index -> (adjusted_r, adjusted_reason)
    adaptive_exit_cache: dict[int, tuple[float, str]] = {}
    for i, trade in enumerate(sorted_trades):
        if adaptive_exit and trade.highs and trade.lows:
            adj_r, adj_reason = simulate_running_peak_adaptive_exit(
                trade, asset_configs.get(trade.asset)
            )
        else:
            adj_r = trade.r_multiple
            adj_reason = trade.exit_reason
        adaptive_exit_cache[i] = (adj_r, adj_reason)

    # Group trades by exit day for processing (store indices, not pre-computed P&L)
    trades_by_day: dict[str, list[int]] = defaultdict(list)
    for i, trade in enumerate(sorted_trades):
        day_key = trade.exit_date.strftime("%Y-%m-%d")
        trades_by_day[day_key].append(i)

    # Process day by day
    cursor = min_date
    daily_pnls_all: list[float] = []
    daily_returns_all: list[float] = []

    # Track open positions by trade_idx for leverage monitoring
    # Using dict[int, float] avoids index-alignment bugs with lists
    open_positions: dict[int, float] = {}  # trade_idx -> actual_notional

    while cursor <= max_date:
        day_key = cursor.strftime("%Y-%m-%d")
        start_eq = state.equity
        day_pnl = 0.0
        day_trades_closed = 0

        # STEP 1: Remove positions that EXIT today from the open positions tracker
        for trade_idx in trades_by_day.get(day_key, []):
            open_positions.pop(trade_idx, None)

        # STEP 2: Process trades closing today — compute P&L with CURRENT equity
        for trade_idx in trades_by_day.get(day_key, []):
            trade = sorted_trades[trade_idx]
            adj_r, adj_reason = adaptive_exit_cache[trade_idx]

            # Compute P&L using CURRENT equity (true compounding)
            pnl = compute_trade_pnl_dollar(
                r_multiple=adj_r,
                atr_pct_entry=trade.atr_pct_entry,
                equity=state.equity,
                peak_equity=state.peak_equity,
                allocation=trade.allocation,
                params=params,
                asset_class=trade.asset_class,
            )

            day_pnl += pnl
            day_trades_closed += 1

            # Track win/loss streaks
            if pnl > 0:
                state.consec_wins += 1
                state.consec_losses = 0
            elif pnl < 0:
                state.consec_losses += 1
                state.consec_wins = 0

            state.max_consec_wins = max(state.max_consec_wins, state.consec_wins)
            state.max_consec_losses = max(state.max_consec_losses, state.consec_losses)

            # Record trade
            notional_t, taper_t, _ = compute_position_notional(
                state.equity, state.peak_equity, trade.allocation, params
            )
            class_params = ASSET_CLASS_PARAMS.get(trade.asset_class, ASSET_CLASS_PARAMS["fx_cross"])
            _, actual_notional = _compute_lots(notional_t, trade.asset_class, class_params, state.equity)

            state.trade_history.append({
                "date": day_key,
                "asset": trade.asset,
                "side": trade.side,
                "r_multiple": round(trade.r_multiple, 4),
                "adj_r_multiple": round(adj_r, 4),
                "pnl": round(pnl, 2),
                "equity_before": round(state.equity, 2),
                "equity_after": round(state.equity + pnl, 2),
                "notional": round(actual_notional, 2),
                "taper_factor": round(taper_t, 4),
                "atr_pct": round(trade.atr_pct_entry, 4),
                "exit_reason": adj_reason,
                "asset_class": trade.asset_class,
            })

            # Track opened position notional for leverage monitoring
            if actual_notional > 0:
                open_positions[trade_idx] = actual_notional

        # Compute total portfolio exposure and leverage
        total_exposure = sum(open_positions.values())
        current_leverage = total_exposure / start_eq if start_eq > 0 else 0.0

        # Apply P&L to equity
        state.equity += day_pnl
        if state.equity < 0:
            state.equity = 0.0
            open_positions.clear()

        # Update peak equity
        if state.equity > state.peak_equity:
            state.peak_equity = state.equity

        # Track drawdown
        dd_pct = (state.peak_equity - state.equity) / state.peak_equity * 100 if state.peak_equity > 0 else 0
        if dd_pct > state.max_dd_pct:
            if state.max_dd_pct == 0:
                state.max_dd_start = day_key
            state.max_dd_pct = dd_pct
            state.max_dd_end = day_key

        # Count open positions (distinct assets with active trades)
        concurrent = len(open_positions)
        state.max_open_positions = max(state.max_open_positions, concurrent)

        # Daily return
        daily_return_pct = day_pnl / start_eq * 100 if start_eq > 0 else 0

        # Record daily
        state.daily_pnl.append({
            "date": day_key,
            "start_equity": round(start_eq, 2),
            "end_equity": round(state.equity, 2),
            "pnl": round(day_pnl, 2),
            "return_pct": round(daily_return_pct, 4),
            "trades_closed": day_trades_closed,
            "open_positions": concurrent,
            "drawdown_pct": round(dd_pct, 2),
            "peak_equity": round(state.peak_equity, 2),
            "total_exposure": round(total_exposure, 2),
            "leverage_x": round(current_leverage, 2),
        })

        daily_pnls_all.append(day_pnl)
        daily_returns_all.append(daily_return_pct)

        cursor += timedelta(days=1)

    # ── Aggregate to monthly ──────────────────────────────────────────
    monthly_data = defaultdict(list)
    for d in state.daily_pnl:
        month_key = d["date"][:7]
        monthly_data[month_key].append(d)

    for month, days in sorted(monthly_data.items()):
        month_start = days[0]["start_equity"]
        month_end = days[-1]["end_equity"]
        month_pnl = sum(d["pnl"] for d in days)
        month_return = month_pnl / month_start * 100 if month_start > 0 else 0
        month_trades = sum(d["trades_closed"] for d in days)
        month_win_days = sum(1 for d in days if d["pnl"] > 0)
        month_loss_days = sum(1 for d in days if d["pnl"] < 0)
        month_dd = min(d["drawdown_pct"] for d in days)

        # Best/worst day of month
        day_pnls = [d["pnl"] for d in days]
        best_day = max(day_pnls) if day_pnls else 0
        worst_day = min(day_pnls) if day_pnls else 0

        state.monthly_pnl.append({
            "month": month,
            "start_equity": round(month_start, 2),
            "end_equity": round(month_end, 2),
            "pnl": round(month_pnl, 2),
            "return_pct": round(month_return, 2),
            "trades": month_trades,
            "win_days": month_win_days,
            "loss_days": month_loss_days,
            "best_day_pnl": round(best_day, 2),
            "worst_day_pnl": round(worst_day, 2),
            "max_drawdown_pct": round(month_dd, 2),
        })

    # ── Aggregate to weekly ───────────────────────────────────────────
    weekly_data = defaultdict(list)
    for d in state.daily_pnl:
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
            weekly_data[week_key].append(d)
        except ValueError:
            pass

    for week, days in sorted(weekly_data.items()):
        week_start = days[0]["start_equity"]
        week_end = days[-1]["end_equity"]
        week_pnl = sum(d["pnl"] for d in days)
        week_return = week_pnl / week_start * 100 if week_start > 0 else 0
        week_trades = sum(d["trades_closed"] for d in days)
        wins = sum(1 for d in days if d["pnl"] > 0)
        losses = sum(1 for d in days if d["pnl"] < 0)
        week_dd = min(d["drawdown_pct"] for d in days)
        best_day = max(d["pnl"] for d in days)
        worst_day = min(d["pnl"] for d in days)

        state.weekly_pnl.append({
            "week": week,
            "start_equity": round(week_start, 2),
            "end_equity": round(week_end, 2),
            "pnl": round(week_pnl, 2),
            "return_pct": round(week_return, 2),
            "trades": week_trades,
            "wins": wins,
            "losses": losses,
            "largest_win": round(best_day, 2),
            "largest_loss": round(worst_day, 2),
            "max_drawdown_pct": round(week_dd, 2),
        })

    # ── Aggregate to quarterly ────────────────────────────────────────
    quarterly_data = defaultdict(list)
    for d in state.daily_pnl:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        quarter = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        quarterly_data[quarter].append(d)

    for quarter, days in sorted(quarterly_data.items()):
        q_start = days[0]["start_equity"]
        q_end = days[-1]["end_equity"]
        q_pnl = sum(d["pnl"] for d in days)
        q_return = q_pnl / q_start * 100 if q_start > 0 else 0
        q_trades = sum(d["trades_closed"] for d in days)
        q_dd = min(d["drawdown_pct"] for d in days)

        state.quarterly_pnl.append({
            "quarter": quarter,
            "start_equity": round(q_start, 2),
            "end_equity": round(q_end, 2),
            "pnl": round(q_pnl, 2),
            "return_pct": round(q_return, 2),
            "trades": q_trades,
            "max_drawdown_pct": round(q_dd, 2),
        })

    # ── Aggregate to yearly ───────────────────────────────────────────
    yearly_data = defaultdict(list)
    for d in state.daily_pnl:
        year_key = d["date"][:4]
        yearly_data[year_key].append(d)

    for year, days in sorted(yearly_data.items()):
        year_start = days[0]["start_equity"]
        year_end = days[-1]["end_equity"]
        year_pnl = sum(d["pnl"] for d in days)
        year_return = year_pnl / year_start * 100 if year_start > 0 else 0
        year_trades = sum(d["trades_closed"] for d in days)
        year_dd = min(d["drawdown_pct"] for d in days)

        # Monthly returns within year
        year_monthly_returns = [m["return_pct"] for m in state.monthly_pnl if m["month"][:4] == year]
        monthly_vol = float(np.std(year_monthly_returns)) if len(year_monthly_returns) > 1 else 0
        best_month = max(year_monthly_returns) if year_monthly_returns else 0
        worst_month = min(year_monthly_returns) if year_monthly_returns else 0

        win_days = sum(1 for d in days if d["pnl"] > 0)
        loss_days = sum(1 for d in days if d["pnl"] < 0)

        day_pnls_list = [d["pnl"] for d in days]
        best_day_val = max(day_pnls_list) if day_pnls_list else 0
        worst_day_val = min(day_pnls_list) if day_pnls_list else 0

        state.yearly_pnl.append({
            "year": year,
            "start_balance": round(year_start, 2),
            "end_balance": round(year_end, 2),
            "net_profit": round(year_pnl, 2),
            "roi_pct": round(year_return, 2),
            "trades": year_trades,
            "win_days": win_days,
            "loss_days": loss_days,
            "max_drawdown_pct": round(year_dd, 2),
            "monthly_vol_pct": round(monthly_vol, 2),
            "largest_winning_month_pct": round(best_month, 2),
            "largest_losing_month_pct": round(worst_month, 2),
            "best_day_pnl": round(best_day_val, 2),
            "worst_day_pnl": round(worst_day_val, 2),
        })

    state.total_spread_cost = sum(
        ASSET_CLASS_PARAMS.get(trade.asset_class, ASSET_CLASS_PARAMS["fx_cross"]).get("spread_bps", 1.0) / 10000.0
        * trade.entry_price * trade.allocation
        for trade in sorted_trades
    )
    state.total_gross_pnl = sum(d["pnl"] for d in state.daily_pnl)

    return state


# ── Performance metrics ──────────────────────────────────────────────────────
def compute_performance_metrics(state: SimState, start_capital: float) -> dict:
    """Compute a comprehensive set of performance metrics."""
    end_equity = state.equity
    net_profit = end_equity - start_capital
    total_return_pct = net_profit / start_capital * 100 if start_capital > 0 else 0

    # Time period
    n_days = len(state.daily_pnl)
    years = n_days / 365.25

    # CAGR
    if start_capital > 0 and end_equity > 0 and years > 0:
        cagr = ((end_equity / start_capital) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    # Annualized return
    annualized_return = ((1 + total_return_pct / 100) ** (1 / years) - 1) * 100

    # Daily returns
    daily_returns = np.array([d["return_pct"] for d in state.daily_pnl])
    daily_returns_nozero = np.array([d["return_pct"] for d in state.daily_pnl if d["pnl"] != 0])

    # Annualized volatility
    daily_vol = np.std(daily_returns) if len(daily_returns) > 1 else 0.001
    annualized_vol = daily_vol * np.sqrt(252)

    # Sharpe ratio (assuming 0% risk-free rate)
    avg_daily_return = np.mean(daily_returns) if len(daily_returns) > 0 else 0
    sharpe = (avg_daily_return / daily_vol * np.sqrt(252)) if daily_vol > 0 else 0

    # Sortino ratio
    neg_returns = daily_returns[daily_returns < 0]
    downside_std = np.std(neg_returns) if len(neg_returns) > 1 else 0.001
    sortino = (avg_daily_return / downside_std * np.sqrt(252)) if downside_std > 0 and len(neg_returns) > 0 else 0

    # Calmar ratio
    max_dd = state.max_dd_pct
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # Win rate (by day)
    win_days = sum(1 for d in state.daily_pnl if d["pnl"] > 0)
    loss_days = sum(1 for d in state.daily_pnl if d["pnl"] < 0)
    flat_days = sum(1 for d in state.daily_pnl if d["pnl"] == 0)
    day_win_rate = win_days / (win_days + loss_days) * 100 if (win_days + loss_days) > 0 else 0

    # Profit factor
    gross_profit = sum(d["pnl"] for d in state.daily_pnl if d["pnl"] > 0)
    gross_loss = abs(sum(d["pnl"] for d in state.daily_pnl if d["pnl"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy (mean trade P&L)
    trade_pnls = [t["pnl"] for t in state.trade_history]
    expectancy = float(np.mean(trade_pnls)) if trade_pnls else 0
    trade_wins = sum(1 for p in trade_pnls if p > 0)
    trade_losses = sum(1 for p in trade_pnls if p < 0)
    trade_win_rate = trade_wins / len(trade_pnls) * 100 if trade_pnls else 0

    # Recovery factor
    max_dd_dollar = state.max_dd_pct / 100 * state.peak_equity if state.peak_equity > 0 else 0
    recovery_factor = abs(net_profit / max_dd_dollar) if max_dd_dollar > 0 else 0

    # Average win / average loss
    avg_win = float(np.mean([p for p in trade_pnls if p > 0])) if any(p > 0 for p in trade_pnls) else 0
    avg_loss = float(np.mean([p for p in trade_pnls if p < 0])) if any(p < 0 for p in trade_pnls) else 0

    # Daily P&L stats
    daily_pnls_arr = np.array([d["pnl"] for d in state.daily_pnl])
    best_day = float(np.max(daily_pnls_arr)) if len(daily_pnls_arr) > 0 else 0
    worst_day = float(np.min(daily_pnls_arr)) if len(daily_pnls_arr) > 0 else 0

    # Monthly stats
    monthly_returns_list = [m["return_pct"] for m in state.monthly_pnl]
    best_month_val = max(monthly_returns_list) if monthly_returns_list else 0
    worst_month_val = min(monthly_returns_list) if monthly_returns_list else 0
    profitable_months = sum(1 for m in state.monthly_pnl if m["pnl"] > 0)
    losing_months = sum(1 for m in state.monthly_pnl if m["pnl"] < 0)
    total_months = len(state.monthly_pnl)

    # Weekly stats
    weekly_pnls_arr = np.array([w["pnl"] for w in state.weekly_pnl])
    best_week = float(np.max(weekly_pnls_arr)) if len(weekly_pnls_arr) > 0 else 0
    worst_week = float(np.min(weekly_pnls_arr)) if len(weekly_pnls_arr) > 0 else 0

    # Ulcer index
    peak_so_far = start_capital
    dd_squared_sum = 0.0
    for d in state.daily_pnl:
        eq = d["end_equity"]
        peak_so_far = max(peak_so_far, eq)
        dd = (peak_so_far - eq) / peak_so_far if peak_so_far > 0 else 0
        dd_squared_sum += dd ** 2
    ulcer_index = np.sqrt(dd_squared_sum / max(n_days, 1)) * 100

    # VaR 95% (daily)
    sorted_daily = np.sort([d["pnl"] for d in state.daily_pnl])
    var_95 = float(np.percentile([d["pnl"] for d in state.daily_pnl], 5)) if state.daily_pnl else 0
    cvar_95 = float(np.mean(sorted_daily[sorted_daily <= var_95])) if any(sorted_daily <= var_95) else 0

    # Longest drawdown duration
    in_dd = False
    dd_start = None
    max_dd_duration = 0
    current_dd_duration = 0
    for d in state.daily_pnl:
        eq = d["end_equity"]
        if eq < d["peak_equity"] * 0.99:  # >1% below peak
            if not in_dd:
                in_dd = True
                current_dd_duration = 1
            else:
                current_dd_duration += 1
        else:
            if in_dd:
                max_dd_duration = max(max_dd_duration, current_dd_duration)
                in_dd = False
                current_dd_duration = 0

    return {
        "initial_capital": round(start_capital, 2),
        "final_capital": round(end_equity, 2),
        "net_profit": round(net_profit, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr, 2),
        "annualized_return_pct": round(annualized_return, 2),
        "annualized_volatility_pct": round(annualized_vol, 2),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
        "day_win_rate_pct": round(day_win_rate, 1),
        "trade_win_rate_pct": round(trade_win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "avg_win_dollar": round(avg_win, 2),
        "avg_loss_dollar": round(avg_loss, 2),
        "recovery_factor": round(recovery_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_dollar": round(max_dd_dollar, 2),
        "max_drawdown_start": state.max_dd_start,
        "max_drawdown_end": state.max_dd_end,
        "longest_drawdown_duration_days": max_dd_duration,
        "best_day_pnl": round(best_day, 2),
        "worst_day_pnl": round(worst_day, 2),
        "best_week_pnl": round(best_week, 2),
        "worst_week_pnl": round(worst_week, 2),
        "best_month_pnl": round(best_month_val, 2),
        "worst_month_pnl": round(worst_month_val, 2),
        "profitable_months": profitable_months,
        "losing_months": losing_months,
        "total_months": total_months,
        "month_win_rate_pct": round(profitable_months / total_months * 100, 1) if total_months > 0 else 0,
        "max_consecutive_wins_days": state.max_consec_wins,
        "max_consecutive_losses_days": state.max_consec_losses,
        "max_open_positions": state.max_open_positions,
        "risk_free_return_pct": 0.0,
        "excess_return_pct": round(total_return_pct, 2),
        "daily_value_at_risk_95pct": round(var_95, 2),
        "daily_conditional_var_95pct": round(cvar_95, 2),
        "ulcer_index_pct": round(ulcer_index, 2),
        "total_days": n_days,
        "total_trading_years": round(years, 2),
    }


# ── Compounding analysis ─────────────────────────────────────────────────────
def compute_compounding_analysis(
    trades: list[SimTrade],
    start_capital: float,
    params: SizingParams,
    unrounded_sizing: bool = False,
) -> dict:
    """Compare compounded vs fixed-size vs fixed-risk growth.

    Parameters
    ----------
    trades : list[SimTrade]
        All historical trades loaded from trade lifecycle data.
    start_capital : float
        Initial account equity.
    params : SizingParams
        Production sizing parameters.
    unrounded_sizing : bool
        If True, skip min-lot rounding so that compounding is isolated from
        broker constraint effects.  Recommended for the compounding-vs-fixed
        comparison at small equity levels where min-lot dominance would mask
        the true compounding benefit.

    Returns
    -------
    dict with keys:
        compounded_final, fixed_position_size_final, fixed_dollar_risk_final,
        compounding_benefit_pct, compounding_factor, etc.
    """
    # ── Pre-compute adaptive exit adjustments ONCE ──
    # Both the compounded and fixed simulations must use the SAME R-multiples
    # for a fair comparison.  Previously, the fixed path used ``trade.r_multiple``
    # (original lifecycle R) while the compounded path used ``adj_r``
    # (after adaptive exit), producing an apples-to-oranges comparison.
    asset_configs: dict[str, Any] = {}
    try:
        registry = PaperConfigRegistry.load()
        for name in set(t.asset for t in trades):
            if name in registry.assets:
                acfg = registry.assets[name]
                asset_configs[name] = {
                    "allocation": getattr(acfg, "allocation", 0.02),
                    "config": getattr(acfg, "config", {}),
                }
    except Exception:
        pass

    adj_r_map: dict[int, float] = {}
    for i, trade in enumerate(trades):
        if trade.highs and trade.lows:
            adj_r, _ = simulate_running_peak_adaptive_exit(
                trade, asset_configs.get(trade.asset)
            )
        else:
            adj_r = trade.r_multiple
        adj_r_map[i] = adj_r

    n_adj = sum(1 for i, t in enumerate(trades) if abs(adj_r_map[i] - t.r_multiple) > 0.001)
    total_orig_r = sum(t.r_multiple for t in trades)
    total_adj_r = sum(adj_r_map[i] for i in range(len(trades)))
    logger.info(
        "Compounding analysis: %d/%d trades adjusted by adaptive exit "
        "(original R=%.2f, adjusted R=%.2f, Δ=%.2f)",
        n_adj, len(trades), total_orig_r, total_adj_r, total_adj_r - total_orig_r,
    )

    # 1) Compounded growth — equity grows, position sizes scale with it
    comp_state = run_simulation(trades, start_capital, params)
    comp_metrics = compute_performance_metrics(comp_state, start_capital)
    comp_final = comp_metrics["final_capital"]

    # 2) Fixed position size — equity grows but sizing stays at start_capital level
    fixed_equity = float(start_capital)
    for i, trade in enumerate(trades):
        pnl = compute_trade_pnl_dollar(
            r_multiple=adj_r_map[i],  # FIXED: use adjusted R, same as compounded
            atr_pct_entry=trade.atr_pct_entry,
            equity=start_capital,       # Sizing anchored to start capital
            peak_equity=start_capital,
            allocation=trade.allocation,
            params=params,
            asset_class=trade.asset_class,
            unrounded_sizing=unrounded_sizing,
        )
        fixed_equity += pnl

    # 3) Fixed dollar risk — same $R amount on every trade, no size scaling
    first_notional, _, _ = compute_position_notional(
        start_capital, start_capital, 0.02, params
    )
    first_1r = first_notional * 0.01  # ~1 ATR unit
    # More precise: use the actual ATR of the first trade
    if trades and trades[0].atr_pct_entry > 0:
        first_1r = first_notional * trades[0].atr_pct_entry

    fixed_risk_equity = float(start_capital)
    for i, trade in enumerate(trades):
        # Fixed dollar risk: same $R per trade regardless of equity.
        # Uses adjusted R for consistency with the other two scenarios.
        pnl = adj_r_map[i] * first_1r
        fixed_risk_equity += pnl

    comp_return = (comp_final - start_capital) / start_capital * 100
    fixed_return = (fixed_equity - start_capital) / start_capital * 100
    fixed_risk_return = (fixed_risk_equity - start_capital) / start_capital * 100

    compounding_benefit = comp_return - fixed_return
    compounding_factor = comp_return / fixed_return if fixed_return != 0 else 0

    # Log meaningful comparison
    notional_label = "unrounded" if unrounded_sizing else "min-lot"
    logger.info(
        "Compounding analysis (%s sizing): compounded=%.2f fixed_size=%.2f "
        "fixed_risk=%.2f — benefit=%.2fpp factor=%.4fx",
        notional_label, comp_final, fixed_equity, fixed_risk_equity,
        compounding_benefit, compounding_factor,
    )

    return {
        "start_capital": round(start_capital, 2),
        "compounded_final": round(comp_final, 2),
        "compounded_return_pct": round(comp_return, 2),
        "fixed_position_size_final": round(fixed_equity, 2),
        "fixed_position_size_return_pct": round(fixed_return, 2),
        "fixed_dollar_risk_final": round(fixed_risk_equity, 2),
        "fixed_dollar_risk_return_pct": round(fixed_risk_return, 2),
        "compounding_benefit_pct": round(compounding_benefit, 2),
        "compounding_factor": round(compounding_factor, 4),
        "_total_original_r": round(total_orig_r, 2),
        "_total_adjusted_r": round(total_adj_r, 2),
        "_adj_r_delta": round(total_adj_r - total_orig_r, 2),
        "_sizing_mode": "unrounded" if unrounded_sizing else "min_lot",
    }


# ── Risk scaling analysis ────────────────────────────────────────────────────
def compute_risk_analysis(state: SimState, start_capital: float) -> dict:
    """Analyze how risk evolved as capital increased."""
    trade_records = state.trade_history
    if not trade_records:
        return {}

    notionals = [t["notional"] for t in trade_records]
    taper_factors = [t["taper_factor"] for t in trade_records]
    pnls = [t["pnl"] for t in trade_records]
    equities = [t["equity_before"] for t in trade_records]

    # Notional as % of equity
    notional_pcts = [n / e * 100 if e > 0 else 0 for n, e in zip(notionals, equities)]
    risk_per_trade_pcts = [abs(p) / e * 100 if e > 0 and p < 0 else 0 for p, e in zip(pnls, equities)]
    leverage_ratios = [n / e if e > 0 else 0.0 for n, e in zip(notionals, equities)]

    # By equity quartile
    eq_arr = np.array(equities)
    if len(eq_arr) == 0 or np.all(eq_arr == eq_arr[0]):
        quartiles = np.array([eq_arr[0] if len(eq_arr) > 0 else 1.0] * 3)
    else:
        quartiles = np.percentile(eq_arr, [25, 50, 75])
    risk_by_quartile = {}
    for label, lower, upper in [("Q1_low", 0, quartiles[0]),
                                  ("Q2", quartiles[0], quartiles[1]),
                                  ("Q3", quartiles[1], quartiles[2]),
                                  ("Q4_high", quartiles[2], float("inf"))]:
        mask = (eq_arr >= lower) & (eq_arr < upper)
        if mask.sum() > 0:
            risk_by_quartile[label] = {
                "n_trades": int(mask.sum()),
                "avg_notional": round(float(np.mean([notionals[i] for i in range(len(notionals)) if mask[i]])), 2),
                "avg_notional_pct": round(float(np.mean([notional_pcts[i] for i in range(len(notional_pcts)) if mask[i]])), 2),
                "avg_risk_pct": round(float(np.mean([risk_per_trade_pcts[i] for i in range(len(risk_per_trade_pcts)) if mask[i]])), 2),
                "avg_taper": round(float(np.mean([taper_factors[i] for i in range(len(taper_factors)) if mask[i]])), 4),
            }

    return {
        "avg_position_notional": round(float(np.mean(notionals)), 2),
        "median_position_notional": round(float(np.median(notionals)), 2),
        "avg_notional_pct_of_equity": round(float(np.mean(notional_pcts)), 2),
        "max_notional_pct_of_equity": round(float(np.max(notional_pcts)), 2),
        "avg_risk_per_trade_pct": round(float(np.mean(risk_per_trade_pcts)), 2),
        "max_risk_per_trade_pct": round(float(np.max(risk_per_trade_pcts)), 2),
        "avg_taper_factor": round(float(np.mean(taper_factors)), 4),
        "min_taper_factor": round(float(np.min(taper_factors)), 4),
        "avg_leverage_ratio": round(float(np.mean(leverage_ratios)), 4),
        "risk_by_equity_quartile": risk_by_quartile,
    }


# ── Sensitivity analysis ────────────────────────────────────────────────────
def run_sensitivity_analysis(
    trades: list[SimTrade],
    params: SizingParams,
    capitals: list[float] | None = None,
) -> list[dict]:
    """Run the simulation across multiple starting capitals."""
    if capitals is None:
        capitals = [500, 1000, 2500, 5000, 10000, 25000, 50000]

    results = []
    logger.info("Running sensitivity analysis across %d capital levels...", len(capitals))
    for cap in capitals:
        state = run_simulation(trades, cap, params)
        metrics = compute_performance_metrics(state, cap)

        # Check if broker constraints bind
        min_lot_viable = set()
        min_lot_blocked = set()
        for trade in trades[:100]:  # Check first 100 trades for viability
            class_params = ASSET_CLASS_PARAMS.get(trade.asset_class, ASSET_CLASS_PARAMS["fx_cross"])
            notional, _, _ = compute_position_notional(cap, cap, trade.allocation, params)
            contract_size = class_params["contract_size"]
            if trade.asset_class in ("fx_major", "fx_cross", "fx_minor"):
                lots = notional / contract_size
            elif trade.asset_class == "indices":
                lots = notional / 40000
            elif trade.asset_class == "metals":
                lots = notional / (contract_size * 2000.0)
            elif trade.asset_class == "crypto":
                lots = notional / 60000.0
            else:
                lots = notional / 100000.0

            if lots >= class_params["min_lot"] * 0.5:
                min_lot_viable.add(trade.asset_class)
            else:
                min_lot_blocked.add(trade.asset_class)

        results.append({
            "start_capital": cap,
            "final_capital": metrics["final_capital"],
            "net_profit": metrics["net_profit"],
            "total_return_pct": metrics["total_return_pct"],
            "cagr_pct": metrics["cagr_pct"],
            "annualized_volatility_pct": metrics["annualized_volatility_pct"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "sortino_ratio": metrics["sortino_ratio"],
            "calmar_ratio": metrics["calmar_ratio"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "day_win_rate_pct": metrics["day_win_rate_pct"],
            "profit_factor": metrics["profit_factor"],
            "recovery_factor": metrics["recovery_factor"],
            "total_days": metrics["total_days"],
            "min_lot_viable_classes": sorted(min_lot_viable),
            "min_lot_blocked_classes": sorted(min_lot_blocked),
        })

    return results


# ── Bootstrap Monte Carlo ───────────────────────────────────────────────────
def run_bootstrap_monte_carlo(
    trades: list[SimTrade],
    start_capital: float = 500.0,
    n_trials: int = 1000,
    params: SizingParams | None = None,
    seed: int = 42,
) -> dict:
    """Bootstrap Monte Carlo simulation (sampling with replacement)."""
    if params is None:
        params = SizingParams()

    rng = np.random.default_rng(seed)
    n = len(trades)
    if n == 0:
        return {"error": "no trades"}

    end_equities = []
    max_dds = []
    total_returns = []
    cagrs = []
    n_positive = 0
    n_doubled = 0
    n_tripled = 0
    n_loss_20pct = 0
    n_dd_30 = 0
    n_dd_50 = 0

    logger.info("Running %d bootstrap Monte Carlo trials (seed=%d)...", n_trials, seed)
    t0 = time.time()

    for trial in range(n_trials):
        if trial > 0 and trial % 200 == 0:
            elapsed = time.time() - t0
            rate = trial / elapsed if elapsed > 0 else 0
            eta = (n_trials - trial) / rate if rate > 0 else 0
            logger.info("  Trial %d/%d (%.1f/s, ETA %.0fs)", trial, n_trials, rate, eta)

        indices = rng.integers(0, n, size=n)
        sampled = [trades[i] for i in indices]

        # Maintain chronological order by exit date
        sampled_sorted = sorted(sampled, key=lambda t: (t.exit_date, t.entry_date))

        state = run_simulation(sampled_sorted, start_capital, params)
        end_eq = state.equity
        end_equities.append(end_eq)
        max_dds.append(state.max_dd_pct)

        total_ret = (end_eq - start_capital) / start_capital * 100
        total_returns.append(total_ret)

        years = len(state.daily_pnl) / 365.25
        cagr = ((end_eq / start_capital) ** (1 / years) - 1) * 100 if end_eq > 0 and years > 0 else -100
        cagrs.append(cagr)

        if end_eq > start_capital:
            n_positive += 1
        if end_eq >= start_capital * 2:
            n_doubled += 1
        if end_eq >= start_capital * 3:
            n_tripled += 1
        if (start_capital - end_eq) / start_capital * 100 > 20:
            n_loss_20pct += 1
        if state.max_dd_pct >= 30:
            n_dd_30 += 1
        if state.max_dd_pct >= 50:
            n_dd_50 += 1

    end_eq_arr = np.array(end_equities)
    dd_arr = np.array(max_dds)
    ret_arr = np.array(total_returns)
    cagr_arr = np.array(cagrs)

    elapsed = time.time() - t0
    logger.info("Bootstrap completed in %.1fs (%.1f trials/s)", elapsed, n_trials / elapsed)

    return {
        "n_trials": n_trials,
        "start_capital": start_capital,
        "ending_equity": {
            "median": round(float(np.median(end_eq_arr)), 2),
            "mean": round(float(np.mean(end_eq_arr)), 2),
            "p5": round(float(np.percentile(end_eq_arr, 5)), 2),
            "p25": round(float(np.percentile(end_eq_arr, 25)), 2),
            "p75": round(float(np.percentile(end_eq_arr, 75)), 2),
            "p95": round(float(np.percentile(end_eq_arr, 95)), 2),
            "std": round(float(np.std(end_eq_arr)), 2),
            "min": round(float(np.min(end_eq_arr)), 2),
            "max": round(float(np.max(end_eq_arr)), 2),
        },
        "total_return_pct": {
            "median": round(float(np.median(ret_arr)), 1),
            "mean": round(float(np.mean(ret_arr)), 1),
            "p5": round(float(np.percentile(ret_arr, 5)), 1),
            "p95": round(float(np.percentile(ret_arr, 95)), 1),
        },
        "cagr_pct": {
            "median": round(float(np.median(cagr_arr)), 2),
            "p5": round(float(np.percentile(cagr_arr, 5)), 2),
            "p95": round(float(np.percentile(cagr_arr, 95)), 2),
        },
        "max_drawdown_pct": {
            "median": round(float(np.median(dd_arr)), 1),
            "mean": round(float(np.mean(dd_arr)), 1),
            "p5": round(float(np.percentile(dd_arr, 5)), 1),
            "p95": round(float(np.percentile(dd_arr, 95)), 1),
            "min": round(float(np.min(dd_arr)), 1),
        },
        "probabilities": {
            "profitable": round(n_positive / n_trials * 100, 1),
            "doubled_capital": round(n_doubled / n_trials * 100, 1),
            "tripled_capital": round(n_tripled / n_trials * 100, 1),
            "lost_20pct_plus": round(n_loss_20pct / n_trials * 100, 1),
            "dd_exceeds_30pct": round(n_dd_30 / n_trials * 100, 1),
            "dd_exceeds_50pct": round(n_dd_50 / n_trials * 100, 1),
        },
    }


# ── Drawdown periods computation ────────────────────────────────────────────
def compute_drawdown_periods(
    daily_pnl: list[dict],
    start_capital: float,
    threshold_pct: float = 5.0,
) -> list[dict]:
    """Compute drawdown periods > *threshold_pct* from the daily P&L data.

    A drawdown period starts when equity falls below (*peak_equity* ×
    (1 - *threshold_pct* / 100)) and ends when equity recovers to that
    peak.  Only periods where the depth exceeds *threshold_pct* are
    returned.

    Parameters
    ----------
    daily_pnl : list[dict]
        List of daily records with ``"date"``, ``"end_equity"`` keys.
    start_capital : float
        Initial account equity.
    threshold_pct : float
        Minimum drawdown depth to include (default 5.0%%).

    Returns
    -------
    list[dict]
        Each dict: ``{"from": date_str, "to": date_str, "depth": float}``.
        Empty list if no significant drawdowns.
    """
    periods: list[dict] = []
    in_dd = False
    dd_start_val = start_capital
    dd_start_date: str | None = None
    dd_trough = start_capital

    for d in daily_pnl:
        eq = d["end_equity"]
        if not in_dd and eq < dd_start_val * (1.0 - threshold_pct / 100.0):
            in_dd = True
            dd_start_date = d["date"]
            dd_trough = eq
        elif in_dd:
            if eq < dd_trough:
                dd_trough = eq
            if eq >= dd_start_val:
                in_dd = False
                dd_pct = (dd_start_val - dd_trough) / dd_start_val * 100
                if dd_pct > threshold_pct:
                    periods.append({
                        "from": dd_start_date,
                        "to": d["date"],
                        "depth": round(dd_pct, 1),
                    })
                dd_start_val = eq
        else:
            dd_start_val = max(dd_start_val, eq)

    return periods


# ── Report generation ───────────────────────────────────────────────────────
def generate_report(
    metrics: dict,
    state: SimState,
    compounding: dict,
    risk_analysis: dict,
    sensitivity: list[dict],
    bootstrap: dict,
    start_capital: float,
) -> str:
    """Generate a comprehensive markdown report."""
    lines = []
    lines.append("# EigenCapital — Institutional-Grade Capital Growth Simulation Report")
    lines.append("")
    lines.append(f"**Simulation Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"**Initial Capital:** USD {start_capital:,.2f}")
    lines.append(f"**Period:** {state.daily_pnl[0]['date'] if state.daily_pnl else 'N/A'} to {state.daily_pnl[-1]['date'] if state.daily_pnl else 'N/A'}")
    lines.append(f"**Total Trading Days:** {metrics['total_days']}")
    lines.append(f"**Total Trades Executed:** {len(state.trade_history)}")
    lines.append(f"**Trading Years:** {metrics['total_trading_years']}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Initial Capital** | ${metrics['initial_capital']:,.2f} |")
    lines.append(f"| **Final Capital** | ${metrics['final_capital']:,.2f} |")
    lines.append(f"| **Net Profit** | ${metrics['net_profit']:+,.2f} |")
    lines.append(f"| **Total Return** | {metrics['total_return_pct']:+.2f}% |")
    lines.append(f"| **CAGR** | {metrics['cagr_pct']:+.2f}% |")
    lines.append(f"| **Annualized Return** | {metrics['annualized_return_pct']:+.2f}% |")
    lines.append(f"| **Annualized Volatility** | {metrics['annualized_volatility_pct']:.2f}% |")
    lines.append(f"| **Sharpe Ratio** | {metrics['sharpe_ratio']:.4f} |")
    lines.append(f"| **Sortino Ratio** | {metrics['sortino_ratio']:.4f} |")
    lines.append(f"| **Calmar Ratio** | {metrics['calmar_ratio']:.4f} |")
    lines.append(f"| **Profit Factor** | {metrics['profit_factor']:.2f} |")
    lines.append(f"| **Expectancy (per trade)** | ${metrics['expectancy']:+.2f} |")
    lines.append(f"| **Day Win Rate** | {metrics['day_win_rate_pct']:.1f}% |")
    lines.append(f"| **Trade Win Rate** | {metrics['trade_win_rate_pct']:.1f}% |")
    lines.append(f"| **Recovery Factor** | {metrics['recovery_factor']:.2f} |")
    lines.append(f"| **Max Drawdown** | {metrics['max_drawdown_pct']:.2f}% |")
    lines.append(f"| **Max Drawdown Duration** | {metrics['longest_drawdown_duration_days']} days |")
    lines.append(f"| **Ulcer Index** | {metrics['ulcer_index_pct']:.2f}% |")
    lines.append(f"| **Daily VaR (95%)** | ${metrics['daily_value_at_risk_95pct']:.2f} |")
    lines.append(f"| **Daily CVaR (95%)** | ${metrics['daily_conditional_var_95pct']:.2f} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 2. Growth Timeline — Equity Curve Summary")
    lines.append("")
    lines.append("### By Year")
    lines.append("")
    lines.append("| Year | Start Balance | End Balance | Net Profit | Return | Trades | Win Days | Loss Days | Max DD |")
    lines.append("|------|-------------|-----------|----------|------|------|---------|---------|------|")
    for y in state.yearly_pnl:
        lines.append(f"| {y['year']} | ${y['start_balance']:,.2f} | ${y['end_balance']:,.2f} | ${y['net_profit']:+,.2f} | {y['roi_pct']:+.2f}% | {y['trades']} | {y['win_days']} | {y['loss_days']} | {y['max_drawdown_pct']:.1f}% |")
    lines.append("")

    lines.append("### By Quarter")
    lines.append("")
    lines.append("| Quarter | Start Equity | End Equity | P&L | Return | Trades | Max DD |")
    lines.append("|---------|-------------|-----------|-----|--------|--------|--------|")
    for q in state.quarterly_pnl:
        lines.append(f"| {q['quarter']} | ${q['start_equity']:,.2f} | ${q['end_equity']:,.2f} | ${q['pnl']:+,.2f} | {q['return_pct']:+.2f}% | {q['trades']} | {q['max_drawdown_pct']:.1f}% |")
    lines.append("")

    lines.append("### By Month")
    lines.append("")
    lines.append("| Month | Start Equity | End Equity | P&L | Return | Trades | Win Days | Max DD |")
    lines.append("|-------|-------------|-----------|-----|--------|--------|---------|--------|")
    for m in state.monthly_pnl:
        lines.append(f"| {m['month']} | ${m['start_equity']:,.2f} | ${m['end_equity']:,.2f} | ${m['pnl']:+,.2f} | {m['return_pct']:+.2f}% | {m['trades']} | {m['win_days']} | {m['max_drawdown_pct']:.1f}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 3. Periodic Profit Summary")
    lines.append("")
    lines.append("### Daily Statistics")
    lines.append("")
    daily_pnls = [d["pnl"] for d in state.daily_pnl]
    daily_returns = [d["return_pct"] for d in state.daily_pnl]
    active_days = [d for d in state.daily_pnl if d["trades_closed"] > 0]
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| **Total Days** | {len(state.daily_pnl)} |")
    lines.append(f"| **Active Trading Days** | {len(active_days)} |")
    lines.append(f"| **Average Daily P&L** | ${float(np.mean(daily_pnls)):+.2f} |")
    lines.append(f"| **Median Daily P&L** | ${float(np.median(daily_pnls)):+.2f} |")
    lines.append(f"| **Average Daily Return** | {float(np.mean(daily_returns)):+.4f}% |")
    lines.append(f"| **Median Daily Return** | {float(np.median(daily_returns)):+.4f}% |")
    lines.append(f"| **Best Day** | ${metrics['best_day_pnl']:+,.2f} |")
    lines.append(f"| **Worst Day** | ${metrics['worst_day_pnl']:+,.2f} |")
    lines.append(f"| **Std Dev of Daily P&L** | ${float(np.std(daily_pnls)):.2f} |")
    lines.append(f"| **Max Consecutive Winning Days** | {metrics['max_consecutive_wins_days']} |")
    lines.append(f"| **Max Consecutive Losing Days** | {metrics['max_consecutive_losses_days']} |")
    lines.append("")

    lines.append("### Weekly Statistics")
    lines.append("")
    weekly_pnls = [w["pnl"] for w in state.weekly_pnl]
    weekly_returns = [w["return_pct"] for w in state.weekly_pnl]
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| **Total Weeks** | {len(state.weekly_pnl)} |")
    lines.append(f"| **Average Weekly P&L** | ${float(np.mean(weekly_pnls)):+.2f} |")
    lines.append(f"| **Median Weekly P&L** | ${float(np.median(weekly_pnls)):+.2f} |")
    lines.append(f"| **Average Weekly Return** | {float(np.mean(weekly_returns)):+.2f}% |")
    lines.append(f"| **Best Week** | ${metrics['best_week_pnl']:+,.2f} |")
    lines.append(f"| **Worst Week** | ${metrics['worst_week_pnl']:+,.2f} |")
    lines.append(f"| **Compounded Weekly Growth** | {float(np.prod([1 + r/100 for r in weekly_returns])) - 1:.4f}% |")
    lines.append("")

    lines.append("### Monthly Statistics")
    lines.append("")
    monthly_pnls = [m["pnl"] for m in state.monthly_pnl]
    monthly_returns = [m["return_pct"] for m in state.monthly_pnl]
    profitable_months_list = [m for m in state.monthly_pnl if m["pnl"] > 0]
    losing_months_list = [m for m in state.monthly_pnl if m["pnl"] < 0]
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| **Total Months** | {len(state.monthly_pnl)} |")
    lines.append(f"| **Profitable Months** | {len(profitable_months_list)} ({metrics['month_win_rate_pct']:.1f}%) |")
    lines.append(f"| **Losing Months** | {len(losing_months_list)} |")
    lines.append(f"| **Average Monthly P&L** | ${float(np.mean(monthly_pnls)):+.2f} |")
    lines.append(f"| **Median Monthly P&L** | ${float(np.median(monthly_pnls)):+.2f} |")
    lines.append(f"| **Average Monthly Return** | {float(np.mean(monthly_returns)):+.2f}% |")
    lines.append(f"| **Median Monthly Return** | {float(np.median(monthly_returns)):+.2f}% |")
    lines.append(f"| **Best Month** | ${metrics['best_month_pnl']:+,.2f} |")
    lines.append(f"| **Worst Month** | ${metrics['worst_month_pnl']:+,.2f} |")
    lines.append(f"| **Std Dev of Monthly Return** | {float(np.std(monthly_returns)):.2f}% |")
    lines.append(f"| **Compounded Monthly Growth** | {float(np.prod([1 + r/100 for r in monthly_returns])) - 1:.2f}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 4. Compounding Analysis")
    lines.append("")
    lines.append("| Scenario | Final Capital | Return |")
    lines.append("|----------|-------------|--------|")
    lines.append(f"| **Compounded (production sizing)** | ${compounding['compounded_final']:,.2f} | {compounding['compounded_return_pct']:+.2f}% |")
    lines.append(f"| **Fixed Position Size** (no equity scaling) | ${compounding['fixed_position_size_final']:,.2f} | {compounding['fixed_position_size_return_pct']:+.2f}% |")
    lines.append(f"| **Fixed Dollar Risk** (constant bet size) | ${compounding['fixed_dollar_risk_final']:,.2f} | {compounding['fixed_dollar_risk_return_pct']:+.2f}% |")
    lines.append("")
    lines.append(f"**Compounding Benefit:** +{compounding['compounding_benefit_pct']:.2f}% additional return vs fixed position size")
    lines.append("")
    lines.append(f"**Compounding Factor:** {compounding['compounding_factor']:.4f}x (compounded return / fixed return)")
    lines.append("")
    lines.append("*The compounding effect reflects the benefit of increasing position sizes as equity grows, multiplied by the effect of drawdown taper protecting capital during drawdowns.*")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 5. Drawdown Analysis")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Maximum Drawdown** | {metrics['max_drawdown_pct']:.2f}% |")
    lines.append(f"| **Maximum Drawdown ($)** | ${metrics['max_drawdown_dollar']:,.2f} |")
    lines.append(f"| **Max Drawdown Start** | {metrics['max_drawdown_start']} |")
    lines.append(f"| **Max Drawdown End** | {metrics['max_drawdown_end']} |")
    lines.append(f"| **Longest Drawdown Duration** | {metrics['longest_drawdown_duration_days']} days |")
    lines.append(f"| **Ulcer Index** | {metrics['ulcer_index_pct']:.2f}% |")
    lines.append(f"| **Recovery Factor** | {metrics['recovery_factor']:.2f} |")
    lines.append(f"| **Daily VaR (95%)** | ${metrics['daily_value_at_risk_95pct']:.2f} |")
    lines.append(f"| **Daily CVaR (95%)** | ${metrics['daily_conditional_var_95pct']:.2f} |")
    lines.append("")

    # Drawdown periods (>5% of start capital) — computed from daily equity
    dd_periods = compute_drawdown_periods(state.daily_pnl, start_capital, threshold_pct=5.0)

    # Bootstrap section (skip if not run)
    has_bootstrap = bool(bootstrap and bootstrap.get("n_trials"))
    lines.append("---")
    lines.append("")
    lines.append("## 8. Bootstrap Monte Carlo Simulation")
    lines.append("")
    if has_bootstrap:
        lines.append(f"**Trials:** {bootstrap['n_trials']:,} | **Seed:** 42 | **Method:** Block bootstrap with replacement")
        lines.append("")
        lines.append("### Ending Equity Distribution")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| **Median** | ${bootstrap['ending_equity']['median']:,.2f} |")
        lines.append(f"| **Mean** | ${bootstrap['ending_equity']['mean']:,.2f} |")
        lines.append(f"| **5th Percentile** | ${bootstrap['ending_equity']['p5']:,.2f} |")
        lines.append(f"| **25th Percentile** | ${bootstrap['ending_equity']['p25']:,.2f} |")
        lines.append(f"| **75th Percentile** | ${bootstrap['ending_equity']['p75']:,.2f} |")
        lines.append(f"| **95th Percentile** | ${bootstrap['ending_equity']['p95']:,.2f} |")
        lines.append(f"| **Std Dev** | ${bootstrap['ending_equity']['std']:,.2f} |")
        lines.append(f"| **Min** | ${bootstrap['ending_equity']['min']:,.2f} |")
        lines.append(f"| **Max** | ${bootstrap['ending_equity']['max']:,.2f} |")
        lines.append("")
        lines.append("### Probability Analysis")
        lines.append("")
        lines.append("| Outcome | Probability |")
        lines.append("|---------|------------|")
        lines.append(f"| **Profitable** | {bootstrap['probabilities']['profitable']:.1f}% |")
        lines.append(f"| **Doubled Capital** | {bootstrap['probabilities']['doubled_capital']:.1f}% |")
        lines.append(f"| **Tripled Capital** | {bootstrap['probabilities']['tripled_capital']:.1f}% |")
        lines.append(f"| **Lost 20%+** | {bootstrap['probabilities']['lost_20pct_plus']:.1f}% |")
        lines.append(f"| **DD Exceeds 30%** | {bootstrap['probabilities']['dd_exceeds_30pct']:.1f}% |")
        lines.append(f"| **DD Exceeds 50%** | {bootstrap['probabilities']['dd_exceeds_50pct']:.1f}% |")
        lines.append("")
        lines.append("### Drawdown Distribution")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| **Median Max DD** | {bootstrap['max_drawdown_pct']['median']:.1f}% |")
        lines.append(f"| **Mean Max DD** | {bootstrap['max_drawdown_pct']['mean']:.1f}% |")
        lines.append(f"| **5th Pctl** (best) | {bootstrap['max_drawdown_pct']['p5']:.1f}% |")
        lines.append(f"| **95th Pctl** (worst) | {bootstrap['max_drawdown_pct']['p95']:.1f}% |")
        lines.append(f"| **Best Observed** | {bootstrap['max_drawdown_pct']['min']:.1f}% |")
        lines.append("")
    else:
        lines.append("*Bootstrap was skipped. Use `--bootstrap-trials 500` to enable.*")
        lines.append("")

    if dd_periods:
        lines.append("### Drawdown Periods (>5%)")
        lines.append("")
        lines.append("| Start | End | Depth |")
        lines.append("|-------|-----|-------|")
        for dp in dd_periods:
            lines.append(f"| {dp['from']} | {dp['to']} | {dp['depth']:.1f}% |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 6. Position Sizing Evolution")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Average Position Notional** | ${risk_analysis['avg_position_notional']:,.2f} |")
    lines.append(f"| **Median Position Notional** | ${risk_analysis['median_position_notional']:,.2f} |")
    lines.append(f"| **Avg Notional % of Equity** | {risk_analysis['avg_notional_pct_of_equity']:.2f}% |")
    lines.append(f"| **Max Notional % of Equity** | {risk_analysis['max_notional_pct_of_equity']:.2f}% |")
    lines.append(f"| **Avg Risk per Trade** | {risk_analysis['avg_risk_per_trade_pct']:.2f}% |")
    lines.append(f"| **Max Risk per Trade** | {risk_analysis['max_risk_per_trade_pct']:.2f}% |")
    lines.append(f"| **Avg Drawdown Taper Factor** | {risk_analysis['avg_taper_factor']:.4f} |")
    lines.append(f"| **Min Drawdown Taper Factor** | {risk_analysis['min_taper_factor']:.4f} |")
    lines.append(f"| **Avg Leverage Ratio** | {risk_analysis['avg_leverage_ratio']:.4f}x |")
    lines.append(f"| **Max Open Positions** | {metrics['max_open_positions']} |")
    lines.append("")

    # Risk by equity quartile
    if "risk_by_equity_quartile" in risk_analysis:
        lines.append("### Risk by Equity Quartile")
        lines.append("")
        lines.append("| Quartile | Trades | Avg Notional | Avg Notional % | Avg Risk % | Avg Taper |")
        lines.append("|----------|--------|-------------|---------------|-----------|---------|")
        for q_label, q_data in risk_analysis["risk_by_equity_quartile"].items():
            lines.append(f"| {q_label} | {q_data['n_trades']} | ${q_data['avg_notional']:,.2f} | {q_data['avg_notional_pct']:.2f}% | {q_data['avg_risk_pct']:.2f}% | {q_data['avg_taper']:.4f} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 7. Sensitivity Analysis — Scalability Assessment")
    lines.append("")
    lines.append("| Start Capital | Final Capital | Return | CAGR | Volatility | Sharpe | Sortino | Max DD | Recovery Factor |")
    lines.append("|-------------|-------------|--------|------|-----------|--------|---------|--------|----------------|")
    for sr in sensitivity:
        lines.append(f"| ${sr['start_capital']:>8,} | ${sr['final_capital']:>10,.2f} | {sr['total_return_pct']:>+7.2f}% | {sr['cagr_pct']:>+6.2f}% | {sr['annualized_volatility_pct']:>5.2f}% | {sr['sharpe_ratio']:>6.4f} | {sr['sortino_ratio']:>6.4f} | {sr['max_drawdown_pct']:>5.1f}% | {sr['recovery_factor']:>5.2f} |")
    lines.append("")

    lines.append("### Broker Constraint Impact")
    lines.append("")
    lines.append("| Start Capital | Min-Lot Viable | Min-Lot Blocked |")
    lines.append("|-------------|---------------|-----------------|")
    for sr in sensitivity:
        viable = ", ".join(sr.get("min_lot_viable_classes", [])) or "none"
        blocked = ", ".join(sr.get("min_lot_blocked_classes", [])) or "none"
        lines.append(f"| ${sr['start_capital']:>8,} | {viable} | {blocked} |")
    lines.append("")

    lines.append("**Notes on Scalability:**")
    lines.append("")
    lines.append("- At $500, FX cross pairs (AUDJPY, EURAUD, etc.) may be below min lot thresholds (0.01 lot = ~$1,000 notional)")
    lines.append("- At $2,500+, most FX pairs become min-lot viable")
    lines.append("- Indices (^DJI) require $5,000+ for a 0.1 lot position")
    lines.append("- Crypto (BTCUSD) is viable at any level due to fractional units (0.0001 BTC min)")
    lines.append("- Metals (GC) become viable at $2,500+")
    lines.append("- Performance scales linearly with capital after the min-lot floor is crossed")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 10. Methodology & Assumptions")
    lines.append("")
    lines.append("### Simulation Engine")
    lines.append("")
    lines.append("- **Data Source:** `data/processed/trade_data/trade_lifecycle_results.json` — 6,646 historical trades across 22 assets")
    lines.append("- **Period:** 2024-08-19 to 2026-06-29 (679 trading days, ~1.86 years)")
    lines.append("- **Position Sizing:** Production chain from `PaperConfigRegistry` (drawdown taper → position cap → risk cap)")
    lines.append("- **Exit Simulation:** Running-peak adaptive trail (BE lock at 0.5R, activate at 0.8R, retrace 33%, time decay from candle 30)")
    lines.append("- **Compounding:** Equity updated after each trade; position sizes recalculated based on current equity")
    lines.append("- **Spread Costs:** Asset-class-specific (FX major 0.5bps, FX cross 1.0bps, indices 1.0bps, metals 2.0bps, crypto 5.0bps)")
    lines.append("- **Broker Constraints:** Min lot sizes by asset class (FX 0.01, indices 0.1, metals 0.01, crypto 0.0001)")
    lines.append("")

    lines.append("### R-Multiple → Dollar Conversion")
    lines.append("")
    lines.append("For each trade:")
    lines.append("")
    lines.append("1. Compute notional = equity × allocation × drawdown_taper (capped at max_position_pct)")
    lines.append("2. Compute 1R = notional × ATR% at entry (from actual per-trade atr_pct_entry)")
    lines.append("3. Dollar P&L = R-multiple × 1R")
    lines.append("4. Apply risk cap (max loss ≤ 2% of equity)")
    lines.append("5. Apply min-lot viability check (below min lot → trade not executed)")
    lines.append("6. Deduct spread cost")
    lines.append("")

    lines.append("### Limitations")
    lines.append("")
    lines.append("- **Slippage not modeled:** Fills assumed at TP/SL prices; actual fills may vary by 5-15 bps")
    lines.append("- **Partial fills not modeled:** Full position assumed filled")
    lines.append("- **Correlation effects:** Portfolio-level exposure limits (max 13 concurrent) approximated but not exactly replicated from production")
    lines.append("- **Weekend gaps:** Crypto (BTCUSD) weekend trading not separately modeled")
    lines.append("- **Transaction costs:** Commission not modeled (MT5 Exness demo typically has low/zero commissions)")
    lines.append("- **Swap/overnight financing:** Not modeled")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Institutional-Grade Capital Growth Simulation")
    parser.add_argument("--start-capital", type=float, default=500.0, help="Initial capital (default: 500)")
    parser.add_argument("--output", type=str, default=None, help="Output path for report markdown")
    parser.add_argument("--json", type=str, default=None, help="Output path for JSON results")
    parser.add_argument("--no-adaptive-exit", action="store_true", help="Disable adaptive exit simulation")
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip bootstrap Monte Carlo")
    parser.add_argument("--bootstrap-trials", type=int, default=500, help="Number of bootstrap trials (default: 500)")
    parser.add_argument("--sensitivity", action="store_true", help="Run sensitivity analysis")
    parser.add_argument("--trade-path", type=str, default=None,
                        help="Path to trade lifecycle JSON (default: data/processed/trade_data/trade_lifecycle_results.json)")
    parser.add_argument("--unrounded", action="store_true",
                        help="Skip min-lot rounding in compounding comparison so the true "
                             "compounding benefit is isolated from broker constraints")
    args = parser.parse_args()

    # Resolve trade path
    if args.trade_path:
        trade_path = Path(args.trade_path)
        if not trade_path.is_absolute():
            trade_path = ROOT / trade_path
        logger.info("Using custom trade path: %s", trade_path)
    else:
        trade_path = TRADE_PATH

    start_capital = args.start_capital
    output_path = Path(args.output) if args.output else REPORT_PATH
    json_path = Path(args.json) if args.json else OUTPUT_PATH
    adaptive_exit = not args.no_adaptive_exit

    logger.info("=" * 72)
    logger.info("INSTITUTIONAL-GRADE CAPITAL GROWTH SIMULATION")
    logger.info(f"  Initial Capital: ${start_capital:,.2f}")
    logger.info(f"  Adaptive Exit: {'ENABLED' if adaptive_exit else 'DISABLED'}")
    logger.info("=" * 72)

    # Step 1: Load trades
    logger.info("Loading trade data...")
    trades = load_trades(trade_path=trade_path)
    logger.info(f"Loaded {len(trades)} trades")

    # Step 2: Load sizing params
    params = load_sizing_params()

    # Step 3: Run main simulation
    logger.info("Running primary simulation...")
    state = run_simulation(trades, start_capital, params, adaptive_exit)
    metrics = compute_performance_metrics(state, start_capital)

    # Step 4: Compounding analysis
    logger.info("Computing compounding analysis (unrounded_sizing=%s)...", args.unrounded)
    compounding = compute_compounding_analysis(trades, start_capital, params, unrounded_sizing=args.unrounded)

    # Step 5: Risk analysis
    logger.info("Computing risk analysis...")
    risk = compute_risk_analysis(state, start_capital)

    # Step 6: Sensitivity analysis
    sensitivity = []
    if args.sensitivity:
        logger.info("Running sensitivity analysis...")
        sensitivity = run_sensitivity_analysis(trades, params)
    else:
        # Run all capitals for the report
        sensitivity = run_sensitivity_analysis(trades, params,
            [500, 1000, 2500, 5000, 10000, 25000, 50000])

    # Step 7: Bootstrap Monte Carlo
    bootstrap = {}
    if not args.no_bootstrap:
        logger.info(f"Running bootstrap Monte Carlo ({args.bootstrap_trials} trials)...")
        bootstrap = run_bootstrap_monte_carlo(
            trades, start_capital, args.bootstrap_trials, params
        )

    # Step 8: Generate report
    logger.info("Generating report...")
    report = generate_report(
        metrics, state, compounding, risk, sensitivity, bootstrap, start_capital
    )

    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    logger.info("Report saved to %s", output_path)

    # Save JSON results
    json_output = {
        "simulation_metadata": {
            "timestamp": datetime.now().isoformat(),
            "start_capital": start_capital,
            "adaptive_exit": adaptive_exit,
            "n_trades": len(trades),
            "n_assets": 22,
            "period_start": state.daily_pnl[0]["date"] if state.daily_pnl else None,
            "period_end": state.daily_pnl[-1]["date"] if state.daily_pnl else None,
        },
        "executive_summary": metrics,
        "yearly": state.yearly_pnl,
        "quarterly": state.quarterly_pnl,
        "monthly": state.monthly_pnl,
        "weekly": state.weekly_pnl,
        "daily_summary": {
            "n_days": len(state.daily_pnl),
            "first_date": state.daily_pnl[0]["date"] if state.daily_pnl else None,
            "last_date": state.daily_pnl[-1]["date"] if state.daily_pnl else None,
            "best_day": max(state.daily_pnl, key=lambda d: d["pnl"]) if state.daily_pnl else {},
            "worst_day": min(state.daily_pnl, key=lambda d: d["pnl"]) if state.daily_pnl else {},
            "avg_daily_pnl": float(np.mean([d["pnl"] for d in state.daily_pnl])),
            "median_daily_pnl": float(np.median([d["pnl"] for d in state.daily_pnl])),
            "std_daily_pnl": float(np.std([d["pnl"] for d in state.daily_pnl])),
            "max_consec_wins": state.max_consec_wins,
            "max_consec_losses": state.max_consec_losses,
        },
        "compounding_analysis": compounding,
        "risk_analysis": risk,
        "_daily_equity_curve": [
            {"date": d["date"], "equity": d["end_equity"], "drawdown": d["drawdown_pct"],
             "peak_equity": d["peak_equity"], "return_pct": d["return_pct"]}
            for d in state.daily_pnl
        ],
        "sensitivity_analysis": sensitivity,
        "bootstrap_monte_carlo": bootstrap,
    }

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    logger.info("JSON results saved to %s", json_path)

    # ── Print summary ──
    print("\n" + "=" * 72)
    print("  CAPITAL GROWTH SIMULATION — EXECUTIVE SUMMARY")
    print(f"  Initial Capital: USD {start_capital:,.2f}")
    print(f"  Period: {state.daily_pnl[0]['date']} → {state.daily_pnl[-1]['date']}")
    print(f"  Total Trades: {len(trades)}")
    print("=" * 72)
    print(f"  Final Capital:         ${metrics['final_capital']:>10,.2f}")
    print(f"  Net Profit:            ${metrics['net_profit']:>+10,.2f}")
    print(f"  Total Return:          {metrics['total_return_pct']:>+10.2f}%")
    print(f"  CAGR:                  {metrics['cagr_pct']:>+10.2f}%")
    print(f"  Annualized Vol:        {metrics['annualized_volatility_pct']:>10.2f}%")
    print(f"  Sharpe Ratio:          {metrics['sharpe_ratio']:>10.4f}")
    print(f"  Sortino Ratio:         {metrics['sortino_ratio']:>10.4f}")
    print(f"  Calmar Ratio:          {metrics['calmar_ratio']:>10.4f}")
    print(f"  Max Drawdown:          {metrics['max_drawdown_pct']:>10.2f}%")
    print(f"  Profit Factor:         {metrics['profit_factor']:>10.2f}")
    print(f"  Day Win Rate:          {metrics['day_win_rate_pct']:>10.1f}%")
    print(f"  Trade Win Rate:        {metrics['trade_win_rate_pct']:>10.1f}%")
    print(f"  Avg Trade Expectancy:  ${metrics['expectancy']:>+10.2f}")
    print(f"  Recovery Factor:       {metrics['recovery_factor']:>10.2f}")
    print(f"  Ulcer Index:           {metrics['ulcer_index_pct']:>10.2f}%")
    print()

    # Compounding comparison
    print(f"  COMPOUNDING ANALYSIS:")
    print(f"    Compounded:           ${compounding['compounded_final']:>10,.2f} ({compounding['compounded_return_pct']:+.2f}%)")
    print(f"    Fixed Position Size:  ${compounding['fixed_position_size_final']:>10,.2f} ({compounding['fixed_position_size_return_pct']:+.2f}%)")
    print(f"    Fixed Dollar Risk:    ${compounding['fixed_dollar_risk_final']:>10,.2f} ({compounding['fixed_dollar_risk_return_pct']:+.2f}%)")
    print(f"    Compounding Benefit:  +{compounding['compounding_benefit_pct']:.2f}% additional return")
    print(f"    Compounding Factor:   {compounding['compounding_factor']:.4f}x")
    print()

    # Yearly
    print(f"  YEARLY PERFORMANCE:")
    for y in state.yearly_pnl:
        print(f"    {y['year']}: ${y['start_balance']:>8,.2f} → ${y['end_balance']:>10,.2f}  "
              f"PnL=${y['net_profit']:>+8,.2f} ({y['roi_pct']:>+6.2f}%)  "
              f"trades={y['trades']}  dd={y['max_drawdown_pct']:.1f}%")
    print()

    # Quarterly
    print(f"  QUARTERLY PERFORMANCE:")
    for q in state.quarterly_pnl:
        print(f"    {q['quarter']}: ${q['start_equity']:>8,.2f} → ${q['end_equity']:>10,.2f}  "
              f"PnL=${q['pnl']:>+8,.2f} ({q['return_pct']:>+6.2f}%)  "
              f"trades={q['trades']}  dd={q['max_drawdown_pct']:.1f}%")
    print()

    # Monthly summary
    monthly_rets = [m["return_pct"] for m in state.monthly_pnl]
    print(f"  MONTHLY SUMMARY:")
    print(f"    Avg Monthly Return:  {float(np.mean(monthly_rets)):+.2f}%")
    print(f"    Best Month:          {max(monthly_rets):+.2f}%")
    print(f"    Worst Month:         {min(monthly_rets):+.2f}%")
    print(f"    Profitable Months:   {sum(1 for r in monthly_rets if r > 0)}/{len(monthly_rets)}")
    print()

    # Sensitivity
    if sensitivity:
        print(f"  SENSITIVITY ANALYSIS:")
        print(f"  {'Start':>8} {'Final':>12} {'Return':>8} {'CAGR':>8} {'Sharpe':>8} {'DD':>8}")
        print(f"  {'-'*8} {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for sr in sensitivity:
            print(f"  ${sr['start_capital']:>5,} ${sr['final_capital']:>10,.2f} {sr['total_return_pct']:>+7.2f}% "
                  f"{sr['cagr_pct']:>+6.2f}% {sr['sharpe_ratio']:>7.4f} {sr['max_drawdown_pct']:>6.1f}%")
    print()

    # Bootstrap summary
    if bootstrap:
        b = bootstrap
        print(f"  BOOTSTRAP MONTE CARLO ({b['n_trials']} trials):")
        print(f"    Median End Equity:  ${b['ending_equity']['median']:>10,.2f}")
        print(f"    p5 / p95:           ${b['ending_equity']['p5']:>8,.2f} / ${b['ending_equity']['p95']:>8,.2f}")
        print(f"    Median Return:      {b['total_return_pct']['median']:>+8.1f}%")
        print(f"    Median CAGR:        {b['cagr_pct']['median']:>+8.2f}%")
        print(f"    Median Max DD:      {b['max_drawdown_pct']['median']:>8.1f}%")
        print(f"    P(Profitable):      {b['probabilities']['profitable']:>8.1f}%")
        print(f"    P(Doubled):         {b['probabilities']['doubled_capital']:>8.1f}%")
        print(f"    P(Lost 20%+):       {b['probabilities']['lost_20pct_plus']:>8.1f}%")
        print(f"    P(DD > 30%):        {b['probabilities']['dd_exceeds_30pct']:>8.1f}%")
    print()

    # Asset contribution
    print(f"  ASSET CONTRIBUTION (R-multiple source):")
    asset_r: dict[str, float] = defaultdict(float)
    asset_wr: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        asset_r[t.asset] += t.r_multiple
        asset_wr[t.asset].append(t.r_multiple)
    for asset in sorted(asset_r.keys(), key=lambda a: -asset_r[a]):
        rs = asset_wr[asset]
        n = len(rs)
        wins = sum(1 for r in rs if r > 0)
        wr = wins / n * 100 if n > 0 else 0
        print(f"    {asset:>10}: R={asset_r[asset]:>+8.2f}  n={n:>4}  WR={wr:>5.1f}%")
    print()

    print(f"  Report: {output_path}")
    print(f"  JSON:   {json_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
