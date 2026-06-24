#!/usr/bin/env python3
"""
Directional filter diagnostic: remove anti-skill direction per asset.

Tests whether filtering out the systematically losing direction
recovers meaningful R-multiple PnL.

Group A (repair candidates — net-negative, strong anti-skill):
  AUDNZD (SELL), EURUSD (SELL), AUDCHF (BUY)
Group B (sanity checks — net-positive or marginal):
  ES (BUY), NQ (BUY), AUDUSD (BUY), NZDCHF (BUY), GBPNZD (SELL), USDCAD (SELL)

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/filter_direction.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from scripts.backtest.backtest_pnl import (
    _asset_pt_sl_from_config,
    build_portfolio_daily_r,
    compute_asset_daily_r,
    load_asset_signals,
)

logger = logging.getLogger("filter_direction")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

# (asset, direction_to_filter)
# 1 = filter BUY (set BUY signals → FLAT)
# -1 = filter SELL (set SELL signals → FLAT)
FILTER_MAP: dict[str, int] = {
    # Group A — repair candidates
    "AUDNZD": -1,   # SELL anti-skill (17.9%)
    "EURUSD": -1,   # SELL anti-skill (27.6%)
    "AUDCHF": 1,    # BUY anti-skill (30.4%)
    # Group B — sanity checks
    "ES": 1,
    "NQ": 1,
    "AUDUSD": 1,
    "NZDCHF": 1,
    "GBPNZD": -1,
    "USDCAD": -1,
}

# These groups are from the original directional-filter diagnostic (2026-06-20).
# AUDNZD, EURUSD, AUDCHF, GBPNZD have since been removed from trading.
# Keep the lists intact here for historical reproducibility.
GROUP_A = ["AUDNZD", "EURUSD", "AUDCHF"]
GROUP_B = ["ES", "NQ", "AUDUSD", "NZDCHF", "GBPNZD", "USDCAD"]


def assign_folds(df: pd.DataFrame, summary_path: Path) -> pd.Series:
    """Assign fold labels to signal rows based on test_start/test_end dates."""
    if not summary_path.exists():
        return pd.Series(-1, index=df.index, dtype=int)
    summary = pd.read_csv(summary_path)
    fold_series = pd.Series(-1, index=df.index, dtype=int)
    for _, row in summary.iterrows():
        start = pd.Timestamp(row["test_start"]).tz_localize("UTC")
        end = pd.Timestamp(row["test_end"]).tz_localize("UTC")
        mask = (df.index >= start) & (df.index <= end)
        fold_series[mask] = int(row["fold"])
    return fold_series


def run_filter(asset: str, filter_sig: int) -> dict | None:
    """Run filter on one asset. Returns per-fold results list."""
    pq_path = WALKDIR / f"{asset}_wf_signals_base.parquet"
    if not pq_path.exists():
        logger.warning("No signal parquet for %s — skipping", asset)
        return None

    pt_sl_map = _asset_pt_sl_from_config()
    if asset not in pt_sl_map:
        logger.warning("No pt_sl config for %s — skipping", asset)
        return None
    tp, sl = pt_sl_map[asset]

    df = load_asset_signals(str(pq_path))
    if df.empty:
        logger.warning("Empty signals for %s — skipping", asset)
        return None

    # Assign folds
    summary_path = WALKDIR / f"{asset}_wf_summary_base.csv"
    folds = assign_folds(df, summary_path)
    df = df[folds >= 0].copy()
    df["fold"] = folds

    # Pre-filter PnL (original)
    r_pre = compute_asset_daily_r(df, tp, sl)

    # Apply filter
    df_filtered = df.copy()
    if filter_sig == 1:
        df_filtered.loc[df_filtered["signal"] == 1, "signal"] = 0
    else:
        df_filtered.loc[df_filtered["signal"] == -1, "signal"] = 0

    r_post = compute_asset_daily_r(df_filtered, tp, sl)

    # Per-fold breakdown
    rows = []
    for f in sorted(df["fold"].unique()):
        idx = df["fold"] == f
        mask_pre = r_pre[idx]
        mask_post = r_post[idx]

        n_pre = int((mask_pre != 0).sum())
        n_post = int((mask_post != 0).sum())
        R_pre = float(mask_pre.sum())
        R_post = float(mask_post.sum())

        rows.append({
            "asset": asset,
            "group": "A" if asset in GROUP_A else "B",
            "filter": "BUY" if filter_sig == 1 else "SELL",
            "fold": int(f),
            "n_pre": n_pre,
            "n_post": n_post,
            "R_pre": round(R_pre, 2),
            "R_post": round(R_post, 2),
            "delta": round(R_post - R_pre, 2),
        })

    # Overall
    n_pre = int((r_pre != 0).sum())
    n_post = int((r_post != 0).sum())
    R_pre_tot = float(r_pre.sum())
    R_post_tot = float(r_post.sum())

    return {
        "per_fold": pd.DataFrame(rows),
        "overall": {
            "asset": asset,
            "group": "A" if asset in GROUP_A else "B",
            "filter": "BUY" if filter_sig == 1 else "SELL",
            "n_pre": n_pre, "n_post": n_post,
            "R_pre": round(R_pre_tot, 2),
            "R_post": round(R_post_tot, 2),
            "delta": round(R_post_tot - R_pre_tot, 2),
        },
        "r_pre": r_pre,
        "r_post": r_post,
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    all_results = {}
    per_fold_rows = []

    print("=" * 72)
    print("DIRECTIONAL FILTER DIAGNOSTIC")
    print("=" * 72)
    print()

    for asset, filter_sig in FILTER_MAP.items():
        res = run_filter(asset, filter_sig)
        if res is None:
            continue

        all_results[asset] = res
        per_fold_rows.append(res["per_fold"])

        o = res["overall"]
        tag = "REPAIR" if o["group"] == "A" else "SANITY"
        print(f"  {asset:8s} [{tag}] filter {o['filter']:5s}: "
              f"{o['R_pre']:>+8.2f}R → {o['R_post']:>+8.2f}R  "
              f"Δ={o['delta']:>+7.2f}R  "
              f"trades: {o['n_pre']:3d} → {o['n_post']:3d}")

    # Portfolio-level comparison
    print()
    print("-" * 72)
    print("Portfolio-level (all filtered assets + rest unchanged)")
    print("-" * 72)

    # Full portfolio pre-filter (all 22 assets from config)
    pt_sl_map = _asset_pt_sl_from_config()
    all_pre: dict[str, pd.Series] = {}
    all_post: dict[str, pd.Series] = {}
    for asset in pt_sl_map:
        if asset in all_results:
            all_pre[asset] = all_results[asset]["r_pre"]
            all_post[asset] = all_results[asset]["r_post"]
        else:
            pq_path = WALKDIR / f"{asset}_wf_signals_base.parquet"
            if not pq_path.exists():
                continue
            tp, sl = pt_sl_map[asset]
            df = load_asset_signals(str(pq_path))
            if df.empty:
                continue
            r = compute_asset_daily_r(df, tp, sl)
            all_pre[asset] = r
            all_post[asset] = r

    pf_pre = build_portfolio_daily_r(all_pre, min_assets=10)
    pf_post = build_portfolio_daily_r(all_post, min_assets=10)

    # Align dates
    common = pf_pre.index.intersection(pf_post.index)
    r_pre_pf = pf_pre.loc[common, "portfolio_r"]
    r_post_pf = pf_post.loc[common, "portfolio_r"]

    delta_total = r_post_pf.sum() - r_pre_pf.sum()
    n_days = len(common)

    print(f"  Days:            {n_days:5d}")
    print(f"  Pre-filter R:    {r_pre_pf.sum():>+8.2f}")
    print(f"  Post-filter R:   {r_post_pf.sum():>+8.2f}")
    print(f"  Delta:           {delta_total:>+8.2f}")
    print()

    # Per-fold combined
    if per_fold_rows:
        combined = pd.concat(per_fold_rows, ignore_index=True)
        print("-" * 72)
        print("Per-fold detail")
        print("-" * 72)
        for _, row in combined.iterrows():
            g = "A" if row["group"] == "A" else "B"
            print(f"  {row['asset']:8s} [{g}] fold {int(row['fold'])}  "
                  f"filter {row['filter']:5s}: "
                  f"trades {int(row['n_pre']):3d}→{int(row['n_post']):3d}  "
                  f"R {row['R_pre']:>+8.2f} → {row['R_post']:>+8.2f}  "
                  f"Δ={row['delta']:>+7.2f}")

        # Save
        out_path = WALKDIR / "filter_direction_results.csv"
        combined.to_csv(out_path, index=False)
        print(f"\nSaved -> {out_path}")

    # Per-group totals
    print()
    print("-" * 72)
    print("Group totals")
    print("-" * 72)
    for g_name, g_assets in [("Group A (repair)", GROUP_A), ("Group B (sanity)", GROUP_B)]:
        g_pre = pd.concat(
            [all_results[a]["r_pre"] for a in g_assets if a in all_results],
            axis=1,
        ).sum(axis=1)
        g_post = pd.concat(
            [all_results[a]["r_post"] for a in g_assets if a in all_results],
            axis=1,
        ).sum(axis=1)
        print(f"  {g_name:20s}: pre={g_pre.sum():>+8.2f}R  "
              f"post={g_post.sum():>+8.2f}R  "
              f"Δ={g_post.sum()-g_pre.sum():>+7.2f}R")


if __name__ == "__main__":
    main()
