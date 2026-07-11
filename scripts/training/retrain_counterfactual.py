#!/usr/bin/env python3
"""Counterfactual retraining — feature ablation to establish causality.

For each flagged asset, trains baseline and counterfactual models via
walk-forward cross-validation, then compares per-direction win rates,
total R, Sharpe, and max drawdown.

Usage:
    # Ablate carry on CHF cluster
    PYTHONPATH=$PYTHONPATH:. python scripts/retrain_counterfactual.py \\
        --assets CADCHF,NZDCHF,USDCHF,EURCHF,AUDUSD --remove-carry

    # Ablate DXY on equity cluster
    PYTHONPATH=$PYTHONPATH:. python scripts/retrain_counterfactual.py \\
        --assets ^DJI,ES,NQ --remove-dxy

    # Full sweep: all 9 SELL_ONLY assets, all ablations
    PYTHONPATH=$PYTHONPATH:. python scripts/retrain_counterfactual.py \\
        --assets all

Output:
    walkforward/counterfactual/{experiment_tag}/
        per_asset.csv     — per-asset metrics for each ablation
        portfolio.csv     — portfolio-level aggregates
        details/          — per-fold breakdown per asset
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eigencapital.domain.value_objects.statistical_metrics import (
    _moments,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv
from labels.compat import PurgedWalkForwardFolds
from labels.triple_barrier import apply_triple_barrier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("counterfactual")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "walkforward", "counterfactual")

CONFIG_ASSETS = {
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "GBPCAD": "GBPCAD=X",
    "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "EURAUD": "EURAUD=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "^DJI": "^DJI",
}

SELL_ONLY_ASSETS = frozenset(
    {
        "CADCHF",
        "NZDCHF",
        "EURAUD",
    }
)


def _get_pt_sl(asset_name: str) -> tuple[float, float]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    acfg = cfg.assets.get(asset_name, {})
    tp = float(acfg.get("tp_mult", 2.0))
    sl = float(acfg.get("sl_mult", 2.0))
    return tp, sl


def _modify_features(alpha_df: pd.DataFrame, args) -> pd.DataFrame:
    """Zero-fill or drop specified feature groups."""
    result = alpha_df.copy()
    prefix = "CLOSE"

    if args.remove_carry:
        carry_cols = [c for c in result.columns if "carry_vol_adj" in c]
        for c in carry_cols:
            result[c] = 0.0

    if args.remove_dxy:
        dxy_cols = [c for c in result.columns if "dxy" in c.lower()]
        for c in dxy_cols:
            result[c] = 0.0

    if args.remove_momentum:
        mom_cols = [c for c in result.columns if c.startswith(f"{prefix}_mom_")]
        for c in mom_cols:
            result[c] = 0.0

    if args.remove_zscore:
        zscore_cols = [c for c in result.columns if c.startswith(f"{prefix}_zscore_")]
        for c in zscore_cols:
            result[c] = 0.0

    if args.remove_cot:
        cot_cols = [c for c in result.columns if "cot" in c.lower()]
        for c in cot_cols:
            result[c] = 0.0

    return result


def _agg_metrics(df: pd.DataFrame, tp: float = 1.0, sl: float = 1.0) -> dict:
    """Compute per-direction and total metrics from signal DataFrame."""
    if df.empty:
        return {"n_signals": 0, "buy_wr": 0.0, "sell_wr": 0.0, "total_r": 0.0, "sharpe": 0.0, "max_dd_r": 0.0}

    buy = df[df["signal"] == 1]
    sell = df[df["signal"] == -1]

    buy_wr = float(buy["label"].eq(1).mean()) if len(buy) > 0 else 0.0
    sell_wr = float(sell["label"].eq(0).mean()) if len(sell) > 0 else 0.0

    daily_r = df.apply(lambda r: _trade_pnl(r["signal"], r["label"], tp, sl), axis=1)
    total_r = float(daily_r.sum())
    sharpe = float(daily_r.mean() / daily_r.std() * np.sqrt(252)) if daily_r.std() > 1e-9 else 0.0
    max_dd_r = float((daily_r.cumsum().cummax() - daily_r.cumsum()).max())

    return {
        "n_signals": len(df),
        "n_buy": len(buy),
        "n_sell": len(sell),
        "buy_wr": round(buy_wr, 4),
        "sell_wr": round(sell_wr, 4),
        "total_r": round(total_r, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_r": round(max_dd_r, 2),
    }


def _trade_pnl(signal: int, label: int, tp: float, sl: float) -> float:
    """R-multiple PnL for a single trade."""
    if signal == 0:
        return 0.0
    if signal == 1:
        return tp if label == 1 else -sl
    return tp if label == 0 else -sl


def _daily_r_series(df: pd.DataFrame, tp: float, sl: float) -> pd.Series:
    """Compute daily R-multiple series from a predictions DataFrame."""
    r = np.zeros(len(df), dtype=float)
    signals = df["signal"].values
    labels = df["label"].values
    buy_mask = signals == 1
    sell_mask = signals == -1
    r[buy_mask & (labels == 1)] = tp
    r[buy_mask & (labels == 0)] = -sl
    r[sell_mask & (labels == 0)] = tp
    r[sell_mask & (labels == 1)] = -sl
    return pd.Series(r, index=df.index, name="daily_r")


def _infer_trial_count(asset_list: list[str], args) -> int:
    """Infer num_trials from asset count x active ablation flags.

    No manual override -- always inferred. This avoids the risk of a
    manual --n-trials flag drifting out of sync with the actual
    number of comparisons being tested.
    """
    n_ablations = sum(
        [
            args.remove_carry,
            args.remove_dxy,
            args.remove_momentum,
            args.remove_zscore,
            args.remove_cot,
        ]
    )
    if n_ablations == 0:
        n_ablations = 1  # baseline-comparison mode
    return len(asset_list) * n_ablations


def run_asset_counterfactual(
    asset_name: str,
    ticker: str,
    args,
    tag: str,
) -> tuple[list[dict], pd.DataFrame]:
    """Run walk-forward for one asset, returning (per_fold_metrics, all_predictions)."""
    tp_mult, sl_mult = _get_pt_sl(asset_name)

    hist_prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if hist_prices.empty or len(hist_prices) < 500:
        logger.warning("%s: insufficient data (%d rows), skipping", asset_name, len(hist_prices))
        return [], pd.DataFrame()

    ohlcv = fetch_asset_ohlcv(ticker)
    _trunc_rows = 600
    hist_prices = hist_prices.iloc[-_trunc_rows:]
    if not rate_diffs.empty:
        rate_diffs = rate_diffs.iloc[-_trunc_rows:]
    dxy = dxy.iloc[-_trunc_rows:]
    vix = vix.iloc[-_trunc_rows:]
    spx = spx.iloc[-_trunc_rows:]
    if not commodities.empty:
        commodities = commodities.iloc[-_trunc_rows:]

    alpha_df = build_alpha_features(
        hist_prices,
        rate_diffs,
        dxy=dxy,
        vix=vix,
        spx=spx,
        commodities=commodities,
    )

    alpha_df = _modify_features(alpha_df, args)

    labels_df = apply_triple_barrier(
        ohlcv if not ohlcv.empty else hist_prices.to_frame("close"),
        pt_sl=[tp_mult, sl_mult],
        vertical_barrier=20,
    )
    label_series = labels_df["label"].reindex(alpha_df.index).fillna(0)

    folds = PurgedWalkForwardFolds(
        n_folds=5,
        gap=10,
        window_type=getattr(args, "window_type", "expanding"),
        rolling_window_bars=getattr(args, "rolling_window_bars", None),
    )
    fold_indices = folds.split(alpha_df.index, label_series)

    per_fold = []
    all_predictions = []

    for fold_idx, (train_idx, test_idx) in enumerate(fold_indices):
        if len(test_idx) < 5:
            continue

        x_tr = alpha_df.iloc[train_idx].values
        y_tr = label_series.iloc[train_idx].values
        y_tr_bin = np.where(y_tr == 1, 1, 0)
        mask = y_tr != 0
        x_tr = x_tr[mask]
        y_tr_bin = y_tr_bin[mask]

        if len(x_tr) < 20:
            continue

        x_te = alpha_df.iloc[test_idx].values
        y_te = label_series.iloc[test_idx].values

        import xgboost as xgb

        n0, n1 = (y_tr_bin == 0).sum(), (y_tr_bin == 1).sum()
        swp = n0 / max(n1, 1)

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=2,
            learning_rate=0.02,
            objective="binary:logistic",
            scale_pos_weight=swp,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(x_tr, y_tr_bin)

        p_long = model.predict_proba(x_te)[:, 1]
        p_short = 1.0 - p_long

        signals = np.zeros(len(x_te), dtype=int)
        signals[p_long > 0.55] = 1
        signals[p_short > 0.55] = -1

        fold_df = pd.DataFrame(
            {
                "signal": signals,
                "label": y_te,
                "p_long": p_long,
                "p_short": p_short,
            },
            index=test_idx,
        )

        metrics = _agg_metrics(fold_df, tp=tp_mult, sl=sl_mult)
        metrics["fold"] = fold_idx
        metrics["n_test"] = len(test_idx)
        per_fold.append(metrics)
        all_predictions.append(fold_df)

    combined = pd.concat(all_predictions) if all_predictions else pd.DataFrame()
    return per_fold, combined


def run_baseline(asset_name: str, ticker: str) -> tuple[list[dict], pd.DataFrame]:
    """Run walk-forward without any feature modification."""

    class NoOpArgs:
        remove_carry = False
        remove_dxy = False
        remove_momentum = False
        remove_zscore = False
        remove_cot = False

    return run_asset_counterfactual(asset_name, ticker, NoOpArgs(), tag="baseline")


def build_tags_from_args(args) -> list[str]:
    tags = ["baseline"]
    if args.remove_carry:
        tags.append("no_carry")
    if args.remove_dxy:
        tags.append("no_dxy")
    if args.remove_momentum:
        tags.append("no_momentum")
    if args.remove_zscore:
        tags.append("no_zscore")
    if args.remove_cot:
        tags.append("no_cot")
    return tags


def main():
    parser = argparse.ArgumentParser(description="Counterfactual feature ablation retraining")
    parser.add_argument("--assets", default="all", help="Comma-separated or 'all'")
    parser.add_argument("--remove-carry", action="store_true", help="Zero-fill carry feature")
    parser.add_argument("--remove-dxy", action="store_true", help="Zero-fill DXY feature")
    parser.add_argument("--remove-momentum", action="store_true", help="Zero-fill momentum features")
    parser.add_argument("--remove-zscore", action="store_true", help="Zero-fill zscore feature")
    parser.add_argument("--remove-cot", action="store_true", help="Zero-fill COT features")
    parser.add_argument("--tag", default="", help="Custom experiment tag (default: auto from flags)")
    parser.add_argument("--parallel-workers", type=int, default=1, help="Parallel asset workers")
    parser.add_argument(
        "--window-type",
        type=str,
        default="expanding",
        choices=["expanding", "rolling"],
        help="Training window type (default: expanding)",
    )
    parser.add_argument(
        "--rolling-window-bars", type=int, default=None, help="Fixed lookback in bars for rolling window"
    )
    args = parser.parse_args()

    asset_list = sorted(SELL_ONLY_ASSETS) if args.assets == "all" else [a.strip() for a in args.assets.split(",")]

    tags = build_tags_from_args(args)
    tag = args.tag or "_".join(t[3:] for t in tags if t != "baseline") or "all_features"

    exp_dir = os.path.join(OUTPUT_DIR, f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(exp_dir, exist_ok=True)
    details_dir = os.path.join(exp_dir, "details")
    os.makedirs(details_dir, exist_ok=True)

    all_rows = []
    all_baseline_r: dict[str, pd.Series] = {}
    all_cf_r: dict[str, pd.Series] = {}
    for asset_name in asset_list:
        ticker = CONFIG_ASSETS.get(asset_name)
        if ticker is None:
            logger.warning("Unknown asset %s, skipping", asset_name)
            continue

        logger.info("=== %s (%s) ===", asset_name, tag)
        tp_mult, sl_mult = _get_pt_sl(asset_name)
        baseline_folds, baseline_preds = run_baseline(asset_name, ticker)
        cf_folds, cf_preds = run_asset_counterfactual(asset_name, ticker, args, tag)

        baseline_agg = _agg_metrics(baseline_preds, tp=tp_mult, sl=sl_mult) if not baseline_preds.empty else {}
        cf_agg = _agg_metrics(cf_preds, tp=tp_mult, sl=sl_mult) if not cf_preds.empty else {}

        row = {
            "asset": asset_name,
            "tag": tag,
            "baseline_total_r": baseline_agg.get("total_r", 0),
            "cf_total_r": cf_agg.get("total_r", 0),
            "delta_r": cf_agg.get("total_r", 0) - baseline_agg.get("total_r", 0),
            "baseline_buy_wr": baseline_agg.get("buy_wr", 0),
            "cf_buy_wr": cf_agg.get("buy_wr", 0),
            "delta_buy_wr": cf_agg.get("buy_wr", 0) - baseline_agg.get("buy_wr", 0),
            "baseline_sell_wr": baseline_agg.get("sell_wr", 0),
            "cf_sell_wr": cf_agg.get("sell_wr", 0),
            "delta_sell_wr": cf_agg.get("sell_wr", 0) - baseline_agg.get("sell_wr", 0),
            "baseline_sharpe": baseline_agg.get("sharpe", 0),
            "cf_sharpe": cf_agg.get("sharpe", 0),
            "baseline_max_dd_r": baseline_agg.get("max_dd_r", 0),
            "cf_max_dd_r": cf_agg.get("max_dd_r", 0),
        }

        # Daily R series for portfolio-level DSR
        if not baseline_preds.empty:
            bl_r = _daily_r_series(baseline_preds, tp_mult, sl_mult)
            all_baseline_r[asset_name] = bl_r
        if not cf_preds.empty:
            cf_r = _daily_r_series(cf_preds, tp_mult, sl_mult)
            all_cf_r[asset_name] = cf_r

        all_rows.append(row)

        # Save per-fold detail
        if baseline_folds or cf_folds:
            detail_rows = []
            for i, fold_m in enumerate(baseline_folds):
                detail_rows.append({"asset": asset_name, "fold": i, "variant": "baseline", **fold_m})
            for i, fold_m in enumerate(cf_folds):
                detail_rows.append({"asset": asset_name, "fold": i, "variant": tag, **fold_m})
            pd.DataFrame(detail_rows).to_csv(os.path.join(details_dir, f"{asset_name}.csv"), index=False)

    if all_rows:
        per_asset_df = pd.DataFrame(all_rows)
        per_asset_path = os.path.join(exp_dir, "per_asset.csv")
        per_asset_df.to_csv(per_asset_path, index=False)
        logger.info("Saved per-asset results to %s", per_asset_path)

        # Portfolio-level summary
        portfolio = {
            "n_assets": len(all_rows),
            "total_delta_r": round(sum(r["delta_r"] for r in all_rows), 2),
            "total_delta_buy_wr": round(
                sum(r["delta_buy_wr"] for r in all_rows if r["baseline_buy_wr"] > 0)
                / max(sum(1 for r in all_rows if r["baseline_buy_wr"] > 0), 1),
                4,
            ),
            "assets_with_improved_buy_wr": sum(1 for r in all_rows if r["delta_buy_wr"] > 0.02),
            "assets_with_degraded_buy_wr": sum(1 for r in all_rows if r["delta_buy_wr"] < -0.02),
            "assets_with_cf_buy_wr_above_50": sum(1 for r in all_rows if r["cf_buy_wr"] > 0.50),
        }
        portfolio_path = os.path.join(exp_dir, "portfolio.csv")
        pd.DataFrame([portfolio]).to_csv(portfolio_path, index=False)
        logger.info("Saved portfolio summary to %s", portfolio_path)

        # Print key findings
        for r in all_rows:
            signal = "*** BUY WR RESTORED" if r["cf_buy_wr"] > 0.50 else ""
            logger.info(
                "%s: baseline_buy_wr=%.1f%% → cf_buy_wr=%.1f%% (Δ=%.1f%%)  "
                "baseline_total_r=%.1f → cf_total_r=%.1f (Δ=%.1f) %s",
                r["asset"],
                r["baseline_buy_wr"] * 100,
                r["cf_buy_wr"] * 100,
                r["delta_buy_wr"] * 100,
                r["baseline_total_r"],
                r["cf_total_r"],
                r["delta_r"],
                signal,
            )

        logger.info("")
        logger.info("=== Portfolio Summary ===")
        logger.info("Total ΔR: %.2f", portfolio["total_delta_r"])
        logger.info(
            "Assets with improved BUY WR (>+2pp): %d/%d",
            portfolio["assets_with_improved_buy_wr"],
            portfolio["n_assets"],
        )
        logger.info(
            "Assets with CF BUY WR > 50%%: %d/%d", portfolio["assets_with_cf_buy_wr_above_50"], portfolio["n_assets"]
        )
        logger.info("Mean ΔBUY WR: %.1f%%", portfolio["total_delta_buy_wr"] * 100)

        # Causal interpretation
        improved = portfolio["assets_with_cf_buy_wr_above_50"]
        if improved >= 3:
            logger.info(
                ">>> CAUSAL CLAIM: Feature removal restores BUY WR on %d/%d assets <<<",
                improved,
                portfolio["n_assets"],
            )
        else:
            logger.info(
                ">>> Feature removal did NOT restore BUY WR (only %d/%d assets above 50%%) <<<",
                improved,
                portfolio["n_assets"],
            )

        # ── DSR: Deflated Sharpe on portfolio delta (baseline → CF) ──
        num_trials = _infer_trial_count(asset_list, args)
        if all_baseline_r and all_cf_r:
            bl_pf = pd.DataFrame(all_baseline_r).mean(axis=1)
            cf_pf = pd.DataFrame(all_cf_r).mean(axis=1)
            common_idx = bl_pf.index.intersection(cf_pf.index)
            if len(common_idx) > 5:
                delta_r = cf_pf.loc[common_idx].values - bl_pf.loc[common_idx].values
                n_days = len(delta_r)
                ddof_std = np.std(delta_r, ddof=1)
                pf_sharpe = float(np.mean(delta_r) / ddof_std * np.sqrt(252)) if ddof_std > 1e-9 else 0.0
                pf_skew, pf_exkurt = _moments(delta_r)
                pf_psr = probabilistic_sharpe_ratio(pf_sharpe, n_days, pf_skew, pf_exkurt, 0.0)
                pf_dsr = deflated_sharpe_ratio(pf_sharpe, n_days, pf_skew, pf_exkurt, num_trials=num_trials)
                logger.info("")
                logger.info("=== Counterfactual DSR ===")
                n_abl = num_trials // max(len(asset_list), 1)
                logger.info("num_trials=%d (%d assets x %d ablations)", num_trials, len(asset_list), n_abl)
                logger.info("Portfolio delta Sharpe: %.4f", pf_sharpe)
                logger.info("PSR(>0): %.4f (probability delta Sharpe > 0)", pf_psr)
                logger.info("DSR: %.4f (deflated for %d trials)", pf_dsr, num_trials)
                if pf_dsr < 0.95:
                    logger.info(">>> DSR < 0.95 - not significant after multiple-testing correction <<<")
                else:
                    logger.info(">>> DSR >= 0.95 - survives multiple-testing correction <<<")

    else:
        logger.warning("No results — no assets processed")


if __name__ == "__main__":
    main()
