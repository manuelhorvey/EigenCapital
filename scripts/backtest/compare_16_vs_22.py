#!/usr/bin/env python3
"""
Compare portfolio performance with and without the 4 negative-IC assets.

Runs the walk-forward PnL backtest using conviction_weighted_v1 on:
  - Full 22-asset portfolio
  - 16-asset subset excluding AUDUSD, EURCHF, GBPCAD, NZDJPY

Uses --use-prod-thresholds --calibrate to match the live engine as closely
as possible.
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
from shared.portfolio_weights import rolling_weight_matrix

from scripts.backtest.backtest_pnl import (
    WALKDIR,
    MODEL_DIR,
    _asset_pt_sl_from_config,
    _asset_direction_thresholds_from_config,
    load_asset_signals,
    rederive_signals_from_p_long,
    compute_asset_daily_r,
    portfolio_metrics,
)

logger = logging.getLogger("compare_16_vs_22")

# The 4 assets with systematically inverted IC (SELL-heavy → negative IC)
EXCLUDED_ASSETS = frozenset({"AUDUSD", "EURCHF", "GBPCAD", "NZDJPY"})

# From earlier IC analysis — 6 SELL_ONLY + remaining positive-IC
POSITIVE_IC_ASSETS = frozenset({
    "^DJI", "AUDJPY", "BTCUSD", "CADCHF", "EURAUD", "EURCAD",
    "EURNZD", "GBPAUD", "GBPCHF", "GBPJPY", "GBPUSD",
    "GC", "NZDCAD", "NZDCHF", "NZDUSD", "USDCAD",
    "USDCHF", "USDJPY",
})


def load_and_process_assets(
    tag: str,
    cal_registry: CalibrationRegistry | None,
    dir_threshold_map: dict | None,
    sell_only_assets: frozenset,
    pt_sl_map: dict,
    exclude: frozenset | None = None,
) -> tuple[dict[str, pd.Series], dict[str, float]]:
    """Load signal parquets, process, and return daily R series + IC values.

    Parameters
    ----------
    exclude : frozenset, optional
        Assets to exclude from loading. If None, load all.
    """
    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    if not parquets:
        fallback = sorted(WALKDIR.glob("*_wf_signals.parquet"))
        if fallback:
            parquets = fallback

    all_daily_r: dict[str, pd.Series] = {}
    asset_ic: dict[str, float] = {}

    for pq in parquets:
        stem = pq.stem
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            continue
        if exclude and asset in exclude:
            continue

        from scipy.stats import spearmanr

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

    return all_daily_r, asset_ic


def main():
    parser = argparse.ArgumentParser(description="Compare 16 vs 22 asset portfolio performance")
    parser.add_argument("--tag", default="base", help="Signal parquet tag")
    parser.add_argument("--min-assets", type=int, default=10, help="Min assets for portfolio inclusion")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Load calibration + config
    cal_dir = MODEL_DIR / "calibration"
    cal_registry = CalibrationRegistry.get_or_load(cal_dir)

    dir_threshold_map = _asset_direction_thresholds_from_config()
    pt_sl_map = _asset_pt_sl_from_config()

    from paper_trading.execution.gate_constants import get_sell_only_assets
    SELL_ONLY_ASSETS = get_sell_only_assets()

    print("=" * 90)
    print("COMPARISON: 22-asset full portfolio vs 16-asset (excl. 4 negative-IC)")
    print("=" * 90)
    print()
    print(f"  Excluded assets (4): {sorted(EXCLUDED_ASSETS)}")
    print(f"  Method: conviction_weighted_v1 with --use-prod-thresholds --calibrate")
    print(f"  Tag: {args.tag}")
    print(f"  SELL_ONLY: {sorted(SELL_ONLY_ASSETS)}")
    print()

    # Load 22 assets
    print("─" * 90)
    print("Loading 22-asset portfolio...")
    all_daily_r_22, ic_22 = load_and_process_assets(
        args.tag, cal_registry, dir_threshold_map, SELL_ONLY_ASSETS, pt_sl_map,
        exclude=None,
    )
    n_22 = len(all_daily_r_22)
    print(f"  Loaded {n_22} assets")

    # Load 16 assets (exclude the 4)
    print("Loading 16-asset portfolio (excluding AUDUSD, EURCHF, GBPCAD, NZDJPY)...")
    all_daily_r_16, ic_16 = load_and_process_assets(
        args.tag, cal_registry, dir_threshold_map, SELL_ONLY_ASSETS, pt_sl_map,
        exclude=EXCLUDED_ASSETS,
    )
    n_16 = len(all_daily_r_16)
    print(f"  Loaded {n_16} assets")

    print()

    # ── Run equal_v1 on both portfolios (baseline) ──
    print("─" * 90)
    print("BASELINE: equal_v1 (no conviction tilt)")
    print("─" * 90)

    from scripts.backtest.backtest_pnl import build_portfolio_daily_r

    for label, asset_series, n_assets in [
        ("22-asset full", all_daily_r_22, n_22),
        ("16-asset subset", all_daily_r_16, n_16),
    ]:
        pf_df = build_portfolio_daily_r(
            asset_series,
            min_assets=min(args.min_assets, n_assets - 1),
            weight_method="equal_v1",
        )
        m = portfolio_metrics(pf_df)
        print(f"\n  {label} (equal_v1, n={n_assets}):")
        print(f"    Total R: {m['total_R']:>+8.2f}")
        print(f"    Sharpe:  {m['sharpe']:>8.4f}")
        print(f"    Adj Shp: {m['sharpe_adj']:>8.4f}")
        print(f"    Max DD:  {m['max_dd_R']:>+8.2f}R")
        print(f"    Calmar:  {m['calmar'] if m['calmar'] else '---':>8}")
        print(f"    Days:    {m['n_days']:>8}")
        print(f"    PSR>0:   {m['psr_gt_0']:>8.4f}")

    print()

    # ── Run conviction_weighted_v1 on both portfolios ──
    print("─" * 90)
    print("CONVICTION-WEIGHTED: conviction_weighted_v1")
    print("─" * 90)

    for label, asset_series, n_assets in [
        ("22-asset full", all_daily_r_22, n_22),
        ("16-asset subset", all_daily_r_16, n_16),
    ]:
        pf_df = build_portfolio_daily_r(
            asset_series,
            min_assets=min(args.min_assets, n_assets - 1),
            weight_method="conviction_weighted_v1",
            conviction=ic_22 if label == "22-asset full" else ic_16,
        )
        m = portfolio_metrics(pf_df)
        print(f"\n  {label} (conviction_weighted_v1, n={n_assets}):")
        print(f"    Total R: {m['total_R']:>+8.2f}")
        print(f"    Sharpe:  {m['sharpe']:>8.4f}")
        print(f"    Adj Shp: {m['sharpe_adj']:>8.4f}")
        print(f"    Max DD:  {m['max_dd_R']:>+8.2f}R")
        print(f"    Calmar:  {m['calmar'] if m['calmar'] else '---':>8}")
        print(f"    Days:    {m['n_days']:>8}")
        print(f"    PSR>0:   {m['psr_gt_0']:>8.4f}")

    # ── Summary comparison ──
    print()
    print("=" * 90)
    print("SUMMARY: Delta (16-asset minus 22-asset)")
    print("=" * 90)

    # Re-run to capture for comparison
    pf_22_eq = build_portfolio_daily_r(all_daily_r_22, min_assets=args.min_assets, weight_method="equal_v1")
    pf_16_eq = build_portfolio_daily_r(all_daily_r_16, min_assets=min(args.min_assets, n_16 - 1), weight_method="equal_v1")
    pf_22_cv = build_portfolio_daily_r(all_daily_r_22, min_assets=args.min_assets, weight_method="conviction_weighted_v1", conviction=ic_22)
    pf_16_cv = build_portfolio_daily_r(all_daily_r_16, min_assets=min(args.min_assets, n_16 - 1), weight_method="conviction_weighted_v1", conviction=ic_16)

    m_22_eq = portfolio_metrics(pf_22_eq)
    m_16_eq = portfolio_metrics(pf_16_eq)
    m_22_cv = portfolio_metrics(pf_22_cv)
    m_16_cv = portfolio_metrics(pf_16_cv)

    print(f"{'Metric':<20} {'22-equal':>10} {'16-equal':>10} {'Δ-equal':>10} | {'22-cv':>10} {'16-cv':>10} {'Δ-cv':>10}")
    print("-" * 80)
    for metric in ["total_R", "sharpe", "sharpe_adj", "max_dd_R", "psr_gt_0", "n_days"]:
        v_22e = m_22_eq.get(metric, 0) or 0
        v_16e = m_16_eq.get(metric, 0) or 0
        v_22c = m_22_cv.get(metric, 0) or 0
        v_16c = m_16_cv.get(metric, 0) or 0
        delta_e = v_16e - v_22e
        delta_c = v_16c - v_22c
        fmt = ".2f" if metric in ("total_R", "max_dd_R") else ".4f"
        print(f"{metric:<20} {v_22e:>10{fmt}} {v_16e:>10{fmt}} {delta_e:>+10{fmt}} | {v_22c:>10{fmt}} {v_16c:>10{fmt}} {delta_c:>+10{fmt}}")

    print()
    print("Interpretation:")
    print("  Positive Δ = 16-asset subset outperforms full 22-asset portfolio")
    print("  Negative Δ = excluding the 4 'negative-IC' assets hurts performance")
    print()

    # Print per-asset IC values for the excluded assets
    print("─" * 90)
    print("PER-ASSET IC (full 22-asset portfolio):")
    print("─" * 90)
    for asset, ic in sorted(ic_22.items(), key=lambda x: x[1]):
        flag = " *** EXCLUDED" if asset in EXCLUDED_ASSETS else ""
        print(f"  {asset:>10}: IC = {ic:+.4f}{flag}")


if __name__ == "__main__":
    main()
