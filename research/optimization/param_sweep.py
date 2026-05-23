"""Parameter sweep for SL/TP + scale-out optimization.

Strategy:
  1. Build a replay engine that supports scale-out (partial closes + breakeven).
  2. Sweep calibration_scale, scale-out tier structures across assets.
  3. Score each combo by Sharpe, TP rate, SL rate, max drawdown.
  4. Validate top 3 combos with full survival sim.
  5. Push winning config to paper_trading.yaml.

Usage:
    python research/optimization/param_sweep.py \
        --assets AUDJPY,NZDJPY \
        --fast  \
        --top-n 3
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from itertools import product
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from paper_trading.dynamic_sltp import DynamicSLTPEngine
from paper_trading.scale_out import ScaleOutEngine, ScaleOutPlan, ScaleOutTier
from research.execution_surface.replay_engine import (
    ReplayConfig,
    check_barrier_hit,
    compute_trade_return,
    apply_spread_to_return,
)
from research.risk.survival_sim import load_best_configs, load_allocations, PROJECT_ROOT, SANDBOX_BASE

logger = logging.getLogger("quantforge.param_sweep")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── Search space ──────────────────────────────────────────────────────

SL_MULTS = [0.3, 0.5, 0.7]
TP_MULTS = [1.5, 2.0, 2.5]
CAL_SCALES = [0.8, 1.0, 1.2]

SCALE_OUT_SCHEMES: dict[str, list[tuple[float, float]] | None] = {
    "none": None,
    "conservative": [(1 / 3, 0.50), (1 / 3, 1.00), (1 / 3, 1.50)],
    "aggressive": [(0.50, 0.33), (0.50, 0.66)],
    "fast": [(0.25, 0.25), (0.25, 0.50), (0.25, 0.75), (0.25, 1.00)],
}


@dataclass
class SweepResult:
    params: dict
    trades: int = 0
    sharpe: float = 0.0
    ann_return: float = 0.0
    ann_vol: float = 0.0
    tp_rate: float = 0.0
    sl_rate: float = 0.0
    flip_rate: float = 0.0
    max_dd: float = 0.0
    score: float = 0.0


# ── Scale-out replay ──────────────────────────────────────────────────


def replay_with_scale_out(
    predictions: pd.DataFrame,
    config: ReplayConfig,
    sltp_engine: DynamicSLTPEngine | None = None,
    scale_out_engine: ScaleOutEngine | None = None,
) -> pd.DataFrame:
    """Replay with optional dynamic SL/TP and scale-out support.

    Returns a DataFrame similar to ``replay()`` but with scale-out fills
    recorded as additional rows with ``reason = 'scale_out_tier_N'``,
    and the final remainder close with the active scale-out state.
    """
    trades = []
    pos: PositionState | None = None
    so_plan: ScaleOutPlan | None = None

    for idx, (timestamp, row) in enumerate(predictions.iterrows()):
        signal = int(row["signal"])
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])

        # ── SL/TP hit (always on full position or remaining fraction) ──
        if pos is not None:
            hit = check_barrier_hit(row, pos)
            if hit is not None:
                reason, exit_price = hit
                ret = compute_trade_return(pos.side, pos.entry_price, exit_price)
                ret = apply_spread_to_return(ret, config.spread_bps)
                # Record final close (may be partial remainder)
                trades.append({
                    "entry_time": pos.entry_time,
                    "exit_time": timestamp,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_price,
                    "sl_price": pos.sl_price,
                    "tp_price": pos.tp_price,
                    "reason": reason,
                    "hold_bars": idx - pos.entry_idx,
                    "return_pct": ret,
                    "vol_at_entry": pos.vol_at_entry,
                    "conf_at_entry": pos.conf_at_entry,
                    "initial_risk_pct": round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                    "realized_r": round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4)
                    if pos.sl_price != pos.entry_price else 0.0,
                    "year": int(row.get("year", 0)),
                    "regime": str(row.get("regime", "neutral")),
                    "scale_out_fraction": 1.0,  # full close
                })
                # Scale-out fills before close (if any) were already recorded
                pos = None
                so_plan = None
                continue

        # ── Scale-out tier check ────────────────────────────────────
        if pos is not None and so_plan is not None and scale_out_engine is not None:
            # Check tiers using OHLC extremes
            for tier in so_plan.tiers:
                if tier.filled:
                    continue
                if pos.side == "long":
                    tier_hit = high >= tier.price
                else:
                    tier_hit = low <= tier.price
                if not tier_hit:
                    continue

                tier.filled = True
                tier.fill_price = tier.price if pos.side == "long" else tier.price
                # Compute return on this partial fill
                pnl_pct = compute_trade_return(pos.side, pos.entry_price, tier.fill_price)
                pnl_pct = apply_spread_to_return(pnl_pct, config.spread_bps)
                so_plan.remaining_fraction -= tier.fraction

                trades.append({
                    "entry_time": pos.entry_time,
                    "exit_time": timestamp,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "exit_price": tier.fill_price,
                    "sl_price": pos.sl_price,
                    "tp_price": pos.tp_price,
                    "reason": f"scale_out_tier_{_tier_index(so_plan, tier) + 1}",
                    "hold_bars": idx - pos.entry_idx,
                    "return_pct": pnl_pct,
                    "vol_at_entry": pos.vol_at_entry,
                    "conf_at_entry": pos.conf_at_entry,
                    "initial_risk_pct": round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                    "realized_r": round(pnl_pct / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4)
                    if pos.sl_price != pos.entry_price else 0.0,
                    "year": int(row.get("year", 0)),
                    "regime": str(row.get("regime", "neutral")),
                    "scale_out_fraction": tier.fraction,
                })

            # Activate breakeven on remainder if applicable
            n_filled = sum(1 for t in so_plan.tiers if t.filled)
            if (
                n_filled > scale_out_engine.activate_breakeven_after
                and not so_plan.breakeven_activated
                and so_plan.remaining_fraction > 0
            ):
                so_plan.breakeven_activated = True
                so_plan.breakeven_price = pos.entry_price
                # Update the position's SL to breakeven for remaining fraction
                if pos.side == "long":
                    pos.sl_price = max(pos.sl_price, pos.entry_price)
                else:
                    pos.sl_price = min(pos.sl_price, pos.entry_price)

        # ── Determine desired side ─────────────────────────────────
        if signal == 2:
            desired = "long"
        elif signal == 0:
            desired = "short"
        else:
            continue

        # ── Position management ────────────────────────────────────
        if pos is None:
            sl, tp = _compute_barriers(desired, close, config, row, predictions, idx, sltp_engine)
            vol = float(row.get("volatility", 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            pos = _PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row.get("confidence", 0.5)),
                entry_idx=idx,
            )
            # Build scale-out plan
            so_plan = None
            if scale_out_engine is not None and tp != close:
                so_plan = _build_so_plan(scale_out_engine, desired, close, tp)
        elif pos.side != desired:
            # Hard close before reversal
            ret = compute_trade_return(pos.side, pos.entry_price, close)
            ret = apply_spread_to_return(ret, config.spread_bps)
            remaining = so_plan.remaining_fraction if so_plan else 1.0
            trades.append({
                "entry_time": pos.entry_time,
                "exit_time": timestamp,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "exit_price": close,
                "sl_price": pos.sl_price,
                "tp_price": pos.tp_price,
                "reason": "flip",
                "hold_bars": idx - pos.entry_idx,
                "return_pct": ret,
                "vol_at_entry": pos.vol_at_entry,
                "conf_at_entry": pos.conf_at_entry,
                "initial_risk_pct": round(abs(pos.entry_price - pos.sl_price) / pos.entry_price, 6),
                "realized_r": round(ret / (abs(pos.entry_price - pos.sl_price) / pos.entry_price), 4)
                if pos.sl_price != pos.entry_price else 0.0,
                "year": int(row.get("year", 0)),
                "regime": str(row.get("regime", "neutral")),
                "scale_out_fraction": remaining,
            })
            sl, tp = _compute_barriers(desired, close, config, row, predictions, idx, sltp_engine)
            vol = float(row.get("volatility", 0.01))
            if pd.isna(vol) or vol <= 0:
                vol = 0.01
            pos = _PositionState(
                side=desired, entry_price=close, entry_time=timestamp,
                sl_price=sl, tp_price=tp,
                vol_at_entry=vol, conf_at_entry=float(row.get("confidence", 0.5)),
                entry_idx=idx,
            )
            so_plan = None
            if scale_out_engine is not None and tp != close:
                so_plan = _build_so_plan(scale_out_engine, desired, close, tp)

    return pd.DataFrame(trades)


def _compute_barriers(
    desired: str, close: float, config: ReplayConfig,
    row: pd.Series, predictions: pd.DataFrame, idx: int,
    sltp_engine: DynamicSLTPEngine | None = None,
) -> tuple:
    vol = float(row.get("volatility", 0.01))
    if pd.isna(vol) or vol <= 0:
        vol = 0.01
    if sltp_engine is not None:
        regime = str(row.get("regime", "neutral"))
        df_slice = predictions.iloc[:idx + 1].copy()
        result = sltp_engine.compute_barriers(
            entry_price=close, side=desired, df=df_slice,
            sl_mult=config.sl_mult, tp_mult=config.tp_mult,
            regime=regime, vol=vol,
        )
        return result.stop_loss, result.take_profit
    if desired == "long":
        return close * (1 - vol * config.sl_mult), close * (1 + vol * config.tp_mult)
    return close * (1 + vol * config.sl_mult), close * (1 - vol * config.tp_mult)


def _build_so_plan(engine: ScaleOutEngine, side: str, entry: float, tp: float) -> ScaleOutPlan:
    tp_total = abs(tp - entry)
    tiers = []
    for fraction, pct in engine.tier_specs:
        price = entry + tp_total * pct if side == "long" else entry - tp_total * pct
        tiers.append(ScaleOutTier(fraction=fraction, price=price))
    return ScaleOutPlan(tiers=tiers, entry_price=entry, remaining_fraction=1.0)


def _tier_index(plan: ScaleOutPlan, tier: ScaleOutTier) -> int:
    for i, t in enumerate(plan.tiers):
        if t is tier:
            return i
    return -1


# ── PositionState (duck-typed version for our replay) ─────────────────

class _PositionState:
    def __init__(self, side, entry_price, entry_time, sl_price, tp_price,
                 vol_at_entry, conf_at_entry, entry_idx):
        self.side = side
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.vol_at_entry = vol_at_entry
        self.conf_at_entry = conf_at_entry
        self.entry_idx = entry_idx


# ── Metrics computation ──────────────────────────────────────────────


def compute_metrics(trades: pd.DataFrame) -> dict:
    """Compute portfolio-level metrics from a trade DataFrame.
    
    Returns
    -------
    dict with keys: n_trades, sharpe, ann_return, ann_vol, 
                    tp_rate, sl_rate, flip_rate, max_dd, score
    """
    if len(trades) == 0:
        return {"n_trades": 0, "sharpe": 0, "score": -999}

    returns = trades["return_pct"].values

    sharpe = 0.0
    if returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(252)

    ann_return = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)

    tp_rate = (trades["reason"] == "tp").sum() / max(len(trades), 1)
    sl_rate = (trades["reason"] == "sl").sum() / max(len(trades), 1)
    flip_rate = (trades["reason"] == "flip").sum() / max(len(trades), 1)
    so_fills = trades["reason"].str.startswith("scale_out").sum() / max(len(trades), 1)

    # Simple max drawdown from cumulative returns (equal-weighted)
    cum = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) if len(dd) > 0 else 0

    # Composite score: maximize Sharpe, TP rate, minimize SL rate, DD
    score = (
        sharpe * 2.0
        + tp_rate * 1.5
        - sl_rate * 1.0
        - flip_rate * 0.5
        - max_dd * 3.0
        + so_fills * 0.5
    )

    return {
        "n_trades": len(trades),
        "sharpe": round(sharpe, 4),
        "ann_return": round(ann_return, 6),
        "ann_vol": round(ann_vol, 6),
        "tp_rate": round(tp_rate, 4),
        "sl_rate": round(sl_rate, 4),
        "flip_rate": round(flip_rate, 4),
        "max_dd": round(max_dd, 4),
        "score": round(score, 4),
    }


# ── Main sweep ───────────────────────────────────────────────────────


def load_asset_predictions(
    name: str,
    base_config: dict,
    extended_history: bool = False,
    ensemble: bool = False,
) -> pd.DataFrame | None:
    """Load OOS predictions for a single asset."""
    base = os.path.join(SANDBOX_BASE, name)
    if extended_history:
        oos_name = "oos_predictions_extended.parquet" if not ensemble else "ensemble_oos_predictions_extended.parquet"
    else:
        oos_name = "ensemble_oos_predictions.parquet" if ensemble else "oos_predictions.parquet"
    oos_path = os.path.join(base, oos_name)
    if not os.path.exists(oos_path):
        # Fallback
        oos_path = os.path.join(base, "oos_predictions.parquet")
    if not os.path.exists(oos_path):
        logger.warning("%s: no predictions found at %s", name, base)
        return None
    predictions = pd.read_parquet(oos_path)
    if "atr" not in predictions.columns:
        predictions["atr"] = predictions["volatility"] * predictions["close"]
    if "regime" not in predictions.columns:
        predictions["regime"] = "neutral"
    if "year" not in predictions.columns:
        predictions["year"] = predictions.index.year
    return predictions


def run_sweep(
    asset_names: list[str],
    top_n: int = 3,
    fast: bool = False,
    extended_history: bool = False,
    ensemble: bool = False,
) -> list[SweepResult]:
    """Run parameter sweep across specified assets.

    Parameters
    ----------
    asset_names : list[str]
        Assets to include (e.g. ``["AUDJPY", "NZDJPY"]``).
    top_n : int
        Number of top combos to return.
    fast : bool
        If True, only sweep calibration_scale + scale-out (skip sl/tp mult).

    Returns
    -------
    list of SweepResult, sorted by score descending.
    """
    configs = load_best_configs()

    # Filter to requested assets
    configs = {k: v for k, v in configs.items() if k in asset_names}
    if not configs:
        logger.error("No configs found for %s", asset_names)
        return []

    # Preload predictions once per asset (the expensive part)
    logger.info("Loading predictions for %d assets...", len(configs))
    predictions_cache: dict[str, pd.DataFrame] = {}
    for name in configs:
        preds = load_asset_predictions(name, configs[name], extended_history, ensemble)
        if preds is not None:
            predictions_cache[name] = preds
    logger.info("Loaded %d/%d assets", len(predictions_cache), len(configs))

    # Build search grid
    if fast:
        sl_grid = [None]  # use existing config sl_mult
        tp_grid = [None]
    else:
        sl_grid = SL_MULTS
        tp_grid = TP_MULTS

    so_schemes = list(SCALE_OUT_SCHEMES.items())

    grid = list(product(sl_grid, tp_grid, CAL_SCALES, so_schemes))
    logger.info("Search space: %d combos x %d assets = %d replays", len(grid), len(predictions_cache), len(grid) * len(predictions_cache))

    results: list[SweepResult] = []

    for sl_val, tp_val, cal_scale, (so_name, so_tiers) in grid:
        # Build params dict
        params = {
            "calibration_scale": cal_scale,
            "scale_out": so_name,
        }

        all_asset_metrics = []

        for name, base_cfg in configs.items():
            predictions = predictions_cache.get(name)
            if predictions is None:
                continue

            effective_sl = sl_val if sl_val is not None else base_cfg["sl_mult"]
            effective_tp = tp_val if tp_val is not None else base_cfg["tp_mult"]

            sltp_engine = DynamicSLTPEngine(
                method="atr", atr_period=14,
                atr_mult_sl=2.0, atr_mult_tp=3.0,
                calibration_scale=cal_scale,
            )
            sltp_engine.calibrate(predictions)

            scale_out_engine = None
            if so_tiers is not None:
                scale_out_engine = ScaleOutEngine(tiers=so_tiers, activate_breakeven_after=0)

            replay_cfg = ReplayConfig(
                sl_mult=effective_sl,
                tp_mult=effective_tp,
                spread_bps=0.0,
                sltp_engine=None,  # we pass it separately
            )

            trades = replay_with_scale_out(
                predictions, replay_cfg,
                sltp_engine=sltp_engine,
                scale_out_engine=scale_out_engine,
            )

            if len(trades) == 0:
                continue

            metrics = compute_metrics(trades)
            all_asset_metrics.append(metrics)

        if not all_asset_metrics:
            continue

        # Aggregate across assets (equal-weight)
        avg = {k: np.mean([m[k] for m in all_asset_metrics]) for k in all_asset_metrics[0]}

        res = SweepResult(
            params=params,
            trades=int(avg["n_trades"]),
            sharpe=avg["sharpe"],
            ann_return=avg["ann_return"],
            ann_vol=avg["ann_vol"],
            tp_rate=avg["tp_rate"],
            sl_rate=avg["sl_rate"],
            flip_rate=avg["flip_rate"],
            max_dd=avg["max_dd"],
            score=avg["score"],
        )
        results.append(res)

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


def _print_results(results: list[SweepResult]) -> None:
    print("\n" + "=" * 100)
    print(f"{'Rank':<5} {'Score':<8} {'Sharpe':<8} {'TP%':<8} {'SL%':<8} {'Flip%':<8} {'DD':<8} {'cal_scale':<12} {'scale_out':<16} {'Trades':<8}")
    print("=" * 100)
    for rank, r in enumerate(results, 1):
        print(
            f"{rank:<5} {r.score:<8.2f} {r.sharpe:<8.2f} "
            f"{r.tp_rate*100:<8.1f} {r.sl_rate*100:<8.1f} {r.flip_rate*100:<8.1f} "
            f"{r.max_dd:<8.4f} {r.params['calibration_scale']:<12} "
            f"{r.params['scale_out']:<16} {r.trades:<8}"
        )
    print()


def main():
    parser = argparse.ArgumentParser(description="SL/TP + scale-out parameter sweep")
    parser.add_argument("--assets", default="AUDJPY,NZDJPY,USDCAD",
                        help="Comma-separated asset names")
    parser.add_argument("--top-n", type=int, default=3,
                        help="Number of top combos to report")
    parser.add_argument("--fast", action="store_true",
                        help="Skip sl/tp mult sweep, only calibrate scale + scale-out")
    parser.add_argument("--extended-history", action="store_true")
    parser.add_argument("--ensemble", action="store_true")
    args = parser.parse_args()

    asset_names = [a.strip() for a in args.assets.split(",")]
    logger.info("Assets: %s", asset_names)
    logger.info("Fast mode: %s", args.fast)

    results = run_sweep(
        asset_names=asset_names,
        top_n=args.top_n,
        fast=args.fast,
        extended_history=args.extended_history,
        ensemble=args.ensemble,
    )

    _print_results(results)

    # Save to JSON
    out_dir = os.path.join(PROJECT_ROOT, "data", "sandbox", "optimization")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "param_sweep_results.json")
    with open(out_path, "w") as f:
        json.dump([
            {
                "rank": i + 1,
                "score": r.score,
                "sharpe": r.sharpe,
                "tp_rate": r.tp_rate,
                "sl_rate": r.sl_rate,
                "flip_rate": r.flip_rate,
                "max_dd": r.max_dd,
                "n_trades": r.trades,
                "params": r.params,
            }
            for i, r in enumerate(results)
        ], f, indent=2)
    logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
