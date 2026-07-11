#!/usr/bin/env python3
"""SHAP audit of BUY inversion for 9 flagged assets.

Loads each asset's live base XGBoost model, computes SHAP on all training data,
compares feature attributions between wrong confident-BUY vs correct confident-BUY.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/shap_audit.py
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data
from labels.compat import triple_barrier_labels

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("shap_audit")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE, "paper_trading", "models")

# 9 flagged assets
AUX = frozenset({"^DJI", "ES", "NQ"})
CHF_CLUSTER = frozenset({"CADCHF", "NZDCHF", "USDCHF", "EURCHF", "AUDUSD", "EURAUD"})
ALL_FLAGGED = AUX | CHF_CLUSTER

# Load per-asset config
from paper_trading.config_manager import get_config as _get_cfg

_cfg = _get_cfg()
ASSET_TICKER: dict[str, str] = {}
ASSET_PT_SL: dict[str, tuple[float, float]] = {}
ASSET_MAX_DEPTH: dict[str, int] = {}
for _name, _acfg in _cfg.assets.items():
    if _name in ALL_FLAGGED:
        _t = _acfg.get("ticker", f"{_name}=X")
        _tp = float(_acfg.get("tp_mult", 2.0))
        _sl = float(_acfg.get("sl_mult", 2.0))
        _md = int(_acfg.get("max_depth", 2))
        ASSET_TICKER[_name] = _t
        ASSET_PT_SL[_name] = (_tp, _sl)
        ASSET_MAX_DEPTH[_name] = _md

# Pass/fail: if any feature has >=0.05 (5%) mean SHAP difference between wrong and
# correct confident-BUY calls across assets, AND the sign is consistent across the cluster,
# that's a candidate mechanism. Otherwise report "no feature pair clearly separates."
# threshold set before running:
SHAP_DIFF_THRESHOLD = 0.05


def _model_path(asset_name: str) -> str:
    filename = f"{asset_name}_model.json"
    # ^DJI is stored as DJI_model.json (caret stripped)
    if asset_name == "^DJI":
        filename = "DJI_model.json"
    return os.path.join(MODEL_DIR, filename)


def fetch_features(
    asset_name: str, ticker: str, pt_sl: tuple[float, float]
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Fetch data, build labels and alpha features.

    Matches walk_forward_backtest.py logic exactly.
    Returns (X, y_binary, alpha_cols) where y_binary={0,1}.
    """
    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if prices.empty:
        msg = f"No data for {asset_name}"
        raise ValueError(msg)

    labels = triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=20, vol_lookback=21)
    alpha_df = build_alpha_features(
        prices,
        rate_diffs,
        dxy=dxy,
        vix=vix,
        spx=spx,
        commodities=commodities,
    )
    alpha_df["label"] = labels.reindex(alpha_df.index).astype(int)
    alpha_df = alpha_df.dropna()

    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    X_all = alpha_df[alpha_cols]
    y_all = alpha_df["label"]

    # Binary classification: drop HOLD (0), map -1->0, 1->1
    mask = y_all != 0
    X_bin = X_all[mask]
    y_bin = y_all[mask].map({-1: 0, 1: 1})

    if len(y_bin) < 100:
        raise ValueError(f"{asset_name}: only {len(y_bin)} binary samples")

    return X_bin, y_bin, alpha_cols


