"""Experiment runner — orchestrates DOE sweeps via walk-forward backtest."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.label_optimization.configs import LabelExperiment
from research.label_optimization.metrics import (
    behavioral_metrics,
    calibration_curve,
    label_distribution,
    trading_metrics_from_signals,
)
from research.label_optimization.schema import (
    create_experiment,
    finalize_experiment,
    save_metrics,
)

logger = logging.getLogger("label_opt.runner")

TICKER_MAP = {
    "EURCHF": "EURCHF=X",
    "GC": "GC=F",
    "DJI": "^DJI",
    "USDCAD": "USDCAD=X",
    "AUDUSD": "AUDUSD=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDJPY": "AUDJPY=X",
    "NZDUSD": "NZDUSD=X",
    "USDMXN": "USDMXN=X",
    "XAGUSD": "XAGUSD=F",
    "XAUUSD": "XAUUSD=X",
    "BTCUSD": "BTC-USD",
    "GBPAUD": "GBPAUD=X",
    "EURNZD": "EURNZD=X",
    "NZDJPY": "NZDJPY=X",
    "GBPJPY": "GBPJPY=X",
    "CADCHF": "CADCHF=X",
    "EURAUD": "EURAUD=X",
    "GBPCHF": "GBPCHF=X",
    "NZDCHF": "NZDCHF=X",
    "NZDCAD": "NZDCAD=X",
    "AUDCAD": "AUDCAD=X",
    "EURGBP": "EURGBP=X",
    "GBPCAD": "GBPCAD=X",
    "AUDNZD": "AUDNZD=X",
    "EURJPY": "EURJPY=X",
}


def _get_git_commit() -> str | None:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def _to_binary(y):
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_experiment(exp: LabelExperiment, tag: str = "") -> dict[str, Any] | None:
    eid = create_experiment(
        asset=exp.asset,
        method=exp.label_method,
        pt=exp.pt,
        sl=exp.sl,
        vb=exp.vb,
        vol_method=exp.vol_method,
        atr_period=exp.atr_period,
        git_commit=_get_git_commit(),
    )
    logger.info("Experiment %s starting...", eid)
    t0 = time.time()
    ticker = TICKER_MAP.get(exp.asset, f"{exp.asset}=X")
    try:
        result = _run_walk_forward_inprocess(
            asset=exp.asset,
            ticker=ticker,
            pt_sl=(exp.pt, exp.sl),
            vb=exp.vb,
            vol_method=exp.vol_method,
            atr_period=exp.atr_period,
        )
        if result is None:
            logger.error("Experiment %s — walk-forward returned None", eid)
            finalize_experiment(eid, "failed")
            return None
        signals, summary = result
        runtime = time.time() - t0
        _store_experiment_metrics(eid, exp, signals, summary)
        finalize_experiment(eid, "done", runtime_sec=round(runtime, 2))
        logger.info("Experiment %s done (%.1fs)", eid, runtime)
        return {"experiment_id": eid, "status": "done", "runtime": runtime}
    except Exception as e:
        logger.exception("Experiment %s failed: %s", eid, e)
        finalize_experiment(eid, "failed")
        return None


def _run_walk_forward_inprocess(asset: str, ticker: str,
                                 pt_sl: tuple[float, float],
                                 vb: int = 20,
                                 vol_method: str | None = None,
                                 atr_period: int | None = None,
                                 ) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Call walk_forward_backtest internals directly within this process."""
    sys.path.insert(0, str(Path.cwd()))
    from features.alpha_features import build_alpha_features
    from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv, _fetch_macro_batch
    from features.event_features import compute_event_features
    from features.positioning_features import check_oi_availability, compute_volume_features
    from features.rates_features import compute_all as compute_rates
    from features.regime_features import generate_regime_features
    from labels.triple_barrier import apply_triple_barrier
    from shared.volatility import VolatilityPrimitive

    prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset, ticker)
    ohlcv = fetch_asset_ohlcv(ticker)
    if prices is None or prices.empty or len(prices) < 100:
        logger.warning("SKIP %s: no data", asset)
        return None

    vol_primitive = None
    if vol_method == "atr":
        vol_primitive = VolatilityPrimitive(period=atr_period or 14)

    if not ohlcv.empty:
        labeled = apply_triple_barrier(
            ohlcv,
            pt_sl=list(pt_sl),
            vertical_barrier=vb,
            vol_primitive=vol_primitive,
        )
        labels = labeled["label"].reindex(prices.index).fillna(0).astype(int)
    else:
        from labels.compat import triple_barrier_labels
        labels = triple_barrier_labels(prices, pt_sl=pt_sl, vertical_barrier=vb, vol_lookback=21)

    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix,
                                     spx=spx, commodities=commodities, ohlcv=ohlcv)
    prefix = asset.upper()
    vol_df = compute_volume_features(ohlcv)
    if vol_df is not None and not vol_df.empty:
        for col in vol_df.columns:
            alpha_df[f"{prefix}_{col}"] = vol_df[col].reindex(alpha_df.index)
    alpha_df[f"{prefix}_oi_available"] = check_oi_availability(ticker)

    macro = _fetch_macro_batch()
    rd_series = (
        rate_diffs[asset]
        if rate_diffs is not None and asset in rate_diffs.columns
        else pd.Series(0.0, index=alpha_df.index)
    )
    rates_df = compute_rates(macro, rd_series, alpha_df.index)
    if rates_df is not None and not rates_df.empty:
        for col in rates_df.columns:
            series = rates_df[col].reindex(alpha_df.index)
            if series.isna().all():
                series = pd.Series(0.0, index=alpha_df.index)
            alpha_df[f"{prefix}_{col}"] = series

    event_df = compute_event_features(alpha_df.index)
    if event_df is not None and not event_df.empty:
        for col in event_df.columns:
            alpha_df[f"{prefix}_{col}"] = event_df[col].reindex(alpha_df.index)

    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()

    regime_ok = not ohlcv.empty
    regime_cols = []
    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    if regime_ok:
        regime_df = generate_regime_features(ohlcv)
        regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
        full_df = alpha_df.join(regime_renamed, how="left").dropna()
        regime_cols = list(regime_renamed.columns)
    else:
        full_df = alpha_df.copy()

    all_cols = alpha_cols + regime_cols
    if len(full_df) < 300:
        logger.warning("%s: insufficient data (%d rows)", asset, len(full_df))
        return None

    X_all = full_df[all_cols]
    y_all = _to_binary(full_df["label"])
    if len(y_all) < 100:
        logger.warning("%s: only %d binary samples", asset, len(y_all))
        return None
    X_all = X_all.loc[y_all.index]

    from labels.compat import PurgedWalkForwardFolds
    cv = PurgedWalkForwardFolds(n_folds=3, gap=max(20, vb), min_train=100,
                                 window_type="expanding", rolling_window_bars=3 * 252)

    windows = []
    all_oos_signals = []
    import xgboost as xgb

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        X_tr = X_all.iloc[train_idx]
        y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_all.iloc[test_idx]

        if y_tr.nunique() < 2:
            continue

        n0 = (y_tr == 0).sum()
        n1 = (y_tr == 1).sum()
        imbalance_ratio = n0 / max(n1, 1)

        n_tr = len(X_tr)
        n_val = max(int(n_tr * 0.2), 1)
        val_start = n_tr - n_val - max(20, vb)
        use_early_stopping = val_start >= 50
        if use_early_stopping:
            X_tr_fit = X_tr.iloc[:val_start]
            y_tr_fit = y_tr.iloc[:val_start]
            X_val = X_tr.iloc[val_start + max(20, vb):]
            y_val = y_tr.iloc[val_start + max(20, vb):]
            eval_set = [(X_val[alpha_cols], y_val)]
        else:
            X_tr_fit = X_tr
            y_tr_fit = y_tr
            eval_set = None

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective="binary:logistic", scale_pos_weight=imbalance_ratio,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
            early_stopping_rounds=50 if eval_set else None,
        )
        if eval_set:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, eval_set=eval_set, verbose=False)
        else:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit)

        p_long = model.predict_proba(X_te[alpha_cols])[:, 1]

        signals = np.zeros(len(p_long), dtype=int)
        signals[p_long >= 0.55] = 1
        signals[p_long <= 0.45] = -1

        label_dir = y_te.values * 2 - 1
        directional = (signals * label_dir).sum() / max((signals != 0).sum(), 1)

        from scipy.stats import spearmanr
        ic, ic_p = spearmanr(p_long, y_te.fillna(0))
        ic = ic if not np.isnan(ic) else 0.0

        windows.append({
            "asset": asset, "fold": fold,
            "train_samples": len(X_tr), "test_samples": len(X_te),
            "hit_rate": round(float(directional), 4),
            "directional": round(float(directional), 4),
            "spearman_ic": round(float(ic), 6),
            "long_rate": round((signals == 1).mean(), 4),
            "short_rate": round((signals == -1).mean(), 4),
            "flat_rate": round((signals == 0).mean(), 4),
        })

        oos_df = pd.DataFrame({
            "signal": signals, "label": y_te.values, "p_long": p_long,
        }, index=X_te.index)
        oos_df["asset"] = asset
        all_oos_signals.append(oos_df)

    if not windows:
        logger.warning("%s: no windows produced", asset)
        return None

    summary = pd.DataFrame(windows)
    signals_df = pd.concat(all_oos_signals) if all_oos_signals else pd.DataFrame()
    return signals_df, summary


