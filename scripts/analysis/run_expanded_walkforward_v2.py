#!/usr/bin/env python3
"""Walk-forward backtest using 10+ year cached data. Bypasses the 5y limit in data_fetch.py."""

import logging
import os
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("expanded_wf_v2")

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


def slugify(ticker):
    return ticker.replace("=X", "").replace("=F", "").replace("-", "").replace("=", "")


def _tag_path(filename: str, tag: str) -> str:
    if not tag:
        return filename
    stem, ext = os.path.splitext(filename)
    return f"{stem}_{tag}{ext}"


def fetch_expanded_for_wf(asset_name: str, ticker: str):
    """Fetch data for walk-forward using local 10+ year cache."""
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
            s.name = None
            s = s[~s.index.duplicated(keep="last")]
            s.name = None
    
    common = close.index
    if common.duplicated().any():
        common = common[~common.duplicated(keep="last")]
    for s, dropna in [(dxy, False), (vix, False), (spx, False), (wti, False), (tnx, True)]:
        if not s.empty:
            idx = s.dropna().index if dropna else s.index
            if idx.duplicated().any():
                idx = idx[~idx.duplicated(keep="last")]
            common = common.intersection(idx)
    
    if common.empty:
        raise ValueError(f"{asset_name}: no overlapping dates with macro")
    
    prices = prices.loc[common]
    ohlcv = ohlcv.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)
    tnx = tnx.reindex(common).ffill().fillna(0.0)
    
    # Rate differentials
    asset_upper = asset_name.upper()
    base_ccy = quote_ccy = None
    if asset_upper not in _ZERO_RATE_ASSETS and len(asset_upper) == 6 \
       and asset_upper[:3] in _KNOWN_CURRENCIES and asset_upper[3:] in _KNOWN_CURRENCIES:
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]
    
    if base_ccy and quote_ccy:
        base_ticker = CURRENCY_YIELD_TICKERS[base_ccy]
        quote_ticker = CURRENCY_YIELD_TICKERS[quote_ccy]
        base_yield = macro.get(base_ticker, tnx)
        quote_yield = macro.get(quote_ticker, tnx)
        rate_diff = base_yield.reindex(common).ffill() - quote_yield.reindex(common).ffill()
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


