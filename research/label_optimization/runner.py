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
    edge_retention,
    fold_metrics,
    label_distribution,
    production_cost_metrics,
)
from research.label_optimization.schema import (
    compute_fold_aggregates,
    create_experiment,
    finalize_experiment,
    get_baseline_sharpe,
    save_baseline,
    save_fold_result,
    save_metrics,
)

logger = logging.getLogger("label_opt.runner")

TICKER_MAP = {
    "EURCHF": "EURCHF=X", "GC": "GC=F", "DJI": "^DJI",
    "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X", "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X", "AUDJPY": "AUDJPY=X",
    "NZDUSD": "NZDUSD=X", "USDMXN": "USDMXN=X", "XAGUSD": "XAGUSD=F",
    "XAUUSD": "XAUUSD=X", "BTCUSD": "BTC-USD", "GBPAUD": "GBPAUD=X",
    "EURNZD": "EURNZD=X", "NZDJPY": "NZDJPY=X", "GBPJPY": "GBPJPY=X",
    "CADCHF": "CADCHF=X", "EURAUD": "EURAUD=X", "GBPCHF": "GBPCHF=X",
    "NZDCHF": "NZDCHF=X", "NZDCAD": "NZDCAD=X", "AUDCAD": "AUDCAD=X",
    "EURGBP": "EURGBP=X", "GBPCAD": "GBPCAD=X", "AUDNZD": "AUDNZD=X",
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
    version = exp.label_strategy_version or "TB_v1"
    baseline_id = None

    eid = create_experiment(
        asset=exp.asset, method=exp.label_method,
        pt=exp.pt, sl=exp.sl, vb=exp.vb,
        vol_method=exp.vol_method, atr_period=exp.atr_period,
        git_commit=_get_git_commit(),
        label_strategy_version=version,
        baseline_id=baseline_id,
    )
    logger.info("Experiment %s (%s)", eid, version)
    t0 = time.time()
    ticker = TICKER_MAP.get(exp.asset, f"{exp.asset}=X")
    t_feature = t_train = 0.0

    try:
        result = _run_walk_forward_inprocess(
            asset=exp.asset, ticker=ticker,
            pt_sl=(exp.pt, exp.sl), vb=exp.vb,
            vol_method=exp.vol_method, atr_period=exp.atr_period,
        )
        if result is None:
            logger.error("%s — walk-forward returned None", eid)
            finalize_experiment(eid, "failed")
            return None

        fold_data_list, signals, summary = result
        runtime = time.time() - t0

        # Store per-fold results
        for fd in fold_data_list:
            save_fold_result(eid, fd["fold"], fd)

        # Compute aggregates from folds
        compute_fold_aggregates(eid)

        # Compute edge retention
        baseline_sharpe = get_baseline_sharpe(exp.asset)
        avg_sharpe = np.mean([fd.get("sharpe", 0) for fd in fold_data_list])
        er = edge_retention(avg_sharpe, baseline_sharpe or avg_sharpe)

        # Store production cost metrics
        avg_cal_inv = np.mean([fd.get("cal_inversion_rate", 0) for fd in fold_data_list])
        avg_ece = np.mean([fd.get("ece", 0) for fd in fold_data_list])
        pc = production_cost_metrics(
            eid, avg_cal_inv, avg_ece, er, avg_sharpe, baseline_sharpe or avg_sharpe,
        )
        save_metrics("production_cost_metrics", eid, pc)

        # Store as baseline if this is the production config
        if baseline_sharpe is None and _is_production_config(exp):
            save_baseline(eid, exp.asset, exp.pt, exp.sl,
                          avg_sharpe, avg_ece, avg_cal_inv)
            logger.info("  -> registered as production baseline for %s", exp.asset)

        finalize_experiment(eid, "done", runtime_sec=round(runtime, 2))
        logger.info(
            "%s done (%.1fs) Sharpe=%.3f ECE=%.4f EdgeRet=%.2f",
            eid, runtime, avg_sharpe, avg_ece, er,
        )
        return {"experiment_id": eid, "status": "done", "runtime": runtime}

    except Exception as e:
        logger.exception("Experiment %s failed: %s", eid, e)
        finalize_experiment(eid, "failed")
        return None


def _is_production_config(exp: LabelExperiment) -> bool:
    """Check if this config matches the production PT/SL for this asset."""
    from features.registry import ASSET_LABEL_PARAMS
    prod = ASSET_LABEL_PARAMS.get(exp.asset, {})
    prod_pt = prod.get("pt", 2.0)
    prod_sl = prod.get("sl", 2.0)
    return abs(exp.pt - prod_pt) < 0.01 and abs(exp.sl - prod_sl) < 0.01


def _run_walk_forward_inprocess(asset: str, ticker: str,
                                 pt_sl: tuple[float, float],
                                 vb: int = 20,
                                 vol_method: str | None = None,
                                 atr_period: int | None = None,
                                 ) -> tuple[list[dict], pd.DataFrame, pd.DataFrame] | None:
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
            ohlcv, pt_sl=list(pt_sl), vertical_barrier=vb, vol_primitive=vol_primitive,
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
    rd_series = (rate_diffs[asset]
                 if rate_diffs is not None and asset in rate_diffs.columns
                 else pd.Series(0.0, index=alpha_df.index))
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
    close_all = full_df["close"].values if "close" in full_df.columns else None
    if len(y_all) < 100:
        logger.warning("%s: only %d binary samples", asset, len(y_all))
        return None
    X_all = X_all.loc[y_all.index]

    from labels.compat import PurgedWalkForwardFolds
    cv = PurgedWalkForwardFolds(
        n_folds=3, gap=max(20, vb), min_train=100,
        window_type="expanding", rolling_window_bars=3 * 252,
    )

    import xgboost as xgb

    windows = []
    all_oos_signals = []
    fold_data_list = []

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        X_tr = X_all.iloc[train_idx]
        y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_all.iloc[test_idx]

        if y_tr.nunique() < 2:
            continue

        n0, n1 = (y_tr == 0).sum(), (y_tr == 1).sum()
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

        t0_fold = time.time()
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
        train_fold_sec = time.time() - t0_fold

        p_long = model.predict_proba(X_te[alpha_cols])[:, 1]
        signals_fold = np.zeros(len(p_long), dtype=int)
        signals_fold[p_long >= 0.55] = 1
        signals_fold[p_long <= 0.45] = -1

        # Per-fold metrics
        fold_df = pd.DataFrame({
            "signal": signals_fold, "label": y_te.values, "p_long": p_long,
        }, index=X_te.index)
        close_segment = close_all[X_all.index.get_indexer(X_te.index)] if close_all is not None else None

        fm = fold_metrics(fold_df, close_segment)
        fm["fold"] = fold
        fm["n_train"] = len(X_tr)
        fm["train_fold_sec"] = round(train_fold_sec, 3)
        fold_data_list.append(fm)

        # Store for aggregate signals
        from scipy.stats import spearmanr
        ic, ic_p = spearmanr(p_long, y_te.fillna(0))
        ic = ic if not np.isnan(ic) else 0.0
        windows.append({
            "asset": asset, "fold": fold,
            "train_samples": len(X_tr), "test_samples": len(X_te),
            "hit_rate": round(float((signals_fold != 0).mean()), 4),
            "directional": round(float((signals_fold != 0).mean()), 4),
            "spearman_ic": round(float(ic), 6),
            "long_rate": round((signals_fold == 1).mean(), 4),
            "short_rate": round((signals_fold == -1).mean(), 4),
            "flat_rate": round((signals_fold == 0).mean(), 4),
        })
        all_oos_signals.append(fold_df)

    if not fold_data_list:
        logger.warning("%s: no windows produced", asset)
        return None

    summary = pd.DataFrame(windows)
    signals_df = pd.concat(all_oos_signals) if all_oos_signals else pd.DataFrame()
    return fold_data_list, signals_df, summary


def run_grid(experiments: list[LabelExperiment], tag: str = "",
             parallel: bool = False) -> list[dict[str, Any]]:
    results = []
    for i, exp in enumerate(experiments):
        logger.info("Grid: %d/%d — %s", i + 1, len(experiments), exp.experiment_id)
        r = run_experiment(exp, tag=tag)
        if r:
            results.append(r)
    return results
