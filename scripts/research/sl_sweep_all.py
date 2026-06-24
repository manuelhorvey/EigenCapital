#!/usr/bin/env python3
"""Systematic SL sweep for all assets. Finds optimal SL multiplier per asset.

Usage:
    python -m backtests.sl_sweep_all
    python -m backtests.sl_sweep_all --dashboard-only
"""

import json
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.registry import FEATURE_REGISTRY
from backtests import compute_per_fold_labels
from backtests.trade_analysis import fetch_ohlcv, load_macro, _signals, _simulate, SLTP_CFG, DEF_SL, DEF_TP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quantforge.sl_sweep")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 18 dashboard assets from paper_trading.yaml
DASHBOARD_TICKERS = [
    "GC=F", "CHFJPY=X", "CADJPY=X", "USDCHF=X", "EURCAD=X",
    "AUDCHF=X", "USDJPY=X", "USDCAD=X", "GBPCHF=X", "ES=F",
    "NQ=F", "AUDNZD=X", "CADCHF=X", "CL=F", "GBPCAD=X",
    "GBPNZD=X", "NZDCAD=X", "^DJI",
]

YEARS = 3
SL_VALUES = [round(0.5 + i * 0.25, 2) for i in range(11)]  # 0.5 to 3.0


def backtest_with_sl(ticker: str, macro: pd.DataFrame, ref: pd.DataFrame | None,
                     sl_mult: float, years: int = 3) -> list[dict]:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from features.builder import build_features
    from backtests import compute_per_fold_labels

    contract = FEATURE_REGISTRY.get(ticker)
    if not contract:
        return []
    name = contract.name
    df = fetch_ohlcv(ticker)
    if len(df) < 200:
        return []
    try:
        fdf = build_features(df, macro, ref, contract, compute_labels=False)
    except Exception:
        return []
    X = fdf[list(contract.features)]
    close, high, low = [c.reindex(X.index).ffill() for c in [df["close"], df["high"], df["low"]]]
    if len(X) < 200:
        return []
    from shared.volatility import compute_atr_pct
    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    now = pd.Timestamp.now()
    test_years = sorted(set(y for y in range(now.year - years, now.year) if y >= 2016))
    tp_mult = SLTP_CFG.get(name, {}).get("tp", DEF_TP)
    all_trades = []
    for ty in test_years:
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train, test = X.index < cut, (X.index >= cut) & (X.index <= eoy)
        if test.sum() < 20:
            continue
        X_tr = X[train]
        y_tr, y_te = compute_per_fold_labels(close, train, test, contract)
        X_te = X[test]
        if len(X_tr) < 200 or set(y_tr.unique()) != {0, 1, 2}:
            continue
        mc = y_tr.value_counts().min()
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(X_tr, y_tr, test_size=0.2, random_state=42,
                                                     stratify=y_tr if mc >= 2 else None)
        if set(y_tr2.unique()) != {0, 1, 2}:
            continue
        model = xgb.XGBClassifier(n_estimators=300, max_depth=2, learning_rate=0.02,
                                   objective="multi:softprob", num_class=3, random_state=42,
                                   n_jobs=1, tree_method="hist", verbosity=0)
        model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
        proba = model.predict_proba(X_te)
        sigs = _signals(proba, X_te.index)
        tr = _simulate(sigs, close.reindex(X_te.index), high.reindex(X_te.index),
                       low.reindex(X_te.index), name, sl_mult, tp_mult, atr)
        all_trades.extend(tr)
    return all_trades


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n_trades": 0}
    df = pd.DataFrame(trades)
    ret = df["return"]
    r = df["r_multiple"]
    return {
        "n_trades": len(df),
        "win_rate": float((ret > 0).mean()),
        "loss_rate": float((ret < 0).mean()),
        "tp_rate": float((df["exit_reason"] == "tp").mean()),
        "sl_rate": float((df["exit_reason"] == "sl").mean()),
        "flip_rate": float((df["exit_reason"] == "signal_flip").mean()),
        "avg_return": float(ret.mean()),
        "avg_r": float(r.mean()),
        "median_r": float(r.median()),
        "profit_factor": float(ret[ret > 0].sum() / abs(ret[ret < 0].sum() + 1e-9)),
    }


