#!/usr/bin/env python3
"""Test feature set improvements for NZDUSD. Read-only — no prod changes."""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import pandas as pd  # noqa: E402
import xgboost as xgb  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from backtests import compute_per_fold_labels  # noqa: E402
from backtests.trade_analysis import _signals, _simulate, aggregate, fetch_ohlcv, load_macro  # noqa: E402
from features.builder import build_features  # noqa: E402
from features.registry import FeatureContract  # noqa: E402
from shared.volatility import compute_atr_pct  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

TP = 1.5
SL = 2.5
DEPTH = 5
MIN_TRADES = 20

VARIANTS = {
    "baseline": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5"),
        "price_mom_windows": (21, 63),
    },
    "+mom126": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5"),
        "price_mom_windows": (21, 63, 126),
    },
    "+mom252": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5"),
        "price_mom_windows": (21, 63, 126, 252),
    },
    "+real_yield_delta": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "real_yield_delta_63"),
        "price_mom_windows": (21, 63),
    },
    "+breakeven_delta": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "breakeven_delta_63"),
        "price_mom_windows": (21, 63),
    },
    "+rate_diff_delta": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "rate_diff_delta_3m"),
        "price_mom_windows": (21, 63),
    },
    "+yield_slope": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "yield_slope"),
        "price_mom_windows": (21, 63),
    },
    "+au_10y": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "au_10y"),
        "price_mom_windows": (21, 63),
    },
    "+au_10y+real_yield": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "au_10y", "real_yield_delta_63"),
        "price_mom_windows": (21, 63),
    },
    "+au_10y+breakeven": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "au_10y", "breakeven_delta_63"),
        "price_mom_windows": (21, 63),
    },
    "+au_10y+yield_slope": {
        "macro_filters": ("rate_diff", "dxy_mom_21", "vix_ma21", "vix_delta_5", "au_10y", "yield_slope"),
        "price_mom_windows": (21, 63),
    },
    "+rate_diff_delta+real_yield": {
        "macro_filters": (
            "rate_diff",
            "dxy_mom_21",
            "vix_ma21",
            "vix_delta_5",
            "rate_diff_delta_3m",
            "real_yield_delta_63",
        ),  # noqa: E501
        "price_mom_windows": (21, 63),
    },
}


def run_5yr(name, variant):
    vc = FeatureContract(
        ticker="NZDUSD=X",
        name="NZDUSD",
        contract_prefix="nzdusd=x",
        label_type="tb20",
        label_params={"pt_sl": [2.0, 2.0], "vertical_barrier": 20},
        macro_filters=variant["macro_filters"],
        price_mom_windows=variant["price_mom_windows"],
        vs_spy_windows=(),
    )

    df = fetch_ohlcv("NZDUSD=X")
    fdf = build_features(df, macro, None, vc, compute_labels=False)
    if fdf is None or fdf.empty:
        return None

    X = fdf[[c for c in vc.features if c in fdf.columns]]

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
        y_tr, y_te = compute_per_fold_labels(close, train_mask, test_mask, vc)
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
            max_depth=DEPTH,
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
        tr = _simulate(sigs, close, high, low, "NZDUSD", SL, TP, atr, regime)
        all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        return None

    agg = aggregate(all_trades)
    o = agg.get("overall", {})
    return {
        "pf": o.get("profit_factor", 0),
        "avg_r": o.get("avg_r", 0),
        "n": agg["n_trades"],
        "feature_count": len(vc.features),
    }


def main():
    results = []
    best_pf = 0
    print(f"{'Variant':30s} {'PF':>8s} {'avgR':>8s} {'Trades':>7s} {'Features':>9s}", flush=True)
    print("-" * 65, flush=True)

    for name, variant in VARIANTS.items():
        r = run_5yr(name, variant)
        if r is None:
            print(f"{name:30s} FAILED", flush=True)
            continue
        is_best = r["pf"] > best_pf
        if is_best:
            best_pf = r["pf"]
        results.append((name, r))
        marker = " <<<" if is_best else ""
        print(
            f"{name:30s} {r['pf']:>8.3f} {r['avg_r']:>+8.4f} {r['n']:>7d} {r['feature_count']:>9d}{marker}", flush=True
        )  # noqa: E501

    print("\n" + "=" * 65, flush=True)
    print("SUMMARY (sorted by PF)", flush=True)
    print("=" * 65, flush=True)
    for name, r in sorted(results, key=lambda x: -x[1]["pf"]):
        print(f"{name:30s} PF={r['pf']:.3f} avgR={r['avg_r']:+.4f} n={r['n']} feat={r['feature_count']}", flush=True)


if __name__ == "__main__":
    main()
