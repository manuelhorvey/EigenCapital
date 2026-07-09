#!/usr/bin/env python3
"""Calibration Hardening — Phases 1-2 Investigation.

Reads all OOS walk-forward signal parquets, diagnoses the structural
miscalibration, tests alternative calibrators, and produces a report.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/calibration_investigation.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from shared.calibration.calibrator import (
    BetaCalibrator,
    BinnedCalibrator,
    DirectionalCalibrator,
    compute_ece,
)

logger = logging.getLogger("calibration_investigation")

WALKDIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "walkforward"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "models"

SEED = 42
np.random.seed(SEED)


def load_all_wf_signals(tag: str = "base") -> dict[str, pd.DataFrame]:
    """Load all walk-forward signal parquets. Returns {asset: df}."""
    parquet_paths = sorted(WALKDIR.glob(f"*_wf_signals.parquet"))
    if not parquet_paths:
        parquet_paths = sorted(WALKDIR.glob("*_wf_signals.parquet"))
    data = {}
    for p in parquet_paths:
        asset = p.name.replace("_wf_signals.parquet", "")
        if "_" in asset and asset.count("_") > 1:
            parts = p.name.split("_wf_signals")
            asset = parts[0] if len(parts) == 2 else p.stem
        df = pd.read_parquet(p)
        if "label" not in df.columns:
            continue
        labels = df["label"].dropna()
        if len(labels) < 10:
            continue
        data[asset] = df.sort_index()
    return data


def load_existing_calibrators() -> dict[str, dict]:
    """Load all calibrator JSON files. Returns {asset: json_data}."""
    cal_dir = MODEL_DIR / "calibration"
    calibrators = {}
    for p in sorted(cal_dir.glob("*.json")):
        with open(p) as f:
            calibrators[p.stem] = json.load(f)
    return calibrators


def reliability_diagram_data(p_long: np.ndarray, labels: np.ndarray, n_bins: int = 10):
    """Return per-bin confidence, accuracy, and count for reliability diagrams."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_data = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        in_bin = (p_long >= lo) & (p_long < hi)
        if i == n_bins - 1:
            in_bin |= p_long == 1.0
        n = in_bin.sum()
        if n > 0:
            bin_data.append({
                "bin_center": (lo + hi) / 2.0,
                "bin_conf": float(p_long[in_bin].mean()),
                "bin_acc": float(labels[in_bin].mean()),
                "bin_n": int(n),
            })
        else:
            bin_data.append({
                "bin_center": (lo + hi) / 2.0,
                "bin_conf": float((lo + hi) / 2.0),
                "bin_acc": 0.0,
                "bin_n": 0,
            })
    return bin_data


def compute_brier(p_long: np.ndarray, labels: np.ndarray) -> float:
    return float(np.mean((p_long - labels) ** 2))


def compute_log_loss(p_long: np.ndarray, labels: np.ndarray, eps: float = 1e-8) -> float:
    p = np.clip(p_long, eps, 1.0 - eps)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def compute_ece_decomposition(p_long: np.ndarray, labels: np.ndarray, n_bins: int = 10):
    """Decompose into calibration error and refinement error."""
    p_long = np.asarray(p_long, dtype=float)
    labels = np.asarray(labels, dtype=int)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total_var = float(np.var(labels))
    cal_error = 0.0
    refinement = 0.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        in_bin = (p_long >= lo) & (p_long < hi)
        if i == n_bins - 1:
            in_bin |= p_long == 1.0
        n_bin = in_bin.sum()
        if n_bin == 0:
            continue
        bin_acc = float(labels[in_bin].mean())
        bin_conf = float(p_long[in_bin].mean())
        cal_error += (n_bin / len(p_long)) * (bin_conf - bin_acc) ** 2
        refinement += (n_bin / len(p_long)) * bin_acc * (1 - bin_acc)
    ece = compute_ece(p_long, labels, n_bins)
    msce = float(cal_error)
    expected_refinement = float(refinement)
    brier_decomposed = msce + expected_refinement
    brier_actual = compute_brier(p_long, labels)
    return {
        "ece": ece,
        "msce": msce,
        "expected_refinement": expected_refinement,
        "brier_decomposed": brier_decomposed,
        "brier_actual": brier_actual,
        "total_variance": total_var,
        "refinement_pct": float(refinement / max(total_var, 1e-10) * 100),
    }


def fit_isotonic(p_long: np.ndarray, labels: np.ndarray) -> tuple:
    """Fit isotonic regression for calibration. Returns (model, calibrated)."""
    from sklearn.isotonic import IsotonicRegression
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    model.fit(p_long, labels)
    cal = model.predict(p_long)
    return model, cal


