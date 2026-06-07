#!/usr/bin/env python3
"""Train initial binary XGBoost models for new assets (EURUSD, NZDUSD)."""

import os, sys, logging, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from features.registry import FEATURE_REGISTRY
from features.builder import build_features
from backtests.trade_analysis import fetch_ohlcv, load_macro

BASE = os.path.join(os.path.dirname(__file__), "..", "paper_trading", "models")

NEW_ASSETS = [
    ("EURUSD", "EURUSD=X", {"sl": 3.0, "tp": 1.5}, 3),
    ("NZDUSD", "NZDUSD=X", {"sl": 2.5, "tp": 1.5}, 5),
]

LABEL_THRESH = 0.002 / 0.15
macro = load_macro()

for name, ticker, s_cfg, depth in NEW_ASSETS:
    contract = FEATURE_REGISTRY.get(ticker)
    if contract is None:
        print(f"SKIP {name}: no contract in registry", flush=True)
        continue

    print(f"\nTraining {name}...", flush=True)
    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, contract)
    features = [c for c in contract.features if c in fdf.columns]
    X = fdf[features].values
    y = (fdf["label"] > LABEL_THRESH).astype(int).values

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.15, shuffle=False)
    X_tr2, X_ev, y_tr2, y_ev = train_test_split(
        X_tr, y_tr, test_size=0.12, random_state=42, stratify=y_tr
    )

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=depth, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
        objective="binary:logistic", eval_metric="logloss",
        use_label_encoder=False, random_state=42,
    )
    model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)

    out_path = os.path.join(BASE, f"{name}_model.json")
    model.save_model(out_path)
    print(f"  Saved {out_path} ({len(features)} features, depth={depth})", flush=True)

print("\nDone.", flush=True)
