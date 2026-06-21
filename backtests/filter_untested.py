#!/usr/bin/env python3
"""Quick filter — correct version using backtest_asset for data alignment."""
import os, sys, logging, itertools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from features.registry import FEATURE_REGISTRY, ASSET_LABEL_PARAMS
from features.builder import build_features
from backtests import compute_per_fold_labels

from shared.volatility import compute_atr_pct
from backtests.trade_analysis import fetch_ohlcv, load_macro, _signals, _simulate, aggregate

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

DASHBOARD = {'GC=F','USDCHF=X','AUDCHF=X','USDCAD=X','ES=F','NQ=F',
             'GBPCAD=X','GBPNZD=X','NZDCAD=X','^DJI','EURUSD=X','NZDUSD=X'}

MIN_TRADES = 15
TP_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
DEPTH_RANGE = [2, 3, 4, 5]

SNIFF_TP = 2.0
SNIFF_DEPTH = 3
SNIFF_SL = 2.0


def run_asset(ticker, name, sl, tp, depth, contract):
    """Correct implementation: reindex close/high/low to test year index."""
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
        # FIX: reindex close/high/low to test index for correct .iloc alignment
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
    untested = sorted(t for t in FEATURE_REGISTRY if t not in DASHBOARD)
    print(f"=== STAGE 1: SNIFF (TP={SNIFF_TP}, depth={SNIFF_DEPTH}, SL={SNIFF_SL}) ===", flush=True)
    print(f"Testing {len(untested)} assets", flush=True)

    stage1 = []
    for ticker in untested:
        contract = FEATURE_REGISTRY[ticker]
        name = contract.name
        r = run_asset(ticker, name, SNIFF_SL, SNIFF_TP, SNIFF_DEPTH, contract)
        if r is None:
            print(f"  {name:10s} NO TRADES — discard", flush=True)
            continue
        label = " <<< PASS" if r["pf"] > 1.0 else ""
        print(f"  {name:10s} PF={r['pf']:.3f} avgR={r['avg_r']:+.4f} n={r['n']}{label}", flush=True)
        if r["pf"] > 1.0:
            stage1.append((ticker, contract))

    if not stage1:
        print("\nNo survivors from Stage 1.", flush=True)
        return

    print(f"\n=== STAGE 2: FULL GRID on {len(stage1)} survivors ===", flush=True)
    survivors = []
    for ticker, contract in stage1:
        name = contract.name
        best_pf = 0
        best = None
        for tp, depth in itertools.product(TP_RANGE, DEPTH_RANGE):
            r = run_asset(ticker, name, SNIFF_SL, tp, depth, contract)
            if r is None:
                continue
            if r["pf"] > best_pf:
                best_pf = r["pf"]
                best = {"name": name, "ticker": ticker, "tp": tp, "depth": depth,
                        "sl": SNIFF_SL, "pf": r["pf"], "avg_r": r["avg_r"], "n": r["n"]}

        if best:
            survivors.append(best)
            flag = " <<< VIABLE" if best_pf > 1.2 else ""
            print(f"  {name:10s} best: PF={best_pf:.3f} avgR={best['avg_r']:+.4f} "
                  f"TP={best['tp']:.1f} depth={best['depth']} n={best['n']}{flag}", flush=True)

    print(f"\n{'='*65}", flush=True)
    print(f"SURVIVORS (PF > 1.2): {len([s for s in survivors if s['pf'] > 1.2])}", flush=True)
    for s in sorted(survivors, key=lambda x: -x["pf"]):
        if s["pf"] > 1.2:
            print(f"  {s['name']:10s} PF={s['pf']:.3f} avgR={s['avg_r']:+.4f} "
                  f"TP={s['tp']:.1f} depth={s['depth']} SL={s['sl']:.1f} n={s['n']}", flush=True)


if __name__ == "__main__":
    main()