def _store_experiment_metrics(eid: str, exp: LabelExperiment,
                              signals: pd.DataFrame | None,
                              summary: pd.DataFrame | None) -> None:
    if signals is not None and "label" in signals.columns:
        labels = signals["label"].values
        label_metrics = label_distribution(pd.Series(labels))
        save_metrics("label_metrics", eid, label_metrics)

    if signals is not None and "p_long" in signals.columns and "label" in signals.columns:
        probs = signals["p_long"].values.astype(float)
        lbls = signals["label"].values.astype(int)
        cal = calibration_curve(probs, lbls)
        save_metrics("calibration_metrics", eid, cal)

    if signals is not None and "p_long" in signals.columns and "signal" in signals.columns:
        probs = signals["p_long"].values.astype(float)
        sigs = signals["signal"].values.astype(int)
        beh = behavioral_metrics(probs, sigs)
        save_metrics("behavioral_metrics", eid, beh)

    if signals is not None:
        ohlcv_data = _load_ohlcv(exp.asset)
        tm = trading_metrics_from_signals(signals, ohlcv_data)
        save_metrics("trading_metrics", eid, tm)

    if summary is not None and not summary.empty:
        mm = {
            "auc": 0.0, "log_loss": 0.0, "f1": 0.0, "mcc": 0.0,
            "precision_buy": 0.0, "recall_buy": 0.0,
            "precision_sell": 0.0, "recall_sell": 0.0,
            "n_train": int(summary["train_samples"].mean()) if "train_samples" in summary.columns else 0,
            "n_valid": 0, "feature_count": 0,
        }
        if "spearman_ic" in summary.columns:
            mm["auc"] = round(float(summary["spearman_ic"].mean()), 6)
        save_metrics("model_metrics", eid, mm)


def _load_ohlcv(asset: str) -> pd.DataFrame | None:
    import glob
    base = Path("data/yfinance_10yr")
    if not base.exists():
        return None
    patterns = [f"*{asset}*ohlcv.parquet", f"*{asset.upper()}*ohlcv.parquet", f"*{asset.lower()}*ohlcv.parquet"]
    for p in patterns:
        matches = list(base.glob(p))
        if matches:
            try:
                return pd.read_parquet(matches[0])
            except Exception:
                return None
    return None


def run_grid(experiments: list[LabelExperiment], tag: str = "",
             parallel: bool = False) -> list[dict[str, Any]]:
    results = []
    for i, exp in enumerate(experiments):
        logger.info("Grid: %d/%d — %s", i + 1, len(experiments), exp.experiment_id)
        r = run_experiment(exp, tag=tag)
        if r:
            results.append(r)
    return results
