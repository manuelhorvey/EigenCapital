#!/usr/bin/env python3
"""
Tests alternative training strategies on the 5 problematic assets + VIX.
Strategies: binary (baseline), 3-class multiclass, balanced weights, both.
Uses default (non-swapped) barriers for all.
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_cot_features
from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("improve")
logger.setLevel(logging.INFO)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "walkforward")

REMAINING = {
    "VIX": ("^VIX", (1.5, 1.5)),
    "GBPUSD": ("GBPUSD=X", (1.97, 0.52)),
    "AUDJPY": ("AUDJPY=X", (2.01, 0.52)),
    "CADJPY": ("CADJPY=X", (1.65, 0.52)),
    "USDJPY": ("USDJPY=X", (1.97, 0.52)),
    "NZDJPY": ("NZDJPY=X", (2.02, 0.51)),
}


def compute_labels(prices, pt_sl, vertical_barrier=20):
    return triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=vertical_barrier)


def _to_binary(y):
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_one(asset_name, ticker, pt_sl):
    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if prices.empty or len(prices) < 100:
        return None
    labels = compute_labels(prices, pt_sl=pt_sl, vertical_barrier=20)
    cot_data = fetch_cot_features(prices.index)
    alpha_df = build_alpha_features(
        prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, cot_data=cot_data
    )
    alpha_df["label"] = labels.reindex(alpha_df.index).astype(int)
    alpha_df = alpha_df.dropna(subset=["label"])
    if len(alpha_df) < 300:
        return None

    feature_cols = [c for c in alpha_df.columns if c != "label"]
    X_all = alpha_df[feature_cols]
    y_all_3c = alpha_df["label"]
    y_all_binary = _to_binary(y_all_3c)

    if len(y_all_binary) < 100:
        logger.warning("%s: only %d binary samples", asset_name, len(y_all_binary))
    X_all_bin = X_all.loc[y_all_binary.index]

    gap = max(5, 20)
    cv = PurgedWalkForwardFolds(n_folds=5, gap=gap, min_train=100)
    cv_indices = list(cv.split(X_all))

    strategies = [
        ("binary", True),
        ("3class", False),
        ("binary_balanced", True),
        ("3class_balanced", False),
    ]

    results = []
    for strat_name, is_binary in strategies:
        window_results = []
        for fold, (train_idx, test_idx) in enumerate(cv_indices):
            train_dates = X_all.index[train_idx]
            test_dates = X_all.index[test_idx]

            if is_binary:
                X_use, y_use = X_all_bin, y_all_binary
            else:
                X_use, y_use = X_all, y_all_3c

            train_common = X_use.index.intersection(train_dates)
            test_common = X_use.index.intersection(test_dates)
            if len(train_common) < 50 or len(test_common) < 10:
                continue

            X_tr = X_use.loc[train_common]
            y_tr = y_use.loc[train_common]
            X_te = X_use.loc[test_common]
            y_te = y_use.loc[test_common]

            if y_tr.nunique() < 2 or len(y_tr) < 50:
                continue

            if not is_binary and y_tr.nunique() < 3:
                continue  # 3-class requires all three labels in fold

            if is_binary:
                model = xgb.XGBClassifier(
                    n_estimators=300,
                    max_depth=2,
                    learning_rate=0.02,
                    objective="binary:logistic",
                    random_state=42,
                    n_jobs=1,
                    tree_method="hist",
                    verbosity=0,
                )
                if "balanced" in strat_name:
                    w = pd.Series(1.0, index=y_tr.index)
                    for cls in y_tr.unique():
                        mask = y_tr == cls
                        w[mask] = 1.0 / (mask.sum() * y_tr.nunique())
                    w *= len(y_tr)
                    model.fit(X_tr, y_tr, sample_weight=w)
                else:
                    n0, n1 = (y_tr == 0).sum(), (y_tr == 1).sum()
                    model.set_params(scale_pos_weight=n0 / max(n1, 1))
                    model.fit(X_tr, y_tr)
            else:
                model = xgb.XGBClassifier(
                    n_estimators=300,
                    max_depth=2,
                    learning_rate=0.02,
                    objective="multi:softprob",
                    num_class=3,
                    random_state=42,
                    n_jobs=1,
                    tree_method="hist",
                    verbosity=0,
                )
                y_tr_mapped = y_tr.map({-1: 0, 0: 1, 1: 2})
                y_te_mapped = y_te.values  # keep original {-1, 0, 1}
                if "balanced" in strat_name:
                    w = pd.Series(1.0, index=y_tr.index)
                    for cls in y_tr.unique():
                        mask = y_tr == cls
                        w[mask] = 1.0 / (mask.sum() * y_tr.nunique())
                    w *= len(y_tr)
                    model.fit(X_tr, y_tr_mapped, sample_weight=w)
                else:
                    model.fit(X_tr, y_tr_mapped)

            # Predict
            if is_binary:
                p_long = model.predict_proba(X_te)[:, 1]
                hi = 0.5 + 0.15 / 2.0
                lo = 0.5 - 0.15 / 2.0
                signals = np.zeros(len(p_long), dtype=int)
                signals[p_long > hi] = 1
                signals[p_long < lo] = -1
                y_te_mapped = y_te.values * 2 - 1  # {0, 1} → {-1, 1}
            else:
                proba = model.predict_proba(X_te)
                signals = np.argmax(proba, axis=1) - 1  # {0,1,2} → {-1,0,1}

            tmask = signals != 0
            directional = (signals[tmask] * y_te_mapped[tmask]).sum() / tmask.sum() if tmask.sum() > 0 else 0.0
            hit_rate = (signals == y_te_mapped).mean()
            long_rate = (signals == 1).mean()
            short_rate = (signals == -1).mean()
            flat_rate = (signals == 0).mean()

            window_results.append(
                {
                    "fold": fold,
                    "hit_rate": hit_rate,
                    "directional": directional,
                    "long_rate": long_rate,
                    "short_rate": short_rate,
                    "flat_rate": flat_rate,
                }
            )
            if fold == 0:
                logger.info(
                    "  %s fold0 %s: dir=%.4f hit=%.3f long=%.3f short=%.3f flat=%.3f",
                    asset_name,
                    strat_name,
                    directional,
                    hit_rate,
                    long_rate,
                    short_rate,
                    flat_rate,
                )

        if len(window_results) >= 2:
            df = pd.DataFrame(window_results)
            results.append(
                {
                    "asset": asset_name,
                    "strategy": strat_name,
                    "mean_ic": df["directional"].mean(),
                    "mean_hit_rate": df["hit_rate"].mean(),
                    "mean_long_rate": df["long_rate"].mean(),
                    "mean_short_rate": df["short_rate"].mean(),
                    "mean_flat_rate": df["flat_rate"].mean(),
                    "pos_folds": int((df["directional"] > 0).sum()),
                    "total_folds": len(df),
                }
            )
    return results


def main():
    all_results = []
    for name, (ticker, pt_sl) in REMAINING.items():
        logger.info("=== %s (%s) pt_sl=%s ===", name, ticker, pt_sl)
        r = run_one(name, ticker, pt_sl)
        if r:
            all_results.extend(r)

    if not all_results:
        print("No results.")
        return

    df = pd.DataFrame(all_results)
    grid_path = os.path.join(OUTPUT_DIR, "improvement_grid.csv")
    df.to_csv(grid_path, index=False)
    logger.info("Saved -> %s", grid_path)

    print("\n" + "=" * 130)
    print("IMPROVEMENT RESULTS — Strategy comparison per asset (default barriers)")
    print("=" * 130)
    print(f"{'Asset':<8} {'Strategy':<18} {'IC':>7} {'HitRate':>8} {'Long':>6} {'Short':>6} {'Flat':>6} {'PosFold':>8}")
    print("-" * 130)
    for _, r in df.sort_values(["asset", "mean_ic"], ascending=[True, False]).iterrows():
        print(
            f"{r['asset']:<8} {r['strategy']:<18} {r['mean_ic']:>7.4f} {r['mean_hit_rate']:>8.3f} "
            f"{r['mean_long_rate']:>6.3f} {r['mean_short_rate']:>6.3f} {r['mean_flat_rate']:>6.3f} "
            f"{r['pos_folds']}/{r['total_folds']}"
        )

    # Cross-asset summary
    print("\n--- Cross-asset average by strategy ---")
    for s in df["strategy"].unique():
        sub = df[df["strategy"] == s]
        g = (sub["pos_folds"] >= sub["total_folds"] / 2).sum()
        print(
            f"  {s:<18}: mean_IC={sub['mean_ic'].mean():.4f}  mean_hit={sub['mean_hit_rate'].mean():.3f}  "
            f"majority_pos={g}/{len(sub)}"
        )


if __name__ == "__main__":
    main()
