#!/usr/bin/env python3
"""Feature set sweeps for the top 5 filter survivors (correct data alignment)."""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

from backtests import compute_per_fold_labels
from backtests.trade_analysis import _signals, _simulate, aggregate, fetch_ohlcv, load_macro
from features.builder import build_features
from features.registry import ASSET_LABEL_PARAMS, FeatureContract
from shared.volatility import compute_atr_pct

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()
MIN_TRADES = 10

ASSETS = [
    {"ticker": "GBPAUD=X", "name": "GBPAUD", "tp": 2.0, "sl": 1.0, "depth": 2},
    {"ticker": "NZDCHF=X", "name": "NZDCHF", "tp": 4.0, "sl": 1.0, "depth": 2},
    {"ticker": "CADCHF=X", "name": "CADCHF", "tp": 4.0, "sl": 1.0, "depth": 2},
    {"ticker": "AUDUSD=X", "name": "AUDUSD", "tp": 4.0, "sl": 1.5, "depth": 2},
    {"ticker": "AUDNZD=X", "name": "AUDNZD", "tp": 1.0, "sl": 2.0, "depth": 2},
]

GBPAUD_VARIANTS = {
    "baseline":              {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+mom126":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63,126), "custom": ()},
    "+real_yield_delta":     {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","real_yield_delta_63"), "mom": (21,63), "custom": ()},
    "+breakeven_delta":      {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","breakeven_delta_63"), "mom": (21,63), "custom": ()},
    "+yield_slope":          {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","yield_slope"), "mom": (21,63), "custom": ()},
    "+rate_diff_delta":      {"macro": ("rate_diff","rate_diff_delta_3m","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+de_10y":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","de_10y"), "mom": (21,63), "custom": ()},
}

NZDCHF_VARIANTS = {
    "baseline":              {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+mom126":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63,126), "custom": ()},
    "+real_yield_delta":     {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","real_yield_delta_63"), "mom": (21,63), "custom": ()},
    "+breakeven_delta":      {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","breakeven_delta_63"), "mom": (21,63), "custom": ()},
    "+yield_slope":          {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","yield_slope"), "mom": (21,63), "custom": ()},
    "+rate_diff_delta":      {"macro": ("rate_diff","rate_diff_delta_3m","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
}

CADCHF_VARIANTS = {
    "baseline":              {"macro": ("ca_jp_spread_mom_21","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+rate_diff":            {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},  # replace ca_jp_spread
    "+rate_diff_delta":      {"macro": ("rate_diff","rate_diff_delta_3m","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+real_yield_delta":     {"macro": ("ca_jp_spread_mom_21","dxy_mom_21","vix_ma21","vix_delta_5","real_yield_delta_63"), "mom": (21,63), "custom": ()},
    "+breakeven_delta":      {"macro": ("ca_jp_spread_mom_21","dxy_mom_21","vix_ma21","vix_delta_5","breakeven_delta_63"), "mom": (21,63), "custom": ()},
    "+yield_slope":          {"macro": ("ca_jp_spread_mom_21","dxy_mom_21","vix_ma21","vix_delta_5","yield_slope"), "mom": (21,63), "custom": ()},
    "+mom126":               {"macro": ("ca_jp_spread_mom_21","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63,126), "custom": ()},
}

AUDUSD_VARIANTS = {
    "baseline":              {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+mom126":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63,126), "custom": ()},
    "+real_yield_delta":     {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","real_yield_delta_63"), "mom": (21,63), "custom": ()},
    "+breakeven_delta":      {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","breakeven_delta_63"), "mom": (21,63), "custom": ()},
    "+yield_slope":          {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","yield_slope"), "mom": (21,63), "custom": ()},
    "+rate_diff_delta":      {"macro": ("rate_diff","rate_diff_delta_3m","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+de_10y":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","de_10y"), "mom": (21,63), "custom": ()},
}

AUDNZD_VARIANTS = {
    "baseline":              {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
    "+mom126":               {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63,126), "custom": ()},
    "+real_yield_delta":     {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","real_yield_delta_63"), "mom": (21,63), "custom": ()},
    "+breakeven_delta":      {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","breakeven_delta_63"), "mom": (21,63), "custom": ()},
    "+yield_slope":          {"macro": ("rate_diff","dxy_mom_21","vix_ma21","vix_delta_5","yield_slope"), "mom": (21,63), "custom": ()},
    "+rate_diff_delta":      {"macro": ("rate_diff","rate_diff_delta_3m","dxy_mom_21","vix_ma21","vix_delta_5"), "mom": (21,63), "custom": ()},
}

VARIANT_MAP = {
    "GBPAUD=X": GBPAUD_VARIANTS,
    "NZDCHF=X": NZDCHF_VARIANTS,
    "CADCHF=X": CADCHF_VARIANTS,
    "AUDUSD=X": AUDUSD_VARIANTS,
    "AUDNZD=X": AUDNZD_VARIANTS,
}


def run_asset(ticker, name, sl, tp, depth, label_params, variant):
    vc = FeatureContract(
        ticker=ticker, name=name,
        contract_prefix=ticker.lower().replace("=", "").replace("^", ""),
        label_type="tb20",
        label_params={"pt_sl": [label_params["pt"], label_params["sl"]], "vertical_barrier": 20},
        macro_filters=variant["macro"],
        price_mom_windows=variant["mom"],
        vs_spy_windows=(),
        custom_features=variant["custom"],
    )

    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, vc, compute_labels=False)
    if fdf is None or fdf.empty:
        return None

    feat = [c for c in vc.features if c in fdf.columns]
    X = fdf[feat]
    close = df["close"].reindex(X.index)
    high = df["high"].reindex(X.index)
    low = df["low"].reindex(X.index)

    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    atr_r = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
    regime = atr_r.fillna(0.5).apply(
        lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")
    ).astype(str)

    all_trades = []
    for ty in range(2023, 2026):
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train = X.index < cut
        test = (X.index >= cut) & (X.index <= eoy)
        if test.sum() < 20:
            continue
        X_tr = X[train]
        X_te = X[test]
        y_tr, y_te = compute_per_fold_labels(close, train, test, vc)
        if len(X_tr) < 200 or set(y_tr.unique()) != {0, 1, 2}:
            continue
        mc = y_tr.value_counts().min()
        strat = y_tr if mc >= 2 else None
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat)
        if set(y_tr2.unique()) != {0, 1, 2}:
            continue
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=depth, learning_rate=0.02,
            objective="multi:softprob", num_class=3, random_state=42,
            n_jobs=1, tree_method="hist", verbosity=0)
        model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
        proba = model.predict_proba(X_te)
        sigs = _signals(proba, X_te.index)
        tr = _simulate(sigs,
                       close.reindex(X_te.index), high.reindex(X_te.index),
                       low.reindex(X_te.index),
                       name, sl, tp, atr, regime)
        all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        return None
    agg = aggregate(all_trades)
    o = agg.get("overall", {})
    return {"pf": o.get("profit_factor", 0), "avg_r": o.get("avg_r", 0), "n": agg["n_trades"], "feat": len(vc.features)}


def main():
    for asset in ASSETS:
        ticker, name, tp, sl, depth = asset["ticker"], asset["name"], asset["tp"], asset["sl"], asset["depth"]
        label_params = ASSET_LABEL_PARAMS.get(name, {"pt": 2.0, "sl": 2.0})
        variants = VARIANT_MAP[ticker]

        print(f"\n{'='*70}", flush=True)
        print(f"=== {name} (TP={tp}, SL={sl}, depth={depth}) ===", flush=True)
        print(f"{'='*70}", flush=True)
        print(f"{'Variant':25s} {'PF':>8s} {'avgR':>8s} {'Trades':>7s} {'Feat':>5s}", flush=True)
        print("-" * 60, flush=True)

        results = []
        best_pf = 0
        for vname, variant in variants.items():
            r = run_asset(ticker, name, sl, tp, depth, label_params, variant)
            if r is None:
                print(f"{vname:25s} FAILED", flush=True)
                continue
            is_best = r["pf"] > best_pf
            if is_best:
                best_pf = r["pf"]
            marker = " <<<" if is_best else ""
            results.append((vname, r))
            print(f"{vname:25s} {r['pf']:>8.3f} {r['avg_r']:>+8.4f} {r['n']:>7d} {r['feat']:>5d}{marker}", flush=True)

        if results:
            print(f"\n--- {name} RANKED ---", flush=True)
            for vname, r in sorted(results, key=lambda x: -x[1]["pf"]):
                print(f"  {vname:25s} PF={r['pf']:.3f} avgR={r['avg_r']:+.4f} n={r['n']}", flush=True)


if __name__ == "__main__":
    main()