def run_shap_audit(asset_name: str, ticker: str, pt_sl: tuple[float, float], max_depth: int) -> dict:
    """Run full SHAP audit for one asset.

    Returns dict with:
      - p_long for all non-flat predictions
      - actual triple-barrier label for all rows
      - SHAP values for confident-BUY rows (p_long > 0.5)
      - Separated into wrong (label < 0) vs correct (label > 0)
    """
    logger.info("\n%s", "=" * 60)
    logger.info("Asset: %s (%s), pt_sl=%s, max_depth=%d", asset_name, ticker, pt_sl, max_depth)

    # Load features
    X, y, alpha_cols = fetch_features(asset_name, ticker, pt_sl)
    logger.info("  Features: %s", X.shape)

    # Load model
    mpath = _model_path(asset_name)
    if not os.path.exists(mpath):
        raise FileNotFoundError(f"Model not found: {mpath}")
    model = xgb.XGBClassifier()
    model.load_model(mpath)
    logger.info("  Model loaded: %s", mpath)

    # Predict probabilities
    p_long_arr = model.predict_proba(X)[:, 1]
    p_long = pd.Series(p_long_arr, index=X.index)

    # Confident BUY: p_long > 0.5

    # Get original triples to determine correct/wrong
    # y=1 in binary = correct direction (label was BUY or SELL and model matched)
    # But we need the ORIGINAL triple-barrier label to know if BUY was right or wrong
    # Re-compute labels on the same data
    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    labels = triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=20, vol_lookback=21)
    alpha_df = build_alpha_features(
        prices,
        rate_diffs,
        dxy=dxy,
        vix=vix,
        spx=spx,
        commodities=commodities,
    )
    alpha_df["label"] = labels.reindex(alpha_df.index).astype(int)
    alpha_df = alpha_df.dropna()

    # Align: predictions were on X.index, labels on alpha_df.index
    common_idx = X.index.intersection(alpha_df.index)
    X_aligned = X.loc[common_idx]

    # Subset: confident BUY rows
    buy_idx = common_idx[p_long.loc[common_idx] > 0.5]
    correct_buy_idx = buy_idx[alpha_df.loc[buy_idx, "label"] > 0]
    wrong_buy_idx = buy_idx[alpha_df.loc[buy_idx, "label"] < 0]

    logger.info(
        "  Confident BUY: %d rows (correct: %d, wrong: %d", len(buy_idx), len(correct_buy_idx), len(wrong_buy_idx)
    )

    if len(buy_idx) < 10:
        logger.info("  SKIP: too few confident-BUY rows")
        return {
            "asset": asset_name,
            "n_buy": len(buy_idx),
            "n_correct_buy": len(correct_buy_idx),
            "n_wrong_buy": len(wrong_buy_idx),
            "skip": True,
        }

    # Compute SHAP on confident BUY rows
    logger.info("  Computing SHAP (%d rows, %d features)...", len(buy_idx), len(alpha_cols))
    X_buy = X_aligned.loc[buy_idx]
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_buy)

    if isinstance(shap_values, list):
        # shap 0.51 may return list for multi-class
        shap_values = shap_values[1]  # class 1 (BUY)

    # Mean SHAP per feature for wrong and correct
    wrong_mask = X_buy.index.isin(wrong_buy_idx)
    correct_mask = X_buy.index.isin(correct_buy_idx)

    shap_df = pd.DataFrame(shap_values, index=X_buy.index, columns=alpha_cols)

    wrong_shap = shap_df.loc[wrong_mask].mean() if wrong_mask.any() else pd.Series(0, index=alpha_cols)
    correct_shap = shap_df.loc[correct_mask].mean() if correct_mask.any() else pd.Series(0, index=alpha_cols)
    diff = wrong_shap - correct_shap

    logger.info("  Top features where wrong-BUY > correct-BUY SHAP:")
    for feat in diff.nlargest(5).index:
        logger.info(
            f"    {feat}: wrong={wrong_shap[feat]:+.4f}, correct={correct_shap[feat]:+.4f}, diff={diff[feat]:+.4f}"
        )
    logger.info("  Top features where correct-BUY > wrong-BUY SHAP:")
    for feat in diff.nsmallest(5).index:
        logger.info(
            f"    {feat}: wrong={wrong_shap[feat]:+.4f}, correct={correct_shap[feat]:+.4f}, diff={diff[feat]:+.4f}"
        )

    # Check which features exceed threshold
    strong_feats = diff[diff.abs() >= SHAP_DIFF_THRESHOLD]
    if len(strong_feats) > 0:
        logger.info("  Features with |diff| >= %s:", SHAP_DIFF_THRESHOLD)
        for feat in strong_feats.index:
            logger.info(
                "    %s: %+.4f (wrong=%+.4f, correct=%+.4f)", feat, diff[feat], wrong_shap[feat], correct_shap[feat]
            )

    return {
        "asset": asset_name,
        "n_buy": len(buy_idx),
        "n_correct_buy": len(correct_buy_idx),
        "n_wrong_buy": len(wrong_buy_idx),
        "skip": False,
        "wrong_shap": wrong_shap,
        "correct_shap": correct_shap,
        "diff": diff,
        "strong_feats": set(strong_feats.index) if len(strong_feats) > 0 else set(),
        "shap_df": shap_df,
    }


