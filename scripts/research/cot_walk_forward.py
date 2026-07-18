#!/usr/bin/env python3
"""Phase 3 — COT Counterfactual Walk-Forward Investigation.

Compares two models on the same walk-forward folds:
    A — Baseline: current production feature set (no COT)
    C — COT-enhanced: current features + proper COT features from cot_features.py

Uses strictly point-in-time COT data (3-day release lag enforced).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/cot_walk_forward.py --assets USDCAD,GBPUSD

Output:
    data/processed/audits/cot_investigation_results.json  — comparison metrics
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv
from data.loaders.cot_loader import load_cot_weekly, get_contract_series, align_cot_to_daily
from archive.deprecated._cot_features import build_cot_features
from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels
from labels.triple_barrier import apply_triple_barrier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cot_investigation")

ASSETS = {
    "USDCAD": "USDCAD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDCHF": "USDCHF=X",
    "NZDUSD": "NZDUSD=X",
    "EURUSD": "EURUSD=X",
}


@dataclass
class FoldComparison:
    asset: str
    fold: int
    baseline_ic: float
    cot_ic: float
    baseline_directional: float
    cot_directional: float
    baseline_sharpe: float
    cot_sharpe: float
    n_trades_baseline: int
    n_trades_cot: int
    cot_feature_count: int
    cot_features_with_gain: list[str] = field(default_factory=list)


@dataclass
class AssetResult:
    asset: str
    mean_baseline_ic: float
    mean_cot_ic: float
    mean_baseline_directional: float
    mean_cot_directional: float
    mean_baseline_sharpe: float
    mean_cot_sharpe: float
    ic_improvement: float
    directional_improvement: float
    sharpe_improvement: float
    positive_ic_folds: int
    total_folds: int
    folds: list[dict[str, Any]] = field(default_factory=list)
    cot_gain_importance: dict[str, float] = field(default_factory=dict)
    top_cot_features: list[str] = field(default_factory=list)


def _compute_sharpe(r: pd.Series) -> float:
    if len(r) < 5 or r.std() < 1e-10:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(252))


def _to_binary(y: pd.Series) -> pd.Series:
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def compute_labels(prices: pd.DataFrame, ohlcv: pd.DataFrame, pt_sl: tuple[float, float]) -> pd.Series:
    if not ohlcv.empty:
        labeled = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=20)
        return labeled["label"].reindex(prices.index).fillna(0).astype(int)
    return triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=20, vol_lookback=21)


def load_cot_for_asset(symbol: str, cot_df: pd.DataFrame, price_index: pd.DatetimeIndex) -> pd.DataFrame | None:
    """Load and align COT data for a single asset with point-in-time (3-day lag) constraints."""
    contract_series = get_contract_series(cot_df, symbol)
    if contract_series is None or contract_series.empty:
        return None
    # Normalise timezone: COT data has naive dates, price_index is UTC-aware
    if hasattr(contract_series.index, 'tz') and contract_series.index.tz is None:
        contract_series.index = contract_series.index.tz_localize("UTC")
    # Point-in-time: release_lag_days=3 (Tuesday close → Friday release)
    aligned = align_cot_to_daily(contract_series, price_index, release_lag_days=3)
    if aligned.empty:
        return None
    # Build COT features from the aligned series
    cot_feats = build_cot_features(aligned)
    return cot_feats


def run_asset_comparison(
    asset_name: str,
    ticker: str,
    cot_df: pd.DataFrame | None,
    pt_sl: tuple[float, float] = (2.5, 2.0),
    n_folds: int = 3,
    weeks_cot_lookback: int = 52,
) -> AssetResult | None:
    import xgboost as xgb

    logger.info("=" * 60)
    logger.info("ASSET: %s (%s) — pt_sl=%s", asset_name, ticker, pt_sl)
    logger.info("=" * 60)

    # ── Data ──────────────────────────────────────────────────────────
    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if prices.empty or len(prices) < 100:
        logger.warning("SKIP: insufficient price data")
        return None

    ohlcv = fetch_asset_ohlcv(ticker)
    labels = compute_labels(prices, ohlcv, pt_sl=pt_sl)

    # Build baseline alpha features (no COT)
    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, ohlcv=ohlcv)
    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()

    # ── COT features ──────────────────────────────────────────────────
    cot_features_df: pd.DataFrame | None = None
    if cot_df is not None:
        cot_features_df = load_cot_for_asset(asset_name, cot_df, alpha_df.index)
        if cot_features_df is not None and not cot_features_df.empty:
            logger.info("  COT features: %d columns, date range %s → %s, %.0f%% non-NaN",
                        len(cot_features_df.columns),
                        cot_features_df.index.min().date(),
                        cot_features_df.index.max().date(),
                        (1 - cot_features_df.isna().mean().mean()) * 100)
        else:
            logger.info("  No COT features available for %s", asset_name)
            cot_features_df = None

    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    cot_cols: list[str] = []

    if cot_features_df is not None and not cot_features_df.empty:
        # Join COT features to alpha features on index
        cot_joined = cot_features_df.reindex(alpha_df.index).ffill().fillna(0.0)
        cot_cols = [f"COT_{c}" for c in cot_features_df.columns]
        cot_renamed = cot_joined.rename(columns=dict(zip(cot_features_df.columns, cot_cols)))
        full_df = alpha_df.join(cot_renamed, how="left")
        # Drop any rows where COT features are entirely NaN after join
        full_df = full_df.dropna(subset=cot_cols, how="all")
    else:
        full_df = alpha_df.copy()

    if len(full_df) < 300:
        logger.warning("SKIP: insufficient rows (%d)", len(full_df))
        return None

    # ── Walk-forward setup ───────────────────────────────────────────
    X_all = full_df[[c for c in full_df.columns if c != "label"]]
    y_all = _to_binary(full_df["label"])
    if len(y_all) < 100:
        logger.warning("SKIP: only %d binary samples", len(y_all))
        return None
    X_all = X_all.loc[y_all.index]

    cv = PurgedWalkForwardFolds(n_folds=n_folds, gap=20, min_train=100)

    folds: list[dict[str, Any]] = []
    all_cot_gain: dict[str, float] = {}
    hi_thresh = 0.5 + 0.15 / 2.0
    lo_thresh = 0.5 - 0.15 / 2.0

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        X_tr = X_all.iloc[train_idx]
        y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_all.iloc[test_idx]

        if y_tr.nunique() < 2:
            logger.warning("  fold %d: only one class — skipping", fold)
            continue

        n0 = (y_tr == 0).sum()
        n1 = (y_tr == 1).sum()
        imbalance_ratio = n0 / max(n1, 1)

        # ── Model A: Baseline (no COT features) ─────────────────────
        base_cols = [c for c in alpha_cols if c in X_tr.columns]
        model_base = xgb.XGBClassifier(
            n_estimators=200, max_depth=2, learning_rate=0.02,
            objective="binary:logistic", scale_pos_weight=imbalance_ratio,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
        )
        model_base.fit(X_tr[base_cols], y_tr)
        p_base = model_base.predict_proba(X_te[base_cols])[:, 1]

        # ── Model C: COT-enhanced ───────────────────────────────────
        cot_present = cot_cols and all(c in X_tr.columns for c in cot_cols)
        if cot_present:
            model_cot = xgb.XGBClassifier(
                n_estimators=200, max_depth=2, learning_rate=0.02,
                objective="binary:logistic", scale_pos_weight=imbalance_ratio,
                random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
            )
            all_train_cols = base_cols + cot_cols
            model_cot.fit(X_tr[all_train_cols], y_tr)
            p_cot = model_cot.predict_proba(X_te[all_train_cols])[:, 1]

            # Extract COT feature gain importance
            booster = model_cot.get_booster()
            gain = booster.get_score(importance_type="gain")
            total_gain = sum(gain.values()) or 1.0
            for col in cot_cols:
                g = gain.get(col, 0.0)
                g_pct = g / total_gain * 100
                all_cot_gain[col] = all_cot_gain.get(col, 0.0) + g_pct
        else:
            p_cot = p_base.copy()

        # ── Signals ─────────────────────────────────────────────────
        sig_base = np.zeros(len(p_base), dtype=int)
        sig_base[p_base > hi_thresh] = 1
        sig_base[p_base < lo_thresh] = -1

        sig_cot = np.zeros(len(p_cot), dtype=int)
        sig_cot[p_cot > hi_thresh] = 1
        sig_cot[p_cot < lo_thresh] = -1

        label_dir = y_te.values * 2 - 1
        directional_base = (sig_base * label_dir).sum() / max((sig_base != 0).sum(), 1)
        directional_cot = (sig_cot * label_dir).sum() / max((sig_cot != 0).sum(), 1)

        from scipy.stats import spearmanr
        ic_base, _ = spearmanr(p_base, y_te.fillna(0))
        ic_base = ic_base if not np.isnan(ic_base) else 0.0
        ic_cot, _ = spearmanr(p_cot, y_te.fillna(0))
        ic_cot = ic_cot if not np.isnan(ic_cot) else 0.0

        # ── R-multiple based Sharpe ─────────────────────────────────
        tp, sl = pt_sl
        r_base = np.where(sig_base == 1, tp, np.where(sig_base == -1, -sl, 0.0))
        r_cot = np.where(sig_cot == 1, tp, np.where(sig_cot == -1, -sl, 0.0))
        r_base_series = pd.Series(r_base)
        r_cot_series = pd.Series(r_cot)
        sharpe_base = _compute_sharpe(r_base_series)
        sharpe_cot = _compute_sharpe(r_cot_series)

        n_trades_base = int((sig_base != 0).sum())
        n_trades_cot = int((sig_cot != 0).sum())

        fold_result = {
            "fold": fold,
            "baseline_ic": round(float(ic_base), 6),
            "cot_ic": round(float(ic_cot), 6),
            "ic_delta": round(float(ic_cot - ic_base), 6),
            "baseline_directional": round(float(directional_base), 4),
            "cot_directional": round(float(directional_cot), 4),
            "directional_delta": round(float(directional_cot - directional_base), 4),
            "baseline_sharpe": round(float(sharpe_base), 4),
            "cot_sharpe": round(float(sharpe_cot), 4),
            "sharpe_delta": round(float(sharpe_cot - sharpe_base), 4),
            "n_trades_baseline": n_trades_base,
            "n_trades_cot": n_trades_cot,
        }
        folds.append(fold_result)

        logger.info(
            "  fold %d: IC base=%.4f cot=%.4f (Δ=%+.4f) | dir base=%.3f cot=%.3f | Sharpe base=%.2f cot=%.2f | trades %d→%d",
            fold, ic_base, ic_cot, ic_cot - ic_base,
            directional_base, directional_cot,
            sharpe_base, sharpe_cot,
            n_trades_base, n_trades_cot,
        )

    if not folds:
        logger.warning("No folds completed for %s", asset_name)
        return None

    # ── Aggregate ────────────────────────────────────────────────────
    mean_base_ic = np.mean([f["baseline_ic"] for f in folds])
    mean_cot_ic = np.mean([f["cot_ic"] for f in folds])
    mean_base_dir = np.mean([f["baseline_directional"] for f in folds])
    mean_cot_dir = np.mean([f["cot_directional"] for f in folds])
    mean_base_sharpe = np.mean([f["baseline_sharpe"] for f in folds])
    mean_cot_sharpe = np.mean([f["cot_sharpe"] for f in folds])

    # Average COT gain importance across folds
    if all_cot_gain and len(folds) > 0:
        for k in all_cot_gain:
            all_cot_gain[k] = round(all_cot_gain[k] / len(folds), 4)
        sorted_cot = sorted(all_cot_gain.items(), key=lambda x: -x[1])
        top_cot = [f"{k}={v:.2f}%" for k, v in sorted_cot if v > 0]
    else:
        top_cot = []

    result = AssetResult(
        asset=asset_name,
        mean_baseline_ic=round(float(mean_base_ic), 6),
        mean_cot_ic=round(float(mean_cot_ic), 6),
        mean_baseline_directional=round(float(mean_base_dir), 4),
        mean_cot_directional=round(float(mean_cot_dir), 4),
        mean_baseline_sharpe=round(float(mean_base_sharpe), 4),
        mean_cot_sharpe=round(float(mean_cot_sharpe), 4),
        ic_improvement=round(float(mean_cot_ic - mean_base_ic), 6),
        directional_improvement=round(float(mean_cot_dir - mean_base_dir), 4),
        sharpe_improvement=round(float(mean_cot_sharpe - mean_base_sharpe), 4),
        positive_ic_folds=sum(1 for f in folds if f["ic_delta"] > 0),
        total_folds=len(folds),
        folds=folds,
        cot_gain_importance=all_cot_gain,
        top_cot_features=top_cot,
    )

    logger.info("")
    logger.info("  ── %s SUMMARY ──", asset_name)
    logger.info("  Baseline mean IC:       %.6f", mean_base_ic)
    logger.info("  COT-enhanced mean IC:   %.6f (Δ=%+.6f)", mean_cot_ic, mean_cot_ic - mean_base_ic)
    logger.info("  Baseline mean dir:      %.4f", mean_base_dir)
    logger.info("  COT-enhanced mean dir:  %.4f (Δ=%+.4f)", mean_cot_dir, mean_cot_dir - mean_base_dir)
    logger.info("  Baseline mean Sharpe:   %.4f", mean_base_sharpe)
    logger.info("  COT-enhanced mean Sharpe: %.4f (Δ=%+.4f)", mean_cot_sharpe, mean_cot_sharpe - mean_base_sharpe)
    logger.info("  Positive IC folds:      %d/%d", result.positive_ic_folds, result.total_folds)
    if top_cot:
        logger.info("  Top COT features (gain%%): %s", ", ".join(top_cot))
    else:
        logger.info("  COT features: zero gain across all folds")
    logger.info("")

    return result


def main():
    parser = argparse.ArgumentParser(description="COT Counterfactual Walk-Forward Investigation")
    parser.add_argument("--assets", default="USDCAD,GBPUSD", help="Comma-separated asset names")
    parser.add_argument("--n-folds", type=int, default=3, help="Number of walk-forward folds")
    parser.add_argument("--output", default="data/processed/audits/cot_investigation_results.json", help="Output JSON path")
    args = parser.parse_args()

    assets = [a.strip() for a in args.assets.split(",")]
    assets_to_run = {a: ASSETS[a] for a in assets if a in ASSETS}

    if not assets_to_run:
        logger.error("No valid assets specified. Valid: %s", list(ASSETS.keys()))
        return

    # Load COT data once (shared across assets)
    cot_df: pd.DataFrame | None = None
    try:
        cot_df = load_cot_weekly()
        logger.info("Loaded COT data: %d rows, %d contracts, %s → %s",
                    len(cot_df), cot_df["Market_and_Exchange_Names"].nunique(),
                    cot_df["date"].min().date(), cot_df["date"].max().date())
    except (FileNotFoundError, OSError, ValueError) as e:
        logger.warning("COT data not available — running baseline-only: %s", e)

    # Per-asset pt_sl from production config
    try:
        from paper_trading.config_manager import get_config
        cfg = get_config()
    except Exception:
        cfg = type("obj", (object,), {"assets": {}})()

    results = []
    for name, ticker in assets_to_run.items():
        try:
            acfg = cfg.assets.get(name, {})
            tp = float(acfg.get("tp_mult", 2.5))
            sl = float(acfg.get("sl_mult", 2.0))
        except (AttributeError, TypeError, ValueError):
            tp, sl = 2.5, 2.0

        result = run_asset_comparison(name, ticker, cot_df, pt_sl=(tp, sl), n_folds=args.n_folds)
        if result is not None:
            results.append(result)

    # ── Report ───────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("COT COUNTERFACTUAL INVESTIGATION — PHASE 3 RESULTS")
    print("=" * 80)

    if not results:
        print("No results produced.")
        return

    print(f"\n{'Asset':<12} {'Base IC':<10} {'COT IC':<10} {'Δ IC':<10} {'Base Dir':<10} {'COT Dir':<10} {'Δ Dir':<10} {'Base Sharpe':<12} {'COT Sharpe':<12} {'Δ Sharpe':<12} {'Pos Folds':<10}")
    print("-" * 120)
    for r in results:
        print(f"{r.asset:<12} {r.mean_baseline_ic:<10.6f} {r.mean_cot_ic:<10.6f} {r.ic_improvement:<+10.6f} "
              f"{r.mean_baseline_directional:<10.4f} {r.mean_cot_directional:<10.4f} {r.directional_improvement:<+10.4f} "
              f"{r.mean_baseline_sharpe:<12.4f} {r.mean_cot_sharpe:<12.4f} {r.sharpe_improvement:<+12.4f} "
              f"{r.positive_ic_folds}/{r.total_folds:<5}")

    print("\n--- COT Feature Gain Importance ---")
    for r in results:
        print(f"\n{r.asset}:")
        if r.top_cot_features:
            for feat in r.top_cot_features:
                print(f"  {feat}")
        else:
            print("  No COT features had non-zero gain importance across any fold.")

    # ── Verdict ───────────────────────────────────────────────────────
    n_improved_ic = sum(1 for r in results if r.ic_improvement > 0)
    n_improved_sharpe = sum(1 for r in results if r.sharpe_improvement > 0)
    any_cot_gain = any(r.cot_gain_importance and any(v > 0 for v in r.cot_gain_importance.values()) for r in results)

    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    print(f"Assets with IC improvement:  {n_improved_ic}/{len(results)}")
    print(f"Assets with Sharpe improvement: {n_improved_sharpe}/{len(results)}")
    print(f"Any COT feature with non-zero gain: {any_cot_gain}")

    if any_cot_gain:
        print("\n→ COT features contribute measurable predictive value when properly computed.")
    else:
        print("\n→ COT features show zero gain importance even when properly computed.")

    if n_improved_sharpe >= len(results) * 0.5 and any_cot_gain:
        print("→ Preliminary: COT may add value as a direct ML feature. Proceeding to Phase 4.")
    else:
        print("→ COT as direct ML feature does not consistently improve metrics. Supports Phase 2 finding that COT belongs elsewhere.")

    # ── Save ──────────────────────────────────────────────────────────
    output_data = {
        "phase": 3,
        "description": "COT counterfactual walk-forward comparison",
        "n_assets": len(results),
        "n_improved_ic": n_improved_ic,
        "n_improved_sharpe": n_improved_sharpe,
        "any_cot_gain": any_cot_gain,
        "results": [asdict(r) for r in results],
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2, default=str)
    logger.info("Results saved to %s", args.output)


if __name__ == "__main__":
    main()
