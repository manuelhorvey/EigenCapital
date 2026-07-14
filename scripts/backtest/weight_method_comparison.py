#!/usr/bin/env python3
"""
Comprehensive weight method comparison across 16 and 22 asset portfolios.

Runs all 4 key weight methods on both portfolio configurations:
  - equal_v1, conviction_weighted_v1, conviction_weighted_v2, risk_parity_v2
  - 22-asset full portfolio
  - 16-asset subset (excluding AUDUSD, EURCHF, GBPCAD, NZDJPY)

All runs use:
  - --use-prod-thresholds
  - --calibrate
  - Same signal tag (default: base)
  - Same min_assets for fair comparison

Output: walkforward/weight_method_comparison.csv + terminal table
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.calibration.registry import CalibrationRegistry
from shared.portfolio_weights import list_methods
from scripts.backtest.backtest_pnl import (
    WALKDIR,
    MODEL_DIR,
    _asset_pt_sl_from_config,
    _asset_direction_thresholds_from_config,
    load_asset_signals,
    rederive_signals_from_p_long,
    compute_asset_daily_r,
    build_portfolio_daily_r,
    portfolio_metrics,
)

logger = logging.getLogger("weight_method_comparison")

EXCLUDED_ASSETS = frozenset({"AUDUSD", "EURCHF", "GBPCAD", "NZDJPY"})

# Methods to test: baseline + 3 conviction methods + risk parity
METHODS = [
    "equal_v1",
    "conviction_weighted_v1",
    "conviction_weighted_v2",
    "risk_parity_v2",
]


def load_and_process(
    tag: str,
    cal_registry: CalibrationRegistry | None,
    dir_threshold_map: dict | None,
    sell_only_assets: frozenset,
    pt_sl_map: dict,
    exclude: frozenset | None = None,
) -> tuple[dict[str, pd.Series], dict[str, float], dict[str, pd.DataFrame]]:
    """Load signal parquets, process, return daily R series + IC + signal DataFrames."""
    from scipy.stats import spearmanr

    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    if not parquets:
        fallback = sorted(WALKDIR.glob("*_wf_signals.parquet"))
        if fallback:
            parquets = fallback

    all_daily_r: dict[str, pd.Series] = {}
    asset_ic: dict[str, float] = {}
    signal_dfs: dict[str, pd.DataFrame] = {}

    for pq in parquets:
        stem = pq.stem
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            continue
        if exclude and asset in exclude:
            continue

        tp, sl = pt_sl_map[asset]
        df = load_asset_signals(str(pq))
        if df.empty:
            continue

        # Calibrate
        if cal_registry and "p_long" in df.columns:
            p_long_raw = df["p_long"].astype(float).values
            p_long_cal = cal_registry.calibrate(asset, p_long_raw)
            df["p_long"] = p_long_cal

        # Re-derive signals
        if dir_threshold_map and asset in dir_threshold_map:
            buy_th, sell_th = dir_threshold_map[asset]
            if (buy_th is not None or sell_th is not None) and "p_long" in df.columns:
                df = rederive_signals_from_p_long(df, buy_th, sell_th)

        # SELL_ONLY filter
        if asset in sell_only_assets:
            df.loc[df["signal"] == 1, "signal"] = 0

        # IC
        if "p_long" in df.columns and "label" in df.columns and len(df) >= 20:
            ic_val, _ = spearmanr(df["p_long"].astype(float), df["label"].astype(float))
            asset_ic[asset] = float(ic_val) if not np.isnan(ic_val) else 0.0
        else:
            asset_ic[asset] = 0.0

        daily_r = compute_asset_daily_r(df, tp, sl)
        all_daily_r[asset] = daily_r

        # Store signal DataFrame for conviction_weighted_v2 (rolling IC)
        if "p_long" in df.columns and "label" in df.columns:
            signal_dfs[asset] = df[["p_long", "label", "signal"]]

    return all_daily_r, asset_ic, signal_dfs


def run_comparison(
    asset_series: dict[str, pd.Series],
    asset_ic: dict[str, float],
    signal_dfs: dict[str, pd.DataFrame],
    min_assets: int,
    tag: str,
    portfolio_label: str,
    conviction_lambda: float | None = None,
) -> list[dict]:
    """Run all weight methods and return results."""
    if not asset_series:
        return []
    results = []
    n_assets = len(asset_series)

    for method in METHODS:
        kw_portfolio: dict = {}

        if method == "conviction_weighted_v1":
            kw_portfolio["conviction"] = asset_ic
        elif method == "conviction_weighted_v2":
            kw_portfolio["asset_signal_dfs"] = signal_dfs if signal_dfs else None
            kw_portfolio["ic_window"] = 60
            kw_portfolio["ic_rebalance_freq"] = "monthly"
            if conviction_lambda is not None:
                kw_portfolio["conviction_lambda"] = conviction_lambda

        pf_df = build_portfolio_daily_r(
            asset_series,
            min_assets=min_assets,
            weight_method=method,
            **kw_portfolio,
        )
        m = portfolio_metrics(pf_df)

        results.append({
            "portfolio": portfolio_label,
            "n_assets": n_assets,
            "method": method,
            "n_days": m["n_days"],
            "total_R": m["total_R"],
            "avg_R": m["avg_R"],
            "sharpe": m["sharpe"],
            "sharpe_adj": m["sharpe_adj"],
            "max_dd_R": m["max_dd_R"],
            "calmar": m["calmar"] if m["calmar"] is not None else "",
            "n_loss_cluster_days": m["n_loss_cluster_days"],
            "n_weekly_clusters": m["n_weekly_clusters"],
            "median_n_assets": m["median_n_assets"],
            "skew": m["skew"],
            "ex_kurt": m["ex_kurt"],
            "psr_gt_0": m["psr_gt_0"],
            "dsr": m["dsr"],
        })

        logger.info("%s %s: total_R=%+.2f sharpe=%.4f", portfolio_label, method, m["total_R"], m["sharpe"])

    return results


def print_table(results: list[dict]) -> None:
    """Print a formatted comparison table."""
    print()
    print("=" * 130)
    print("WEIGHT METHOD COMPARISON — 16 vs 22 ASSET PORTFOLIOS")
    print("=" * 130)
    print()

    # Group by portfolio
    for portfolio_label in ["22-asset full", "16-asset subset"]:
        rows = [r for r in results if r["portfolio"] == portfolio_label]
        print(f"  {portfolio_label} ({rows[0]['n_assets']} assets):")
        print()
        header = (
            f"  {'Method':<28} {'TotalR':>8} {'Sharpe':>8} {'AdjShp':>8} "
            f"{'MaxDD':>8} {'Calmar':>8} {'PSR>0':>7} {'DSR':>6} {'Days':>6}"
        )
        print(header)
        print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")
        for r in rows:
            calmar_str = f"{r['calmar']:.2f}" if r['calmar'] != '' else "  --- "
            print(
                f"  {r['method']:<28} {r['total_R']:>+8.2f} {r['sharpe']:>8.4f} "
                f"{r['sharpe_adj']:>8.4f} {r['max_dd_R']:>+8.2f} {calmar_str:>8} "
                f"{r['psr_gt_0']:>7.4f} {r['dsr']:>6.4f} {r['n_days']:>6}"
            )
        print()

    # Summary: best method by portfolio
    print("  BEST METHOD BY PORTFOLIO:")
    print(f"  {'Portfolio':<20} {'Metric':<10} {'Best Method':<28} {'Value':<12}")
    print(f"  {'-'*20} {'-'*10} {'-'*28} {'-'*12}")
    for portfolio_label in ["22-asset full", "16-asset subset"]:
        rows = [r for r in results if r["portfolio"] == portfolio_label]
        if not rows:
            continue
        best_total_r = max(rows, key=lambda r: r["total_R"])
        best_sharpe = max(rows, key=lambda r: r["sharpe"])
        best_dsr = max(rows, key=lambda r: r["dsr"])
        best_dd = min(rows, key=lambda r: r["max_dd_R"] if r["max_dd_R"] < 0 else float("inf"))
        print(f"  {portfolio_label:<20} {'TotalR':<10} {best_total_r['method']:<28} {best_total_r['total_R']:<+12.2f}")
        print(f"  {portfolio_label:<20} {'Sharpe':<10} {best_sharpe['method']:<28} {best_sharpe['sharpe']:<12.4f}")
        print(f"  {portfolio_label:<20} {'DSR':<10} {best_dsr['method']:<28} {best_dsr['dsr']:<12.4f}")
        if best_dd["max_dd_R"] < 0:
            print(f"  {portfolio_label:<20} {'Min DD':<10} {best_dd['method']:<28} {best_dd['max_dd_R']:<+12.2f}")
        else:
            print(f"  {portfolio_label:<20} {'Min DD':<10} {'(all zero)':<28} {'---':<12}")
        print()

    # Delta table: 16-asset minus 22-asset
    print("  DELTA (16-asset minus 22-asset) — positive = subset outperforms:")
    print(f"  {'Method':<28} {'Δ TotalR':>9} {'Δ Sharpe':>9} {'Δ AdjShp':>9}")
    print(f"  {'-'*28} {'-'*9} {'-'*9} {'-'*9}")

    for method in METHODS:
        r22 = next(r for r in results if r["portfolio"] == "22-asset full" and r["method"] == method)
        r16 = next(r for r in results if r["portfolio"] == "16-asset subset" and r["method"] == method)
        delta_r = r16["total_R"] - r22["total_R"]
        delta_sharpe = r16["sharpe"] - r22["sharpe"]
        delta_adj = r16["sharpe_adj"] - r22["sharpe_adj"]
        sign = "+" if delta_r > 0 else ""
        print(f"  {method:<28} {sign}{delta_r:<+8.2f} {delta_sharpe:<+9.4f} {delta_adj:<+9.4f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Weight method comparison 16 vs 22")
    parser.add_argument("--tag", default="base", help="Signal parquet tag")
    parser.add_argument("--min-assets", type=int, default=10, help="Min assets")
    parser.add_argument(
        "--conviction-lambda", type=float, default=None,
        help="Override conviction_lambda for conviction_weighted_v2 (default: 0.35 from the strategy)",
    )
    parser.add_argument("--output", default=None, help="Output CSV path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Load configs
    cal_dir = MODEL_DIR / "calibration"
    cal_registry = CalibrationRegistry.get_or_load(cal_dir)
    dir_threshold_map = _asset_direction_thresholds_from_config()
    pt_sl_map = _asset_pt_sl_from_config()
    from paper_trading.execution.gate_constants import get_sell_only_assets
    SELL_ONLY_ASSETS = get_sell_only_assets()

    print("=" * 130)
    print("LOADING ASSETS")
    print("=" * 130)

    # Load 22-asset portfolio
    print("Loading 22-asset portfolio...")
    r22, ic22, sig22 = load_and_process(
        args.tag, cal_registry, dir_threshold_map, SELL_ONLY_ASSETS, pt_sl_map,
    )
    print(f"  Loaded {len(r22)} assets")

    # Load 16-asset portfolio
    print("Loading 16-asset portfolio (excl. AUDUSD, EURCHF, GBPCAD, NZDJPY)...")
    r16, ic16, sig16 = load_and_process(
        args.tag, cal_registry, dir_threshold_map, SELL_ONLY_ASSETS, pt_sl_map,
        exclude=EXCLUDED_ASSETS,
    )
    print(f"  Loaded {len(r16)} assets")
    print()

    # Run comparisons
    all_results: list[dict] = []

    for label, series, ic, sig, n in [
        ("22-asset full", r22, ic22, sig22, len(r22)),
        ("16-asset subset", r16, ic16, sig16, len(r16)),
    ]:
        if not series:
            logger.error("%s: no assets loaded — skipping", label)
            continue
        min_a = min(args.min_assets, n - 1) if n > 1 else args.min_assets
        if min_a < args.min_assets:
            logger.warning(
                "%s: capping min_assets from %d to %d (only %d assets available)",
                label, args.min_assets, min_a, n,
            )
        logger.info("Running %s (min_assets=%d)...", label, min_a)
        results = run_comparison(series, ic, sig, min_a, args.tag, label, conviction_lambda=args.conviction_lambda)
        all_results.extend(results)

    # Print terminal table
    print_table(all_results)

    # Save CSV
    output_path = args.output or str(WALKDIR / "weight_method_comparison.csv")
    df = pd.DataFrame(all_results)
    df.to_csv(output_path, index=False)
    logger.info("Comparison CSV saved to %s", output_path)
    print(f"  Results saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
