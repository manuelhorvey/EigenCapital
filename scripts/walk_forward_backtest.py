#!/usr/bin/env python3
"""
Walk-forward backtest using the alpha feature pipeline.

Trains an XGBoost model on expanding windows, predicts on out-of-sample
data, and reports signal quality metrics (Sharpe, hit rate, stability).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/walk_forward_backtest.py \\
        --asset AUDJPY --years 3 --step 1

Output:
    walkforward/{asset}_wf_summary.csv  — per-window metrics
    walkforward/{asset}_wf_signals.parquet  — all OOS predictions
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, fetch_cot_features
from features.regime_features import generate_regime_features
from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels
from labels.trend_adjusted_labels import trend_adjusted_labels
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("walkforward")

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "walkforward",
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ASSETS = {
    # Research / screening candidates
    "AUDJPY": "AUDJPY=X",
    "CHFJPY": "CHFJPY=X",
    "USDJPY": "USDJPY=X",
    # Promoted portfolio (19 assets)
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "GBPCAD": "GBPCAD=X",
    "GBPNZD": "GBPNZD=X",
    "NZDCAD": "NZDCAD=X",
    "^DJI": "^DJI",
    "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "EURAUD": "EURAUD=X",
}


def slugify(ticker: str) -> str:
    """Derive clean asset name from yfinance ticker (strip =X, =F, -)."""
    return ticker.replace("=X", "").replace("=F", "").replace("-", "").replace("=", "")


def _tag_path(filename: str, tag: str) -> str:
    """Insert _tag before the file extension if tag is non-empty."""
    if not tag:
        return filename
    stem, ext = os.path.splitext(filename)
    return f"{stem}_{tag}{ext}"


def compute_labels(
    prices: pd.DataFrame,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    vertical_barrier: int = 20,
    label_type: str = "standard",
) -> pd.Series:
    """Compute triple-barrier labels aligned to prices index.

    Args:
        label_type: "standard" (legacy EWM vol) or "trend_adjusted"
            (per-timestep pt_sl based on trend strength).
    """
    if label_type == "trend_adjusted":
        return trend_adjusted_labels(
            prices,
            pt_sl=pt_sl,
            vertical_barrier=vertical_barrier,
        )
    return triple_barrier_labels(
        prices,
        pt_sl=pt_sl,
        vertical_barrier=vertical_barrier,
        vol_lookback=21,
    )


def _to_binary(y: pd.Series) -> pd.Series:
    """Drop HOLD (0), map {-1, 1} to {0, 1}."""
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_walk_forward(
    asset_name: str,
    ticker: str,
    window_years: int = 3,
    step_years: int = 1,
    n_folds: int = 5,
    gap: int = 5,
    ensemble_weight: float = 0.6,
    ensemble_threshold: float = 0.15,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    max_depth: int = 2,
    tag: str = "",
    window_type: str = "expanding",
    rolling_window_bars: int | None = None,
    label_type: str = "standard",
) -> pd.DataFrame | None:
    import xgboost as xgb

    logger.info("=== %s walk-forward (%dy windows, %dy step, pt_sl=%s) ===", asset_name, window_years, step_years, pt_sl)

    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
    if prices.empty or len(prices) < 100:
        logger.warning("SKIP: %s (%s) — no data or insufficient rows", asset_name, ticker)
        return None
    # Use vertical_barrier=20 by default (matches FEATURE_REGISTRY), gap >= barrier
    labels = compute_labels(prices, pt_sl=pt_sl, vertical_barrier=20, label_type=label_type)
    gap = max(gap, 20)
    cot_data = fetch_cot_features(prices.index)
    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, cot_data=cot_data)

    alpha_df["label"] = labels.reindex(alpha_df.index).astype(int)
    alpha_df = alpha_df.dropna()

    # Build regime features (matching production pipeline)
    ohlcv = fetch_asset_ohlcv(ticker)
    regime_ok = not ohlcv.empty
    regime_cols: list[str] = []
    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    if regime_ok:
        regime_df = generate_regime_features(ohlcv)
        prefix = asset_name.upper()
        regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
        full_df = alpha_df.join(regime_renamed, how="left").dropna()
        regime_cols = list(regime_renamed.columns)
    else:
        full_df = alpha_df.copy()

    all_cols = alpha_cols + regime_cols

    if len(full_df) < 300:
        logger.warning("%s: insufficient data (%d rows) — skipping", asset_name, len(full_df))
        return None

    X_all = full_df[all_cols]
    y_all = _to_binary(full_df["label"])

    if len(y_all) < 100:
        logger.warning("%s: only %d binary samples — skipping", asset_name, len(y_all))
        return None

    X_all = X_all.loc[y_all.index]

    cv = PurgedWalkForwardFolds(n_folds=n_folds, gap=gap, min_train=100)

    windows = []
    all_oos_signals = []

    hi_thresh = 0.5 + ensemble_threshold / 2.0
    lo_thresh = 0.5 - ensemble_threshold / 2.0

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        # Rolling window: truncate training to last N bars
        if window_type == "rolling":
            max_bars = rolling_window_bars or (window_years * 252)
            train_idx = train_idx[-max_bars:]
        train_start = X_all.index[train_idx[0]]
        train_end = X_all.index[train_idx[-1]]
        test_start = X_all.index[test_idx[0]]
        test_end = X_all.index[test_idx[-1]]

        X_tr = X_all.iloc[train_idx]
        y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_all.iloc[test_idx]

        if y_tr.nunique() < 2:
            logger.warning("  fold %d: only one class in train, skipping", fold)
            continue

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=max_depth,
            learning_rate=0.02,
            objective="binary:logistic",
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(X_tr[alpha_cols], y_tr)

        base_p_long = model.predict_proba(X_te[alpha_cols])[:, 1]

        # Ensemble blending (matching production: regime model on alpha + regime features)
        p_long = base_p_long
        if ensemble_weight < 1.0 and regime_ok and regime_cols:
            X_tr_regime = X_tr[all_cols]
            X_te_regime = X_te[all_cols]
            regime_model = RegimeConditionalModel()
            regime_model.train(X_tr_regime, y_tr, all_cols)
            r_p_long = regime_model.predict_long_prob(X_te_regime).ravel()
            ensemble = EnsembleSignal(base_weight=ensemble_weight, ensemble_threshold=ensemble_threshold)
            blended, _ = ensemble.combine(base_p_long, r_p_long)
            p_long = blended.ravel()

        # Signal from binary P(LONG)
        signals = np.zeros(len(p_long), dtype=int)
        signals[p_long > hi_thresh] = 1
        signals[p_long < lo_thresh] = -1

        hit_rate = (signals == y_te.values).mean()
        directional = (signals * (y_te.values * 2 - 1)).sum() / max((signals != 0).sum(), 1)
        long_rate = (signals == 1).mean()
        short_rate = (signals == -1).mean()
        flat_rate = (signals == 0).mean()

        window = {
            "asset": asset_name,
            "fold": fold,
            "train_start": str(train_start.date()),
            "train_end": str(train_end.date()),
            "test_start": str(test_start.date()),
            "test_end": str(test_end.date()),
            "train_samples": len(X_tr),
            "test_samples": len(X_te),
            "hit_rate": round(float(hit_rate), 4),
            "directional": round(float(directional), 4),
            "long_rate": round(float(long_rate), 4),
            "short_rate": round(float(short_rate), 4),
            "flat_rate": round(float(flat_rate), 4),
        }
        windows.append(window)

        oos_df = pd.DataFrame(
            {
                "signal": signals,
                "label": y_te.values,
                "p_long": p_long,
            },
            index=X_te.index,
        )
        oos_df["asset"] = asset_name
        all_oos_signals.append(oos_df)

        logger.info(
            "  fold %d: train=%s..%s (%d) | test=%s..%s (%d) | hit=%.3f dir=%.3f long=%.2f short=%.2f",
            fold,
            window["train_start"], window["train_end"], len(X_tr),
            window["test_start"], window["test_end"], len(X_te),
            hit_rate, directional, long_rate, short_rate,
        )

    if not windows:
        logger.warning("%s: no windows produced", asset_name)
        return None

    summary = pd.DataFrame(windows)
    summary_path = os.path.join(OUTPUT_DIR, _tag_path(f"{asset_name}_wf_summary.csv", tag))
    summary.to_csv(summary_path, index=False)
    logger.info("%s: summary -> %s", asset_name, summary_path)

    # Save per-fold IC data
    fold_data = []
    for w in windows:
        fold_data.append({
            "fold": w["fold"],
            "train_start": w["train_start"],
            "train_end": w["train_end"],
            "test_start": w["test_start"],
            "test_end": w["test_end"],
            "ic": w["directional"],
            "hit_rate": w["hit_rate"],
        })
    ic_record = {
        "ticker": asset_name,
        "folds": fold_data,
        "mean_ic": round(float(sum(w["directional"] for w in windows) / len(windows)), 4),
        "positive_folds": sum(1 for w in windows if w["directional"] > 0),
        "total_folds": len(windows),
    }
    import json
    fold_ic_path = os.path.join(OUTPUT_DIR, _tag_path(f"{asset_name}_fold_ic.json", tag))
    with open(fold_ic_path, "w") as f:
        json.dump(ic_record, f, indent=2)
    logger.info("%s: fold IC -> %s", asset_name, fold_ic_path)

    if all_oos_signals:
        signals_df = pd.concat(all_oos_signals)
        signals_path = os.path.join(OUTPUT_DIR, _tag_path(f"{asset_name}_wf_signals.parquet", tag))
        signals_df.to_parquet(signals_path)
        logger.info("%s: signals -> %s", asset_name, signals_path)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest using alpha features")
    parser.add_argument("--asset", default=None, help="Single asset name (default: all)")
    parser.add_argument("--assets", default=None, help="Comma-separated asset names (from ASSETS dict)")
    parser.add_argument("--tickers", default=None, help="Comma-separated yfinance tickers (raw)")
    parser.add_argument("--years", type=int, default=3, help="Training window in years")
    parser.add_argument("--step", type=int, default=1, help="Step size in years")
    parser.add_argument("--ensemble-weight", type=float, default=1.0, help="Base model weight in ensemble (1.0 = base only)")
    parser.add_argument("--ensemble-threshold", type=float, default=0.15, help="Ensemble signal threshold")
    parser.add_argument("--pt-sl", type=str, default=None,
                        help="Override pt_sl as tp,sl (e.g. --pt-sl 1.0,2.0). Default: per-asset from production config.")
    parser.add_argument("--tag", type=str, default="", help="Suffix for output filenames (ensemble/base, etc.)")
    parser.add_argument("--window-type", type=str, default="expanding", choices=["expanding", "rolling"],
                        help="Training window type: expanding (all history) or rolling (fixed lookback)")
    parser.add_argument("--rolling-window-bars", type=int, default=None,
                        help="Fixed lookback in bars for rolling window (default: window_years * 252)")
    parser.add_argument("--label-type", type=str, default="standard",
                        choices=["standard", "trend_adjusted"],
                        help="Label type: standard (legacy triple-barrier) or trend_adjusted (per-timestep pt_sl)")
    args = parser.parse_args()

    # Load per-asset pt_sl from production config
    from paper_trading.config_manager import get_config
    _cfg = get_config()
    _asset_pt_sl: dict[str, tuple[float, float]] = {}
    for _name, _acfg in _cfg.assets.items():
        _tp = float(_acfg.get("tp_mult", 2.0))
        _sl = float(_acfg.get("sl_mult", 2.0))
        _asset_pt_sl[_name] = (_tp, _sl)

    # Override all if --pt-sl specified
    _pt_sl_override: tuple[float, float] | None = None
    if args.pt_sl:
        parts = [float(x.strip()) for x in args.pt_sl.split(",")]
        _pt_sl_override = (parts[0], parts[1])
        logger.info("pt_sl override: %s (applied to all assets)", _pt_sl_override)

    assets_to_run: dict[str, str] = {}

    if args.tickers:
        raw_tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        for t in raw_tickers:
            name = slugify(t)
            logger.info("ticker: %s -> name: %s", t, name)
            assets_to_run[name] = t
    elif args.assets:
        names = [n.strip() for n in args.assets.split(",")]
        assets_to_run = {n: ASSETS[n] for n in names if n in ASSETS}
    elif args.asset:
        assets_to_run = {args.asset: ASSETS[args.asset]}
    else:
        assets_to_run = ASSETS

    # BTC-USD gets wider barriers due to higher vol
    btc_pt_sl = (2.5, 3.0)

    # Save ticker map for report generation
    import json as _json
    ticker_map_path = os.path.join(OUTPUT_DIR, _tag_path("ticker_map.json", args.tag))
    with open(ticker_map_path, "w") as _f:
        _json.dump(assets_to_run, _f, indent=2)
    logger.info("ticker map -> %s", ticker_map_path)

    all_summaries = []
    for name, ticker in assets_to_run.items():
        if _pt_sl_override is not None:
            pt_sl = _pt_sl_override
        elif ticker == "BTC-USD":
            pt_sl = btc_pt_sl
        else:
            pt_sl = _asset_pt_sl.get(name, (2.0, 2.0))
        # Load per-asset max_depth from production config
        _acfg = _cfg.assets.get(name, {})
        _md = int(_acfg.get("max_depth", 2))
        result = run_walk_forward(
            name, ticker,
            window_years=args.years,
            step_years=args.step,
            ensemble_weight=args.ensemble_weight,
            ensemble_threshold=args.ensemble_threshold,
            pt_sl=pt_sl,
            max_depth=_md,
            tag=args.tag,
            window_type=args.window_type,
            rolling_window_bars=args.rolling_window_bars,
            label_type=args.label_type,
        )
        if result is not None:
            all_summaries.append(result)

    if all_summaries:
        combined = pd.concat(all_summaries)
        combined_path = os.path.join(OUTPUT_DIR, _tag_path("all_assets_wf_summary.csv", args.tag))
        combined.to_csv(combined_path, index=False)
        logger.info("combined summary -> %s", combined_path)

        print("\n=== Cross-Asset Walk-Forward Summary ===")
        avg = combined.groupby("asset")[["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]].mean()
        print(avg.to_string(float_format="%.3f"))


if __name__ == "__main__":
    main()
