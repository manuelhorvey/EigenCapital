#!/usr/bin/env python3
"""Counterfactual: retrain ALL assets with symmetric tp_sl=(2.0,2.0) labels.

This tests whether asymmetric TP/SL barriers are the root cause of SELL dominance.
If symmetric labels produce bidirectional skill, the barrier asymmetry IS the root cause.
If SELL dominance persists, the cause is deeper (features, model architecture, market structure).
"""

import logging
import os
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("counterfactual_symmetric")

ASSETS = {
    "AUDJPY": "AUDJPY=X", "AUDUSD": "AUDUSD=X", "CADCHF": "CADCHF=X",
    "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X", "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURNZD": "EURNZD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X",
    "GBPJPY": "GBPJPY=X", "GBPUSD": "GBPUSD=X", "GC": "GC=F",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X",
    "NZDUSD": "NZDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X", "BTCUSD": "BTC-USD", "^DJI": "^DJI",
}

OUTPUT_DIR = Path("scripts/walkforward")
DATA_DIR = Path("data/yfinance_10yr")

SYMMETRIC_PT_SL = (2.0, 2.0)  # TP=2R, SL=2R — symmetric barriers


def _tag_path(filename: str, tag: str) -> str:
    if not tag:
        return filename
    stem, ext = os.path.splitext(filename)
    return f"{stem}_{tag}{ext}"


def fetch_expanded_for_wf(asset_name, ticker):
    from features.alpha_features import build_alpha_features
    from features.data_fetch import _normalize_index, _fetch_macro_batch, CURRENCY_YIELD_TICKERS, _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS
    
    ohlcv_path = DATA_DIR / f"{asset_name}_ohlcv.parquet"
    if not ohlcv_path.exists():
        raise FileNotFoundError(f"No cached data for {asset_name}")
    
    ohlcv = pd.read_parquet(ohlcv_path)
    ohlcv.index = _normalize_index(ohlcv.index)
    close = ohlcv["close"].copy()
    close.name = asset_name
    prices = close.to_frame(asset_name)
    
    macro = _fetch_macro_batch()
    dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
    vix = macro.get("^VIX", pd.Series(dtype=float))
    spx = macro.get("^GSPC", pd.Series(dtype=float))
    wti = macro.get("CL=F", pd.Series(dtype=float))
    tnx = macro.get("^TNX", pd.Series(dtype=float))
    
    for s in [dxy, vix, spx, wti, tnx]:
        if not s.empty and s.index.duplicated().any():
            s = s[~s.index.duplicated(keep="last")]
    
    common = close.index
    if common.duplicated().any():
        common = common[~common.duplicated(keep="last")]
    for s, dropna in [(dxy, False), (vix, False), (spx, False), (wti, False), (tnx, True)]:
        if not s.empty:
            idx = s.dropna().index if dropna else s.index
            if idx.duplicated().any():
                idx = idx[~idx.duplicated(keep="last")]
            common = common.intersection(idx)
    
    prices = prices.loc[common]
    ohlcv = ohlcv.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)
    tnx = tnx.reindex(common).ffill().fillna(0.0)
    
    asset_upper = asset_name.upper()
    base_ccy = quote_ccy = None
    if asset_upper not in _ZERO_RATE_ASSETS and len(asset_upper) == 6 \
       and asset_upper[:3] in _KNOWN_CURRENCIES and asset_upper[3:] in _KNOWN_CURRENCIES:
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]
    
    if base_ccy and quote_ccy:
        rate_diff = macro.get(CURRENCY_YIELD_TICKERS[base_ccy], tnx).reindex(common).ffill() \
                  - macro.get(CURRENCY_YIELD_TICKERS[quote_ccy], tnx).reindex(common).ffill()
    else:
        rate_diff = pd.Series(0.0, index=common)
    
    rate_diffs = pd.DataFrame({asset_name: rate_diff}, index=common)
    commodities = wti.to_frame("WTI")
    
    logger.info(f"  {asset_name}: {len(prices)} rows ({prices.index[0].date()}..{prices.index[-1].date()})")
    return prices, rate_diffs, dxy, vix, spx, commodities, ohlcv


def compute_labels(ohlcv, pt_sl, vertical_barrier=20):
    from labels.triple_barrier import apply_triple_barrier
    labeled = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=vertical_barrier)
    return labeled["label"].fillna(0).astype(int)