def run_asset(asset_name, ticker, pt_sl, max_depth=2, window_years=5, step_years=2, n_folds=5, gap=20,
             ensemble_weight=1.0, ensemble_threshold=0.15, tag="expanded_10yr"):
    import xgboost as xgb
    from features.alpha_features import build_alpha_features
    from features.regime_features import generate_regime_features
    from labels.compat import PurgedWalkForwardFolds
    from paper_trading.inference.ensemble import EnsembleSignal
    from paper_trading.inference.regime_model import RegimeConditionalModel
    
    logger.info(f"=== {asset_name} walk-forward (expanded) ===")
    
    try:
        prices, rate_diffs, dxy, vix, spx, commodities, ohlcv = fetch_expanded_for_wf(asset_name, ticker)
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"SKIP {asset_name}: {e}")
        return None
    
    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx, commodities=commodities, ohlcv=ohlcv)
    labels = compute_labels(ohlcv, pt_sl, vertical_barrier=20)
    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()
    
    if len(alpha_df) < 300:
        logger.warning(f"{asset_name}: insufficient rows ({len(alpha_df)}) after feature building")
        return None
    
    # Build regime features
    regime_ok = True
    regime_cols = []
    alpha_cols = [c for c in alpha_df.columns if c != "label"]
    regime_df = generate_regime_features(ohlcv)
    prefix = asset_name.upper()
    regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
    full_df = alpha_df.join(regime_renamed, how="left").dropna()
    regime_cols = list(regime_renamed.columns)
    all_cols = alpha_cols + regime_cols
    
    logger.info(f"  features: {len(alpha_cols)} alpha + {len(regime_cols)} regime = {len(all_cols)} total")
    
    X_all = full_df[all_cols]
    y_all = _to_binary(full_df["label"])
    
    if len(y_all) < 100 or y_all.nunique() < 2:
        logger.warning(f"{asset_name}: insufficient binary samples ({len(y_all)})")
        return None
    
    X_all = X_all.loc[y_all.index]
    
    # Log label balance
    n0 = int((y_all == 0).sum())
    n1 = int((y_all == 1).sum())
    logger.info(f"  binary labels: 0={n0} 1={n1} ratio={n0/max(n1,1):.2f}")
    
    cv = PurgedWalkForwardFolds(
        n_folds=n_folds, gap=gap, min_train=100,
        window_type="expanding", rolling_window_bars=window_years * 252,
    )
    
    windows = []
    all_oos_signals = []
    hi_thresh = 0.5 + ensemble_threshold / 2.0
    lo_thresh = 0.5 - ensemble_threshold / 2.0
    
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
            logger.warning(f"  fold {fold}: only one class in train, skipping")
            continue
        
        n0_tr = int((y_tr == 0).sum())
        n1_tr = int((y_tr == 1).sum())
        imbalance_ratio = n0_tr / max(n1_tr, 1)
        
        # Validation split for early stopping
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
            n_estimators=300, max_depth=max_depth, learning_rate=0.02,
            objective="binary:logistic", scale_pos_weight=imbalance_ratio,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
            early_stopping_rounds=50 if eval_set else None,
        )
        if eval_set:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, eval_set=eval_set, verbose=False)
        else:
            model.fit(X_tr_fit[alpha_cols], y_tr_fit, verbose=False)
        
        base_p_long = model.predict_proba(X_te[alpha_cols])[:, 1]
        
        p_long = base_p_long
        if ensemble_weight < 1.0 and regime_ok and regime_cols:
            X_tr_regime = X_tr[all_cols]
            X_te_regime = X_te[all_cols]
            regime_model = RegimeConditionalModel()
            regime_model.train(X_tr_regime, y_tr, all_cols)
            r_p_long = regime_model.predict_long_prob(X_te_regime).ravel()
            ensemble = EnsembleSignal(base_weight=ensemble_weight, ensemble_threshold=ensemble_threshold)
            blended, _ = ensemble.combine(p_long, r_p_long)
            p_long = blended.ravel()
        
        signals = np.zeros(len(p_long), dtype=int)
        signals[p_long > hi_thresh] = 1
        signals[p_long < lo_thresh] = -1
        
        label_dir = y_te.values * 2 - 1
        directional = (signals * label_dir).sum() / max((signals != 0).sum(), 1)
        hit_rate = directional
        long_rate = (signals == 1).mean()
        short_rate = (signals == -1).mean()
        flat_rate = (signals == 0).mean()
        
        from scipy.stats import spearmanr
        ic, ic_p = spearmanr(p_long, y_te.fillna(0))
        ic = ic if not np.isnan(ic) else 0.0
        
        window = {
            "asset": asset_name, "fold": fold,
            "train_start": str(train_start.date()), "train_end": str(train_end.date()),
            "test_start": str(test_start.date()), "test_end": str(test_end.date()),
            "train_samples": len(X_tr), "test_samples": len(X_te),
            "hit_rate": round(float(hit_rate), 4),
            "directional": round(float(directional), 4),
            "spearman_ic": round(float(ic), 6),
            "long_rate": round(float(long_rate), 4),
            "short_rate": round(float(short_rate), 4),
            "flat_rate": round(float(flat_rate), 4),
        }
        windows.append(window)
        
        oos_df = pd.DataFrame({"signal": signals, "label": y_te.values, "p_long": p_long}, index=X_te.index)
        oos_df["asset"] = asset_name
        all_oos_signals.append(oos_df)
        
        logger.info(f"  fold {fold}: train={window['train_start']}..{window['train_end']} ({len(X_tr)}) | "
                     f"test={window['test_start']}..{window['test_end']} ({len(X_te)}) | "
                     f"hit={hit_rate:.3f} dir={directional:.3f} long={long_rate:.2f} short={short_rate:.2f}")
    
    if not windows:
        logger.warning(f"{asset_name}: no windows produced")
        return None
    
    summary = pd.DataFrame(windows)
    summary_path = OUTPUT_DIR / _tag_path(f"{asset_name}_wf_summary.csv", tag)
    summary.to_csv(summary_path, index=False)
    logger.info(f"  summary -> {summary_path}")
    
    fold_data = [{"fold": w["fold"], "train_start": w["train_start"], "train_end": w["train_end"],
                   "test_start": w["test_start"], "test_end": w["test_end"],
                   "ic": w["directional"], "hit_rate": w["hit_rate"]} for w in windows]
    ic_record = {
        "ticker": asset_name, "folds": fold_data,
        "mean_ic": round(float(sum(w["directional"] for w in windows) / len(windows)), 4),
        "positive_folds": sum(1 for w in windows if w["directional"] > 0), "total_folds": len(windows),
    }
    with open(OUTPUT_DIR / _tag_path(f"{asset_name}_fold_ic.json", tag), "w") as f:
        json.dump(ic_record, f, indent=2)
    
    if all_oos_signals:
        signals_df = pd.concat(all_oos_signals)
        signals_path = OUTPUT_DIR / _tag_path(f"{asset_name}_wf_signals.parquet", tag)
        signals_df.to_parquet(signals_path)
        logger.info(f"  signals -> {signals_path}")
    
    return summary


def main():
    logger.info("=" * 60)
    logger.info("Expanded walk-forward backtest (10+ year cached data)")
    logger.info("=" * 60)
    
    from paper_trading.config_manager import get_config
    cfg = get_config()
    
    all_summaries = []
    btc_pt_sl = (2.5, 3.0)
    
    for name, ticker in ASSETS.items():
        if ticker == "BTC-USD":
            pt_sl = btc_pt_sl
        else:
            acfg = cfg.assets.get(name, {})
            tp = float(acfg.get("tp_mult", 2.0))
            sl = float(acfg.get("sl_mult", 2.0))
            pt_sl = (tp, sl)
        md = int(cfg.assets.get(name, {}).get("max_depth", 2))
        
        try:
            result = run_asset(name, ticker, pt_sl, max_depth=md,
                               window_years=5, step_years=2, n_folds=5,
                               tag="expanded_10yr")
        except Exception as e:
            logger.error(f"{name}: FAILED — {e}", exc_info=True)
            continue
        
        if result is not None:
            all_summaries.append(result)
    
    if all_summaries:
        combined = pd.concat(all_summaries)
        combined_path = OUTPUT_DIR / _tag_path("all_assets_wf_summary.csv", "expanded_10yr")
        combined.to_csv(combined_path, index=False)
        logger.info(f"\nCombined summary -> {combined_path}")
        
        print("\n=== Cross-Asset Walk-Forward Summary (10yr Expanded) ===")
        metrics = ["hit_rate", "directional", "long_rate", "short_rate", "flat_rate"]
        avg = combined.groupby("asset")[metrics].mean()
        print(avg.to_string(float_format="%.3f"))
    
    logger.info("\nDone. Now run: PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_directional_skill.py --tag expanded_10yr --save")


if __name__ == "__main__":
    main()
