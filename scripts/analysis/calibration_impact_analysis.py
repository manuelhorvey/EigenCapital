#!/usr/bin/env python3
"""Calibration Impact Analysis — Compare raw vs calibrated signal performance.

Applies the production DirectionalCalibrator to raw walk-forward signal parquets
and compares raw vs calibrated directional R outcomes. Unlike the walk-forward's
built-in --calibrate flag (which fits per-fold calibrators with limited data),
this script loads the production calibrators (trained on pooled data) for a
more accurate estimate of calibration's impact.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/calibration_impact_analysis.py

Reads:
    scripts/walkforward/{asset}_wf_signals_{TAG}.parquet
    paper_trading/models/calibration/{asset}.json

Outputs: Per-asset comparison of raw vs calibrated BUY/SELL R, win rates,
         and signal filtering (neutral %) for each asset.

Edit the ASSETS and TAG constants at the top of this file to target
different assets or walk-forward runs.
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── Configuration — edit these to target different assets/tags ──────────────
ASSETS = [
    "AUDJPY", "AUDUSD", "BTCUSD", "CADCHF",
    "EURAUD", "EURCAD", "EURCHF", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPUSD",
    "GC",
    "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD",
    "USDCAD", "USDCHF", "USDJPY",
    "^DJI",
]
TAG = "fresh_v2"  # walk-forward signal tag to analyze

# Production thresholds (from sizing.yaml)
MIN_CONFIDENCE_BUY = 40.0
MIN_CONFIDENCE_SELL = 55.0
# Per-asset BUY threshold overrides (lower thresholds to unlock marginal trades)
PER_ASSET_BUY = {"GC": 40.0, "EURCHF": 40.0, "GBPCHF": 40.0}
PER_ASSET_SELL = {}


def platt_inverse(a: float, b: float, prob: np.ndarray) -> np.ndarray:
    """Apply Platt sigmoid: p_cal = 1 / (1 + exp(-(a * prob + b)))"""
    z = a * prob + b
    z = np.clip(z, -100, 100)
    return 1.0 / (1.0 + np.exp(-z))


def load_calibrator(asset: str) -> tuple:
    """Load DirectionalCalibrator JSON and return (buy_a, buy_b, sell_a, sell_b)."""
    path = ROOT / "paper_trading" / "models" / "calibration" / f"{asset}.json"
    if not path.exists():
        return None, None, None, None

    with open(path) as f:
        cal = json.load(f)

    buy_cal = cal.get("buy_calibrator") or cal.get("buy") or {}
    sell_cal = cal.get("sell_calibrator") or cal.get("sell") or {}

    buy_a = buy_cal.get("a") if cal.get("buy_fitted", False) else None
    buy_b = buy_cal.get("b") if cal.get("buy_fitted", False) else None
    sell_a = sell_cal.get("a") if cal.get("sell_fitted", False) else None
    sell_b = sell_cal.get("b") if cal.get("sell_fitted", False) else None

    return buy_a, buy_b, sell_a, sell_b


def compute_r(direction: int, label: int, tp_mult: float, sl_mult: float) -> float:
    """Compute R multiple given predicted direction and actual label.

    direction: 1 = BUY, -1 = SELL
    label: 0 = SELL wins or flat, 1 = BUY wins (triple-barrier remapped)
    """
    if direction == 1:  # Predicted BUY
        return tp_mult if label == 1 else -sl_mult
    else:  # Predicted SELL
        return tp_mult if label == 0 else -sl_mult


def get_tp_sl(asset: str) -> tuple[float, float]:
    """Get TP/SL multipliers from asset config."""
    import yaml

    config_path = ROOT / "configs" / "domains" / "assets" / f"{asset}.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("tp_mult", 2.0), cfg.get("sl_mult", 1.0)
    return 2.0, 1.0


def analyze(asset: str):
    """Analyze raw vs calibrated signal performance for one asset."""
    import pandas as pd

    print(f"\n{'=' * 70}")
    print(f"  {asset}  (tag={TAG})")
    print(f"{'=' * 70}")

    parquet_path = ROOT / "scripts" / "walkforward" / f"{asset}_wf_signals_{TAG}.parquet"
    if not parquet_path.exists():
        print(f"  ERROR: Signal parquet not found at {parquet_path}")
        print(f"  Run walk_forward_backtest.py --tag {TAG} first.")
        return

    df = pd.read_parquet(parquet_path)
    print(f"  Samples: {len(df)}")

    tp_mult, sl_mult = get_tp_sl(asset)
    print(f"  TP: {tp_mult}x, SL: {sl_mult}x")

    buy_a, buy_b, sell_a, sell_b = load_calibrator(asset)

    p_long = df["p_long"].values
    labels = df["label"].values if "label" in df.columns else None

    if labels is None:
        print("  ERROR: No label column")
        return

    # ── RAW (uncalibrated) Performance ──
    raw_direction = np.where(p_long >= 0.5, 1, -1)
    raw_r = np.array([compute_r(raw_direction[i], labels[i], tp_mult, sl_mult)
                      for i in range(len(p_long))])

    buy_mask_raw = raw_direction == 1
    sell_mask_raw = raw_direction == -1

    print(f"\n  ── RAW (uncalibrated) Performance ──")
    print(f"  p_long: mean={p_long.mean():.4f}, std={p_long.std():.4f}")
    print(f"  Signals: BUY={buy_mask_raw.sum()}, SELL={sell_mask_raw.sum()}")
    print(f"  Total R: {raw_r.sum():.2f}")
    print(f"  BUY R: {raw_r[buy_mask_raw].sum():.2f} ({buy_mask_raw.sum()} trades)")
    print(f"  SELL R: {raw_r[sell_mask_raw].sum():.2f} ({sell_mask_raw.sum()} trades)")
    print(f"  Label distribution: 0={int((labels == 0).sum())}, 1={int((labels == 1).sum())}")

    # ── Calibrated Performance ──
    print(f"\n  ── Calibrated Performance ──")

    cal_buy = p_long.copy() if buy_a is None else platt_inverse(buy_a, buy_b, p_long)
    cal_sell = (1.0 - cal_buy) if sell_a is None else platt_inverse(sell_a, sell_b, 1.0 - p_long)

    fitted_buy = buy_a is not None and buy_b is not None
    fitted_sell = sell_a is not None and sell_b is not None
    print(f"  BUY calibrator: {'FITTED' if fitted_buy else 'NOT FITTED (using raw)'}")
    print(f"  SELL calibrator: {'FITTED' if fitted_sell else 'NOT FITTED (using 1-calibrated_buy)'}")
    print(f"  Calibrated BUY:  mean={np.nanmean(cal_buy):.4f}, std={np.nanstd(cal_buy):.4f}")
    print(f"  Calibrated SELL: mean={np.nanmean(cal_sell):.4f}, std={np.nanstd(cal_sell):.4f}")

    # Direction: whichever confidence is higher
    cal_direction = np.where(cal_buy >= cal_sell, 1, -1)

    # Apply confidence gates
    buy_th = PER_ASSET_BUY.get(asset, MIN_CONFIDENCE_BUY) / 100.0
    sell_th = PER_ASSET_SELL.get(asset, MIN_CONFIDENCE_SELL) / 100.0

    cal_active = np.zeros(len(p_long), dtype=bool)
    for i in range(len(p_long)):
        if cal_direction[i] == 1 and cal_buy[i] >= buy_th:
            cal_active[i] = True
        elif cal_direction[i] == -1 and cal_sell[i] >= sell_th:
            cal_active[i] = True

    cal_r = np.array([compute_r(cal_direction[i], labels[i], tp_mult, sl_mult)
                      if cal_active[i] else 0.0
                      for i in range(len(p_long))])

    buy_mask_cal = cal_active & (cal_direction == 1)
    sell_mask_cal = cal_active & (cal_direction == -1)
    neutral_mask_cal = ~cal_active

    print(f"  Thresholds: BUY>={buy_th * 100:.0f}%, SELL>={sell_th * 100:.0f}%")
    print(f"  Signals: BUY={buy_mask_cal.sum()}, SELL={sell_mask_cal.sum()}, "
          f"NEUTRAL={neutral_mask_cal.sum()}")
    print(f"  Total R: {cal_r.sum():.2f}")
    print(f"  BUY R: {cal_r[buy_mask_cal].sum():.2f} ({buy_mask_cal.sum()} trades)")
    print(f"  SELL R: {cal_r[sell_mask_cal].sum():.2f} ({sell_mask_cal.sum()} trades)")

    # ── Directional Summary ──
    print(f"\n  ── Directional Summary ──")
    summaries = [
        ("Raw BUY", raw_r[buy_mask_raw].sum() if buy_mask_raw.any() else 0.0, buy_mask_raw),
        ("Raw SELL", raw_r[sell_mask_raw].sum() if sell_mask_raw.any() else 0.0, sell_mask_raw),
        ("Calibrated BUY", cal_r[buy_mask_cal].sum() if buy_mask_cal.any() else 0.0, buy_mask_cal),
        ("Calibrated SELL", cal_r[sell_mask_cal].sum() if sell_mask_cal.any() else 0.0, sell_mask_cal),
    ]
    for name, r_val, mask in summaries:
        n = mask.sum() if mask.any() else 0
        print(f"  {name:20s}: {r_val:>8.2f} R ({n} trades)")


if __name__ == "__main__":
    for asset in ASSETS:
        analyze(asset)
    print("\nDone.")
