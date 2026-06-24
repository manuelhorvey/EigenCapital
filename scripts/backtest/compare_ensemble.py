#!/usr/bin/env python3
"""
Compare ensemble vs base walk-forward results from two tagged CSV files.

Usage:
    python scripts/compare_ensemble.py \\
        --ensemble walkforward/all_assets_wf_summary_ensemble.csv \\
        --base walkforward/all_assets_wf_summary_base.csv

Output: per-asset IC deltas with sign-test and t-test p-values,
plus pooled summary across all assets.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel, binomtest


def load_and_validate(ens_path: str, base_path: str) -> pd.DataFrame:
    ens = pd.read_csv(ens_path)
    base = pd.read_csv(base_path)

    print(f"Ensemble rows: {len(ens)}, assets: {ens['asset'].nunique()}")
    print(f"Base rows:     {len(base)}, assets: {base['asset'].nunique()}")

    ens_folds = ens.groupby("asset").size()
    base_folds = base.groupby("asset").size()

    print(f"\nEnsemble folds/asset:\n  min={ens_folds.min()}, max={ens_folds.max()}, mean={ens_folds.mean():.1f}")
    print(f"Base folds/asset:\n  min={base_folds.min()}, max={base_folds.max()}, mean={base_folds.mean():.1f}")

    # Detect fold-count mismatch
    mismatch = []
    for asset in set(list(ens_folds.index) + list(base_folds.index)):
        en = ens_folds.get(asset, 0)
        bn = base_folds.get(asset, 0)
        if en != bn:
            mismatch.append((asset, en, bn))
    if mismatch:
        print("\nFOLD COUNT MISMATCH — aborting. Investigate before diffing:")
        for asset, en, bn in mismatch:
            print(f"  {asset}: ensemble has {en} folds, base has {bn} folds")
        sys.exit(1)

    merged = ens.merge(base, on=["asset", "fold"], suffixes=("_ens", "_base"))
    n_ens = len(ens)
    n_base = len(base)
    n_merged = len(merged)
    if n_merged != n_ens or n_merged != n_base:
        print(f"\nMERGED ROWS ({n_merged}) ≠ ensemble ({n_ens}) or base ({n_base}) — fold key mismatch. Aborting.")
        sys.exit(1)

    print(f"\nMerged rows: {n_merged} — OK (all fold keys match)")
    print("-" * 72)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Compare ensemble vs base walk-forward results")
    parser.add_argument("--ensemble", required=True, help="Ensemble combined CSV path")
    parser.add_argument("--base", required=True, help="Base-only combined CSV path")
    args = parser.parse_args()

    merged = load_and_validate(args.ensemble, args.base)

    merged["ic_delta"] = merged["directional_ens"] - merged["directional_base"]

    results = []
    for asset, grp in merged.groupby("asset"):
        n = len(grp)
        mean_delta = grp["ic_delta"].mean()
        std_delta = grp["ic_delta"].std(ddof=1) if n > 1 else 0.0

        # Sign test: count folds where ensemble wins (delta > 0)
        n_wins = (grp["ic_delta"] > 0).sum()
        n_losses = (grp["ic_delta"] < 0).sum()
        n_ties = n - n_wins - n_losses

        # Two-sided sign test against p=0.5 (H0: ensemble no better than base)
        n_non_ties = n_wins + n_losses
        if n_non_ties > 0:
            sign_p = binomtest(n_wins, n_non_ties, p=0.5, alternative="two-sided").pvalue
        else:
            sign_p = 1.0

        # Paired t-test
        if n > 1 and std_delta > 0:
            t_stat, t_p = ttest_rel(grp["directional_ens"], grp["directional_base"])
        else:
            t_stat, t_p = 0.0, 1.0

        results.append({
            "asset": asset,
            "n_folds": n,
            "delta_mean": round(mean_delta, 4),
            "delta_std": round(std_delta, 4),
            "wins": n_wins,
            "losses": n_losses,
            "ties": n_ties,
            "sign_p": sign_p,
            "t_p": t_p,
        })

    per_asset = pd.DataFrame(results)

    print("\nPer-asset IC deltas (ensemble - base):")
    print("=" * 72)
    display = per_asset.set_index("asset")[
        ["n_folds", "delta_mean", "delta_std", "wins", "losses", "sign_p", "t_p"]
    ].sort_values("delta_mean", ascending=False)
    for idx, row in display.iterrows():
        sig = ""
        if row["sign_p"] < 0.10:
            sig = " *"
        elif row["sign_p"] < 0.05:
            sig = " **"
        elif row["sign_p"] < 0.01:
            sig = " ***"
        print(
            f"  {idx:>8s}  n={int(row['n_folds']):d}  "
            f"Δ={row['delta_mean']:+.4f} ±{row['delta_std']:.4f}  "
            f"W/L={int(row['wins']):d}/{int(row['losses']):d}  "
            f"sign-p={row['sign_p']:.3f}{sig}  t-p={row['t_p']:.3f}"
        )

    # Pooled sign test (all asset×fold pairs)
    all_deltas = merged["ic_delta"]
    n_total = len(all_deltas)
    n_wins_total = (all_deltas > 0).sum()
    n_losses_total = (all_deltas < 0).sum()
    n_ties_total = n_total - n_wins_total - n_losses_total
    n_non_ties_total = n_wins_total + n_losses_total
    if n_non_ties_total > 0:
        pooled_p = binomtest(n_wins_total, n_non_ties_total, p=0.5, alternative="two-sided").pvalue
    else:
        pooled_p = 1.0

    print("\n" + "=" * 72)
    print(f"Pooled across {n_total} asset×fold pairs:")
    print(f"  Wins: {n_wins_total}, Losses: {n_losses_total}, Ties: {n_ties_total}")
    print(f"  Mean Δ: {all_deltas.mean():+.4f}, Median Δ: {all_deltas.median():+.4f}")
    print(f"  Sign test p (pooled): {pooled_p:.4f}")
    print(f"  Assets improved: {(per_asset['delta_mean'] > 0).sum()}/{len(per_asset)}")

    # Save full results
    out_path = "walkforward/ensemble_comparison.csv"
    per_asset.to_csv(out_path, index=False)
    print(f"\nPer-asset detail -> {out_path}")


if __name__ == "__main__":
    main()
