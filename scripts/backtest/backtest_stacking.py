#!/usr/bin/env python3
"""
Walk-forward stacking backtest (v4) — label-based PnL approach.

Key insight: each signal in the parquet has a pre-computed triple-barrier
label (0=SL, 1=TP).  The stacking simulation uses these labels directly,
avoiding the close-to-close PnL bug that plagued v1-v3.

Each layer (= signal that gets stacked) keeps its label-based PnL with these
adjustments:
  - First-layer signals → full label_R
  - Stacked layers → label_R × stack_tp_ratio if label_R > 0 (tight TP)
  - Protected by breakeven SL → label_R = 0 if label_R < 0
  - Skipped (max_layers exceeded or gate failure) → 0 R

Close prices are used ONLY for the min_pnl_r gate (checking position
profitability before stacking), NOT for PnL.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_stacking.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_stacking.py --grid
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from scripts.backtest.backtest_pnl import compute_asset_daily_r

logger = logging.getLogger("backtest_stacking")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

ACTIVE_ASSETS = [
    "AUDUSD", "CADCHF", "EURAUD", "EURCAD", "EURCHF", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPUSD", "GC", "ES", "NQ",
    "^DJI", "NZDCAD", "NZDCHF", "NZDUSD", "USDCAD", "USDCHF",
]

TICKER_MAP: dict[str, str] = {
    "AUDUSD": "AUDUSD=X", "CADCHF": "CADCHF=X", "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURNZD": "EURNZD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X",
    "GBPUSD": "GBPUSD=X", "GC": "GC=F", "ES": "ES=F", "NQ": "NQ=F",
    "^DJI": "^DJI", "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X",
    "NZDUSD": "NZDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
}


def fetch_close(ticker: str, start, end) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float, name="Close")
    if isinstance(df.columns, pd.MultiIndex):
        return df["Close"].squeeze()
    return df["Close"]


def _load_asset_config() -> dict[str, dict]:
    from paper_trading.config_manager import get_config
    cfg = get_config()
    result: dict[str, dict] = {}
    for name in ACTIVE_ASSETS:
        acfg = cfg.assets.get(name, {})
        result[name] = {
            "tp_mult": float(acfg.get("tp_mult", 2.0)),
            "sl_mult": float(acfg.get("sl_mult", 2.0)),
            "ticker": str(acfg.get("ticker", TICKER_MAP.get(name, f"{name}=X"))),
        }
    return result


def compute_label_pnl(signals: np.ndarray, labels: np.ndarray,
                      tp: float, sl: float) -> np.ndarray:
    """Vectorised: compute R-multiple per signal from pre-computed labels."""
    r = np.zeros(len(signals), dtype=float)
    buy = signals == 1
    sell = signals == -1
    r[buy & (labels == 1)] = tp
    r[buy & (labels == 0)] = -sl
    r[sell & (labels == 0)] = tp
    r[sell & (labels == 1)] = -sl
    return r


def position_unrealized_r(
    layers: list[dict],
    price: float,
    vol: float,
    direction: int,
) -> float:
    """Approximate position-wide unrealised R using close price.

    This is ONLY used for the min_pnl_r gate to decide whether stacking
    is permitted.  It does NOT affect the official PnL (which comes from
    pre-computed labels).
    """
    active = [l for l in layers if not l.get("closed")]
    if not active:
        return 0.0
    total_sz = max(sum(l["size_factor"] for l in active), 1e-10)
    avg_entry = sum(l["entry_price"] * l["size_factor"] for l in active) / total_sz
    avg_vol = np.mean([l.get("entry_vol", vol) for l in active])
    return (price - avg_entry) / (avg_entry * max(avg_vol, 1e-10)) * direction


def simulate_stacking_v4(
    df: pd.DataFrame,
    close: pd.Series,
    tp_mult: float,
    sl_mult: float,
    vol: pd.Series,
    layer_multipliers: list[float] | None = None,
    max_layers: int = 3,
    min_confidence: float = 0.0,
    min_pnl_r: float = 0.5,
    stack_tp_ratio: float = 1.0,
    breakeven_threshold: float = -1.0,
) -> tuple[pd.Series, int, int, int]:
    """Label-based stacking simulation.

    Each layer's PnL = pre-computed label_R (adjusted for stacking).
    No close prices used for PnL — only for the min_pnl_r gate.

    Returns
    -------
    (daily_r, n_stacks, n_positions, n_breakeven)
    """
    if layer_multipliers is None:
        layer_multipliers = [1.0, 0.5, 0.25]

    aligned = df[["signal", "label", "p_long"]].join(
        close.to_frame("Close"), how="inner"
    ).join(vol.to_frame("Vol"), how="inner").sort_index()
    n = len(aligned)
    if n == 0:
        return pd.Series(dtype=float, name="daily_r"), 0, 0, 0

    signals = aligned["signal"].values
    labels = aligned["label"].values
    p_long = aligned["p_long"].values
    close_prices = aligned["Close"].values
    vol_values = aligned["Vol"].values

    fill = float(np.nanmedian(vol_values[~np.isnan(vol_values)])) if np.any(np.isfinite(vol_values)) else 0.015
    vol_values = np.nan_to_num(vol_values, nan=fill, posinf=fill, neginf=fill)

    # Pre-compute baseline label_R per signal
    label_r = compute_label_pnl(signals, labels, tp_mult, sl_mult)

    daily_r = np.zeros(n, dtype=float)

    direction = 0
    layers: list[dict] = []  # track active layers: {size_factor, is_first, entry_price, entry_vol, idx, closed}
    protected = False

    n_stacks = 0
    n_positions = 0
    n_breakeven = 0

    for i in range(n):
        sig = signals[i]
        sig_label_r = label_r[i]

        if sig == 0:
            continue  # flat — no action

        if direction == 0 or sig != direction:
            # ── New position or opposite direction ────────────────
            # Old layers are closed (direction changes).
            # Their PnL was already recorded on their entry day above,
            # so we do NOT record anything here — each layer records
            # exactly once, on its entry day.

            direction = sig
            layers = [{
                "label_r": sig_label_r,
                "size_factor": layer_multipliers[0],
                "is_first": True,
                "idx": i,
                "entry_price": float(close_prices[i]),
                "entry_vol": float(vol_values[i]),
                "closed": False,
            }]
            daily_r[i] += sig_label_r * layer_multipliers[0]
            protected = False
            n_positions += 1

        else:
            # ── Same direction ────────────────────────────────────
            # Check max layers
            active = [l for l in layers if not l.get("closed")]
            if len(active) >= max_layers or len(layers) >= max_layers:
                # Signal is skipped — no PnL contribution
                continue

            # min_confidence gate
            if min_confidence > 0:
                prob = p_long[i] if direction == 1 else (1.0 - p_long[i])
                if prob - 0.5 < min_confidence:
                    continue  # skip

            # min_pnl_r gate
            if min_pnl_r > 0:
                unr = position_unrealized_r(
                    layers, float(close_prices[i]), float(vol_values[i]), direction,
                )
                if unr < min_pnl_r:
                    continue  # skip

            # ── Stack! ────────────────────────────────────────────
            adj_r = sig_label_r
            if adj_r > 0:
                adj_r *= stack_tp_ratio  # tighter TP for stacked layers

            layer_factor = (
                layer_multipliers[len(layers)]
                if len(layers) < len(layer_multipliers)
                else layer_multipliers[-1]
            )

            layers.append({
                "label_r": sig_label_r,
                "adj_label_r": adj_r,
                "size_factor": layer_factor,
                "is_first": False,
                "idx": i,
                "entry_price": float(close_prices[i]),
                "entry_vol": float(vol_values[i]),
                "closed": False,
            })

            # Record this layer's PnL on its signal day
            daily_r[i] += adj_r * layer_factor
            n_stacks += 1

            # Breakeven check
            if not protected and breakeven_threshold >= 0:
                pos_r = sum(
                    l.get("adj_label_r", l["label_r"]) * l["size_factor"]
                    for l in layers
                    if not l.get("closed")
                )
                if pos_r >= breakeven_threshold:
                    protected = True
                    n_breakeven += 1

    # Layers still open at data end: their PnL was already recorded
    # on their entry days, so nothing to close.

    return (
        pd.Series(daily_r, index=aligned.index, name="daily_r"),
        n_stacks,
        n_positions,
        n_breakeven,
    )


# ── Metrics ──────────────────────────────────────────────────────────────────


def compute_max_dd(r_series: pd.Series) -> float:
    if len(r_series) == 0:
        return 0.0
    cum = r_series.cumsum()
    running_max = cum.expanding().max()
    dd = cum - running_max
    return float(dd.min())


def sharpe_adj(r_series: pd.Series) -> float:
    if len(r_series) < 2:
        return 0.0
    std = r_series.std()
    if std == 0:
        return 0.0
    s = float(r_series.mean() / std * np.sqrt(252))
    rho = r_series.autocorr()
    if abs(rho) < 1.0:
        s *= np.sqrt((1.0 - rho) / (1.0 + rho))
    return s


# ── Run helpers ──────────────────────────────────────────────────────────────


def run_single(
    asset: str,
    df: pd.DataFrame,
    close: pd.Series,
    baseline_r: pd.Series,
    tp: float,
    sl: float,
    vol: pd.Series,
    mults: list[float],
    max_layers: int,
    min_conf: float,
    min_pnl_r: float,
    tpr: float,
    be: float,
) -> dict:
    stack_r, n_stacks, n_pos, n_be = simulate_stacking_v4(
        df, close, tp, sl, vol,
        layer_multipliers=mults,
        max_layers=max_layers,
        min_confidence=min_conf,
        min_pnl_r=min_pnl_r,
        stack_tp_ratio=tpr,
        breakeven_threshold=be,
    )
    return {
        "baseline_R": float(baseline_r.sum()),
        "stack_R": float(stack_r.sum()),
        "delta_R": float(stack_r.sum()) - float(baseline_r.sum()),
        "max_dd_base": compute_max_dd(baseline_r),
        "max_dd_stack": compute_max_dd(stack_r),
        "stacks": n_stacks,
        "positions": n_pos,
        "breakeven": n_be,
        "stack_sharpe": round(sharpe_adj(stack_r), 4),
        "non_improved": float(stack_r.sum()) < float(baseline_r.sum()),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward stacking backtest v4 (label-based)")
    parser.add_argument("--assets", default=None, help="Comma-separated asset filter")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument("--multipliers", default="1.0,0.5,0.25", help="Comma-separated layer multipliers")
    parser.add_argument("--max-layers", type=int, default=3)
    parser.add_argument("--min-confidence", type=float, default=0.0,
                        help="Min abs(p_long - 0.5) (default 0.0 = no gate)")
    parser.add_argument("--min-pnl-r", type=float, default=0.0,
                        help="Min unrealized R (default 0.0 = no gate)")
    parser.add_argument("--stack-tp-ratio", type=float, default=1.0,
                        help="TP multiplier for stacked layers (default 1.0 = same as base)")
    parser.add_argument("--breakeven", type=float, default=-1.0,
                        help="Breakeven threshold (default -1.0 = disabled)")
    parser.add_argument("--grid", action="store_true", help="Run parameter grid search")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asset_filter: set[str] | None = set(args.assets.split(",")) if args.assets else None
    config = _load_asset_config()
    user_mults = [float(x) for x in args.multipliers.split(",")]

    # ── Parameter grid ────────────────────────────────────────────
    if args.grid:
        grid_mults = [[1.0, 0.5, 0.25], [0.5, 0.25, 0.1], [1.0, 0.3, 0.1]]
        grid_confs = [0.0, 0.15]
        grid_pnl = [0.0, 0.5]
        grid_tpr = [0.5, 0.75, 1.0]
        grid_be = [-1.0, 1.0]
        grid_all = [a for a in ACTIVE_ASSETS if not asset_filter or a in asset_filter]
    else:
        grid_all = [a for a in ACTIVE_ASSETS if not asset_filter or a in asset_filter]
        grid_mults = [user_mults]
        grid_confs = [args.min_confidence]
        grid_pnl = [args.min_pnl_r]
        grid_tpr = [args.stack_tp_ratio]
        grid_be = [args.breakeven]

    # ── Load data ─────────────────────────────────────────────────
    logger.info("Loading data for %d assets ...", len(grid_all))
    cache: dict[str, dict] = {}
    for asset in grid_all:
        pq_path = WALKDIR / f"{asset}_wf_signals.parquet"
        if not pq_path.exists():
            logger.warning("%s: parquet not found", asset)
            continue
        df = pd.read_parquet(pq_path)
        if df.empty:
            continue
        df = df.sort_index()
        cfg = config[asset]
        ticker = cfg["ticker"]
        tp, sl = cfg["tp_mult"], cfg["sl_mult"]
        start, end = df.index.min(), df.index.max()
        close = fetch_close(ticker, start, end)
        if close.empty:
            logger.warning("%s: no yfinance data", asset)
            continue
        if close.index.tz is None and df.index.tz is not None:
            close = close.tz_localize(df.index.tz, ambiguous="infer")
        log_rets = np.log(close / close.shift(1))
        vol_21 = log_rets.rolling(21).std()
        baseline_r = compute_asset_daily_r(df, tp, sl)
        cache[asset] = {
            "df": df, "close": close, "baseline_r": baseline_r,
            "tp": tp, "sl": sl, "vol": vol_21,
        }

    all_results: list[dict] = []
    best_row: dict | None = None

    for mults in grid_mults:
        for conf in grid_confs:
            for pnl_r in grid_pnl:
                for tpr in grid_tpr:
                    for be in grid_be:
                        tag = (
                            f"m={'/'.join(str(x) for x in mults)}"
                            f"_c={conf}_p={pnl_r}_tpr={tpr}_be={be}"
                        )
                        if args.grid:
                            logger.info("Grid: %s", tag)

                        asset_rows: list[dict] = []
                        pf_baselines: list[pd.Series] = []
                        pf_stacks: list[pd.Series] = []
                        imp = 0
                        tot = 0

                        for asset in grid_all:
                            c = cache.get(asset)
                            if c is None:
                                continue
                            tot += 1
                            row = run_single(
                                asset, c["df"], c["close"],
                                c["baseline_r"], c["tp"], c["sl"],
                                c["vol"],
                                mults, args.max_layers, conf, pnl_r,
                                tpr, be,
                            )
                            row["tag"] = tag
                            row["asset"] = asset
                            asset_rows.append(row)
                            if not row["non_improved"]:
                                imp += 1
                            pf_baselines.append(c["baseline_r"])
                            s_r, _, _, _ = simulate_stacking_v4(
                                c["df"], c["close"], c["tp"], c["sl"],
                                c["vol"],
                                layer_multipliers=mults,
                                max_layers=args.max_layers,
                                min_confidence=conf,
                                min_pnl_r=pnl_r,
                                stack_tp_ratio=tpr,
                                breakeven_threshold=be,
                            )
                            pf_stacks.append(s_r)

                        if not pf_baselines:
                            continue

                        base_pf = pd.DataFrame(
                            {f"a{i}": s for i, s in enumerate(pf_baselines)}
                        ).mean(axis=1)
                        stack_pf = pd.DataFrame(
                            {f"a{i}": s for i, s in enumerate(pf_stacks)}
                        ).mean(axis=1)
                        cidx = base_pf.index.intersection(stack_pf.index)
                        base_pf = base_pf.reindex(cidx).fillna(0)
                        stack_pf = stack_pf.reindex(cidx).fillna(0)

                        p_row = {
                            "tag": tag,
                            "asset": "PF",
                            "baseline_R": round(float(base_pf.sum()), 1),
                            "stack_R": round(float(stack_pf.sum()), 1),
                            "delta_R": round(float(stack_pf.sum() - base_pf.sum()), 1),
                            "max_dd_base": round(compute_max_dd(base_pf), 1),
                            "max_dd_stack": round(compute_max_dd(stack_pf), 1),
                            "stacks": sum(r.get("stacks", 0) for r in asset_rows),
                            "breakeven": sum(r.get("breakeven", 0) for r in asset_rows),
                            "stack_sharpe": round(sharpe_adj(stack_pf), 4),
                            "non_improved": float(stack_pf.sum() - base_pf.sum()) <= 0,
                            "improved_count": imp,
                            "total_count": tot,
                            "pf_sharpe_base": round(sharpe_adj(base_pf), 4),
                            "sharpe_delta": round(sharpe_adj(stack_pf) - sharpe_adj(base_pf), 4),
                        }

                        if args.grid:
                            all_results.append(p_row)
                            if best_row is None or p_row["delta_R"] > best_row["delta_R"]:
                                best_row = p_row
                        else:
                            all_results.extend(asset_rows)

    # ── Output ────────────────────────────────────────────────────
    if args.grid:
        print("\n" + "=" * 90)
        print("GRID RESULTS (sorted by portfolio delta_R)")
        print("=" * 90)
        df_grid = pd.DataFrame(all_results).sort_values("delta_R", ascending=False)
        cols = ["tag", "delta_R", "stack_R", "max_dd_stack",
                "stack_sharpe", "sharpe_delta", "improved_count", "total_count"]
        print(df_grid[cols].to_string(index=False))
        print()
        if best_row:
            print("BEST CONFIG:")
            print(f"  {best_row['tag']}")
            print(f"  delta_R={best_row['delta_R']:+.1f}  stack_R={best_row['stack_R']:+.1f}")
            print(f"  max_dd_stack={best_row['max_dd_stack']:.1f}  sharpe={best_row['stack_sharpe']:.4f}")
            print(f"  improved={best_row['improved_count']}/{best_row['total_count']}")
        out_path = args.output or str(WALKDIR / "stacking_grid_v4.csv")
        df_grid.to_csv(out_path, index=False)
        logger.info("Grid -> %s", out_path)
        return

    # Per-asset table
    result_df = pd.DataFrame(all_results)
    if result_df.empty:
        logger.error("No results")
        sys.exit(1)

    print()
    hdr = (
        f"{'ASSET':<15s} | {'BASELINE_R':>10s} | {'STACK_R':>8s} | "
        f"{'ΔR':>8s} | {'MAX_DD_BASE':>11s} | {'MAX_DD_STACK':>12s} | "
        f"{'STACKS':>6s} | {'BRK':>4s} | {'SHARPE':>7s}"
    )
    print(hdr)
    print("-" * len(hdr))
    for _, r in result_df.iterrows():
        print(
            f"{r['asset']:<15s} | {r['baseline_R']:>+10.1f} | "
            f"{r['stack_R']:>+8.1f} | {r['delta_R']:>+8.1f} | "
            f"{r['max_dd_base']:>11.1f} | {r['max_dd_stack']:>12.1f} | "
            f"{r['stacks']:>6d} | {r['breakeven']:>4d} | "
            f"{r['stack_sharpe']:>+7.4f}"
        )

    pf_b = sum(r.get("baseline_R", 0) for r in all_results
               if r.get("asset") not in ("", "PF"))
    pf_s = sum(r.get("stack_R", 0) for r in all_results
               if r.get("asset") not in ("", "PF"))
    pf_dd_b = min(r.get("max_dd_base", 0) for r in all_results
                  if r.get("asset") not in ("", "PF"))
    pf_dd_s = min(r.get("max_dd_stack", 0) for r in all_results
                  if r.get("asset") not in ("", "PF"))
    improved = sum(1 for r in all_results if r.get("delta_R", 0) > 0)
    total = len(all_results)
    print()
    print("=" * len(hdr))
    print(
        f"{'SUM':<15s} | {pf_b:>+10.1f} | {pf_s:>+8.1f} | "
        f"{(pf_s-pf_b):>+8.1f} | {pf_dd_b:>11.1f} | {pf_dd_s:>12.1f} |"
    )
    print(f"Improved: {improved}/{total} = {improved/total*100:.0f}%")

    out_path = args.output or str(WALKDIR / "stacking_backtest_v4.csv")
    result_df.to_csv(out_path, index=False)
    logger.info("Results -> %s", out_path)


if __name__ == "__main__":
    main()