def main(dashboard_only: bool = False):
    assets = DASHBOARD_TICKERS if dashboard_only else list(FEATURE_REGISTRY.keys())

    print(f"\n{'='*100}")
    print(f"  SYSTEMATIC SL SWEEP — ALL {len(assets)} ASSETS")
    print(f"{'='*100}")
    print(f"  Sweep range: 0.50 \u2192 3.00  step=0.25  ({len(SL_VALUES)} values)")
    print(f"  Walk-forward: {YEARS} years")
    print()

    macro = load_macro()
    ref = fetch_ohlcv("SPY", 15)

    all_results = {}

    for ticker in assets:
        contract = FEATURE_REGISTRY.get(ticker)
        if not contract:
            continue
        name = contract.name
        current_sl = SLTP_CFG.get(name, {}).get("sl", DEF_SL)
        print(f"  {name:8s} (SL={current_sl:.2f}) — ...", end="", flush=True)

        r = ref if contract.requires_ref else None
        results = []

        for sl in SL_VALUES:
            trades = backtest_with_sl(ticker, macro, r, sl, YEARS)
            m = compute_metrics(trades)
            m["sl_mult"] = sl
            results.append(m)

        all_results[name] = results

        valid = [r for r in results if r["n_trades"] >= 10]
        if not valid:
            print("  (insufficient data)", flush=True)
            continue
        best_pf = max(valid, key=lambda x: x["profit_factor"])
        cur = min(results, key=lambda r: abs(r["sl_mult"] - current_sl))
        impr = best_pf["profit_factor"] - cur["profit_factor"]
        mark = " ★" if impr > 0.02 else ""
        print(f"  cur PF={cur['profit_factor']:.3f}  \u2192  best SL={best_pf['sl_mult']:.2f} "
              f"(PF={best_pf['profit_factor']:.3f}, win={best_pf['win_rate']:.1%}){mark}", flush=True)

    # Summary table
    print(f"\n{'='*100}")
    print(f"  SUMMARY — BEST SL PER ASSET")
    print(f"{'='*100}")
    header = f"  {'Asset':8s} {'CurrentSL':>10s} {'BestPF':>7s} {'BestWin':>8s} {'BestR':>7s} {'CurPF':>7s} {'CurWin':>7s} {'CurR':>6s} {'Trades':>7s} {'Improv?':>7s}"
    print(header)
    print("  " + "-" * len(header))
    rows = []
    for name in sorted(all_results.keys()):
        results = all_results[name]
        valid = [r for r in results if r["n_trades"] >= 10]
        if not valid:
            continue
        best = max(valid, key=lambda x: x["profit_factor"])
        current_sl = SLTP_CFG.get(name, {}).get("sl", DEF_SL)
        cur = min(results, key=lambda r: abs(r["sl_mult"] - current_sl))
        impr = best["profit_factor"] - cur["profit_factor"]
        mark = " ★" if abs(impr) > 0.02 else ""
        rows.append((impr, name, current_sl, best["sl_mult"], cur["profit_factor"],
                     best["profit_factor"], best["win_rate"], best["avg_r"], best["n_trades"], mark))

    for row in sorted(rows, key=lambda x: x[4], reverse=True):
        impr, name, cur_sl, best_sl, cur_pf, best_pf, win, r_val, n, mark = row
        print(f"  {name:8s}  SL {cur_sl:.2f} \u2192 {best_sl:.2f}  "
              f"PF {cur_pf:.3f} \u2192 {best_pf:.3f}  win {win:.1%}  R {r_val:+.3f}  ({n} trades){mark}")

    top = sorted([r for r in rows if r[0] > 0.02], key=lambda x: x[0], reverse=True)
    print(f"\n  ---")
    print(f"  Assets with meaningful improvement (PF +>0.02):")
    for row in top:
        impr, name, cur_sl, best_sl, cur_pf, best_pf, win, r_val, n, _ = row
        print(f"    {name:8s}: SL {cur_sl:.2f} \u2192 {best_sl:.2f}  (PF {cur_pf:.3f} \u2192 {best_pf:.3f}, +{impr:.3f})")

    out = os.path.join(BASE, "data", "live", "sl_sweep_all.json")
    with open(out, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "sweep": {k: v for k, v in all_results.items()}}, f, indent=2)
    print(f"\n  Saved to {out}")
    print()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dashboard-only", action="store_true", help="Only sweep 18 dashboard assets")
    a = p.parse_args()
    main(a.dashboard_only)
