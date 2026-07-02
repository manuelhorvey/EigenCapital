#!/usr/bin/env python3
"""3-asset ensemble pilot backtest.

Compares base-only vs ensemble (base + regime model) on a chronological
walk-forward.  Runs on AUDNZD (worst), EURUSD (mid), GBPCAD (best).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/ensemble_pilot_backtest.py

Output:
    ensemble_pilot/{asset}_pilotsummary.csv  — per-window metrics
    ensemble_pilot/summary.json              — cross-asset comparison
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, fetch_cot_features
from features.regime_features import generate_regime_features
from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ensemble_pilot")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "ensemble_pilot")
os.makedirs(OUTPUT_DIR, exist_ok=True)

MODEL_DIR = os.path.join(BASE, "paper_trading", "models")

PILOT_ASSETS: dict[str, str] = {
    "AUDNZD": "AUDNZD=X",
    "EURUSD": "EURUSD=X",
    "GBPCAD": "GBPCAD=X",
}


def slugify(ticker: str) -> str:
    return ticker.replace("=X", "").replace("=F", "").replace("-", "").replace("=", "")


def _to_binary(y: pd.Series) -> pd.Series:
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_ensemble_pilot(
    asset_name: str,
    ticker: str,
    n_folds: int = 5,
    gap: int = 20,
) -> dict | None:
    import xgboost as xgb

    pt_sl = (2.0, 2.0)

    logger.info("=== %s ensemble pilot ===", asset_name)

    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if prices.empty or len(prices) < 300:
        logger.warning("SKIP: %s — insufficient data", asset_name)
        return None

    ohlcv = fetch_asset_ohlcv(ticker)

    labels = triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=20)
    cot_data = fetch_cot_features(prices.index)
    alpha_df = build_alpha_features(
        prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, cot_data=cot_data
    )  # noqa: E501

    alpha_df["label"] = labels.reindex(alpha_df.index).astype(int)
    alpha_df = alpha_df.dropna()
    if len(alpha_df) < 300:
        logger.warning("%s: insufficient alpha features (%d)", asset_name, len(alpha_df))
        return None

    regime_ok = not ohlcv.empty
    if regime_ok:
        regime_df = generate_regime_features(ohlcv)
        prefix = asset_name.upper()
        regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
        alpha_df.index.intersection(regime_renamed.index)
        full_df = alpha_df.join(regime_renamed, how="left")
    else:
        full_df = alpha_df.copy()

    full_df = full_df.dropna()
    if len(full_df) < 300:
        logger.warning("%s: insufficient full features (%d)", asset_name, len(full_df))
        return None

    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    regime_cols = list(regime_renamed.columns) if regime_ok else []
    all_cols = alpha_cols + regime_cols

    y_bin = _to_binary(full_df["label"])
    X_all = full_df[all_cols].loc[y_bin.index]

    if len(y_bin) < 200:
        logger.warning("%s: only %d binary samples", asset_name, len(y_bin))
        return None

    cv = PurgedWalkForwardFolds(n_folds=n_folds, gap=gap, min_train=100)

    base_windows = []
    ensemble_windows = []

    hi_thresh = 0.5 + 0.15 / 2.0
    lo_thresh = 0.5 - 0.15 / 2.0

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        train_start = X_all.index[train_idx[0]]
        train_end = X_all.index[train_idx[-1]]
        test_start = X_all.index[test_idx[0]]
        test_end = X_all.index[test_idx[-1]]

        X_tr = X_all.iloc[train_idx]
        y_tr = y_bin.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_bin.iloc[test_idx]

        if y_tr.nunique() < 2:
            logger.warning("  fold %d: only one class in train, skipping", fold)
            continue

        # Base model (same params as live pipeline: max_depth=2, no scale_pos_weight
        # for pilot consistency)
        base_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=2,
            learning_rate=0.02,
            objective="binary:logistic",
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        base_model.fit(X_tr[alpha_cols], y_tr)
        base_p_long = base_model.predict_proba(X_te[alpha_cols])[:, 1]

        # Regime model (train on alpha + regime features, using RegimeConditionalModel for production parity)
        if regime_ok and len(regime_cols) > 0:
            X_tr_regime = X_tr[all_cols]
            X_te_regime = X_te[all_cols]
            regime_model = RegimeConditionalModel()
            regime_model.train(X_tr_regime, y_tr, all_cols)
            regime_p_long = regime_model.predict_long_prob(X_te_regime).ravel()
        else:
            regime_p_long = None

        # Base-only signals
        base_signals = np.zeros(len(base_p_long), dtype=int)
        base_signals[base_p_long > hi_thresh] = 1
        base_signals[base_p_long < lo_thresh] = -1

        base_hit = (base_signals == y_te.values).mean()
        base_dir = (base_signals * (y_te.values * 2 - 1)).sum() / max((base_signals != 0).sum(), 1)
        base_long_prec = ((base_signals == 1) & (y_te.values == 1)).sum() / max((base_signals == 1).sum(), 1)
        base_short_prec = ((base_signals == -1) & (y_te.values == 0)).sum() / max((base_signals == -1).sum(), 1)

        base_windows.append(
            {
                "fold": fold,
                "train_start": str(train_start.date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "hit_rate": float(f"{base_hit:.4f}"),
                "directional_ic": float(f"{base_dir:.4f}"),
                "long_precision": float(f"{base_long_prec:.4f}"),
                "short_precision": float(f"{base_short_prec:.4f}"),
            }
        )

        # Ensemble signals
        if regime_p_long is not None:
            ensemble = EnsembleSignal(base_weight=0.6, ensemble_threshold=0.15)
            blended, ens_signals_arr = ensemble.combine(base_p_long, regime_p_long)
        else:
            blended = base_p_long.copy()
            ens_signals_arr = np.zeros(len(blended), dtype=int)
            ens_signals_arr[blended > hi_thresh] = 1
            ens_signals_arr[blended < lo_thresh] = -1

        ens_hit = (ens_signals_arr == y_te.values).mean()
        ens_dir = (ens_signals_arr * (y_te.values * 2 - 1)).sum() / max((ens_signals_arr != 0).sum(), 1)
        ens_long_prec = ((ens_signals_arr == 1) & (y_te.values == 1)).sum() / max((ens_signals_arr == 1).sum(), 1)
        ens_short_prec = ((ens_signals_arr == -1) & (y_te.values == 0)).sum() / max((ens_signals_arr == -1).sum(), 1)

        ensemble_windows.append(
            {
                "fold": fold,
                "hit_rate": float(f"{ens_hit:.4f}"),
                "directional_ic": float(f"{ens_dir:.4f}"),
                "long_precision": float(f"{ens_long_prec:.4f}"),
                "short_precision": float(f"{ens_short_prec:.4f}"),
            }
        )

        logger.info(
            "  fold %d: base=(hit=%.3f dir=%.3f long=%.3f short=%.3f) ens=(hit=%.3f dir=%.3f long=%.3f short=%.3f)",
            fold,
            base_hit,
            base_dir,
            base_long_prec,
            base_short_prec,
            ens_hit,
            ens_dir,
            ens_long_prec,
            ens_short_prec,
        )

    if not base_windows:
        logger.warning("%s: no windows produced", asset_name)
        return None

    base_summary = pd.DataFrame(base_windows)
    ens_summary = pd.DataFrame(ensemble_windows)

    comparison = {
        "asset": asset_name,
        "base_mean_hit": float(base_summary["hit_rate"].mean()),
        "base_mean_ic": float(base_summary["directional_ic"].mean()),
        "base_mean_long_prec": float(base_summary["long_precision"].mean()),
        "base_mean_short_prec": float(base_summary["short_precision"].mean()),
        "base_positive_ic_folds": int((base_summary["directional_ic"] > 0).sum()),
        "ens_mean_hit": float(ens_summary["hit_rate"].mean()),
        "ens_mean_ic": float(ens_summary["directional_ic"].mean()),
        "ens_mean_long_prec": float(ens_summary["long_precision"].mean()),
        "ens_mean_short_prec": float(ens_summary["short_precision"].mean()),
        "ens_positive_ic_folds": int((ens_summary["directional_ic"] > 0).sum()),
        "delta_hit": float(ens_summary["hit_rate"].mean() - base_summary["hit_rate"].mean()),
        "delta_ic": float(ens_summary["directional_ic"].mean() - base_summary["directional_ic"].mean()),
        "delta_long_prec": float(ens_summary["long_precision"].mean() - base_summary["long_precision"].mean()),
        "delta_short_prec": float(ens_summary["short_precision"].mean() - base_summary["short_precision"].mean()),
        "n_folds": len(base_windows),
        "regime_feature_count": len(regime_cols),
    }

    # Save per-window detail
    base_summary.to_csv(os.path.join(OUTPUT_DIR, f"{asset_name}_base_windows.csv"), index=False)
    ens_summary.to_csv(os.path.join(OUTPUT_DIR, f"{asset_name}_ens_windows.csv"), index=False)

    logger.info(
        "%s: base=(hit=%.3f ic=%.3f long_prec=%.3f short_prec=%.3f) "
        "ens=(hit=%.3f ic=%.3f long_prec=%.3f short_prec=%.3f) "
        "delta=(hit=%.3f ic=%.3f long_prec=%.3f short_prec=%.3f)",
        asset_name,
        comparison["base_mean_hit"],
        comparison["base_mean_ic"],
        comparison["base_mean_long_prec"],
        comparison["base_mean_short_prec"],
        comparison["ens_mean_hit"],
        comparison["ens_mean_ic"],
        comparison["ens_mean_long_prec"],
        comparison["ens_mean_short_prec"],
        comparison["delta_hit"],
        comparison["delta_ic"],
        comparison["delta_long_prec"],
        comparison["delta_short_prec"],
    )

    return comparison


def main():
    results = []
    for name, ticker in PILOT_ASSETS.items():
        try:
            result = run_ensemble_pilot(name, ticker, n_folds=5, gap=20)
            if result is not None:
                results.append(result)
        except Exception as e:
            logger.error("%s: failed — %s", name, e, exc_info=True)

    if not results:
        logger.error("No assets produced results — exiting")
        return

    print("\n" + "=" * 80)
    print("ENSEMBLE PILOT BACKTEST — BASE VS ENSEMBLE COMPARISON")
    print("=" * 80)

    r_df = pd.DataFrame(results)
    for _, r in r_df.iterrows():
        print(f"\n{r['asset']}:")
        print(
            f"  Base:    hit={r['base_mean_hit']:.3f}  ic={r['base_mean_ic']:.3f}  "
            f"long={r['base_mean_long_prec']:.3f}  short={r['base_mean_short_prec']:.3f}"
        )
        print(
            f"  Ens:     hit={r['ens_mean_hit']:.3f}  ic={r['ens_mean_ic']:.3f}  "
            f"long={r['ens_mean_long_prec']:.3f}  short={r['ens_mean_short_prec']:.3f}"
        )
        print(
            f"  Delta:   hit={r['delta_hit']:+.3f}  ic={r['delta_ic']:+.3f}  "
            f"long={r['delta_long_prec']:+.3f}  short={r['delta_short_prec']:+.3f}"
        )
        print(f"  Folds: {r['n_folds']}  Regime feats: {r['regime_feature_count']}")

    # Decision rule: IC (Sharpe proxy) + both precisions improve on >= 2/3 assets
    improved = sum(
        1 for _, r in r_df.iterrows() if r["delta_ic"] > 0 and r["delta_long_prec"] > 0 and r["delta_short_prec"] > 0
    )
    passed = improved >= 2

    print(f"\n{'=' * 80}")
    print(f"DECISION: {'PASS — enable ensemble for all 21' if passed else 'FAIL — keep ensemble disabled'}")
    print(f"  Assets where IC + both precisions improved: {improved}/{len(results)}")
    print("  Threshold: >= 2/3 required")

    summary_path = os.path.join(OUTPUT_DIR, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(
            {
                "results": results,
                "passed": passed,
                "improved_count": improved,
                "total_assets": len(results),
                "threshold": ">= 2/3",
                "run_timestamp": datetime.utcnow().isoformat(),
            },
            f,
            indent=2,
        )
    print(f"\nFull results -> {summary_path}")


if __name__ == "__main__":
    main()
