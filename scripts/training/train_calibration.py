#!/usr/bin/env python3
"""Train calibration models from walk-forward signal parquets.

For each asset, loads the OOS signal parquet(s), fits a BinnedCalibrator
on (p_long, label) pairs, and saves to the model calibration directory.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/train_calibration.py
    PYTHONPATH=$PYTHONPATH:. python scripts/train_calibration.py --method beta
    PYTHONPATH=$PYTHONPATH:. python scripts/train_calibration.py --asset EURUSD
    PYTHONPATH=$PYTHONPATH:. python scripts/train_calibration.py --min-bins 5
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from shared.calibration import BetaCalibrator, BinnedCalibrator, CalibrationMethod, CalibrationRegistry
from shared.calibration.calibrator import compute_ece

logger = logging.getLogger("train_calibration")

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "models"
WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"
CALIBRATION_DIR = MODEL_DIR / "calibration"


def load_signal_parquet(asset: str, tag: str = "base") -> pd.DataFrame | None:
    """Load a single asset's walk-forward signal parquet."""
    pq_path = WALKDIR / f"{asset}_wf_signals_{tag}.parquet"
    if not pq_path.exists():
        pq_path = WALKDIR / f"{asset}_wf_signals.parquet"
    if not pq_path.exists():
        logger.warning("No signal parquet found for %s", asset)
        return None
    df = pd.read_parquet(pq_path)
    if df.empty:
        return None
    return df.sort_index()


def compute_pre_post_ece(df: pd.DataFrame, calibrator: CalibrationMethod) -> dict:
    """Compute ECE before and after calibration."""
    p_long_raw = df["p_long"].values.astype(float)
    labels = df["label"].values.astype(int)
    ece_before = compute_ece(p_long_raw, labels, n_bins=10)
    p_long_cal = calibrator.calibrate(p_long_raw)
    ece_after = compute_ece(p_long_cal, labels, n_bins=10)
    return {
        "ece_before": round(ece_before, 4),
        "ece_after": round(ece_after, 4),
        "ece_delta": round(ece_before - ece_after, 4),
        "improvement_pct": round((1 - ece_after / max(ece_before, 1e-8)) * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Train calibration models from walk-forward signal parquets")
    parser.add_argument("--method", default="binned", choices=["binned", "beta"], help="Calibration method")
    parser.add_argument("--asset", type=str, default=None, help="Single asset to train (default: all)")
    parser.add_argument("--tag", default="base", help="Signal parquet tag (default base)")
    parser.add_argument("--n-bins", type=int, default=10, help="Number of bins for BinnedCalibrator")
    parser.add_argument("--min-samples", type=int, default=5, help="Min samples per bin")
    parser.add_argument("--dry-run", action="store_true", help="Print ECE comparison without saving")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Discover assets from walk-forward parquets
    suffix = f"_wf_signals_{args.tag}.parquet"
    parquet_paths = sorted(WALKDIR.glob(f"*{suffix}"))
    if not parquet_paths:
        suffix = "_wf_signals.parquet"
        parquet_paths = sorted(WALKDIR.glob(f"*{suffix}"))

    all_assets = sorted({p.name.replace(suffix, "") for p in parquet_paths})
    if args.asset:
        all_assets = [args.asset]

    registry = CalibrationRegistry()
    results = []

    for asset in all_assets:
        df = load_signal_parquet(asset, tag=args.tag)
        if df is None:
            continue

        p_long = df["p_long"].values.astype(float)
        labels = df["label"].values.astype(int)

        if args.method == "binned":
            cal = BinnedCalibrator(n_bins=args.n_bins, min_samples_per_bin=args.min_samples)
        else:
            cal = BetaCalibrator()

        cal.fit(p_long, labels)
        ece_info = compute_pre_post_ece(df, cal)

        metadata = {
            "method": args.method,
            "n_bins": args.n_bins if args.method == "binned" else "N/A",
            "n_samples": len(df),
            "timestamp": pd.Timestamp.now().isoformat(),
            **ece_info,
        }

        registry.register(asset, cal, metadata)
        results.append((asset, ece_info))

        logger.info(
            "%s: ECE %.4f \u2192 %.4f (%+.1f%%)  [n=%d]",
            asset,
            ece_info["ece_before"],
            ece_info["ece_after"],
            ece_info["improvement_pct"],
            len(df),
        )

    # Summary
    print(f"\n{'=' * 72}")
    print(f"CALIBRATION TRAINING SUMMARY (method={args.method})")
    print(f"{'=' * 72}")
    _delta = "\u0394"
    print(f"{'Asset':<12} {'ECE Before':<12} {'ECE After':<12} {_delta:<12} {'Improvement':<12}")
    print(f"{'-' * 60}")

    total_before, total_after = 0.0, 0.0
    for asset, ece_info in results:
        print(
            f"{asset:<12} {ece_info['ece_before']:<12.4f} {ece_info['ece_after']:<12.4f} "
            f"{ece_info['ece_delta']:<+12.4f} {ece_info['improvement_pct']:<+12.1f}%"
        )
        total_before += ece_info["ece_before"]
        total_after += ece_info["ece_after"]

    if results:
        n = len(results)
        print(f"{'-' * 60}")
        print(
            f"{'AVERAGE':<12} {total_before / n:<12.4f} {total_after / n:<12.4f} "
            f"{(total_before - total_after) / n:<+12.4f}"
        )

    if not args.dry_run and results:
        saved = registry.save_all(CALIBRATION_DIR)
        print(f"\nSaved {saved} calibrators to {CALIBRATION_DIR}")
        print(f"Assets: {', '.join(registry.available_assets())}")

    if args.dry_run:
        print("\nDRY RUN \u2014 no files saved. Use without --dry-run to persist.")


if __name__ == "__main__":
    main()
