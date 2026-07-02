#!/usr/bin/env python3
"""SL multiplier sensitivity sweep for problem assets: ES, CL, DJI.

Usage:
    python -m backtests.sl_sensitivity
"""

import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtests import compute_per_fold_labels
from backtests.trade_analysis import _signals, _simulate, fetch_ohlcv, load_macro
from features.registry import FEATURE_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.sl_sensitivity")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SWEEP_TICKERS = ["ES=F", "CL=F", "^DJI"]
TP_MULTIPLIERS = {"ES": 4.69, "CL": 2.00, "DJI": 1.50}
YEARS = 3


def backtest_with_sl(ticker: str, macro: pd.DataFrame, ref: pd.DataFrame | None,
                     sl_mult: float, years: int = 3) -> list[dict]:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split

    from features.builder import build_features

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
    tp_mult = TP_MULTIPLIERS.get(name, 2.0)
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
        "avg_bars_tp": float(df[df["exit_reason"] == "tp"]["bars_held"].mean()) if (df["exit_reason"] == "tp").any() else 0,
        "avg_bars_sl": float(df[df["exit_reason"] == "sl"]["bars_held"].mean()) if (df["exit_reason"] == "sl").any() else 0,
    }


def main():
    print("\n" + "=" * 90)
    print("  SL MULTIPLIER SENSITIVITY SWEEP — ES, CL, DJI")
    print("=" * 90)
    print("  Sweep range: 0.50 → 3.00  step=0.25")
    print(f"  Walk-forward: {YEARS} years")
    print()

    macro = load_macro()
    ref = fetch_ohlcv("SPY", 15)

    sl_values = [round(0.5 + i * 0.25, 2) for i in range(11)]  # 0.5 to 3.0

    all_results = {}

    for ticker in SWEEP_TICKERS:
        contract = FEATURE_REGISTRY.get(ticker)
        name = contract.name if contract else ticker
        print(f"  {name} ({ticker}) — sweeping SL...")
        r = ref if contract and contract.requires_ref else None

        results = []
        for sl in sl_values:
            trades = backtest_with_sl(ticker, macro, r, sl, YEARS)
            m = compute_metrics(trades)
            m["sl_mult"] = sl
            results.append(m)
            print(f"    sl_mult={sl:5.2f}  trades={m['n_trades']:>4d}  "
                  f"win={m['win_rate']:.1%}  avgR={m['avg_r']:>+7.3f}  "
                  f"PF={m['profit_factor']:.3f}  TP={m['tp_rate']:.0%}  SL={m['sl_rate']:.0%}  "
                  f"flip={m['flip_rate']:.0%}  barsTP={m['avg_bars_tp']:.1f}  barsSL={m['avg_bars_sl']:.1f}")

        all_results[name] = results
        print()

    # Print summary table
    print("\n" + "=" * 90)
    print("  SUMMARY TABLE")
    print("=" * 90)
    for name, results in all_results.items():
        print(f"\n  {name}:")
        header = f"  {'SL Mult':>8s} {'Trades':>7s} {'Win%':>6s} {'AvgR':>8s} {'PF':>6s} {'TP%':>5s} {'SL%':>5s} {'Flip%':>6s} {'BarTP':>6s} {'BarSL':>6s}"
        print(header)
        print("  " + "-" * len(header))
        for r in results:
            print(f"  {r['sl_mult']:>8.2f} {r['n_trades']:>7d} {r['win_rate']:>5.1%} "
                  f"{r['avg_r']:>+7.3f} {r['profit_factor']:>5.3f} {r['tp_rate']:>4.0%} "
                  f"{r['sl_rate']:>4.0%} {r['flip_rate']:>5.0%} "
                  f"{r['avg_bars_tp']:>5.1f} {r['avg_bars_sl']:>5.1f}")
        # Find best PF
        best = max(results, key=lambda x: x["profit_factor"])
        best2 = max(results, key=lambda x: x["avg_r"])
        print(f"  ── Best PF: sl_mult={best['sl_mult']:.2f} (PF={best['profit_factor']:.3f}, "
              f"win={best['win_rate']:.1%}, avgR={best['avg_r']:+.3f})")
        print(f"  ── Best R:  sl_mult={best2['sl_mult']:.2f} (avgR={best2['avg_r']:+.3f}, "
              f"win={best2['win_rate']:.1%}, PF={best2['profit_factor']:.3f})")

    # Save
    out = os.path.join(BASE, "data", "live", "sl_sensitivity.json")
    with open(out, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "sweep": all_results}, f, indent=2)
    print(f"\n  Saved to {out}")
    print()


if __name__ == "__main__":
    main()
