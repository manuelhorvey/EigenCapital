#!/usr/bin/env python3
"""Sweep REGIME_GEOM configurations — tests global regime multiplier configs."""
import os, sys, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from features.registry import FEATURE_REGISTRY
from features.builder import build_features
from backtests import compute_per_fold_labels

from shared.volatility import compute_atr_pct
from backtests.trade_analysis import fetch_ohlcv, load_macro, _signals, _simulate, aggregate, SLTP_CFG, DASHBOARD_TICKERS, MODEL_DEPTH, REGIME_GEOM

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

# Override REGIME_GEOM with test config — replicated from trade_analysis.py so we can hot-swap
# The _simulate function reads the module-level REGIME_GEOM, so we need to monkey-patch
import backtests.trade_analysis as ta

CONFIGS = {
    "baseline (all 1.0)": {"low": (1.0, 1.0), "mid": (1.0, 1.0), "high": (1.0, 1.0)},
    "high-vol protective": {"low": (0.9, 1.1), "mid": (1.0, 1.0), "high": (1.3, 0.8)},
    "aggressive hi-protect": {"low": (0.8, 1.2), "mid": (1.0, 1.0), "high": (1.4, 0.7)},
    "moderate": {"low": (0.9, 1.1), "mid": (1.0, 1.0), "high": (1.2, 0.9)},
    "low-vol tighten": {"low": (0.8, 1.1), "mid": (1.0, 1.0), "high": (1.0, 1.0)},
    "low-tight hi-wide": {"low": (0.7, 1.2), "mid": (1.0, 1.0), "high": (1.5, 0.8)},
    "symmetric": {"low": (0.8, 1.1), "mid": (1.0, 1.0), "high": (1.2, 0.9)},
}

MIN_TRADES = 5

def run_backtest(cfg_name, geom):
    ta.REGIME_GEOM.clear()
    for rg, (sl, tp) in geom.items():
        ta.REGIME_GEOM[rg] = {"sl": sl, "tp": tp}

    all_trades = []
    for ticker, name in sorted(DASHBOARD_TICKERS.items(), key=lambda x: x[1]):
        c = SLTP_CFG.get(name)
        depth = MODEL_DEPTH.get(name, 2)
        if c is None:
            continue
        slm, tpm = c["sl"], c["tp"]

        contract = FEATURE_REGISTRY.get(ticker)
        if contract is None:
            continue

        df = fetch_ohlcv(ticker)
        fdf = build_features(df, macro, None, contract, compute_labels=False)
        if fdf is None or fdf.empty:
            continue

        X = fdf[[col for col in contract.features if col in fdf.columns]]
    
        close = df["close"].reindex(X.index)
        high = df["high"].reindex(X.index)
        low = df["low"].reindex(X.index)

        atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
        atr_r = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
        regime = atr_r.fillna(0.5).apply(
            lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")
        ).astype(str)

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
                X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat)
            model = xgb.XGBClassifier(
                n_estimators=300, max_depth=depth, learning_rate=0.02,
                objective="multi:softprob", num_class=3, random_state=42,
                n_jobs=1, tree_method="hist", verbosity=0)
            model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
            proba = model.predict_proba(X_te)
            sigs = _signals(proba, X_te.index)
            tr = _simulate(sigs, close, high, low, name, slm, tpm, atr, regime)
            all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        return None

    # Per-asset breakdown
    by_asset = {}
    for t in all_trades:
        by_asset.setdefault(t["asset"], []).append(t)

    perfs = {}
    total_rs = []
    for aname, ts in by_asset.items():
        rs = [t["r_multiple"] for t in ts]
        wins = sum(1 for v in rs if v > 0)
        losses = sum(1 for v in rs if v < 0)
        avg_r = np.mean(rs) if rs else 0
        pf = abs(sum(v for v in rs if v > 0) / sum(abs(v) for v in rs if v < 0)) if sum(abs(v) for v in rs if v < 0) > 0 else float('inf')
        perfs[aname] = {"avg_r": avg_r, "pf": pf, "n": len(ts), "win": wins, "loss": losses}
        total_rs.extend(rs)

    overall_pf = abs(sum(v for v in total_rs if v > 0) / sum(abs(v) for v in total_rs if v < 0)) if sum(abs(v) for v in total_rs if v < 0) > 0 else float('inf')
    overall_avg_r = np.mean(total_rs) if total_rs else 0

    return {
        "overall_pf": overall_pf,
        "overall_avg_r": overall_avg_r,
        "n_trades": len(total_rs),
        "perfs": perfs,
    }


def main():
    results = []
    best_pf = 0

    for cfg_name, geom in CONFIGS.items():
        print(f"\n{'='*65}", flush=True)
        print(f"Config: {cfg_name}", flush=True)
        print(f"  LOW:  sl={geom['low'][0]:.1f} tp={geom['low'][1]:.1f}", flush=True)
        print(f"  MID:  sl={geom['mid'][0]:.1f} tp={geom['mid'][1]:.1f}", flush=True)
        print(f"  HIGH: sl={geom['high'][0]:.1f} tp={geom['high'][1]:.1f}", flush=True)
        print(f"{'='*65}", flush=True)

        r = run_backtest(cfg_name, geom)
        if r is None:
            print("  FAILED", flush=True)
            continue

        results.append((cfg_name, r))
        is_best = r["overall_pf"] > best_pf
        if is_best:
            best_pf = r["overall_pf"]

        print(f"  Overall: PF={r['overall_pf']:.3f} avgR={r['overall_avg_r']:+.4f} n={r['n_trades']}", flush=True)
        print(f"  By asset:", flush=True)
        for aname in sorted(r["perfs"]):
            p = r["perfs"][aname]
            print(f"    {aname:10s} PF={p['pf']:.3f} avgR={p['avg_r']:+.4f} n={p['n']} "
                  f"W={p['win']} L={p['loss']}", flush=True)

    print(f"\n{'='*65}", flush=True)
    print("SUMMARY (sorted by PF)", flush=True)
    print(f"{'='*65}", flush=True)
    for cfg_name, r in sorted(results, key=lambda x: -x[1]["overall_pf"]):
        print(f"{cfg_name:30s} PF={r['overall_pf']:.3f} avgR={r['overall_avg_r']:+.4f} n={r['n_trades']}",
              flush=True)


if __name__ == "__main__":
    main()
