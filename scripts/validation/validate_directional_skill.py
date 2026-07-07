#!/usr/bin/env python3
"""Per-asset directional-skill validation.

For each of the 22 portfolio assets, loads the walk-forward OOS signal
parquet and computes:

  1. BUY / SELL / FLAT breakdown (counts, win rate, avg R)
  2. Binomial test: is win rate significantly > 50% for each direction?
  3. Calibration quality (ECE) before and after calibration
  4. Directional-bias classification

Also specifically tests the 3 SELL_ONLY assets (CADCHF, NZDCHF, EURAUD)
for true one-sidedness.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_directional_skill.py
    PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_directional_skill.py --tag retrained
    PYTHONPATH=$PYTHONPATH:. python scripts/validation/validate_directional_skill.py --tag true_baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest

logger = logging.getLogger("validate_directional_skill")

SELL_ONLY_ASSETS: frozenset[str] = frozenset({"CADCHF", "NZDCHF", "EURAUD"})
WALKDIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "walkforward"
CALIBRATION_DIR = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "models" / "calibration"
OUTDIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"

THRESHOLD = 0.5


def load_signal_parquet(asset: str, tag: str) -> pd.DataFrame | None:
    """Load OOS signal parquet for an asset."""
    for candidate_tag in (tag, "retrained", "true_baseline", "baseline", "base"):
        path = WALKDIR / f"{asset}_wf_signals_{candidate_tag}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            if not df.empty:
                return df.sort_index()
    return None


def discover_assets(tag: str) -> list[str]:
    """Discover assets from walk-forward parquet files."""
    suffix = f"_wf_signals_{tag}.parquet"
    paths = sorted(WALKDIR.glob(f"*{suffix}"))
    if not paths:
        suffix = "_wf_signals.parquet"
        paths = sorted(WALKDIR.glob(f"*{suffix}"))
    return sorted({p.name.replace(suffix, "") for p in paths})


def load_calibrator(asset: str) -> dict | None:
    """Load a calibrator JSON file if it exists."""
    path = CALIBRATION_DIR / f"{asset}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def apply_binned_calibration(p_long: np.ndarray, cal_data: dict) -> np.ndarray:
    """Apply a BinnedCalibrator from its serialised JSON data."""
    centers = np.array(cal_data.get("bin_centers", []), dtype=float)
    empirical = np.array(cal_data.get("bin_empirical_probs", []), dtype=float)
    if len(centers) == 0 or len(empirical) == 0:
        return p_long.copy()
    cal_p = np.interp(p_long, centers, empirical)
    return np.clip(cal_p, 0.001, 0.999)


def compute_directional_metrics(
    df: pd.DataFrame, p_long_col: str = "p_long"
) -> dict[str, Any]:
    """Compute per-direction win rates and related metrics.

    Triple-barrier label semantics:
        label=1 → upper barrier hit first
        label=0 → lower barrier hit first (mapped from -1 by _to_binary)

    For BUY (signal=1):  upper = TP → label=1 is a WIN
    For SELL (signal=-1): upper = SL → label=1 is a LOSS, label=0 is a WIN
    """
    p_long = df[p_long_col].values.astype(float)
    labels = df["label"].values.astype(int)
    signals = df["signal"].values.astype(int)

    buy_mask = signals == 1
    sell_mask = signals == -1
    flat_mask = signals == 0

    metrics: dict[str, Any] = {}

    for direction, mask in [
        ("buy", buy_mask),
        ("sell", sell_mask),
        ("flat", flat_mask),
        ("all", np.ones(len(df), dtype=bool)),
    ]:
        n = int(mask.sum())
        if n == 0:
            metrics[f"n_{direction}"] = 0
            metrics[f"wr_{direction}"] = 0.0
            metrics[f"avg_p_long_{direction}"] = 0.0
            metrics[f"p_value_{direction}"] = 1.0
            metrics[f"significant_{direction}"] = False
            continue

        # Direction-conditional win computation
        if direction in ("buy", "all"):
            # BUY: label=1 → win
            wins = int(labels[mask].sum())
        elif direction == "sell":
            # SELL: label=0 → win (label=1 means SL hit first = loss)
            wins = int((1 - labels[mask]).sum())
        else:
            wins = int(labels[mask].sum())

        wr = wins / n
        avg_p = float(p_long[mask].mean())

        # Binomial test: H0 = win rate <= 0.5 (one-sided greater)
        result = binomtest(wins, n, p=0.5, alternative="greater")
        p_value = result.pvalue

        metrics[f"n_{direction}"] = n
        metrics[f"wr_{direction}"] = round(wr, 4)
        metrics[f"avg_p_long_{direction}"] = round(avg_p, 4)
        metrics[f"p_value_{direction}"] = round(p_value, 4)
        metrics[f"significant_{direction}"] = bool(p_value < 0.05)

    return metrics


def compute_ece(p_long: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
    """Compute Expected Calibration Error."""
    p_long = np.asarray(p_long, dtype=float)
    labels = np.asarray(labels, dtype=int)
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(p_long)
    if total == 0:
        return 0.0
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        in_bin = (p_long >= lo) & (p_long < hi)
        if i == n_bins - 1:
            in_bin |= p_long == 1.0
        n_bin = int(in_bin.sum())
        if n_bin == 0:
            continue
        avg_conf = float(p_long[in_bin].mean())
        acc = float(labels[in_bin].mean())
        ece += (n_bin / total) * abs(avg_conf - acc)
    return round(ece, 4)


def classify_direction(
    buy_wr: float, sell_wr: float,
    buy_sig: bool, sell_sig: bool,
    n_buy: int, n_sell: int,
) -> str:
    """Classify directional skill."""
    min_trades = 10

    if n_buy < min_trades and n_sell < min_trades:
        return "insufficient_data"

    if n_buy >= min_trades and buy_sig and n_sell >= min_trades and sell_sig:
        return "bidirectional"
    if n_buy >= min_trades and buy_sig and n_sell >= min_trades and not sell_sig:
        return "buy_only"
    if n_sell >= min_trades and sell_sig and n_buy >= min_trades and not buy_sig:
        return "sell_only"
    if n_sell >= min_trades and sell_sig and n_buy < min_trades:
        return "sell_only"
    if n_buy >= min_trades and buy_sig and n_sell < min_trades:
        return "buy_only"

    # Neither direction significant
    if n_buy >= min_trades or n_sell >= min_trades:
        return "coin_flip"

    return "unknown"


def analyze_asset(
    asset: str, tag: str, cal_data: dict | None
) -> dict[str, Any]:
    """Full analysis for one asset."""
    df = load_signal_parquet(asset, tag)
    if df is None:
        return {"asset": asset, "error": "no_data", "ok": False}

    result: dict[str, Any] = {
        "asset": asset,
        "ok": True,
        "n_total": len(df),
        "sell_only_flagged": asset in SELL_ONLY_ASSETS,
    }

    # ── 1. Uncalibrated directional metrics ──────────────────────────
    raw_metrics = compute_directional_metrics(df, "p_long")
    result["raw"] = raw_metrics

    # ── 2. Calibrated directional metrics ────────────────────────────
    if cal_data is not None and cal_data.get("type") == "BinnedCalibrator":
        df = df.copy()
        df["p_long_calibrated"] = apply_binned_calibration(
            df["p_long"].values.astype(float), cal_data
        )
        cal_metrics = compute_directional_metrics(df, "p_long_calibrated")
        result["calibrated"] = cal_metrics
    else:
        result["calibrated"] = None

    # ── 3. Classification ────────────────────────────────────────────
    buy_wr = raw_metrics["wr_buy"]
    sell_wr = raw_metrics["wr_sell"]
    buy_sig = raw_metrics["significant_buy"]
    sell_sig = raw_metrics["significant_sell"]
    n_buy = raw_metrics["n_buy"]
    n_sell = raw_metrics["n_sell"]
    result["classification"] = classify_direction(
        buy_wr, sell_wr, buy_sig, sell_sig, n_buy, n_sell
    )

    # ── 4. Calibration quality (ECE) ─────────────────────────────────
    p_long = df["p_long"].values.astype(float)
    labels = df["label"].values.astype(int)
    ece_before = compute_ece(p_long, labels)
    result["ece_before"] = ece_before

    if "p_long_calibrated" in df.columns:
        ece_after = compute_ece(
            df["p_long_calibrated"].values.astype(float), labels
        )
        result["ece_after"] = ece_after
        result["ece_delta"] = round(ece_before - ece_after, 4)
    else:
        result["ece_after"] = ece_before
        result["ece_delta"] = 0.0

    # ── 5. SELL_ONLY specific: BUY confidence analysis ───────────────
    if asset in SELL_ONLY_ASSETS and n_buy >= 5:
        buy_conf = p_long[df["signal"].values == 1]
        buy_labels = labels[df["signal"].values == 1]
        result["sell_only_buy_analysis"] = {
            "n_buy_signals": n_buy,
            "buy_wr": raw_metrics["wr_buy"],
            "avg_buy_p_long": raw_metrics["avg_p_long_buy"],
            "max_buy_p_long": round(float(buy_conf.max()), 4),
            "min_buy_p_long": round(float(buy_conf.min()), 4),
            "buy_wins": int(buy_labels.sum()),
            "buy_losses": int(n_buy - buy_labels.sum()),
        }

    # ── 6. BUY confidence profile (all assets) ──────────────────────
    if n_buy >= 10:
        buy_conf = p_long[df["signal"].values == 1]
        buy_labels = labels[df["signal"].values == 1]
        high_conf_mask = buy_conf > 0.65
        low_conf_mask = buy_conf <= 0.65
        result["buy_confidence_profile"] = {
            "high_conf_buy_count": int(high_conf_mask.sum()),
            "high_conf_buy_wr": round(float(buy_labels[high_conf_mask].mean()), 4)
            if high_conf_mask.sum() > 0
            else 0.0,
            "low_conf_buy_count": int(low_conf_mask.sum()),
            "low_conf_buy_wr": round(float(buy_labels[low_conf_mask].mean()), 4)
            if low_conf_mask.sum() > 0
            else 0.0,
        }

    if n_sell >= 10:
        sell_mask = df["signal"].values == -1
        sell_conf = 1.0 - p_long[sell_mask]
        # SELL: label=0 → win, so sell_win = (1 - label)
        sell_wins = 1 - labels[sell_mask]
        high_conf_mask = sell_conf > 0.65
        low_conf_mask = sell_conf <= 0.65
        result["sell_confidence_profile"] = {
            "high_conf_sell_count": int(high_conf_mask.sum()),
            "high_conf_sell_wr": round(float(sell_wins[high_conf_mask].mean()), 4)
            if high_conf_mask.sum() > 0
            else 0.0,
            "low_conf_sell_count": int(low_conf_mask.sum()),
            "low_conf_sell_wr": round(float(sell_wins[low_conf_mask].mean()), 4)
            if low_conf_mask.sum() > 0
            else 0.0,
        }

    # ── 7. Trade type breakdown ─────────────────────────────────────
    signal_counts = df["signal"].value_counts()
    result["signal_distribution"] = {
        str(k): int(v) for k, v in sorted(signal_counts.to_dict().items())
    }

    return result


def print_summary_table(results: list[dict[str, Any]]) -> None:
    """Print a formatted summary table."""
    print()
    print(f"{'=' * 120}")
    print(f"PER-ASSET DIRECTIONAL SKILL VALIDATION")
    print(f"{'=' * 120}")

    header = f"{'Asset':<10} {'N':>6} {'BUY WR':>8} {'BUY sig':>8} {'SELL WR':>9} {'SELL sig':>9} {'ECE bf':>7} {'ECE af':>7} {'Class':<20}"
    print(header)
    print(f"{'-' * 120}")

    classifications: dict[str, int] = {}
    sell_only_confirmations: list[str] = []
    sell_only_failures: list[str] = []

    for r in results:
        if not r.get("ok"):
            print(f"{r['asset']:<10} {'ERROR':>6} {r.get('error', '?')}")
            continue

        raw = r.get("raw", {})
        cal = r.get("calibrated", {})
        cls = r.get("classification", "?")
        classifications[cls] = classifications.get(cls, 0) + 1

        buy_wr = raw.get("wr_buy", 0)
        sell_wr = raw.get("wr_sell", 0)
        buy_sig = "✓" if raw.get("significant_buy", False) else "✗"
        sell_sig = "✓" if raw.get("significant_sell", False) else "✗"
        ece_before = r.get("ece_before", 0)
        ece_after = r.get("ece_after", 0)

        flag = ""
        if r.get("sell_only_flagged"):
            flag = " ★"
            if cls == "sell_only":
                sell_only_confirmations.append(r["asset"])
            else:
                sell_only_failures.append(r["asset"])

        line = (
            f"{r['asset']:<10} {raw.get('n_all', 0):>6} "
            f"{buy_wr:>8.2%} {buy_sig:>8} "
            f"{sell_wr:>8.2%} {sell_sig:>9} "
            f"{ece_before:>7.3f} {ece_after:>7.3f} "
            f"{cls:<20}{flag}"
        )
        print(line)

    print(f"{'-' * 120}")
    print("\nDistribution of classifications:")
    for cls, count in sorted(classifications.items(), key=lambda x: -x[1]):
        print(f"  {cls:<20} {count:>3} assets")

    print(f"\nSELL_ONLY assets (3):")
    for a in sorted(SELL_ONLY_ASSETS):
        status = f"CONFIRMED (genuinely sell-only)" if a in sell_only_confirmations else f"FAILED (not sell-only)"
        print(f"  {a}: {status}")

    if sell_only_failures:
        print(f"\n⚠ SELL_ONLY candidates that may need reclassification:")
        for a in sell_only_failures:
            print(f"  {a}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate per-asset directional skill")
    parser.add_argument("--tag", default="retrained", help="Signal parquet tag")
    parser.add_argument("--asset", type=str, default=None, help="Single asset to analyze")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--save", action="store_true", help="Save results to file")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    assets = [args.asset] if args.asset else discover_assets(args.tag)
    results: list[dict[str, Any]] = []

    for asset in assets:
        cal_data = load_calibrator(asset)
        result = analyze_asset(asset, args.tag, cal_data)
        results.append(result)

    if args.json:
        json.dump(results, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print_summary_table(results)

    if args.save:
        OUTDIR.mkdir(parents=True, exist_ok=True)
        path = OUTDIR / f"directional_skill_{args.tag}.json"
        with open(path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
