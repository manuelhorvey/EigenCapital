#!/usr/bin/env python3
"""Sweep candidate assets for re-promotion potential. Read-only — no prod changes."""

import itertools
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

from backtests import compute_per_fold_labels
from backtests.trade_analysis import _signals, _simulate, aggregate, fetch_ohlcv, load_macro
from features.builder import build_features
from features.registry import FEATURE_REGISTRY
from shared.volatility import compute_atr_pct

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sweeper")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

# Dashboard assets (10): GC, USDCHF, AUDCHF, USDCAD, ES, NQ, GBPCAD, GBPNZD, NZDCAD, ^DJI
# Previously removed failures: AUDNZD, CADCHF, CADJPY, CL, EURCAD, GBPCHF, USDJPY,
#   BTCUSD, EURGBP, EURJPY, NZDCHF, GBPUSD, GBPJPY, GBPAUD, AUDCAD, EURCHF, NZDJPY
# Remaining candidates from the 32-ticker list:
CANDIDATES = ["AUDJPY", "AUDUSD", "EURAUD", "EURNZD", "EURUSD", "NZDUSD"]

TP_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
DEPTH_RANGE = [2, 3, 4, 5]
SL_DEFAULT = 2.0

MIN_TRADES = 20


def run_3yr(asset_name, ticker, slm, tpm, depth, contract):
    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, contract, compute_labels=False)
    if fdf is None or fdf.empty:
        return None

    X = fdf[[c for c in contract.features if c in fdf.columns]]

    close = df["close"].reindex(X.index)
    high = df["high"].reindex(X.index)
    low = df["low"].reindex(X.index)

    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    atr_pct = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
    regime = atr_pct.fillna(0.5).apply(lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")).astype(str)

    all_trades = []
    for ty in range(2023, 2026):
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train_mask = X.index < cut
        test_mask = (X.index >= cut) & (X.index <= eoy)
        if test_mask.sum() < 20:
            continue

        X_tr = X[train_mask]; y_tr, y_te = compute_per_fold_labels(close, train_mask, test_mask, contract)
        X_te = X[test_mask]

        if len(X_tr) < 200:
            continue
        uq = set(y_tr.unique())
        if uq != {0, 1, 2}:
            continue

        mc = y_tr.value_counts().min()
        strat = y_tr if mc >= 2 else None
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(
            X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat
        )

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=depth, learning_rate=0.02,
            objective="multi:softprob", num_class=3, random_state=42,
            n_jobs=1, tree_method="hist", verbosity=0,
        )
        model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
        proba = model.predict_proba(X_te)
        sigs = _signals(proba, X_te.index)
        tr = _simulate(sigs, close, high, low, asset_name, slm, tpm, atr, regime)
        all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        return None

    agg = aggregate(all_trades)
    return agg


def main():
    results = []

    for target_name in CANDIDATES:
        contract = None
        ticker = None
        for t, c in FEATURE_REGISTRY.items():
            if c.name == target_name:
                contract = c
                ticker = t
                break
        if contract is None:
            continue

        print(f"\n{'='*60}", flush=True)
        print(f"{target_name} ({ticker}) — features={contract.features}", flush=True)
        print(f"{'='*60}", flush=True)

        best = {"pf": 0, "tp": 2.0, "depth": 2, "sl": SL_DEFAULT, "avg_r": 0, "n": 0}

        for tpm, depth in itertools.product(TP_RANGE, DEPTH_RANGE):
            agg = run_3yr(target_name, ticker, SL_DEFAULT, tpm, depth, contract)
            if agg is None:
                continue

            o = agg.get("overall", {})
            pf = o.get("profit_factor", 0)
            ar = o.get("avg_r", 0)
            n = agg["n_trades"]

            marker = " <<<" if pf > best["pf"] else ""
            if pf > best["pf"]:
                best = {"pf": pf, "tp": tpm, "depth": depth, "sl": SL_DEFAULT, "avg_r": ar, "n": n}

            print(f"  TP={tpm:3.1f} depth={depth} (SL={SL_DEFAULT:.1f}): PF={pf:.3f} avgR={ar:+.4f} n={n}{marker}", flush=True)

        results.append({
            "asset": target_name,
            "ticker": ticker,
            "best_pf": round(best["pf"], 3),
            "best_avg_r": round(best["avg_r"], 4),
            "best_tp": best["tp"],
            "best_depth": best["depth"],
            "best_sl": best["sl"],
            "n_trades": best["n"],
        })

        print(f"\n  >> BEST: {target_name}: TP={best['tp']} depth={best['depth']} SL={best['sl']:.1f} -> PF={best['pf']:.3f} avgR={best['avg_r']:+.4f} n={best['n']}", flush=True)

    print(f"\n{'='*60}", flush=True)
    print("SUMMARY", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"{'Asset':10s} {'PF':>8s} {'avgR':>8s} {'TP':>5s} {'Depth':>6s} {'SL':>5s} {'Trades':>7s}", flush=True)
    print("-" * 55, flush=True)
    for r in sorted(results, key=lambda x: -x["best_pf"]):
        print(f"{r['asset']:10s} {r['best_pf']:>8.3f} {r['best_avg_r']:>+8.4f} {r['best_tp']:>5.1f} {r['best_depth']:>6d} {r['best_sl']:>5.1f} {r['n_trades']:>7d}", flush=True)

    out_path = os.path.join(BASE_DIR, "candidate_sweep_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
