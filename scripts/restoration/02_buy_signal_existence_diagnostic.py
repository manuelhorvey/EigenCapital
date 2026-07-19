#!/usr/bin/env python3
"""
BUY Signal Existence Diagnostic Framework
==========================================

Determines whether BUY signal is recoverable for SELL_ONLY assets.

Tests:
  A. Label inversion — train with flipped labels (model learns P(DOWN)
     instead of P(UP)), evaluate whether BUY WR improves against original labels.
     Run: walk_forward_backtest.py --invert-labels --tag inv_labels

  B. Symmetry test — compares SELL-only vs BUY-only performance on existing
     walk-forward data. Quantifies the asymmetry magnitude for each asset.

  C. Information sufficiency — compares BUY WR across SELL_ONLY vs non-SELL_ONLY
     assets. Determines if the issue is asset-specific or a global representation
     failure.

Usage:
    # Run full diagnostic (uses existing parquets for B, C; skips A if no inverted parquet)
    PYTHONPATH=$PYTHONPATH:. python scripts/restoration/02_buy_signal_existence_diagnostic.py

    # Run with label inversion (generates inverted model for EURAUD)
    PYTHONPATH=$PYTHONPATH:. python scripts/restoration/02_buy_signal_existence_diagnostic.py --rerun-inversion

    # Run on a specific asset
    PYTHONPATH=$PYTHONPATH:. python scripts/restoration/02_buy_signal_existence_diagnostic.py --asset EURAUD
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("buy_signal_existence")

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "NZDCHF",
        "EURAUD",
    }
)
# ^DJI, USDCHF, EURCHF removed 2026-06-26 after trend-exhaustion features improved BuyWR above breakeven.

NON_SELL_ONLY_ASSETS: list[str] = [
    "GBPUSD",
    "AUDUSD",
    "EURNZD",
    "NZDUSD",
    "GBPAUD",
    "GBPCAD",
    "NZDCAD",
    "EURCAD",
    "GBPCHF",
    "GC",
    "USDCAD",
    "AUDNZD",
]

PER_ASSET_PT_SL: dict[str, tuple[float, float]] = {
    "CADCHF": (4.0, 1.0),
    "ES": (5.5, 2.0),
    "NQ": (5.0, 2.5),
    "NZDCHF": (4.0, 1.0),
    "EURAUD": (1.77, 0.54),
    "^DJI": (4.0, 0.5),
    "USDCHF": (3.0, 0.85),
    "EURCHF": (3.0, 1.0),
    "GBPUSD": (1.97, 0.52),
    "AUDUSD": (2.0, 0.75),
    "EURNZD": (2.74, 1.37),
    "NZDUSD": (2.5, 2.0),
    "GBPAUD": (2.0, 1.0),
    "GBPCAD": (3.54, 1.77),
    "NZDCAD": (4.47, 2.24),
    "EURCAD": (1.73, 0.87),
    "GBPCHF": (2.0, 1.0),
    "GC": (4.0, 1.0),
    "USDCAD": (3.19, 1.59),
    "AUDNZD": (1.0, 3.0),
}


def load_signals(asset: str, tag: str = "") -> pd.DataFrame | None:
    """Load walk-forward signal parquet. Tries walkforward/ and scripts/walkforward/."""
    for base_dir in ["walkforward", "scripts/walkforward"]:
        p = Path(base_dir) / f"{asset}_wf_signals{'_' + tag if tag else ''}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            return df
    return None


def compute_direction_stats(df: pd.DataFrame, tp: float, sl: float) -> dict:
    """Compute BUY/SELL/neutral stats at default threshold (0.575/0.425)."""
    buy_mask = df["p_long"] >= 0.575
    sell_mask = df["p_long"] <= 0.425
    flat_mask = ~buy_mask & ~sell_mask

    n_buy = int(buy_mask.sum())
    n_sell = int(sell_mask.sum())
    n_flat = int(flat_mask.sum())

    # Use label_original if available (from invert-labels run), else label
    label_col = "label_original" if "label_original" in df.columns else "label"
    y = df[label_col].values

    buy_correct = int((df.loc[buy_mask, label_col] == 1).sum()) if n_buy > 0 else 0
    sell_correct = int((df.loc[sell_mask, label_col] == 0).sum()) if n_sell > 0 else 0

    buy_wr = buy_correct / n_buy if n_buy > 0 else 0.0
    sell_wr = sell_correct / n_sell if n_sell > 0 else 0.0
    total_wr = (buy_correct + sell_correct) / (n_buy + n_sell) if (n_buy + n_sell) > 0 else 0.0

    buy_r = buy_correct * tp - (n_buy - buy_correct) * sl
    sell_r = sell_correct * tp - (n_sell - sell_correct) * sl
    total_r = buy_r + sell_r

    return {
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_flat": n_flat,
        "n_total": len(df),
        "buy_wr": round(buy_wr, 4),
        "sell_wr": round(sell_wr, 4),
        "total_wr": round(total_wr, 4),
        "buy_r": round(buy_r, 2),
        "sell_r": round(sell_r, 2),
        "total_r": round(total_r, 2),
        "up_rate": round(float(y.mean()), 4),
    }


# ── Test B: Symmetry Test ────────────────────────────────────────────


def run_symmetry_test(asset: str) -> dict:
    """Compare SELL-only vs BUY-only performance on existing walk-forward data.

    Quantifies the asymmetry magnitude:
      asymmetry = sell_wr - buy_wr
      if asymmetry >> 0 → structural imbalance favoring SELL
      if asymmetry ≈ 0 → symmetric prediction
    """
    df = load_signals(asset)
    if df is None:
        return {"asset": asset, "status": "NO_DATA", "asymmetry": None}

    tp, sl = PER_ASSET_PT_SL.get(asset, (2.0, 2.0))
    stats = compute_direction_stats(df, tp, sl)
    asymmetry = stats["sell_wr"] - stats["buy_wr"]

    if stats["n_buy"] < 10 and stats["n_sell"] < 10:
        status = "INCONCLUSIVE (too few trades)"
    elif asymmetry > 0.30 and stats["n_buy"] >= 10:
        status = "SEVERE_ASYMMETRY"
    elif asymmetry > 0.15 and stats["n_buy"] >= 10:
        status = "MODERATE_ASYMMETRY"
    elif stats["buy_wr"] >= 0.50:
        status = "SYMMETRIC"
    else:
        status = "WEAK_ASYMMETRY"

    return {
        "asset": asset,
        "status": status,
        "buy_wr": stats["buy_wr"],
        "sell_wr": stats["sell_wr"],
        "asymmetry": round(asymmetry, 4),
        "n_buy": stats["n_buy"],
        "n_sell": stats["n_sell"],
        "n_flat": stats["n_flat"],
        "n_total": stats["n_total"],
        "buy_r": stats["buy_r"],
        "sell_r": stats["sell_r"],
        "total_r": stats["total_r"],
    }


# ── Test C: Information Sufficiency ──────────────────────────────────


def run_sufficiency_test() -> dict:
    """Compare BUY WR across SELL_ONLY vs non-SELL_ONLY assets.

    Determines whether the issue is:
      - Global: no assets have BUY WR > 50% → representation failure
      - Asset-specific: non-SELL_ONLY have BUY WR > 50% → domain-specific issue
    """
    sell_only_results = []
    non_sell_results = []

    for asset in sorted(SELL_ONLY_ASSETS):
        r = run_symmetry_test(asset)
        if r["buy_wr"] is not None:
            sell_only_results.append(r)

    for asset in NON_SELL_ONLY_ASSETS:
        r = run_symmetry_test(asset)
        if r["buy_wr"] is not None:
            non_sell_results.append(r)

    so_buy_wrs = [r["buy_wr"] for r in sell_only_results]
    ns_buy_wrs = [r["buy_wr"] for r in non_sell_results]
    so_sell_wrs = [r["sell_wr"] for r in sell_only_results]
    ns_sell_wrs = [r["sell_wr"] for r in non_sell_results]

    so_mean_buy = np.mean(so_buy_wrs) if so_buy_wrs else 0
    ns_mean_buy = np.mean(ns_buy_wrs) if ns_buy_wrs else 0
    so_mean_sell = np.mean(so_sell_wrs) if so_sell_wrs else 0
    ns_mean_sell = np.mean(ns_sell_wrs) if ns_sell_wrs else 0

    # How many SELL_ONLY assets have BUY WR > 50%?
    so_buy_ok = sum(1 for w in so_buy_wrs if w >= 0.50)
    # How many non-SELL_ONLY assets have BUY WR > 50%?
    ns_buy_ok = sum(1 for w in ns_buy_wrs if w >= 0.50)
    # How many non-SELL_ONLY assets have BUY WR > 50% AND SELL WR > 50%?
    ns_both_ok = sum(1 for r in non_sell_results if r["buy_wr"] >= 0.50 and r["sell_wr"] >= 0.50)

    verdict = "UNKNOWN"
    if ns_mean_buy >= 0.50 and so_mean_buy < 0.40:
        verdict = "ASSET_SPECIFIC — BUY learnable for most assets, but SELL_ONLY cluster has domain-specific failure"
    elif ns_mean_buy < 0.50:
        verdict = "GLOBAL — BUY not learnable for any asset cluster, representation failure"
    elif so_mean_buy >= 0.50:
        verdict = "NO_ISSUE — SELL_ONLY assets have BUY WR > 50%, filter may not be needed"

    return {
        "verdict": verdict,
        "sell_only": {
            "n_assets": len(sell_only_results),
            "mean_buy_wr": round(float(so_mean_buy), 4),
            "mean_sell_wr": round(float(so_mean_sell), 4),
            "assets_with_buy_wr_gt_50": so_buy_ok,
            "results": sell_only_results,
        },
        "non_sell_only": {
            "n_assets": len(non_sell_results),
            "mean_buy_wr": round(float(ns_mean_buy), 4),
            "mean_sell_wr": round(float(ns_mean_sell), 4),
            "assets_with_buy_wr_gt_50": ns_buy_ok,
            "assets_with_both_wr_gt_50": ns_both_ok,
            "results": non_sell_results,
        },
    }


# ── Test A: Label Inversion ──────────────────────────────────────────


def run_label_inversion_test(asset: str, rerun: bool = False) -> dict:
    """Train with flipped labels, evaluate BUY WR against original labels.

    If the inverted model's BUY signal (p_long > threshold) produces BUY WR > 50%
    against ORIGINAL labels, then the BUY signal is recoverable via label reorientation.

    Steps:
    1. Check if inverted-model parquet already exists
    2. If not (or --rerun), call walk_forward_backtest.py --invert-labels
    3. Compute BUY WR against label_original
    4. Compare with baseline BUY WR
    """
    tp, sl = PER_ASSET_PT_SL.get(asset, (2.0, 2.0))
    inv_tag = "inv_labels"

    # Load baseline (non-inverted) stats first
    base_df = load_signals(asset)
    base_stats = compute_direction_stats(base_df, tp, sl) if base_df is not None else None

    # Load or generate inverted-model parquet
    inv_df = load_signals(asset, tag=inv_tag)
    if inv_df is None or rerun:
        logger.info("Generating inverted-label walk-forward for %s...", asset)
        # We need to set PYTHONPATH and run the backtest script
        wfb_path = Path(__file__).resolve().parent.parent / "backtest" / "walk_forward_backtest.py"
        cmd = [
            sys.executable,
            str(wfb_path),
            "--assets",
            asset,
            "--tag",
            inv_tag,
            "--invert-labels",
        ]
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, cwd=Path(__file__).resolve().parent.parent.parent, capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            logger.error("Walk-forward failed for %s:\n%s", asset, result.stderr)
            return {"asset": asset, "status": "FAILED", "error": result.stderr[:500]}
        logger.info("Walk-forward output:\n%s", result.stdout[-300:])
        inv_df = load_signals(asset, tag=inv_tag)

    if inv_df is None:
        return {"asset": asset, "status": "NO_INVERTED_DATA"}

    # The inverted-model parquet has:
    #   label = y_inverted (what model trained/predicted against)
    #   label_original = y_original (ground truth, pre-inversion)
    if "label_original" not in inv_df.columns:
        # Fallback: label_original = 1 - label (if invert-labels was set but older version)
        inv_df["label_original"] = 1 - inv_df["label"].values

    # Compute stats against ORIGINAL labels
    inv_stats = compute_direction_stats(inv_df, tp, sl)

    # Compare: is inverted BUY WR > baseline BUY WR?
    base_buy_wr = base_stats["buy_wr"] if base_stats else 0.0
    base_sell_wr = base_stats["sell_wr"] if base_stats else 0.0

    buy_wr_delta = inv_stats["buy_wr"] - base_buy_wr
    improvement = buy_wr_delta > 0.03  # >3pp improvement
    buy_recovered = inv_stats["buy_wr"] >= 0.50

    if buy_recovered:
        status = "RECOVERED — label inversion restores BUY signal"
    elif improvement and inv_stats["buy_wr"] > base_buy_wr + 0.10:
        status = "IMPROVED — label inversion helps but BUY WR still < 50%"
    elif improvement:
        status = "MARGINAL — small improvement, not sufficient"
    else:
        status = "NOT_RECOVERED — label inversion does not fix BUY inversion"

    return {
        "asset": asset,
        "status": status,
        "buy_wr": inv_stats["buy_wr"],
        "sell_wr": inv_stats["sell_wr"],
        "base_buy_wr": base_buy_wr,
        "base_sell_wr": base_sell_wr,
        "buy_wr_delta": round(buy_wr_delta, 4),
        "total_r": inv_stats["total_r"],
        "base_total_r": base_stats["total_r"] if base_stats else 0,
        "n_buy": inv_stats["n_buy"],
        "n_sell": inv_stats["n_sell"],
        "n_total": inv_stats["n_total"],
        "up_rate": inv_stats["up_rate"],
        # Also compute "corrected signal" — treat model's BUY as SELL and vice versa
        **compute_corrected_stats(inv_df, tp, sl),
    }


def compute_corrected_stats(df: pd.DataFrame, tp: float, sl: float) -> dict:
    """If we flip signal interpretation: SELL when model says BUY, BUY when model says SELL.

    This tests whether the model has correct DIRECTIONAL information but wrong signal assignment.
    """
    y = df["label_original"].values if "label_original" in df.columns else df["label"].values

    p = df["p_long"].values
    # Original signals: BUY on p > 0.575, SELL on p < 0.425
    # Corrected signals: BUY when model says NOT-DOWN (p < 0.425), SELL when model says DOWN (p > 0.575)
    # With inverted model: p = P(DOWN). So:
    #   BUY when P(DOWN) < 0.425 (model says UP)
    #   SELL when P(DOWN) > 0.575 (model says DOWN)
    buy_mask = p > 0.575
    sell_mask = p < 0.425

    n_buy = int(buy_mask.sum())
    n_sell = int(sell_mask.sum())

    # BUY when model says DOWN → profit from DOWN → correct when y=0 (original DOWN)
    buy_correct = int((y[buy_mask] == 0).sum()) if n_buy > 0 else 0
    # SELL when model says NOT-DOWN → profit from UP → correct when y=1 (original UP)
    sell_correct = int((y[sell_mask] == 1).sum()) if n_sell > 0 else 0

    buy_wr_corrected = buy_correct / n_buy if n_buy > 0 else 0.0
    sell_wr_corrected = sell_correct / n_sell if n_sell > 0 else 0.0

    # R-multiple for corrected interpretation
    buy_r_corrected = buy_correct * tp - (n_buy - buy_correct) * sl
    sell_r_corrected = sell_correct * tp - (n_sell - sell_correct) * sl
    total_r_corrected = buy_r_corrected + sell_r_corrected

    return {
        "buy_wr_corrected": round(buy_wr_corrected, 4),
        "sell_wr_corrected": round(sell_wr_corrected, 4),
        "total_r_corrected": round(total_r_corrected, 2),
        "n_buy_corrected": n_buy,
        "n_sell_corrected": n_sell,
    }


# ── Output formatting ────────────────────────────────────────────────


def fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def fmt_r(v: float) -> str:
    return f"{v:+.1f}"


def print_symmetry_results(results: list[dict], label: str):
    print(f"\n{'=' * 80}")
    print(f"  {label}")
    print(f"{'=' * 80}")
    print(
        f"{'Asset':>10s}  {'Status':>25s}  {'BUY WR':>8s}  {'SELL WR':>8s}  {'Asym':>7s}  {'nBUY':>5s}  {'nSELL':>5s}  {'BUY R':>8s}  {'SELL R':>8s}  {'Total R':>9s}"  # noqa: E501
    )  # noqa: E501
    print("-" * 100)
    for r in results:
        print(
            f"{r['asset']:>10s}  {r['status']:>25s}  {fmt_pct(r['buy_wr']):>8s}  {fmt_pct(r['sell_wr']):>8s}  {r['asymmetry']:>+7.3f}  {r['n_buy']:>5d}  {r['n_sell']:>5d}  {fmt_r(r['buy_r']):>8s}  {fmt_r(r['sell_r']):>8s}  {fmt_r(r['total_r']):>9s}"  # noqa: E501
        )  # noqa: E501


def print_inversion_result(r: dict):
    print(f"\n{'=' * 80}")
    print(f"  Test A: Label Inversion — {r['asset']}")
    print(f"{'=' * 80}")
    print(f"  Status:          {r['status']}")
    print(f"  Baseline BUY WR: {fmt_pct(r['base_buy_wr'])}")
    print(f"  Inverted BUY WR: {fmt_pct(r['buy_wr'])}  (Δ {r['buy_wr_delta']:+.1%})")
    print(f"  Baseline SELL WR: {fmt_pct(r['base_sell_wr'])}")
    print(f"  Inverted SELL WR: {fmt_pct(r['sell_wr'])}")
    print(f"  Baseline Total R: {fmt_r(r['base_total_r'])}")
    print(f"  Inverted Total R: {fmt_r(r['total_r'])}")
    print(f"  nBUY={r['n_buy']}  nSELL={r['n_sell']}  nTotal={r['n_total']}  UP_rate={fmt_pct(r['up_rate'])}")
    print()
    print("  Corrected interpretation (SELL when model says BUY):")
    print(f"    BUY WR (corrected): {fmt_pct(r.get('buy_wr_corrected', 0))}")
    print(f"    SELL WR (corrected): {fmt_pct(r.get('sell_wr_corrected', 0))}")
    print(f"    Total R (corrected): {fmt_r(r.get('total_r_corrected', 0))}")


def print_verdict(so_results: list[dict], sufficiency: dict, inv_result: dict | None):
    print(f"\n{'=' * 80}")
    print("  SYNTHESIS AND RECOMMENDATION")
    print(f"{'=' * 80}")

    # How many SELL_ONLY assets have severe asymmetry?
    severe = sum(1 for r in so_results if r["status"] == "SEVERE_ASYMMETRY")
    mod = sum(1 for r in so_results if r["status"] == "MODERATE_ASYMMETRY")
    weak = sum(1 for r in so_results if r["status"] == "WEAK_ASYMMETRY" or r["status"] == "SYMMETRIC")
    no_data = sum(1 for r in so_results if "NO_DATA" in r["status"])

    print(f"\n  Symmetry (Test B): {severe} severe / {mod} moderate / {weak} weak-symmetric / {no_data} no data")
    print(f"  Sufficiency (Test C): {sufficiency['verdict']}")
    if inv_result:
        print(f"  Label Inversion (Test A, {inv_result['asset']}): {inv_result['status']}")

    # Overall verdict
    if severe >= 6:
        print("\n  >>> OVERALL: STRUCTURAL ASYMMETRY CONFIRMED")
        print("      BUY direction not recoverable for majority of SELL_ONLY assets.")
        print("      Recommend: embrace-asymmetry architecture (directional SELL engine)")
    elif severe >= 3 and inv_result and inv_result.get("buy_wr_corrected", 0) < 0.50:
        print("\n  >>> OVERALL: PARTIAL ASYMMETRY")
        print("      Some assets show severe asymmetry even with label correction.")
        print("      Recommend: EURAUD pilot restoration with dual guardrails")
    elif inv_result and inv_result.get("buy_wr", 0) >= 0.50:
        print("\n  >>> OVERALL: BUY RECOVERABLE via label reorientation")
        print("      Recommend: dual-model approach (separate BUY/SELL models)")
    else:
        print("\n  >>> OVERALL: INCONCLUSIVE — more data or different approach needed")
        print("      No single test conclusively determines recoverability.")


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="BUY Signal Existence Diagnostic")
    parser.add_argument("--asset", default=None, help="Single asset to test (default: all SELL_ONLY)")
    parser.add_argument(
        "--rerun-inversion",
        action="store_true",
        default=False,
        help="Regenerate inverted-label walk-forward even if parquet exists",
    )
    args = parser.parse_args()

    # ── Test C: Information Sufficiency (global comparison) ──
    print(f"\n{'#' * 80}")
    print("  TEST C: Information Sufficiency")
    print("  Comparing BUY WR: SELL_ONLY cluster vs non-SELL_ONLY cluster")
    print(f"{'#' * 80}")
    sufficiency = run_sufficiency_test()

    so_results = sufficiency["sell_only"]["results"]
    ns_results = sufficiency["non_sell_only"]["results"]

    print_symmetry_results(so_results, "SELL_ONLY Assets")
    print_symmetry_results(ns_results, "Non-SELL_ONLY Assets")
    print(f"\n  Sufficiency verdict: {sufficiency['verdict']}")

    # ── Test B: Symmetry Test (per-asset asymmetry) ──
    print(f"\n{'#' * 80}")
    print("  TEST B: Asymmetry Analysis (per-asset)")
    print("  asymmetry = sell_wr - buy_wr at default 0.575/0.425 threshold")
    print(f"{'#' * 80}")

    # Already computed in sufficiency

    # ── Test A: Label Inversion (EURAUD pilot) ──
    print(f"\n{'#' * 80}")
    print("  TEST A: Label Inversion")
    print("  Training model with y' = 1-y to test if BUY signal is recoverable")
    print("  via label reorientation")
    print(f"{'#' * 80}")

    inv_target = args.asset if args.asset else "EURAUD"
    if inv_target in SELL_ONLY_ASSETS:
        inv_result = run_label_inversion_test(inv_target, rerun=args.rerun_inversion)
        print_inversion_result(inv_result)
    else:
        inv_result = None
        print(f"  Skipped: {inv_target} is not a SELL_ONLY asset")

    # ── Synthesis ──
    print_verdict(so_results, sufficiency, inv_result)

    # ── Recommendations for gatekeeper ──
    print(f"\n{'=' * 80}")
    print("  RECOMMENDED GATEKEEPER CRITERIA")
    print(f"{'=' * 80}")
    print("""
  Before any SELL_ONLY asset can be restored to two-way trading:

  1. PASS label inversion test (Test A) — inverted-model BUY WR > 50%
     against original labels for the specific asset.

  2. PASS sufficiency test (Test C) — at least 6/8 SELL_ONLY assets show
     BUY WR > 40% (indicating the BUY signal exists, even if weak).

  3. Shadow mode (30 trading days) — hypothetical trades show BUY WR > 50%
     and total R > 0 with at least 10 BUY trades.

  4. Tripwire protection — three-level rollback active:
     L1: warning if 20-trade BUY WR < 35%
     L2: protection if 40-trade BUY WR < 35% (reduce allocation 50%)
     L3: reversion if 60-trade BUY WR < 35% OR BUY R < 0 (return to SELL_ONLY)
  """)


if __name__ == "__main__":
    main()