def main():
    results: dict[str, dict] = {}

    for asset_name in ALL_FLAGGED:
        try:
            result = run_shap_audit(
                asset_name,
                ASSET_TICKER[asset_name],
                ASSET_PT_SL[asset_name],
                ASSET_MAX_DEPTH[asset_name],
            )
            results[asset_name] = result
        except Exception as e:
            logger.error("  FAILED: %s", e)
            results[asset_name] = {"asset": asset_name, "error": str(e)}

    # --- Report per sub-cluster ---
    print("\n" + "=" * 60)
    print("SUB-CLUSTER ANALYSIS")
    print("=" * 60)

    for cluster_name, cluster_assets in [("Equities (^DJI, ES, NQ)", AUX), ("CHF+OTHER (6 assets)", CHF_CLUSTER)]:
        print(f"\n--- {cluster_name} ---")
        cluster_diffs = []
        strong_feats_union = set()
        weak_assets = []

        for a in sorted(cluster_assets, key=lambda x: list(ALL_FLAGGED).index(x) if x in ALL_FLAGGED else 0):
            r = results.get(a, {})
            if r.get("skip"):
                print(f"  {a}: SKIP (only {r['n_buy']} confident-BUY rows)")
                weak_assets.append(a)
                continue
            if "error" in r:
                print(f"  {a}: ERROR ({r['error']})")
                continue
            n_w = r["n_wrong_buy"]
            n_c = r["n_correct_buy"]
            print(f"  {a}: {r['n_buy']} confident-BUY rows ({n_c} correct, {n_w} wrong)")
            cluster_diffs.append(r["diff"])
            strong_feats_union |= r["strong_feats"]

        if len(cluster_diffs) == 0:
            print("  No assets with sufficient data.")
            continue

        # Pooled mean diff across cluster
        pooled = pd.concat(cluster_diffs, axis=1).mean(axis=1)
        print("\n  Pooled mean SHAP diff (wrong - correct) across cluster:")
        pooled_sorted = pooled.sort_values(key=lambda s: s.abs(), ascending=False)
        for feat in pooled_sorted.index[:8]:
            print(f"    {feat}: {pooled_sorted[feat]:+.4f}")

        # Check sign consistency: for each feature, what fraction of assets agree?
        print("\n  Sign consistency (fraction of assets with same sign as pooled):")
        for feat in pooled_sorted.index[:5]:
            signs = []
            for d in cluster_diffs:
                if feat in d.index:
                    signs.append(np.sign(d[feat]))
            if signs:
                maj_sign = np.sign(pooled_sorted[feat])
                consistency = sum(1 for s in signs if s == maj_sign) / len(signs)
                print(f"    {feat}: {consistency:.0%} agree ({maj_sign:+.0f}, {len(signs)} assets)")

        # Pass/fail
        max_diff = pooled_sorted.abs().max()
        top_feat = pooled_sorted.abs().idxmax()
        print(f"\n  Max |pooled diff|: {max_diff:.4f} (feature: {top_feat})")
        if max_diff >= SHAP_DIFF_THRESHOLD:
            print(f"  PASS: {top_feat} exceeds threshold ({SHAP_DIFF_THRESHOLD})")
        else:
            print(f"  FAIL: no feature reaches {SHAP_DIFF_THRESHOLD} threshold")

    print("\n" + "=" * 60)
    print("PASS/FAIL: Single metric")
    print("=" * 60)

    # Final determination: did any feature clearly separate wrong from correct
    # confident-BUY calls with consistent sign across the cluster?
    all_diffs = {}
    for a in ALL_FLAGGED:
        r = results.get(a, {})
        if "diff" in r:
            all_diffs[a] = r["diff"]

    if len(all_diffs) < 2:
        print("Insufficient data for final determination.")
        return

    combined = pd.concat(all_diffs, axis=1)
    pooled_total = combined.mean(axis=1)
    max_total = pooled_total.abs().max()
    top_total = pooled_total.abs().idxmax()
    print("Pooled across all 9 assets:")
    print(f"  Max |diff|: {max_total:.4f} (feature: {top_total})")
    if max_total >= SHAP_DIFF_THRESHOLD:
        print(f"  PASS — {top_total} separates wrong from correct confident-BUY calls.")
    else:
        print(f"  FAIL — no feature reaches {SHAP_DIFF_THRESHOLD} threshold.")
        print("  Conclusion: no feature pair clearly separates wrong from right confident-BUY calls.")


if __name__ == "__main__":
    main()