def _to_binary(y):
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_asset(asset_name, ticker, pt_sl, tag="symmetric_labels", **wf_kw):
    import xgboost as xgb
    from features.alpha_features import build_alpha_features
    from features.regime_features import generate_regime_features
    from labels.compat import PurgedWalkForwardFolds
    
    logger.info(f"=== {asset_name} pt_sl={pt_sl} ===")
    
    try:
        prices, rate_diffs, dxy, vix, spx, commodities, ohlcv = fetch_expanded_for_wf(asset_name, ticker)
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"SKIP {asset_name}: {e}")
        return None
    
    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, ohlcv=ohlcv)
    
    # Compute symmetric labels
    labels = compute_labels(ohlcv, pt_sl, vertical_barrier=20)
    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()
    
    if len(alpha_df) < 300:
        logger.warning(f"{asset_name}: insufficient rows ({len(alpha_df)})")
        return None
    
    # Report label distribution
    labs = alpha_df["label"].values.astype(int)
    n_up = int((labs == 1).sum())
    n_dn = int((labs == -1).sum())
    n_hold = int((labs == 0).sum())
    logger.info(f"  labels: UP={n_up} DOWN={n_dn} HOLD={n_hold}  UP_rate={n_up/max(n_up+n_dn,1)*100:.1f}%")
    
    regime_df = generate_regime_features(ohlcv)
    prefix = asset_name.upper()
    regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
    full_df = alpha_df.join(regime_renamed, how="left").dropna()
    
    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    regime_cols = list(regime_renamed.columns)
    all_cols = alpha_cols + regime_cols
    
    X_all = full_df[all_cols]
    y_all = _to_binary(full_df["label"])
    
    if len(y_all) < 100 or y_all.nunique() < 2:
        logger.warning(f"{asset_name}: insufficient binary samples ({len(y_all)})")
        return None
    X_all = X_all.loc[y_all.index]
    
    n0 = int((y_all == 0).sum())
    n1 = int((y_all == 1).sum())
    logger.info(f"  binary labels: 0={n0} 1={n1} ratio={n0/max(n1,1):.2f}")
    
    cv = PurgedWalkForwardFolds(
        n_folds=5, gap=20, min_train=100,
        window_type="expanding", rolling_window_bars=5*252,
    )
    
    windows = []
    all_oos_signals = []
    hi_thresh = 0.575
    lo_thresh = 0.425
    
    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        X_tr = X_all.iloc[train_idx]; y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]; y_te = y_all.iloc[test_idx]
        
        if y_tr.nunique() < 2:
            continue
        
        n0_tr = int((y_tr == 0).sum()); n1_tr = int((y_tr == 1).sum())
        imbalance_ratio = n0_tr / max(n1_tr, 1)
        
        n_tr = len(X_tr); n_val = max(int(n_tr * 0.2), 1)
        val_start = n_tr - n_val - 20
        use_es = val_start >= 50
        if use_es:
            X_tr_fit = X_tr.iloc[:val_start]; y_tr_fit = y_tr.iloc[:val_start]
            X_val = X_tr.iloc[val_start + 20:]; y_val = y_tr.iloc[val_start + 20:]
            eval_set = [(X_val[alpha_cols], y_val)]
        else:
            X_tr_fit = X_tr; y_tr_fit = y_tr; eval_set = None
        
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective="binary:logistic", scale_pos_weight=imbalance_ratio,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
            early_stopping_rounds=50 if use_es else None,
        )
        if eval_set:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, eval_set=eval_set, verbose=False)
        else:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, verbose=False)
        
        p_long = model.predict_proba(X_te[alpha_cols])[:, 1]
        
        signals = np.zeros(len(p_long), dtype=int)
        signals[p_long > hi_thresh] = 1
        signals[p_long < lo_thresh] = -1
        
        label_dir = y_te.values * 2 - 1
        directional = (signals * label_dir).sum() / max((signals != 0).sum(), 1)
        
        window = {
            "asset": asset_name, "fold": fold,
            "train_start": str(X_all.index[train_idx[0]].date()),
            "train_end": str(X_all.index[train_idx[-1]].date()),
            "test_start": str(X_all.index[test_idx[0]].date()),
            "test_end": str(X_all.index[test_idx[-1]].date()),
            "train_samples": len(X_tr), "test_samples": len(X_te),
            "hit_rate": round(float(directional), 4),
            "directional": round(float(directional), 4),
            "long_rate": round(float((signals==1).mean()), 4),
            "short_rate": round(float((signals==-1).mean()), 4),
            "flat_rate": round(float((signals==0).mean()), 4),
        }
        windows.append(window)
        
        oos_df = pd.DataFrame({"signal": signals, "label": y_te.values, "p_long": p_long}, index=X_te.index)
        oos_df["asset"] = asset_name
        all_oos_signals.append(oos_df)
        
        logger.info(f"  fold {fold}: train={len(X_tr)} test={len(X_te)} hit={directional:.3f} long={(signals==1).mean():.2f} short={(signals==-1).mean():.2f}")
    
    if not windows:
        return None
    
    summary = pd.DataFrame(windows)
    summary.to_csv(OUTPUT_DIR / _tag_path(f"{asset_name}_wf_summary.csv", tag), index=False)
    
    if all_oos_signals:
        signals_df = pd.concat(all_oos_signals)
        signals_df.to_parquet(OUTPUT_DIR / _tag_path(f"{asset_name}_wf_signals.parquet", tag))
    
    return summary


def main():
    logger.info("=" * 60)
    logger.info("COUNTERFACTUAL: Symmetric tp_sl=(2.0, 2.0) for all assets")
    logger.info("=" * 60)
    
    all_summaries = []
    for name, ticker in ASSETS.items():
        try:
            result = run_asset(name, ticker, SYMMETRIC_PT_SL, tag="symmetric_labels")
            if result is not None:
                all_summaries.append(result)
        except Exception as e:
            logger.error(f"{name}: FAILED — {e}", exc_info=True)
    
    if all_summaries:
        combined = pd.concat(all_summaries)
        combined.to_csv(OUTPUT_DIR / "all_assets_wf_summary_symmetric_labels.csv", index=False)
        
        print("\n=== Symmetric Labels Walk-Forward Summary ===")
        metrics = ["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]
        avg = combined.groupby("asset")[metrics].mean()
        print(avg.to_string(float_format="%.3f"))
    
    logger.info("\nDone. Now run validation: python scripts/validation/validate_directional_skill.py --tag symmetric_labels --save")


if __name__ == "__main__":
    main()