def fit_platt_scaling(p_long: np.ndarray, labels: np.ndarray) -> tuple:
    """Fit Platt scaling (logistic regression on log-odds)."""
    from sklearn.linear_model import LogisticRegression

    eps = 1e-6
    p = np.clip(p_long, eps, 1.0 - eps)
    logit_p = np.log(p / (1.0 - p))
    model = LogisticRegression(C=1e6, solver="lbfgs")
    model.fit(logit_p.reshape(-1, 1), labels)
    cal = model.predict_proba(logit_p.reshape(-1, 1))[:, 1]
    return model, cal


def fit_beta_logodds(p_long: np.ndarray, labels: np.ndarray) -> tuple:
    """Beta calibrator (already on log-odds)."""
    cal = BetaCalibrator()
    cal.fit(p_long, labels)
    return cal, cal.calibrate(p_long)


def fit_directional_binned(p_long: np.ndarray, labels: np.ndarray) -> tuple:
    """Directional Binned calibrator."""
    cal = DirectionalCalibrator(n_bins=10, min_samples_per_bin=3)
    cal.fit(p_long, labels)
    return cal, cal.calibrate(p_long)


def analyze_p_long_compression(p_long: np.ndarray, asset: str):
    """Analyze how compressed the p_long range is."""
    q = np.percentile(p_long, [1, 5, 25, 50, 75, 95, 99])
    iqr = q[4] - q[2]
    std = float(p_long.std())
    if std < 0.05:
        narrowness = "CRITICAL"
    elif std < 0.10:
        narrowness = "HIGH"
    else:
        narrowness = "MODERATE"
    return {
        "asset": asset,
        "min": float(p_long.min()),
        "max": float(p_long.max()),
        "mean": float(p_long.mean()),
        "std": std,
        "p1": float(q[0]),
        "p25": float(q[2]),
        "p75": float(q[4]),
        "p99": float(q[6]),
        "iqr": float(iqr),
        "narrowness": narrowness,
    }


def investigate_per_asset(asset: str, df: pd.DataFrame) -> dict:
    """Run full investigation for a single asset."""
    p_long = df["p_long"].values.astype(float)
    labels = df["label"].values.astype(int)

    n_total = len(p_long)
    n_pos = int(labels.sum())
    n_neg = n_total - n_pos
    imbalance = n_neg / max(n_pos, 1)

    # Raw ECE and decomposition
    decomp = compute_ece_decomposition(p_long, labels)

    # Per-direction ECE
    buy_mask = p_long >= 0.5
    sell_mask = p_long < 0.5
    ece_buy = compute_ece(p_long[buy_mask], labels[buy_mask]) if buy_mask.any() else None
    ece_sell = compute_ece(p_long[sell_mask], labels[sell_mask]) if sell_mask.any() else None

    # Decile reliability diagram data
    decile_data = reliability_diagram_data(p_long, labels, n_bins=10)

    # Compression analysis
    compress = analyze_p_long_compression(p_long, asset)

    # Brier / log loss
    brier = compute_brier(p_long, labels)
    logloss = compute_log_loss(p_long, labels)

    # How often is the model very confident?
    very_confident = float(np.mean((p_long >= 0.8) | (p_long <= 0.2)))

    # Actual p_long distribution (stored for report)
    pctiles = {
        "p1": float(np.percentile(p_long, 1)),
        "p5": float(np.percentile(p_long, 5)),
        "p25": float(np.percentile(p_long, 25)),
        "p50": float(np.percentile(p_long, 50)),
        "p75": float(np.percentile(p_long, 75)),
        "p95": float(np.percentile(p_long, 95)),
        "p99": float(np.percentile(p_long, 99)),
    }

    return {
        "asset": asset,
        "n_samples": n_total,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "imbalance_ratio": round(imbalance, 3),
        "ece_raw": round(decomp["ece"], 4),
        "ece_buy": round(ece_buy, 4) if ece_buy is not None else None,
        "ece_sell": round(ece_sell, 4) if ece_sell is not None else None,
        "brier": round(brier, 4),
        "log_loss": round(logloss, 4),
        "msce": round(decomp["msce"], 4),
        "refinement_error": round(decomp["expected_refinement"], 4),
        "total_variance": round(decomp["total_variance"], 4),
        "refinement_captured_pct": round(decomp["refinement_pct"], 1),
        "very_confident_pct": round(very_confident * 100, 1),
        "p_long_percentiles": pctiles,
        "p_long_compression": compress,
        "deciles": decile_data,
    }


