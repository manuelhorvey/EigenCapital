"""
Check 4: Barrier sensitivity curve.
Run walk-forward at multiple TP/SL ratios on 4 representative assets.
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, Path(__file__).resolve().parent.parent.parent)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check4_barrier_sensitivity")

WALKFORWARD_DIR = Path("scripts/walkforward")
DATA_DIR = Path("data/yfinance_10yr")

# 2 representative assets
ASSETS = {
    "USDCAD": (3.90, 1.30),  # Tier A - most stable multi-fold
    "NZDCHF": (4.0, 1.0),    # Tier C - clear WR decay
}

# Intermediate barrier ratios (tp, sl)
# Endpoints (4.0,1.0) and (2.0,2.0) already exist from expanded_10yr + symmetric_labels runs
BARRIER_RATIOS = [
    (3.5, 1.0),
    (3.0, 1.0),
    (2.5, 1.0),
    (2.0, 1.0),
    (3.0, 1.5),
]


def slugify(ticker):
    return ticker.replace("=X", "").replace("=F", "").replace("-", "").replace("=", "")


def fetch_data(asset_name):
    from features.alpha_features import build_alpha_features
    from features.data_fetch import _normalize_index, _fetch_macro_batch, CURRENCY_YIELD_TICKERS, _KNOWN_CURRENCIES, _ZERO_RATE_ASSETS

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
            idx = s.index
            common = common.intersection(idx)
    if not wti.empty:
        idx = wti.dropna().index
        common = common.intersection(idx)

    prices = prices.loc[common]
    ohlcv = ohlcv.loc[common]
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)

    # Rate diffs
    asset_upper = asset_name.upper()
    base_ccy = quote_ccy = None
    if asset_upper not in _ZERO_RATE_ASSETS and len(asset_upper) == 6 \
       and asset_upper[:3] in _KNOWN_CURRENCIES and asset_upper[3:] in _KNOWN_CURRENCIES:
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]

    if base_ccy and quote_ccy:
        base_ticker = CURRENCY_YIELD_TICKERS[base_ccy]
        quote_ticker = CURRENCY_YIELD_TICKERS[quote_ccy]
        base_yield = macro.get(base_ticker, macro.get("^TNX", pd.Series(0.0, index=common)))
        quote_yield = macro.get(quote_ticker, macro.get("^TNX", pd.Series(0.0, index=common)))
        rate_diff = base_yield.reindex(common).ffill() - quote_yield.reindex(common).ffill()
    else:
        rate_diff = pd.Series(0.0, index=common)

    rate_diffs = pd.DataFrame({asset_name: rate_diff}, index=common)

    alpha_df = build_alpha_features(prices, rate_diffs, dxy=dxy, vix=vix, spx=spx,
                                    commodities=wti.to_frame("WTI"), ohlcv=ohlcv)
    return prices, alpha_df, ohlcv


def compute_labels(ohlcv, pt_sl, vertical_barrier=20):
    from labels.triple_barrier import apply_triple_barrier
    labeled = apply_triple_barrier(ohlcv, pt_sl=list(pt_sl), vertical_barrier=vertical_barrier)
    return labeled["label"].fillna(0).astype(int)


def _to_binary(y):
    y_int = y.astype(int)
    mask = y_int != 0
    return y_int[mask].map({-1: 0, 1: 1})


def run_walkforward(asset_name, pt_sl, max_depth=2, tag_suffix=""):
    import xgboost as xgb
    from labels.compat import PurgedWalkForwardFolds

    tag = f"barrier_{pt_sl[0]}x{pt_sl[1]}{tag_suffix}"

    prices, alpha_df, ohlcv = fetch_data(asset_name)

    labels = compute_labels(ohlcv, pt_sl, vertical_barrier=20)
    alpha_df["label"] = labels.reindex(alpha_df.index).fillna(0).astype(int)
    alpha_df = alpha_df.dropna()

    if len(alpha_df) < 300:
        logger.warning(f"{asset_name} @ {pt_sl}: insufficient rows ({len(alpha_df)})")
        return None

    y_all = _to_binary(alpha_df["label"])
    if len(y_all) < 100 or y_all.nunique() < 2:
        logger.warning(f"{asset_name} @ {pt_sl}: insufficient binary samples ({len(y_all)})")
        return None

    X_all = alpha_df.loc[y_all.index]
    feature_cols = [c for c in X_all.columns if c != "label"]

    n0 = int((y_all == 0).sum())
    n1 = int((y_all == 1).sum())
    logger.info(f"  {asset_name} @ tp={pt_sl[0]} sl={pt_sl[1]}: "
                f"labels 0={n0} 1={n1} ratio={n0/max(n1,1):.2f}, features={len(feature_cols)}")

    cv = PurgedWalkForwardFolds(
        n_folds=5, gap=20, min_train=100,
        window_type="expanding", rolling_window_bars=5 * 252,
    )

    windows = []
    all_oos_signals = []
    hi_thresh = 0.5 + 0.15 / 2.0
    lo_thresh = 0.5 - 0.15 / 2.0

    for fold, (train_idx, test_idx) in enumerate(cv.split(X_all)):
        X_tr = X_all.iloc[train_idx]
        y_tr = y_all.iloc[train_idx]
        X_te = X_all.iloc[test_idx]
        y_te = y_all.iloc[test_idx]

        if y_tr.nunique() < 2:
            continue

        n0_tr = int((y_tr == 0).sum())
        n1_tr = int((y_tr == 1).sum())
        imbalance = n0_tr / max(n1_tr, 1)

        n_tr = len(X_tr)
        n_val = max(int(n_tr * 0.2), 1)
        val_start = n_tr - n_val - 20
        use_es = val_start >= 50
        if use_es:
            X_fit = X_tr.iloc[:val_start]
            y_fit = y_tr.iloc[:val_start]
            X_val = X_tr.iloc[val_start + 20:]
            y_val = y_tr.iloc[val_start + 20:]
            eset = [(X_val[feature_cols], y_val)]
        else:
            X_fit = X_tr
            y_fit = y_tr
            eset = None

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=max_depth, learning_rate=0.02,
            objective="binary:logistic", scale_pos_weight=imbalance,
            random_state=42, n_jobs=1, tree_method="hist", verbosity=0,
            early_stopping_rounds=50 if eset else None,
        )
        if eset:
            model.fit(X_fit[feature_cols], y_fit, eval_set=eset, verbose=False)
        else:
            model.fit(X_fit[feature_cols], y_fit, verbose=False)

        p_long = model.predict_proba(X_te[feature_cols])[:, 1]
        signals = np.zeros(len(p_long), dtype=int)
        signals[p_long > hi_thresh] = 1
        signals[p_long < lo_thresh] = -1

        label_dir = y_te.values * 2 - 1
        directional = (signals * label_dir).sum() / max((signals != 0).sum(), 1)
        long_rate = (signals == 1).mean()
        short_rate = (signals == -1).mean()
        flat_rate = (signals == 0).mean()

        win = {
            "fold": fold,
            "train_samples": len(X_tr),
            "test_samples": len(X_te),
            "directional": round(float(directional), 4),
            "hit_rate": round(float(directional), 4),
            "long_rate": round(float(long_rate), 4),
            "short_rate": round(float(short_rate), 4),
            "flat_rate": round(float(flat_rate), 4),
        }
        windows.append(win)

        oos = pd.DataFrame({"signal": signals, "label": y_te.values, "p_long": p_long}, index=X_te.index)
        oos["asset"] = asset_name
        all_oos_signals.append(oos)

    if not windows:
        return None

    summary_df = pd.DataFrame(windows)
    return summary_df


def main():
    results = {}
    for asset, (orig_tp, orig_sl) in ASSETS.items():
        logger.info(f"\n=== {asset} barrier sensitivity ===")
        results[asset] = {}
        for tp, sl in BARRIER_RATIOS:
            # Use asset's own config for baseline, fixed ratios otherwise
            fixed_pt_sl = (tp, sl)
            tag = f"barrier_{tp}x{sl}"
            logger.info(f"  Running {asset} @ tp={tp} sl={sl}...")
            try:
                df = run_walkforward(asset, fixed_pt_sl, max_depth=2)
            except Exception as e:
                logger.warning(f"{asset} @ {tp}x{sl} FAILED: {e}")
                continue
            if df is not None:
                agg = df.mean(numeric_only=True).to_dict()
                results[asset][f"{tp}x{sl}"] = {
                    "tp": tp, "sl": sl,
                    "ratio": round(tp / sl, 2),
                    "hit_rate": round(float(agg.get("hit_rate", 0)), 4),
                    "short_rate": round(float(agg.get("short_rate", 0)), 4),
                    "flat_rate": round(float(agg.get("flat_rate", 0)), 4),
                    "long_rate": round(float(agg.get("long_rate", 0)), 4),
                    "n_folds_completed": len(df),
                    "n_sell_trades": int(agg.get("test_samples", 0) * agg.get("short_rate", 0)),
                }
                asym = tp / sl
                logger.info(f"  → hit={agg['hit_rate']:.4f} short={agg['short_rate']:.2%} "
                           f"flat={agg['flat_rate']:.2%}  (asym={asym:.1f})")

    out_path = Path("data/processed") / "check4_barrier_sensitivity.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Saved to {out_path}")

    # Print summary
    print("\n" + "=" * 80)
    print("BARRIER SENSITIVITY CURVE")
    print("=" * 80)
    for asset, ratios in results.items():
        print(f"\n{asset}:")
        print(f"  {'Ratio':>6} | {'Hit rate':>9} | {'nSell':>6} | {'Flat%':>6}")
        print(f"  " + "-" * 35)
        for rkey, rdata in sorted(ratios.items(), key=lambda x: x[1]["ratio"]):
            print(f"  {rdata['ratio']:>5.1f}x | {rdata['hit_rate']:>+9.4f} | {rdata['n_sell_trades']:>6d} | {rdata['flat_rate']:.2%}")


if __name__ == "__main__":
    main()
