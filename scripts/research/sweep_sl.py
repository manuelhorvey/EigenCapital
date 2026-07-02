#!/usr/bin/env python3
"""Pass 2: SL sweep on top candidates at optimal TP/depth (walk-forward 3yr)."""

import json
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

import xgboost as xgb  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from backtests import compute_per_fold_labels  # noqa: E402
from backtests.trade_analysis import _signals, _simulate, aggregate, fetch_ohlcv, load_macro  # noqa: E402
from features.builder import build_features  # noqa: E402
from features.registry import FEATURE_REGISTRY  # noqa: E402
from shared.volatility import compute_atr_pct  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

CANDIDATES = [
    ("AUDUSD", "AUDUSD=X", 2.5, 3),
    ("EURAUD", "EURAUD=X", 3.0, 4),
    ("EURNZD", "EURNZD=X", 1.0, 3),
    ("NZDUSD", "NZDUSD=X", 1.5, 5),
    ("EURUSD", "EURUSD=X", 1.5, 3),
]

SL_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0]
MIN_TRADES = 20


def run_3yr_sl(asset_name, ticker, slm, tpm, depth, contract):
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
    regime = (
        atr_pct.fillna(0.5).apply(lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")).astype(str)
    )

    all_trades = []
    for ty in range(2023, 2026):
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train_mask = X.index < cut
        test_mask = (X.index >= cut) & (X.index <= eoy)
        if test_mask.sum() < 20:
            continue

        X_tr = X[train_mask]
        y_tr, y_te = compute_per_fold_labels(close, train_mask, test_mask, contract)
        X_te = X[test_mask]

        if len(X_tr) < 200:
            continue
        uq = set(y_tr.unique())
        if uq != {0, 1, 2}:
            continue

        mc = y_tr.value_counts().min()
        strat = y_tr if mc >= 2 else None
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat)

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=depth,
            learning_rate=0.02,
            objective="multi:softprob",
            num_class=3,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
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

    for name, ticker, best_tp, best_depth in CANDIDATES:
        contract = FEATURE_REGISTRY.get(ticker)
        if contract is None:
            print(f"SKIP {name}: no contract", flush=True)
            continue

        print(f"\n{'=' * 60}", flush=True)
        print(f"{name} ({ticker}) — TP={best_tp}, depth={best_depth}, SL sweep", flush=True)
        print(f"{'=' * 60}", flush=True)

        asset_results = []
        for sl in SL_VALUES:
            agg = run_3yr_sl(name, ticker, sl, best_tp, best_depth, contract)
            if agg is None:
                print(f"  SL={sl:.1f}: NO TRADES / FAILED", flush=True)
                continue

            o = agg.get("overall", {})
            pf = o.get("profit_factor", 0)
            ar = o.get("avg_r", 0)
            n = agg["n_trades"]
            marker = " <<<" if pf > 1.2 else ""
            asset_results.append({"sl": sl, "pf": round(pf, 3), "avg_r": round(ar, 4), "n": n})
            print(f"  SL={sl:.1f}: PF={pf:.3f} avgR={ar:+.4f} n={n}{marker}", flush=True)

        best = max(asset_results, key=lambda x: x["pf"]) if asset_results else None
        if best:
            results.append(
                {
                    "asset": name,
                    "ticker": ticker,
                    "best_pf": best["pf"],
                    "best_avg_r": best["avg_r"],
                    "best_tp": best_tp,
                    "best_depth": best_depth,
                    "best_sl": best["sl"],
                    "n_trades": best["n"],
                    "all_sl_sweep": asset_results,
                }
            )
            print(
                f"\n  >> BEST: {name}: SL={best['sl']:.1f} -> PF={best['pf']:.3f} avgR={best['avg_r']:+.4f} n={best['n']}",  # noqa: E501
                flush=True,
            )  # noqa: E501

    print(f"\n{'=' * 60}", flush=True)
    print("SL SWEEP SUMMARY", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"{'Asset':10s} {'PF':>8s} {'avgR':>8s} {'TP':>5s} {'Depth':>6s} {'SL':>5s} {'Trades':>7s}", flush=True)
    print("-" * 55, flush=True)
    for r in sorted(results, key=lambda x: -x["best_pf"]):
        print(
            f"{r['asset']:10s} {r['best_pf']:>8.3f} {r['best_avg_r']:>+8.4f} {r['best_tp']:>5.1f} {r['best_depth']:>6d} {r['best_sl']:>5.1f} {r['n_trades']:>7d}",  # noqa: E501
            flush=True,
        )  # noqa: E501

    out_path = os.path.join(BASE_DIR, "candidate_sl_sweep_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