def test_calibrator(asset: str, df: pd.DataFrame, method: str) -> dict:
    """Test a calibrator method on this asset's OOS predictions."""
    p_long = df["p_long"].values.astype(float)
    labels = df["label"].values.astype(int)

    ece_before = compute_ece(p_long, labels, n_bins=10)

    if method == "binned":
        cal = BinnedCalibrator(n_bins=10, min_samples_per_bin=3)
        cal.fit(p_long, labels)
        p_cal = cal.calibrate(p_long)
    elif method == "beta":
        cal = BetaCalibrator()
        cal.fit(p_long, labels)
        p_cal = cal.calibrate(p_long)
    elif method == "isotonic":
        model, p_cal = fit_isotonic(p_long, labels)
    elif method == "platt":
        model, p_cal = fit_platt_scaling(p_long, labels)
    elif method == "directional":
        cal = DirectionalCalibrator(n_bins=10, min_samples_per_bin=3)
        cal.fit(p_long, labels)
        p_cal = cal.calibrate(p_long)
    elif method == "beta_logodds":
        cal, p_cal = fit_beta_logodds(p_long, labels)
    else:
        return {"error": f"Unknown method: {method}"}

    ece_after = compute_ece(p_cal, labels, n_bins=10)

    # Count real-data bins for binned
    fallback_info = {}
    if method == "binned":
        n_real = 0
        n_bins = 10
        for i in range(n_bins):
            lo = i * 0.1
            hi = (i + 1) * 0.1
            in_bin = (p_long >= lo) & (p_long < hi)
            if i == n_bins - 1:
                in_bin |= p_long == 1.0
            if in_bin.sum() >= 3:
                n_real += 1
        fallback_info = {
            "n_real_data_bins": n_real,
            "fallback_pct": round((n_bins - n_real) / n_bins * 100, 1),
        }

    return {
        "asset": asset,
        "method": method,
        "ece_before": round(ece_before, 4),
        "ece_after": round(ece_after, 4),
        "ece_delta": round(ece_before - ece_after, 4),
        "improvement_pct": round((1 - ece_after / max(ece_before, 1e-8)) * 100, 1),
        "brier_before": round(compute_brier(p_long, labels), 4),
        "brier_after": round(compute_brier(p_cal, labels), 4),
        **fallback_info,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calibration Investigation — Phases 1-2"
    )
    parser.add_argument("--tag", default="base")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    data = load_all_wf_signals(args.tag)
    n_assets = len(data)
    print(f"\n{'=' * 72}")
    print(f"CALIBRATION INVESTIGATION")
    print(f"{n_assets} assets loaded from {WALKDIR}")
    print(f"{'=' * 72}")

    # ── 1. Full per-asset investigation ──────────────────────────────
    print(f"\n--- Phase 1: Per-asset diagnostic ---")
    per_asset_results = {}
    for asset, df in sorted(data.items()):
        res = investigate_per_asset(asset, df)
        per_asset_results[asset] = res

    # ── 2. Summary statistics ──────────────────────────────────────
    eces = [v["ece_raw"] for v in per_asset_results.values()]
    briers = [v["brier"] for v in per_asset_results.values()]
    imbalances = [v["imbalance_ratio"] for v in per_asset_results.values()]
    very_confs = [v["very_confident_pct"] for v in per_asset_results.values()]

    print(f"\n{'='*72}")
    print("SUMMARY")
    print(f"{'='*72}")
    print(f"Mean ECE:           {np.mean(eces):.4f} (median {np.median(eces):.4f})")
    print(f"Mean Brier:         {np.mean(briers):.4f}")
    print(f"Mean imbalance:     {np.mean(imbalances):.2f}")
    n_above = sum(1 for e in eces if e > 0.15)
    print(f"Assets ECE > 0.15:  {n_above}/{n_assets} ({n_above/n_assets*100:.0f}%)")
    print(f"Avg very-conf pct:  {np.mean(very_confs):.1f}%")

    # ── 3. ECE Decomposition ──────────────────────────────────────
    msces = [v["msce"] for v in per_asset_results.values()]
    refinements = [v["refinement_error"] for v in per_asset_results.values()]
    ref_captured = [v["refinement_captured_pct"] for v in per_asset_results.values()]

    print(f"\n--- ECE Decomposition (Brier = MSCE + Refinement) ---")
    print(f"Mean MSCE (calibration):       {np.mean(msces):.4f}")
    print(f"Mean Refinement Error:          {np.mean(refinements):.4f}")
    print(f"Mean refinement/total variance: {np.mean(ref_captured):.1f}%")
    print(f"(Higher refinement% = more irreducible noise)")

    # ── 4. Per-direction ECE ──────────────────────────────────────
    print(f"\n--- Directional ECE ---")
    buy_eces = [v["ece_buy"] for v in per_asset_results.values() if v["ece_buy"] is not None]
    sell_eces = [v["ece_sell"] for v in per_asset_results.values() if v["ece_sell"] is not None]
    print(f"Mean ECE (BUY):  {np.mean(buy_eces):.4f}  ({len(buy_eces)} assets)")
    print(f"Mean ECE (SELL): {np.mean(sell_eces):.4f}  ({len(sell_eces)} assets)")

    # ── 5. Test all calibrators on all assets ─────────────────────
    print(f"\n--- Phase 2: Calibrator Comparison ---")
    calibrator_tests = {}
    for asset, df in sorted(data.items()):
        calibrator_tests[asset] = {}
        for method in ["binned", "beta", "isotonic", "platt", "directional", "beta_logodds"]:
            tr = test_calibrator(asset, df, method)
            calibrator_tests[asset][method] = tr

    methods = ["binned", "beta", "isotonic", "platt", "directional", "beta_logodds"]
    print(f"\n{'Method':<18}", end="")
    for m in methods:
        print(f"{'ECE_after':>10}", end="")
    print(f"  {'Improve':>8}")
    print(f"{'-' * 68}")
    for m in methods:
        ece_vals = [calibrator_tests[a][m]["ece_after"] for a in data]
        impr_vals = [calibrator_tests[a][m]["improvement_pct"] for a in data]
        print(f"{m:<18}{np.mean(ece_vals):>10.4f}{np.mean(impr_vals):>8.1f}%")

    # ── 6. Narrow p_long compression analysis ──────────────────────
    print(f"\n--- P_LONG Compression Analysis ---")
    narrow_threshold = 0.10
    narrow_assets_std = [(v["asset"], v["p_long_compression"]["std"]) 
                         for v in per_asset_results.values()
                         if v["p_long_compression"]["std"] < narrow_threshold]
    narrow_assets_std.sort(key=lambda x: x[1])
    for asset, std in narrow_assets_std:
        c = per_asset_results[asset]["p_long_compression"]
        print(f"  {asset:8s} std={std:.4f}  range=[{c['min']:.4f}, {c['max']:.4f}]  iqr={c['iqr']:.4f}  {c['narrowness']}")
    print(f"  ({len(narrow_assets_std)}/{n_assets} have std < {narrow_threshold})")

    # ── 7. Check calibrator fallback rates ────────────────────────
    print(f"\n--- Existing Calibrator Fallback Analysis ---")
    existing = load_existing_calibrators()
    for asset, cal_data in sorted(existing.items()):
        if cal_data["type"] != "BinnedCalibrator":
            continue
        centers = cal_data.get("bin_centers", [])
        empirical = cal_data.get("bin_empirical_probs", [])
        if not centers or not empirical:
            continue
        fallback_count = sum(1 for p in empirical if p == 0.5)
        fallback_pct = fallback_count / len(empirical) * 100
        if fallback_pct > 50:
            tag = " (FALLBACK DOMINANT)"
        else:
            tag = ""
        print(f"  {asset:8s}: {fallback_count}/{len(empirical)} fallback bins ({fallback_pct:.0f}%){tag}")

    # ── 8. Save results JSON ──────────────────────────────────────
    summary = {
        "n_assets": n_assets,
        "mean_ece_raw": round(float(np.mean(eces)), 4),
        "median_ece_raw": round(float(np.median(eces)), 4),
        "ece_above_threshold": sum(1 for e in eces if e > 0.15),
        "mean_brier": round(float(np.mean(briers)), 4),
        "mean_imbalance": round(float(np.mean(imbalances)), 2),
        "mean_very_confident_pct": round(float(np.mean(very_confs)), 1),
        "ece_by_method": {
            m: round(float(np.mean([calibrator_tests[a][m]["ece_after"] for a in data])), 4)
            for m in methods
        },
        "improvement_by_method": {
            m: round(float(np.mean([calibrator_tests[a][m]["improvement_pct"] for a in data])), 1)
            for m in methods
        },
        "narrow_compression_count": len(narrow_assets_std),
        "refinement_captured_pct_mean": round(float(np.mean(ref_captured)), 1),
        "ece_buy_mean": round(float(np.mean(buy_eces)), 4),
        "ece_sell_mean": round(float(np.mean(sell_eces)), 4),
    }

    results = {
        "summary": summary,
        "per_asset": per_asset_results,
        "calibrator_tests": calibrator_tests,
    }

    output_path = OUTPUT_DIR / "calibration_investigation_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n=== Results saved to {output_path} ===")
    print("Now generating report...")


if __name__ == "__main__":
    main()