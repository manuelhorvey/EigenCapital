#!/usr/bin/env python3
"""Per-regime trade analysis by running walk-forward per asset."""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xgboost as xgb  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from backtests import compute_per_fold_labels  # noqa: E402
from backtests.trade_analysis import (  # noqa: E402
    DASHBOARD_TICKERS,
    MODEL_DEPTH,
    SLTP_CFG,
    _signals,
    _simulate,
    fetch_ohlcv,
    load_macro,
)
from features.builder import build_features  # noqa: E402
from features.registry import FEATURE_REGISTRY  # noqa: E402
from shared.volatility import compute_atr_pct  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()
MIN_TRADES = 10

REGIMES = ["low", "mid", "high"]

for ticker, name in sorted(DASHBOARD_TICKERS.items(), key=lambda x: x[1]):
    cfg = SLTP_CFG.get(name)
    depth = MODEL_DEPTH.get(name, 2)
    if cfg is None:
        continue
    slm, tpm = cfg["sl"], cfg["tp"]

    contract = FEATURE_REGISTRY.get(ticker)
    if contract is None:
        continue

    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, contract, compute_labels=False)
    if fdf is None or fdf.empty:
        continue

    X = fdf[[c for c in contract.features if c in fdf.columns]]

    close = df["close"].reindex(X.index)
    high = df["high"].reindex(X.index)
    low = df["low"].reindex(X.index)

    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    atr_r = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
    regime = (
        atr_r.fillna(0.5).apply(lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")).astype(str)
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
        tr = _simulate(sigs, close, high, low, name, slm, tpm, atr, regime)
        all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        continue

    per_r = {r: [t for t in all_trades if t.get("entry_regime", "mid") == r] for r in REGIMES}

    print(
        f"\n{name:10s}  overall avgR={np.mean([t['r_multiple'] for t in all_trades]):+.4f}  n={len(all_trades)}",
        flush=True,
    )  # noqa: E501
    for r in REGIMES:
        ts = per_r[r]
        if len(ts) < 3:
            print(f"  {r:6s}: n={len(ts):3d}  (too few)", flush=True)
            continue
        rs = [t["r_multiple"] for t in ts]
        maes = [abs(t["mae_r"]) for t in ts]
        mfes = [abs(t["mfe_r"]) for t in ts]
        wins = sum(1 for v in rs if v > 0)
        pf = (
            abs(sum(v for v in rs if v > 0) / sum(abs(v) for v in rs if v < 0))
            if sum(abs(v) for v in rs if v < 0) > 0
            else float("inf")
        )  # noqa: E501
        print(
            f"  {r:6s}: n={len(ts):3d}  avgR={np.mean(rs):+.4f}  win={wins / len(ts) * 100:.0f}%  "
            f"PF={pf:.2f}  MAE={np.mean(maes):.2f}R  MFE={np.mean(mfes):.2f}R",
            flush=True,
        )
