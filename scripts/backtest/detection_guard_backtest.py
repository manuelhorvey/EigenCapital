#!/usr/bin/env python3
"""
Detection guard backtest — evaluate rules for detecting base-model directional reversal.

Tests two rules on walk-forward signal parquets:
    Rule A: fast EMA(5) < slow EMA(20) AND p_long < 0.3
    Rule B: |p_long - prior_fold_mean| > 2 * prior_fold_std

Design folds (calibration):
    AUDNZD fold 2-3 + EURUSD fold 1  (known wrong-direction flips)

Validation: all other folds across 25 assets (including 19 promoted).

Ground truth for "failure": signal is wrong at cycle level
(predicts BUY when label=0, or predicts SELL when label=1).
The detection is evaluated on whether it flags BEFORE the wrong signals.
"""

from __future__ import annotations

import glob
import logging
import sys

import numpy as np
import pandas as pd
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("detection_guard")

BASE = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(BASE) / "walkforward"

DESIGN_FOLDS = {
    "AUDNZD": [2, 3],
    "EURUSD": [1],
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def load_assets() -> dict[str, pd.DataFrame]:
    """Load all signal parquets + summary CSVs, return {asset: signals_df}."""
    qry = Path(OUTPUT_DIR) / "*_wf_signals_base.parquet"
    paths = sorted(glob.glob(qry))
    if not paths:
        logger.warning("No signal parquets found at %s", qry)
        return {}

    # Build fold-range lookup from summary CSVs
    fold_ranges: dict[str, list[dict]] = {}
    summary_qry = Path(OUTPUT_DIR) / "*_wf_summary_base.csv"
    for sp in sorted(glob.glob(summary_qry)):
        asset = Path(sp).name.replace("_wf_summary_base.csv", "")
        df = pd.read_csv(sp)
        for _, row in df.iterrows():
            fold_ranges.setdefault(asset, []).append(
                {
                    "fold": int(row["fold"]),
                    "test_start": pd.Timestamp(row["test_start"], tz="UTC"),
                    "test_end": pd.Timestamp(row["test_end"], tz="UTC"),
                }
            )

    assets: dict[str, pd.DataFrame] = {}
    for p in paths:
        name = Path(p).name.replace("_wf_signals_base.parquet", "")
        sig = pd.read_parquet(p)
        sig.index = pd.to_datetime(sig.index)
        sig.index.name = "date"
        sig = sig.sort_index()

        # Assign fold numbers by date range
        sig["fold"] = -1
        if name in fold_ranges:
            for fr in fold_ranges[name]:
                mask = (sig.index >= fr["test_start"]) & (sig.index <= fr["test_end"])
                sig.loc[mask, "fold"] = fr["fold"]

        assets[name] = sig
        logger.info(
            "Loaded %s: %d rows, %d folds assigned",
            name,
            len(sig),
            (sig["fold"] >= 0).sum(),
        )

    return assets


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def rule_a_flag(df: pd.DataFrame) -> pd.Series:
    """Rule A: fast EMA < slow EMA && p_long < 0.3."""
    fast = ema(df["p_long"], span=5)
    slow = ema(df["p_long"], span=20)
    return (fast < slow) & (df["p_long"] < 0.3)


def rule_b_flag(
    df: pd.DataFrame,
    fold_stats: dict[int, dict[str, float]],
) -> pd.Series:
    """Rule B: |p_long - prior_fold_mean| > 2 * prior_fold_std.

    Uses the mean/std from the immediately prior fold.
    Falls back to all prior folds if fold 0 has no prior.
    """
    flag = pd.Series(False, index=df.index)
    for fold in sorted(df["fold"].unique()):
        if fold < 0:
            continue
        mask = df["fold"] == fold
        prior = [v for k, v in fold_stats.items() if k < fold]
        if not prior:
            continue
        mean = np.mean([p["mean"] for p in prior])
        std = np.mean([p["std"] for p in prior])
        if std <= 0:
            continue
        flag.loc[mask] = (df.loc[mask, "p_long"] - mean).abs() > 2 * std
    return flag


def row_is_wrong(df: pd.DataFrame) -> pd.Series:
    """Ground truth: signal is a directional bet AND it's wrong."""
    return ((df["signal"] == 1) & (df["label"] == 0)) | ((df["signal"] == -1) & (df["label"] == 1))


def row_is_right(df: pd.DataFrame) -> pd.Series:
    """Ground truth: signal is a directional bet AND it's correct."""
    return ((df["signal"] == 1) & (df["label"] == 1)) | ((df["signal"] == -1) & (df["label"] == 0))


def fold_stats(df: pd.DataFrame, fold: int) -> dict[str, float] | None:
    """Compute p_long mean/std for a given fold."""
    sub = df[df["fold"] == fold]
    if len(sub) < 5:
        return None
    return {"mean": float(sub["p_long"].mean()), "std": float(sub["p_long"].std())}


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


def eval_rules(
    assets: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Run both rules across all assets, return per-fold results."""
    rows: list[dict] = []
    for asset_name, df in assets.items():
        df = df[df["fold"] >= 0].copy()
        if df.empty:
            continue
        df["wrong"] = row_is_wrong(df)
        df["right"] = row_is_right(df)
        df["has_bet"] = df["signal"] != 0

        # Fold-level p_long stats for Rule B
        fstats: dict[int, dict[str, float]] = {}
        for f in sorted(df["fold"].unique()):
            fs = fold_stats(df, f)
            if fs is not None:
                fstats[f] = fs

        flag_a = rule_a_flag(df)
        flag_b = rule_b_flag(df, fstats)
        df["flag_a"] = flag_a
        df["flag_b"] = flag_b

        for fold in sorted(df["fold"].unique()):
            sub = df[df["fold"] == fold]
            n = len(sub)
            n_bets = sub["has_bet"].sum()
            n_wrong = sub["wrong"].sum()
            n_right = sub["right"].sum()

            # Rule A: flags that fire when wrong (correct detection)
            n_flag_a = sub["flag_a"].sum()
            a_detects_wrong = (sub["flag_a"] & sub["wrong"]).sum()
            a_false_pos = (sub["flag_a"] & ~sub["wrong"]).sum()

            # Rule B
            n_flag_b = sub["flag_b"].sum()
            b_detects_wrong = (sub["flag_b"] & sub["wrong"]).sum()
            b_false_pos = (sub["flag_b"] & ~sub["wrong"]).sum()

            is_design = asset_name in DESIGN_FOLDS and fold in DESIGN_FOLDS[asset_name]

            rows.append(
                {
                    "asset": asset_name,
                    "fold": fold,
                    "n": n,
                    "n_bets": n_bets,
                    "n_wrong": n_wrong,
                    "n_right": n_right,
                    "wrong_rate": round(n_wrong / max(n_bets, 1), 4),
                    "is_design": is_design,
                    # Rule A
                    "a_flag_rate": round(n_flag_a / max(n, 1), 4),
                    "a_detected_wrong": a_detects_wrong,
                    "a_false_positive": a_false_pos,
                    "a_precision": round(a_detects_wrong / max(n_flag_a, 1), 4),
                    "a_recall": round(a_detects_wrong / max(n_wrong, 1), 4),
                    # Rule B
                    "b_flag_rate": round(n_flag_b / max(n, 1), 4),
                    "b_detected_wrong": b_detects_wrong,
                    "b_false_positive": b_false_pos,
                    "b_precision": round(b_detects_wrong / max(n_flag_b, 1), 4),
                    "b_recall": round(b_detects_wrong / max(n_wrong, 1), 4),
                }
            )

    return pd.DataFrame(rows)


def print_results(results: pd.DataFrame) -> None:
    """Print summary table."""
    design = results[results["is_design"]]
    valid = results[~results["is_design"]]

    print("\n=== Detection Guard Backtest ===")
    print(f"Assets: {results['asset'].nunique()}")
    print(f"Rows (folds): {len(results)}")
    print(f"Design folds: {len(design)}")
    print(f"Validation folds: {len(valid)}")

    for label, grp in [("DESIGN", design), ("VALIDATION (all)", valid)]:
        print(f"\n--- {label} ---")
        for rule in ["a", "b"]:
            prec = grp[f"{rule}_precision"].mean()
            rec = grp[f"{rule}_recall"].mean()
            fp = grp[f"{rule}_false_positive"].sum()
            n = grp["n"].sum()
            print(
                f"  Rule {rule.upper()}: "
                f"avg_precision={prec:.3f} "
                f"avg_recall={rec:.3f} "
                f"total_FP={fp}/{n} ({fp / max(n, 1) * 100:.1f}%)"
            )

    # Worst false-positive assets for Rule A
    print("\n--- Worst false-positive assets (Rule A, validation only) ---")
    agg_a = (
        valid.groupby("asset")
        .agg({"a_false_positive": "sum", "n": "sum"})
        .assign(fp_rate=lambda x: x["a_false_positive"] / x["n"])
        .sort_values("fp_rate", ascending=False)
    )
    print(agg_a.head(5).to_string(float_format="%.4f"))

    print("\n--- Worst false-positive assets (Rule B, validation only) ---")
    agg_b = (
        valid.groupby("asset")
        .agg({"b_false_positive": "sum", "n": "sum"})
        .assign(fp_rate=lambda x: x["b_false_positive"] / x["n"])
        .sort_values("fp_rate", ascending=False)
    )
    print(agg_b.head(5).to_string(float_format="%.4f"))


def main():
    assets = load_assets()
    if not assets:
        sys.exit(1)
    results = eval_rules(assets)
    results.to_csv(Path(OUTPUT_DIR) / "detection_guard_results.csv", index=False)
    print_results(results)


if __name__ == "__main__":
    main()
