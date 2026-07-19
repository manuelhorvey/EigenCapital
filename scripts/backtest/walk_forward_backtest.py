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
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent))

from features.alpha_features import build_alpha_features
from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, _fetch_macro_batch
from features.registry import FEATURE_REGISTRY
from features.regime_features import generate_regime_features
from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels
from labels.trend_adjusted_labels import trend_adjusted_labels
from labels.triple_barrier import apply_triple_barrier
from paper_trading.inference.ensemble import EnsembleSignal
from paper_trading.inference.regime_model import RegimeConditionalModel
from shared.volatility import VolatilityPrimitive

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("walkforward")

OUTPUT_DIR = Path(Path(__file__).resolve().parent.parent,
    "walkforward",
)
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

ASSETS = {
    # Research / screening candidates
    "AUDJPY": "AUDJPY=X",
    "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "GBPJPY": "GBPJPY=X",
    "NZDJPY": "NZDJPY=X",
    "USDJPY": "USDJPY=X",
    # Promoted portfolio (16 assets)
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "GBPCAD": "GBPCAD=X",
    "NZDCAD": "NZDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPUSD": "GBPUSD=X",
    "EURAUD": "EURAUD=X",
    # Recent additions
    "BTCUSD": "BTC-USD",
    "^DJI": "^DJI",
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
    ohlcv: pd.DataFrame,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    vertical_barrier: int = 20,
    label_type: str = "standard",
    vol_primitive: VolatilityPrimitive | None = None,
) -> pd.Series:
    if label_type == "trend_adjusted":
        return trend_adjusted_labels(
            prices,
            pt_sl=pt_sl,
            vertical_barrier=vertical_barrier,
        )
    if not ohlcv.empty:
        labeled = apply_triple_barrier(
            ohlcv,
            pt_sl=list(pt_sl),
            vertical_barrier=vertical_barrier,
            vol_primitive=vol_primitive,
        )
        return labeled["label"].reindex(prices.index).fillna(0).astype(int)
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
    n_folds: int = 3,
    gap: int = 5,
    ensemble_weight: float = 0.6,
    ensemble_threshold: float = 0.15,
    pt_sl: tuple[float, float] = (2.0, 2.0),
    max_depth: int = 2,
    tag: str = "",
    window_type: str = "expanding",
    rolling_window_bars: int | None = None,
    label_type: str = "standard",
    invert_labels: bool = False,
    sample_weight_flag: bool = False,
    calibrate_flag: bool = False,
    no_scale_pos_weight: bool = False,
    allowed_direction: str = "BOTH",
    expanded_data_dir: str | None = None,
) -> pd.DataFrame | None:
    import xgboost as xgb

    logger.info(
        "=== %s walk-forward (%dy windows, %dy step, pt_sl=%s, dir=%s) ===",
        asset_name,
        window_years,
        step_years,
        pt_sl,
        allowed_direction,
    )

    # Use expanded 10y+ cache when available (same pattern as retrain_all_fixed.py).
    # When expanded_data_dir is None, falls back to live fetch (backward compatible).
    if expanded_data_dir is not None:
        from scripts.training._data_sources import (
            fetch_from_expanded_or_live,
            fetch_ohlcv_from_expanded_or_live,
        )

        expanded_path = None if expanded_data_dir == "auto" else Path(expanded_data_dir)
        prices, rate_diffs, dxy, vix, spx, commodities = fetch_from_expanded_or_live(
            asset_name, ticker, expanded_dir=expanded_path,
        )
        ohlcv = fetch_ohlcv_from_expanded_or_live(
            asset_name, ticker, expanded_dir=expanded_path,
        )
        if prices is not None and not prices.empty:
            logger.info(
                "  using expanded cache — %d rows (%s..%s)",
                len(prices),
                prices.index[0].date(),
                prices.index[-1].date(),
            )
    else:
        prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset_name, ticker)
        ohlcv = fetch_asset_ohlcv(ticker)
    if prices is None or prices.empty or len(prices) < 100:
        logger.warning("SKIP: %s (%s) — no data or insufficient rows", asset_name, ticker)
        return None
    # Load per-asset vol_method from FEATURE_REGISTRY (if configured)
    _vol_primitive: VolatilityPrimitive | None = None
    for _ticker, _contract in FEATURE_REGISTRY.items():
        if _contract.name == asset_name:
            _vm = _contract.label_params.get("vol_method", "ewm_100")
            if _vm == "atr":
                _ap = _contract.label_params.get("atr_period", 14)
                _vol_primitive = VolatilityPrimitive(period=_ap)
                logger.info("  %s: using ATR vol (period=%d) for labels", asset_name, _ap)
            else:
                logger.info("  %s: using EWM vol (span=100) for labels", asset_name)
            break

    # Use vertical_barrier=20 by default (matches FEATURE_REGISTRY), gap >= barrier
    labels = compute_labels(prices, ohlcv, pt_sl=pt_sl, vertical_barrier=20, label_type=label_type, vol_primitive=_vol_primitive)
    gap = max(gap, 20)
    alpha_df = build_alpha_features(
        prices,
        rate_diffs,
        dxy=dxy,
        vix=vix,
        spx=spx,
        commodities=commodities,
        ohlcv=ohlcv,
    )

    # ── Group 2: Positioning features (volume momentum) ──────────────
    from features.positioning_features import check_oi_availability, compute_volume_features

    prefix = asset_name.upper()
    vol_df = compute_volume_features(ohlcv)
    if vol_df is not None and not vol_df.empty:
        for col in vol_df.columns:
            alpha_df[f"{prefix}_{col}"] = vol_df[col].reindex(alpha_df.index)
    alpha_df[f"{prefix}_oi_available"] = check_oi_availability(ticker)

    # ── Group 3: Rates & carry features ─────────────────────────────
    from features.rates_features import compute_all as compute_rates

    _macro = _fetch_macro_batch()
    rd_series = (
        rate_diffs[asset_name]
        if rate_diffs is not None and asset_name in rate_diffs.columns
        else pd.Series(0.0, index=alpha_df.index)
    )
    rates_df = compute_rates(_macro, rd_series, alpha_df.index)
    if rates_df is not None and not rates_df.empty:
        for col in rates_df.columns:
            _series = rates_df[col].reindex(alpha_df.index)
            # Fill all-NaN columns to 0 to prevent dropna from killing all rows
            if _series.isna().all():
                _series = pd.Series(0.0, index=alpha_df.index)
            alpha_df[f"{prefix}_{col}"] = _series

    # ── Group 4: Event & calendar features ──────────────────────────
    from features.event_features import compute_event_features

    event_df = compute_event_features(alpha_df.index)
    if event_df is not None and not event_df.empty:
        for col in event_df.columns:
            alpha_df[f"{prefix}_{col}"] = event_df[col].reindex(alpha_df.index)

    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()

    # Build regime features (matching production pipeline)
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

    # ── Label inversion (diagnostic test A) ──
    # When set, flip training labels so the model learns P(DOWN) instead of P(UP).
    # The OOS parquet saves both the inverted label (what the model predicts)
    # and the original label (for computing BUY WR against ground truth).
    y_original = y_all.copy()
    if invert_labels:
        y_all = 1 - y_all
        logger.info("%s: labels inverted (training on DOWN=1, UP=0)", asset_name)

    cv = PurgedWalkForwardFolds(
        n_folds=n_folds,
        gap=gap,
        min_train=100,
        window_type=window_type,
        rolling_window_bars=rolling_window_bars or (window_years * 252),
    )

    windows = []
    all_oos_signals = []

    # ── Load per-asset confidence thresholds from production config ──
    # Matches the fallback chain in decision_pipeline.py:apply_confidence_gate:
    #   1. Per-asset direction-specific override (e.g. GBPJPY.min_confidence_buy)
    #   2. Global direction-specific default (defaults.min_confidence_buy)
    #   3. Per-asset global threshold (GBPJPY.min_confidence)
    #   4. Global default (defaults.min_confidence)
    from paper_trading.config_manager import get_config as _get_prod_cfg
    _prod_cfg = _get_prod_cfg()
    _def = getattr(_prod_cfg, "defaults", {}) or {}
    _acfg = _prod_cfg.assets.get(asset_name, {})
    _buy_conf = (
        _acfg.get("min_confidence_buy")
        or _def.get("min_confidence_buy")
        or _acfg.get("min_confidence")
        or _def.get("min_confidence", 55.0)
    )
    _sell_conf = (
        _acfg.get("min_confidence_sell")
        or _def.get("min_confidence_sell")
        or _acfg.get("min_confidence")
        or _def.get("min_confidence", 55.0)
    )
    hi_thresh = _buy_conf / 100.0  # BUY when p_long >= _buy_conf%
    lo_thresh = 1.0 - _sell_conf / 100.0  # SELL when (1-p_long) >= _sell_conf%
    sell_thresh = _sell_conf / 100.0  # SELL confidence gate for direction-conditional logic
    logger.info(
        "  thresholds: BUY>=%.3f SELL>=%.3f (conf); (from config: buy=%s sell=%s)",
        hi_thresh, sell_thresh, _buy_conf, _sell_conf,
    )
    # ensemble_threshold is now used only for ensemble blending, not signal generation

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
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

        # ── scale_pos_weight (matching production training) ──
        n0 = (y_tr == 0).sum()
        n1 = (y_tr == 1).sum()
        imbalance_ratio = n0 / max(n1, 1)
        if no_scale_pos_weight:
            imbalance_ratio = 1.0
            logger.info("  scale_pos_weight forced to 1.0 (class imbalance ignored)")

        # ── Validation split (matching production early stopping) ──
        # When the fold has enough data, reserve 20% for validation + gap.
        # Otherwise fall back to training on all data.
        n_tr = len(X_tr)
        n_val = max(int(n_tr * 0.2), 1)
        val_start = n_tr - n_val - gap
        use_early_stopping = val_start >= 50
        if use_early_stopping:
            X_tr_fit = X_tr.iloc[:val_start]
            y_tr_fit = y_tr.iloc[:val_start]
            X_val = X_tr.iloc[val_start + gap:]
            y_val = y_tr.iloc[val_start + gap:]
            eval_set = [(X_val[alpha_cols], y_val)]
        else:
            X_tr_fit = X_tr
            y_tr_fit = y_tr
            eval_set = None

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=max_depth,
            learning_rate=0.02,
            objective="binary:logistic",
            scale_pos_weight=imbalance_ratio,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
            early_stopping_rounds=50 if eval_set else None,
        )
        # ── Sample weights (direction-weighted training) ──
        # When --weighted is passed, BUY samples (label=1) get 2x weight to
        # penalize BUY misclassifications more heavily in the loss function.
        fit_kwargs = {}
        if sample_weight_flag:
            y_tr_vals = y_tr_fit.values if hasattr(y_tr_fit, "values") else np.asarray(y_tr_fit)
            fit_kwargs["sample_weight"] = np.where(y_tr_vals == 1, 2.0, 1.0)

        if eval_set:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, eval_set=eval_set, verbose=False, **fit_kwargs)
        else:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, **fit_kwargs)
        if use_early_stopping:
            logger.info("  fold %d: early stopping at %d/%d trees", fold, model.best_iteration + 1, model.n_estimators)

        base_p_tr = model.predict_proba(X_tr[alpha_cols])[:, 1]
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

        # ── Calibration (direction-conditional, Step 2) ────────────────
        # When --calibrate is set, fit a DirectionalCalibrator on
        # OUT-OF-SAMPLE predictions (the validation fold held out during
        # model training), then apply it to the test fold's probabilities.
        # This avoids fitting the calibrator on in-sample predictions
        # which are systematically overconfident.
        if calibrate_flag:
            from shared.calibration import DirectionalCalibrator

            if use_early_stopping and len(X_val) >= 10:
                # Fit calibrator on OOS validation predictions
                cal_p = model.predict_proba(X_val[alpha_cols])[:, 1]
                cal = DirectionalCalibrator(n_bins=10)
                cal.fit(cal_p, y_val.values)
                p_long = cal.calibrate(p_long)
                logger.info(
                    "  fold %d: calibration on %d OOS val samples (buy=%s sell=%s)",
                    fold,
                    len(cal_p),
                    cal._buy_fitted,
                    cal._sell_fitted,
                )
            else:
                # Fallback: too small for a validation holdout.
                logger.warning(
                    "  fold %d: skipping calibration — need >=10 val samples (got %d)",
                    fold,
                    len(X_val) if use_early_stopping else 0,
                )

        # Signal from direction-conditional thresholds (matches production decision_pipeline.py)
        # Determine direction first (p_long >= 0.5 = BUY), then check confidence gate.
        # BUY gate: p_long >= min_confidence_buy% (hi_thresh = buy_conf/100)
        # SELL gate: (1-p_long) >= min_confidence_sell% (sell_thresh = sell_conf/100)
        # When neither gate passes, signal is neutral (0).
        # NOTE: lo_thresh = 1 - sell_conf/100 is a p_long threshold for the OLD logic;
        # for direction-conditional we need the raw sell confidence threshold.
        sell_thresh = _sell_conf / 100.0
        signals = np.zeros(len(p_long), dtype=int)
        signals[(p_long >= 0.5) & (p_long >= hi_thresh)] = 1
        signals[(p_long < 0.5) & ((1.0 - p_long) >= sell_thresh)] = -1

        # ── Directional filter (Architecture C validation) ────────────
        # When --allowed-direction is BUY or SELL, suppress signals that
        # trade the opposite direction so the model only produces trades
        # in the tested direction. This validates the directional-specialist
        # hypothesis without requiring separate model retraining.
        if allowed_direction == "BUY":
            signals[signals == -1] = 0  # null out SELL signals
        elif allowed_direction == "SELL":
            signals[signals == 1] = 0   # null out BUY signals

        # direction-aware accuracy: maps labels {0,1} to {-1,1} so SELL
        # predictions are correctly counted — old (signals == y_te)
        # never matched SELL (-1) against the SHORT label (0)
        label_dir = y_te.values * 2 - 1
        directional = (signals * label_dir).sum() / max((signals != 0).sum(), 1)
        hit_rate = directional
        long_rate = (signals == 1).mean()
        short_rate = (signals == -1).mean()
        flat_rate = (signals == 0).mean()

        # Spearman rank correlation IC (Information Coefficient)
        from scipy.stats import spearmanr
        ic, ic_p = spearmanr(p_long, y_te.fillna(0))
        ic = ic if not np.isnan(ic) else 0.0
        ic_p = ic_p if not np.isnan(ic_p) else 1.0

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
            "spearman_ic": round(float(ic), 6),
            "spearman_ic_pvalue": round(float(ic_p), 6),
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
        if invert_labels:
            # Recover original labels (pre-inversion) for diagnostic evaluation
            label_original = y_original.loc[y_te.index]
            oos_df["label_original"] = label_original.values
            oos_df.attrs["invert_labels"] = True
        all_oos_signals.append(oos_df)

        logger.info(
            "  fold %d: train=%s..%s (%d) | test=%s..%s (%d) | hit=%.3f dir=%.3f long=%.2f short=%.2f dir_filter=%s",
            fold,
            window["train_start"],
            window["train_end"],
            len(X_tr),
            window["test_start"],
            window["test_end"],
            len(X_te),
            hit_rate,
            directional,
            long_rate,
            short_rate,
            allowed_direction,
        )

    if not windows:
        logger.warning("%s: no windows produced", asset_name)
        return None

    summary = pd.DataFrame(windows)
    summary_path = Path(OUTPUT_DIR) / _tag_path(f"{asset_name}_wf_summary.csv", tag)
    summary.to_csv(summary_path, index=False)
    logger.info("%s: summary -> %s", asset_name, summary_path)

    # Save per-fold IC data
    fold_data = []
    for w in windows:
        fold_data.append(
            {
                "fold": w["fold"],
                "train_start": w["train_start"],
                "train_end": w["train_end"],
                "test_start": w["test_start"],
                "test_end": w["test_end"],
                "ic": w["directional"],
                "hit_rate": w["hit_rate"],
            }
        )
    ic_record = {
        "ticker": asset_name,
        "folds": fold_data,
        "mean_ic": round(float(sum(w["directional"] for w in windows) / len(windows)), 4),
        "positive_folds": sum(1 for w in windows if w["directional"] > 0),
        "total_folds": len(windows),
    }
    import json

    fold_ic_path = Path(OUTPUT_DIR) / _tag_path(f"{asset_name}_fold_ic.json", tag)
    with open(fold_ic_path, "w") as f:
        json.dump(ic_record, f, indent=2)
    logger.info("%s: fold IC -> %s", asset_name, fold_ic_path)

    if all_oos_signals:
        signals_df = pd.concat(all_oos_signals)
        signals_path = Path(OUTPUT_DIR) / _tag_path(f"{asset_name}_wf_signals.parquet", tag)
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
    parser.add_argument(
        "--ensemble-weight",
        type=float,
        default=1.0,
        help="Base model weight in ensemble (1.0 = base only)",
    )
    parser.add_argument("--ensemble-threshold", type=float, default=0.15, help="Ensemble signal threshold")
    parser.add_argument(
        "--pt-sl",
        type=str,
        default=None,
        help="Override pt_sl as tp,sl (e.g. --pt-sl 1.0,2.0). Default: from production config.",
    )
    parser.add_argument("--tag", type=str, default="", help="Suffix for output filenames")
    parser.add_argument(
        "--window-type",
        type=str,
        default="expanding",
        choices=["expanding", "rolling"],
        help="Training window: expanding (all history) or rolling (fixed lookback)",
    )
    parser.add_argument(
        "--rolling-window-bars",
        type=int,
        default=None,
        help="Fixed lookback in bars for rolling window (default: years * 252)",
    )
    parser.add_argument(
        "--label-type",
        type=str,
        default="standard",
        choices=["standard", "trend_adjusted"],
        help="Label type: standard (triple-barrier) or trend_adjusted (per-timestep pt_sl)",
    )
    parser.add_argument(
        "--invert-labels",
        action="store_true",
        default=False,
        help="Flip labels (y -> 1-y) so model learns P(DOWN) instead of P(UP).",
    )
    parser.add_argument(
        "--weighted",
        action="store_true",
        default=False,
        help="Apply direction-weighted training: BUY samples get 2x sample weight in loss.",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        default=False,
        help="Apply DirectionalCalibrator after each fold.",
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=3,
        help="Number of walk-forward folds (default 3; reduce for assets with sparse labels)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Override max_depth for all assets (default: from production config)",
    )
    parser.add_argument(
        "--no-scale-pos-weight",
        action="store_true",
        default=False,
        help="Force scale_pos_weight=1.0 (ignore class imbalance). Tests whether imbalance weighting contributes to sell bias.",
    )
    parser.add_argument(
        "--allowed-direction",
        type=str,
        default="BOTH",
        choices=["BOTH", "BUY", "SELL"],
        help="Filter signals to only BUY, only SELL, or BOTH (default). Validates directional-specialist architecture.",
    )
    parser.add_argument(
        "--expanded-dir",
        type=str,
        default=None,
        help=(
            "Path to 10-year cached OHLCV parquet directory "
            "(e.g. data/yfinance_10yr). When set, reads from cached parquet "
            "instead of live yfinance, enabling longer walk-forward windows. "
            "Use 'auto' to auto-detect via EIGENCAPITAL_EXPANDED_DATA_DIR env var "
            "or the default data/yfinance_10yr/ path."
        ),
    )
    args = parser.parse_args()

    # Ensure data fetcher has a no-op store (for yfinance-only operation)
    from paper_trading.ops.data_fetcher import _set_store

    class _NullStore:
        def save_cache(self, *args, **kwargs): pass
        def load_cache(self, *args, **kwargs): return None
        def cache_path(self, *args, **kwargs): return "/dev/null"

    _set_store(_NullStore())

    # Load per-asset pt_sl from production config
    from paper_trading.config_manager import get_config
    from features.registry import ASSET_LABEL_PARAMS

    _cfg = get_config()
    _asset_pt_sl: dict[str, tuple[float, float]] = {}
    for _name, _acfg in _cfg.assets.items():
        _tp = float(_acfg.get("tp_mult", 2.0))
        _sl = float(_acfg.get("sl_mult", 2.0))
        _asset_pt_sl[_name] = (_tp, _sl)
    # Fallback to FEATURE_REGISTRY for non-production assets (e.g. JPYCROSS screening)
    for _name in ASSETS:
        if _name not in _asset_pt_sl and _name in ASSET_LABEL_PARAMS:
            _tp = ASSET_LABEL_PARAMS[_name]["pt"]
            _sl = ASSET_LABEL_PARAMS[_name]["sl"]
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

    ticker_map_path = Path(OUTPUT_DIR) / _tag_path("ticker_map.json", args.tag)
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
        _md = args.max_depth if args.max_depth is not None else int(_acfg.get("max_depth", 2))
        result = run_walk_forward(
            name,
            ticker,
            window_years=args.years,
            step_years=args.step,
            n_folds=args.n_folds,
            ensemble_weight=args.ensemble_weight,
            ensemble_threshold=args.ensemble_threshold,
            pt_sl=pt_sl,
            max_depth=_md,
            tag=args.tag,
            window_type=args.window_type,
            rolling_window_bars=args.rolling_window_bars,
            label_type=args.label_type,
            invert_labels=args.invert_labels,
            sample_weight_flag=args.weighted,
            calibrate_flag=args.calibrate,
            no_scale_pos_weight=args.no_scale_pos_weight,
            allowed_direction=args.allowed_direction,
            expanded_data_dir=args.expanded_dir,
        )
        if result is not None:
            all_summaries.append(result)

    if all_summaries:
        combined = pd.concat(all_summaries)
        combined_path = Path(OUTPUT_DIR) / _tag_path("all_assets_wf_summary.csv", args.tag)
        combined.to_csv(combined_path, index=False)
        logger.info("combined summary -> %s", combined_path)

        print("\n=== Cross-Asset Walk-Forward Summary ===")
        metrics = ["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]
        avg = combined.groupby("asset")[metrics].mean()
        print(avg.to_string(float_format="%.3f"))


if __name__ == "__main__":
    main()
