"""
Check 5: Feature attribution via permutation importance.
Trains models on full data for 4 representative assets, computes
permutation importance, flags features linked to label construction.
"""

import json
import logging
import sys
from pathlib import Path
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, Path(__file__).resolve().parent.parent.parent)
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check5_features")

OUTPUT_DIR = Path("data/processed")
DATA_DIR = Path("data/yfinance_10yr")

ASSETS = {
    "USDCAD": (3.90, 1.30),  # Tier A - most stable
    "NZDCHF": (4.0, 1.0),    # Tier C - WR decay
    "CADCHF": (4.0, 1.0),    # Tier A - permanent SELL_ONLY
    "AUDJPY": (2.01, 0.52),  # Tier C - single fold
}


def slugify(ticker):
    return ticker.replace("=X", "").replace("=F", "").replace("-", "").replace("=", "")


def fetch_and_train(asset_name, pt_sl, max_depth=4):
    from features.alpha_features import build_alpha_features
    from features.data_fetch import _normalize_index, _fetch_macro_batch, CURRENCY_YIELD_TICKERS, _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS
    from labels.triple_barrier import apply_triple_barrier
    import xgboost as xgb

    ohlcv_path = DATA_DIR / f"{asset_name}_ohlcv.parquet"
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

    common = prices.index
    for s in [dxy, vix, spx]:
        if not s.empty:
            common = common.intersection(s.index)
    if not wti.empty:
        common = common.intersection(wti.dropna().index)

    prices = prices.loc[common]
    ohlcv = ohlcv.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)

    asset_upper = asset_name.upper()
    base_ccy, quote_ccy = None, None
    if asset_upper not in _ZERO_RATE_ASSETS and len(asset_upper) == 6 \
       and asset_upper[:3] in _KNOWN_CURRENCIES and asset_upper[3:] in _KNOWN_CURRENCIES:
        base_ccy, quote_ccy = asset_upper[:3], asset_upper[3:]
    if base_ccy and quote_ccy:
        base_y = macro.get(CURRENCY_YIELD_TICKERS[base_ccy], macro.get("^TNX", pd.Series(0.0, index=common)))
        quote_y = macro.get(CURRENCY_YIELD_TICKERS[quote_ccy], macro.get("^TNX", pd.Series(0.0, index=common)))
        rate_diff = base_y.reindex(common).ffill() - quote_y.reindex(common).ffill()
    else:
        rate_diff = pd.Series(0.0, index=common)
    rate_diffs = pd.DataFrame({asset_name: rate_diff}, index=common)

    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx,
                                    commodities=wti.to_frame("WTI"), ohlcv=ohlcv)

    labels = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=20)["label"].fillna(0).astype(int)
    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()

    # Binary labels
    y = alpha_df["label"].astype(int)
    mask = y != 0
    y_binary = y[mask].map({-1: 0, 1: 1})
    X = alpha_df.loc[y_binary.index]
    feature_cols = [c for c in X.columns if c != "label"]

    logger.info(f"{asset_name}: {len(X)} training rows, {len(feature_cols)} features")

    n0 = int((y_binary == 0).sum())
    n1 = int((y_binary == 1).sum())
    imbalance = n0 / max(n1, 1)

    # Train
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=max_depth, learning_rate=0.02,
        objective="binary:logistic", scale_pos_weight=imbalance,
        random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
    )
    model.fit(X[feature_cols], y_binary, verbose=False)

    # Permutation importance: for each feature, permute and measure WR drop
    importances = {}
    y_pred_default = (model.predict_proba(X[feature_cols])[:, 1] > 0.55).astype(int)
    wr_default = (y_pred_default == y_binary.values).mean()

    for feat in feature_cols:
        X_perm = X[feature_cols].copy()
        X_perm[feat] = np.random.permutation(X_perm[feat].values)
        y_pred_perm = (model.predict_proba(X_perm)[:, 1] > 0.55).astype(int)
        wr_perm = (y_pred_perm == y_binary.values).mean()
        importances[feat] = round(float(wr_default - wr_perm), 4)

    sorted_feats = sorted(importances.items(), key=lambda x: -abs(x[1]))
    
    return model, sorted_feats, feature_cols


def main():
    results = {}
    for asset, pt_sl in ASSETS.items():
        logger.info(f"\n=== {asset} feature attribution ===")
        try:
            model, importances, all_feats = fetch_and_train(asset, pt_sl, max_depth=4)
        except Exception as e:
            logger.error(f"{asset} FAILED: {e}")
            results[asset] = {"error": str(e)}
            continue

        top10 = [{"feature": f, "importance": imp} for f, imp in importances[:10]]
        bottom5 = [{"feature": f, "importance": imp} for f, imp in importances[-5:]]

        # Flag features that could be label-leakage
        label_leakage_candidates = []
        for feat, imp in importances:
            feat_upper = feat.upper()
            if any(kw in feat_upper for kw in ["VOL", "ATR", "BARR", "ZSCORE"]):
                label_leakage_candidates.append({"feature": feat, "importance": imp})

        results[asset] = {
            "pt_sl": list(pt_sl),
            "n_features": len(all_feats),
            "top_10_features": top10,
            "bottom_5_features": bottom5,
            "label_leakage_candidates": label_leakage_candidates[:10],
        }

        print(f"\n{asset} (tp={pt_sl[0]}, sl={pt_sl[1]}):")
        print(f"  {'Feature':>25} | {'Importance'}")
        print(f"  " + "-" * 40)
        for f in top10:
            print(f"  {f['feature']:>25} | {f['importance']:>+8.4f}")

    out_path = OUTPUT_DIR / "check5_feature_attribution.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
