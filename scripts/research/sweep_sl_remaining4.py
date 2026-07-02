#!/usr/bin/env python3
"""SL sweep for remaining 4 filter survivors: EURCHF, EURCAD, EURNZD, GBPCHF."""
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
from features.registry import FEATURE_REGISTRY
from shared.volatility import compute_atr_pct

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()
MIN_TRADES = 10
SL_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

ASSETS = [
    ("EURCHF=X", "EURCHF", 3.0, 4),
    ("EURCAD=X", "EURCAD", 1.0, 3),
    ("EURNZD=X", "EURNZD", 2.5, 3),
    ("GBPCHF=X", "GBPCHF", 2.0, 2),
]


def run_asset(ticker, name, sl, tp, depth):
    contract = FEATURE_REGISTRY[ticker]
    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, contract, compute_labels=False)
    if fdf is None or fdf.empty:
        return None

    X = fdf[[c for c in contract.features if c in fdf.columns]]

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
        X_tr = X[train]; y_tr, y_te = compute_per_fold_labels(close, train, test, contract)
        X_te = X[test]
        if len(X_tr) < 200 or set(y_tr.unique()) != {0, 1, 2}:
            continue
        mc = y_tr.value_counts().min()
        strat = y_tr if mc >= 2 else None
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(
            X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat)
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
    return {"pf": o.get("profit_factor", 0), "avg_r": o.get("avg_r", 0), "n": agg["n_trades"]}


def main():
    for ticker, name, tp, depth in ASSETS:
        print(f"\n{'='*65}", flush=True)
        print(f"=== {name} TP={tp} depth={depth} ===", flush=True)
        print(f"{'='*65}", flush=True)
        print(f"{'SL':>5s} {'PF':>8s} {'avgR':>8s} {'Trades':>7s}", flush=True)
        print("-" * 35, flush=True)

        best = None
        for sl in SL_RANGE:
            r = run_asset(ticker, name, sl, tp, depth)
            if r is None:
                print(f"{sl:>5.1f} NO TRADES", flush=True)
                continue
            marker = ""
            if best is None or r["pf"] > best["pf"]:
                best = {"sl": sl, **r}
                marker = " <<<"
            print(f"{sl:>5.1f} {r['pf']:>8.3f} {r['avg_r']:>+8.4f} {r['n']:>7d}{marker}", flush=True)

        if best:
            print(f"  Best: SL={best['sl']:.1f} PF={best['pf']:.3f} avgR={best['avg_r']:+.4f} n={best['n']}", flush=True)


if __name__ == "__main__":
    main()
