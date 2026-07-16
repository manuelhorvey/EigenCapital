#!/usr/bin/env python3
"""
Model Quality Diagnostics — ROC & Calibration Curves.

Reads the trade lifecycle JSON and generates a two-panel diagnostic chart:

  1. ROC curves      — per-asset receiver operating characteristic with AUC
  2. Calibration     — per-asset reliability diagram with ECE (Expected
                       Calibration Error)

Also prints a summary table of AUC and ECE for all 22 assets.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/model_quality_diagnostics.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/model_quality_diagnostics.py \\
        --json data/processed/audits/trade_lifecycle_results.json \\
        --output-dir data/processed
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "data" / "processed" / "audits" / "trade_lifecycle_results.json"
OUTPUT_DIR = ROOT / "data" / "processed" / "charts"

# ── Color scheme (matches simulation_diagnostics.py) ──
BG = "#0f1119"
BG2 = "#1a1c2a"
TEXT = "#ccccdd"
TEXT2 = "#888899"
GREEN = "#3dd9ae"
RED = "#ef4444"
BLUE = "#5b8def"
AMBER = "#f59e0b"
PURPLE = "#a78bfa"
GRID = "#2a2a3a"
SPINE = "#333344"


def load_data(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _safe(val: float | None, default: float = 0.0) -> float:
    """Return val if it's a finite number, else default."""
    if val is None:
        return default
    if isinstance(val, (int, float)) and not math.isnan(val) and math.isfinite(val):
        return float(val)
    return default


def _compute_roc(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_thresholds: int = 200,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Compute ROC curve and AUC.

    Parameters
    ----------
    y_true : np.ndarray
        Binary labels (1 = win, 0 = loss).
    y_score : np.ndarray
        Predicted probabilities (p_long for BUY accuracy, or 1-p_long for SELL).
    n_thresholds : int
        Number of thresholds to evaluate.

    Returns
    -------
    fpr, tpr, auc : (np.ndarray, np.ndarray, float)
    """
    # Sort by score descending
    order = np.argsort(-y_score)
    y_true = y_true[order]
    y_score = y_score[order]

    n_pos = y_true.sum()
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return np.array([0, 1]), np.array([0, 1]), 0.5

    # Generate thresholds
    thresholds = np.linspace(0, 1, n_thresholds + 1)

    fpr = np.zeros(n_thresholds + 1)
    tpr = np.zeros(n_thresholds + 1)

    for i, th in enumerate(thresholds):
        pred = y_score >= th
        tp = (pred & (y_true == 1)).sum()
        fp = (pred & (y_true == 0)).sum()
        fn = n_pos - tp
        tn = n_neg - fp

        tpr[i] = tp / n_pos if n_pos > 0 else 0
        fpr[i] = fp / n_neg if n_neg > 0 else 0

    # Sort by fpr ascending (may be out of order due to score ties)
    order_fpr = np.argsort(fpr)
    fpr = fpr[order_fpr]
    tpr = tpr[order_fpr]

    # AUC via trapezoidal rule
    auc = float(np.trapz(tpr, fpr))

    return fpr, tpr, auc


def _compute_calibration(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_bins: int = 10,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Compute calibration curve and ECE.

    Parameters
    ----------
    y_true : np.ndarray
        Binary labels.
    y_score : np.ndarray
        Predicted probabilities.
    n_bins : int
        Number of equal-width bins.

    Returns
    -------
    bin_centers : np.ndarray
        Center of each bin.
    accuracies : np.ndarray
        Actual frequency in each bin.
    counts : np.ndarray
        Number of samples in each bin.
    ece : float
        Expected Calibration Error.
    """
    bins = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    accuracies = np.zeros(n_bins)
    counts = np.zeros(n_bins)

    # Last bin includes right edge to catch p_long == 1.0
    for i in range(n_bins):
        lo = bins[i]
        hi = bins[i + 1]
        if i == n_bins - 1:
            mask = (y_score >= lo) & (y_score <= hi)
        else:
            mask = (y_score >= lo) & (y_score < hi)
        n_in_bin = mask.sum()
        counts[i] = n_in_bin
        if n_in_bin > 0:
            accuracies[i] = y_true[mask].mean()
        else:
            accuracies[i] = np.nan

    # ECE: weighted average of |predicted - actual|
    ece = 0.0
    total = len(y_score)
    for i in range(n_bins):
        if counts[i] > 0 and not np.isnan(accuracies[i]):
            ece += (counts[i] / total) * abs(bin_centers[i] - accuracies[i])

    return bin_centers, accuracies, counts, ece


def _compute_metrics(
    trades: list[dict],
) -> dict:
    """Compute ROC (BUY + SELL) and calibration for a single asset's trades.

    Direction-conditional labels:
    - BUY side: only trades where model predicted BUY (p_long > 0.5).
      Score = p_long. Label = 1 if profitable, 0 if loss.
    - SELL side: only trades where model predicted SELL (p_long < 0.5).
      Score = 1 - p_long. Label = 1 if profitable, 0 if loss.

    This avoids the mathematical redundancy of using the same labels
    for both sides (which forces SELL AUC = 1 - BUY AUC).
    """
    y_buy: list[float] = []
    s_buy: list[float] = []
    y_sell: list[float] = []
    s_sell: list[float] = []
    y_all: list[float] = []
    p_all: list[float] = []

    for t in trades:
        rm = _safe(t.get("r_multiple"))
        pl = _safe(t.get("p_long"), 0.5)
        outcome = 1.0 if rm > 0 else 0.0
        y_all.append(outcome)
        p_all.append(pl)
        if pl > 0.5:
            y_buy.append(outcome)
            s_buy.append(pl)
        else:
            y_sell.append(outcome)
            s_sell.append(1.0 - pl)

    arr_all = np.array(y_all, dtype=float)
    arr_p = np.array(p_all, dtype=float)
    arr_buy_y = np.array(y_buy, dtype=float)
    arr_buy_s = np.array(s_buy, dtype=float)
    arr_sell_y = np.array(y_sell, dtype=float)
    arr_sell_s = np.array(s_sell, dtype=float)

    # BUY ROC: only BUY-direction trades
    if len(arr_buy_y) >= 5:
        fpr_b, tpr_b, auc_b = _compute_roc(arr_buy_y, arr_buy_s)
    else:
        fpr_b, tpr_b, auc_b = np.array([0, 1]), np.array([0, 1]), 0.5

    # SELL ROC: only SELL-direction trades
    if len(arr_sell_y) >= 5:
        fpr_s, tpr_s, auc_s = _compute_roc(arr_sell_y, arr_sell_s)
    else:
        fpr_s, tpr_s, auc_s = np.array([0, 1]), np.array([0, 1]), 0.5

    # Calibration uses ALL trades (p_long vs outcome)
    bc, acc, cnt, ece = _compute_calibration(arr_all, arr_p)

    return {
        "auc_buy": auc_b,
        "auc_sell": auc_s,
        "ece": ece,
        "n_trades": len(trades),
        "win_rate": float(arr_all.mean()) * 100,
        "roc_buy": (fpr_b, tpr_b),
        "roc_sell": (fpr_s, tpr_s),
        "calibration": (bc, acc, cnt),
        "avg_p_long": float(arr_p.mean()),
        "n_buy_trades": len(arr_buy_y),
        "n_sell_trades": len(arr_sell_y),
    }


def generate_roc_calibration_chart(data: dict, output_dir: Path) -> Path:
    """Generate two-panel ROC + Calibration chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    trades = data.get("_trades", {})
    if not trades:
        print("  WARNING: No trade data found. Skipping chart.")
        return output_dir / "model_quality_placeholder.txt"

    # Compute metrics per asset
    asset_metrics: dict[str, dict] = {}
    for asset, ts in trades.items():
        asset_metrics[asset] = _compute_metrics(ts)

    assets_sorted = sorted(asset_metrics.keys())
    n_assets = len(assets_sorted)

    if n_assets == 0:
        print("  WARNING: Empty asset list. Skipping chart.")
        return output_dir / "model_quality_placeholder.txt"

    # ── Build the figure: BUY ROC | SELL ROC | Calibration ──
    fig, (ax_buy, ax_sell, ax_cal) = plt.subplots(1, 3, figsize=(18, 7))
    fig.patch.set_facecolor(BG)

    for ax in [ax_buy, ax_sell, ax_cal]:
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT2)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        for s in ["left", "bottom"]:
            ax.spines[s].set_color(SPINE)
        ax.grid(True, alpha=0.08, color=GRID)

    # ── Color mapping by AUC tier ──
    def _auc_color(auc: float) -> str:
        if auc >= 0.65:
            return GREEN
        elif auc >= 0.55:
            return BLUE
        elif auc >= 0.45:
            return AMBER
        else:
            return RED

    # Collect all AUCs for ranking
    all_aucs_buy = {a: asset_metrics[a]["auc_buy"] for a in assets_sorted}
    all_aucs_sell = {a: asset_metrics[a]["auc_sell"] for a in assets_sorted}
    all_eces = {a: asset_metrics[a]["ece"] for a in assets_sorted}

    def _plot_roc(ax, auc_dict, label_prefix, title_suffix):
        """Plot ROC curves for a given side (BUY or SELL)."""
        ax.plot([0, 1], [0, 1], color=TEXT2, linewidth=0.6, linestyle="--", alpha=0.5,
                label="Random (AUC=0.50)")

        auc_values = np.array(list(auc_dict.values()))
        auc_median = float(np.median(auc_values))
        auc_best = max(auc_values)
        auc_worst = min(auc_values)
        best_asset = max(auc_dict, key=auc_dict.get)
        worst_asset = min(auc_dict, key=auc_dict.get)

        for asset in assets_sorted:
            m = asset_metrics[asset]
            key = "roc_buy" if label_prefix == "BUY" else "roc_sell"
            fpr, tpr = m[key]
            auc_val = auc_dict[asset]
            color = _auc_color(auc_val)
            lw = 1.8 if asset in (best_asset, worst_asset) else 0.7
            alpha_v = 0.9 if asset in (best_asset, worst_asset) else 0.3
            label = f"{asset} (AUC={auc_val:.3f})" if asset in (best_asset, worst_asset) else None
            ax.plot(fpr, tpr, color=color, linewidth=lw, alpha=alpha_v, label=label)

        ax.text(0.12, 0.06, f"Best: {best_asset} (AUC={auc_best:.3f})",
                fontsize=8.5, color=GREEN, fontweight="bold", transform=ax.transAxes)
        ax.text(0.12, 0.01, f"Worst: {worst_asset} (AUC={auc_worst:.3f})",
                fontsize=8.5, color=RED, fontweight="bold", transform=ax.transAxes)

        ax.set_xlabel("False Positive Rate", fontsize=10, color=TEXT)
        ax.set_ylabel("True Positive Rate", fontsize=10, color=TEXT)
        ax.set_title(
            f"{label_prefix} ROC — {n_assets} Assets  (Median AUC: {auc_median:.3f})",
            fontsize=12, fontweight="bold", color=TEXT, pad=8,
        )
        ax.legend(loc="lower right", fontsize=7, facecolor=BG2, edgecolor=SPINE,
                  labelcolor=TEXT)

        # AUC distribution inset
        auc_sorted = sorted(auc_values)
        auc_colors = [_auc_color(v) for v in auc_sorted]
        ins = ax.inset_axes([0.55, 0.08, 0.4, 0.18])
        ins.set_facecolor(BG2)
        ins.tick_params(colors=TEXT2, labelsize=5.5)
        for s in ins.spines.values():
            s.set_color(SPINE)
        ins.bar(range(len(auc_sorted)), auc_sorted, color=auc_colors,
                edgecolor="none", width=0.8, alpha=0.8)
        ins.axhline(0.5, color=TEXT2, linewidth=0.5, linestyle="--", alpha=0.5)
        ins.set_ylabel("AUC", fontsize=6.5, color=TEXT2)
        ins.set_xlabel("Assets", fontsize=6.5, color=TEXT2)
        ins.set_ylim(0, 1)

    # ── LEFT PANEL: BUY ROC (p_long) ──
    _plot_roc(ax_buy, all_aucs_buy, "BUY", "(p_long)")

    # ── MIDDLE PANEL: SELL ROC (1 - p_long) ──
    _plot_roc(ax_sell, all_aucs_sell, "SELL", "(1 − p_long)")

    # ── RIGHT PANEL: Calibration Curves ──
    ax_cal.plot([0, 1], [0, 1], color=TEXT2, linewidth=0.8, linestyle="-", alpha=0.4,
                label="Perfect calibration")

    # Find best/worst ECE assets (these are local to this scope, not from _plot_roc)
    ece_best_asset = min(all_eces, key=all_eces.get)
    ece_worst_asset = max(all_eces, key=all_eces.get)

    n_bins = 10
    cal_bin_centers = (np.linspace(0, 1, n_bins + 1)[:-1] + np.linspace(0, 1, n_bins + 1)[1:]) / 2
    ece_values = []
    for asset in assets_sorted:
        m = asset_metrics[asset]
        bc, acc, cnt = m["calibration"]
        ece = m["ece"]
        ece_values.append(ece)
        color = _auc_color(m["auc_buy"])
        lw = 1.8 if asset in (ece_best_asset, ece_worst_asset) else 0.7
        alpha_v = 0.9 if asset in (ece_best_asset, ece_worst_asset) else 0.25
        label = f"{asset} (ECE={ece:.3f})" if asset in (ece_best_asset, ece_worst_asset) else None
        # Only plot bins with data
        valid = ~np.isnan(acc)
        ax_cal.plot(bc[valid], acc[valid], color=color, linewidth=lw,
                    alpha=alpha_v, marker=".", markersize=3, label=label)

    ece_median = float(np.median(ece_values))
    ece_best_v = min(ece_values)
    ece_worst_v = max(ece_values)

    ax_cal.text(0.55, 0.3, f"Best: {ece_best_asset} (ECE={ece_best_v:.3f})",
                fontsize=9, color=GREEN, fontweight="bold", transform=ax_cal.transAxes)
    ax_cal.text(0.55, 0.24, f"Worst: {ece_worst_asset} (ECE={ece_worst_v:.3f})",
                fontsize=9, color=RED, fontweight="bold", transform=ax_cal.transAxes)

    ax_cal.set_xlabel("Predicted Probability (p_long)", fontsize=11, color=TEXT)
    ax_cal.set_ylabel("Actual Win Frequency", fontsize=11, color=TEXT)
    ax_cal.set_title(
        f"Calibration Curves — {n_assets} Assets  (Median ECE: {ece_median:.3f})",
        fontsize=13, fontweight="bold", color=TEXT, pad=10,
    )
    ax_cal.legend(loc="upper left", fontsize=8, facecolor=BG2, edgecolor=SPINE,
                  labelcolor=TEXT)

    # ECE distribution inset
    ece_sorted = sorted(ece_values)
    ax_cal_inset = ax_cal.inset_axes([0.08, 0.55, 0.35, 0.2])
    ax_cal_inset.set_facecolor(BG2)
    ax_cal_inset.tick_params(colors=TEXT2, labelsize=6)
    for s in ax_cal_inset.spines.values():
        s.set_color(SPINE)
    ece_colors = [GREEN if v <= 0.05 else (AMBER if v <= 0.10 else RED) for v in ece_sorted]
    ax_cal_inset.bar(range(len(ece_sorted)), ece_sorted, color=ece_colors,
                     edgecolor="none", width=0.8, alpha=0.8)
    ax_cal_inset.set_ylabel("ECE", fontsize=7, color=TEXT2)
    ax_cal_inset.set_xlabel("Assets (sorted)", fontsize=7, color=TEXT2)

    # ── Summary annotation ──
    auc_buy_vals = np.array(list(all_aucs_buy.values()))
    auc_sell_vals = np.array(list(all_aucs_sell.values()))
    total_trades = sum(len(ts) for ts in trades.values())

    buy_med = float(np.median(auc_buy_vals))
    sell_med = float(np.median(auc_sell_vals))
    n_auc_good_buy = sum(1 for v in auc_buy_vals if v >= 0.6)
    n_auc_good_sell = sum(1 for v in auc_sell_vals if v >= 0.6)

    # Find which side each asset favors
    n_buy_better = sum(1 for a in assets_sorted if asset_metrics[a]["auc_buy"] > asset_metrics[a]["auc_sell"])
    n_sell_better = n_assets - n_buy_better

    summary = (
        f"{total_trades:,} trades, {n_assets} assets  |  "
        f"BUY median AUC: {buy_med:.3f} ({n_auc_good_buy}/{n_assets} ≥0.60)  |  "
        f"SELL median AUC: {sell_med:.3f} ({n_auc_good_sell}/{n_assets} ≥0.60)  |  "
        f"Assets BUY-better: {n_buy_better} / SELL-better: {n_sell_better}"
    )
    fig.text(0.5, 0.005, summary, ha="center", fontsize=8.5, color=TEXT2, family="monospace")

    plt.tight_layout()
    path = output_dir / "model_quality_roc_calibration.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def print_summary_table(asset_metrics: dict[str, dict]) -> None:
    """Print a formatted summary table with BUY AUC, SELL AUC and direction favor."""
    sep = "─" * 110
    print(f"\\n  BUY vs SELL Model Quality — {len(asset_metrics)} Assets")
    print(f"  {sep}")
    header = (f"  {'Asset':<10s} {'Total':>6s} {'BUY#':>5s} {'BL%':>4s} {'SELL#':>6s} {'SL%':>4s} "
              f"{'AUC_BUY':>8s} {'AUC_SELL':>8s} {'Δ':>7s} {'Dir':>7s} {'ECE':>6s}")
    print(header)
    print(f"  {'─'*10} {'─'*6} {'─'*5} {'─'*4} {'─'*6} {'─'*4} {'─'*8} {'─'*8} {'─'*7} {'─'*7} {'─'*6}")

    def _dir(auc_b, auc_s) -> str:
        if auc_b >= 0.55 and auc_s >= 0.55:
            return "BOTH"
        elif auc_b >= 0.55:
            return "BUY"
        elif auc_s >= 0.55:
            return "SELL"
        else:
            return "none"

    for asset in sorted(asset_metrics.keys()):
        m = asset_metrics[asset]
        auc_b = m["auc_buy"]
        auc_s = m["auc_sell"]
        delta = auc_b - auc_s
        d = _dir(auc_b, auc_s)
        n_b = m.get("n_buy_trades", 0)
        n_s = m.get("n_sell_trades", 0)
        tot = m["n_trades"]
        wr = m["win_rate"]
        buy_pct = n_b / tot * 100 if tot > 0 else 0
        sell_pct = n_s / tot * 100 if tot > 0 else 0
        print(
            f"  {asset:<10s} {tot:>6d} {n_b:>5d} {buy_pct:>3.0f}% {n_s:>6d} {sell_pct:>3.0f}% "
            f"{auc_b:>8.3f} {auc_s:>8.3f} {delta:>+7.3f} {d:>7s} {m['ece']:>6.3f}"
        )

    avg_auc_b = float(np.mean([m["auc_buy"] for m in asset_metrics.values()]))
    avg_auc_s = float(np.mean([m["auc_sell"] for m in asset_metrics.values()]))
    avg_ece = float(np.mean([m["ece"] for m in asset_metrics.values()]))
    n_buy_better = sum(1 for m in asset_metrics.values() if m["auc_buy"] > m["auc_sell"])

    print(f"  {'─'*10} {'─'*6} {'─'*5} {'─'*4} {'─'*6} {'─'*4} {'─'*8} {'─'*8} {'─'*7} {'─'*7} {'─'*6}")
    print(f"  {'Portfolio':<10s} {'':>6s} {'':>5s} {'':>4s} {'':>6s} {'':>4s} "
          f"{avg_auc_b:>8.3f} {avg_auc_s:>8.3f} "
          f"{avg_auc_b - avg_auc_s:>+7.3f} {'':>7s} {avg_ece:>6.3f}")
    print(f"  {'BUY-better':>10s} {n_buy_better:>7d} assets")
    print(f"  {'SELL-better':>10s} {len(asset_metrics) - n_buy_better:>7d} assets")
    print(f"  {sep}")


def print_auroc_sheet(asset_metrics: dict[str, dict]) -> None:
    """Print a compact AUROC sheet sorted by BUY AUC descending."""
    print(f"\n  AUROC Sheet (sorted by BUY AUC descending):")
    sep = "─" * 56
    print(f"  {sep}")
    print(f"  {'Asset':<10s}  {'AUC_BUY':>8s}  {'AUC_SELL':>8s}  {'Δ':>7s}  {'ECE':>6s}")
    print(f"  {sep}")
    for asset in sorted(asset_metrics, key=lambda a: asset_metrics[a]["auc_buy"], reverse=True):
        m = asset_metrics[asset]
        d = m["auc_buy"] - m["auc_sell"]
        print(f"  {asset:<10s}  {m['auc_buy']:>8.3f}  {m['auc_sell']:>8.3f}  {d:>+7.3f}  {m['ece']:>6.3f}")
    print(f"  {sep}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Model Quality Diagnostics — ROC & Calibration Curves"
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="Path to trade lifecycle JSON",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for chart",
    )
    args = parser.parse_args()

    json_path = Path(args.json) if args.json else JSON_PATH
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading trade data from: {json_path}")
    data = load_data(json_path)

    trades = data.get("_trades", {})
    if not trades:
        print("ERROR: No trade data found.")
        sys.exit(1)

    total_trades = sum(len(ts) for ts in trades.values())
    print(f"Loaded {total_trades:,} trades across {len(trades)} assets")

    # Compute metrics
    print("\nComputing per-asset ROC and calibration...")
    asset_metrics: dict[str, dict] = {}
    for asset, ts in trades.items():
        asset_metrics[asset] = _compute_metrics(ts)
    print(f"  Done — {len(asset_metrics)} assets processed.")

    # Print summary table
    print_summary_table(asset_metrics)
    print_auroc_sheet(asset_metrics)

    # Generate chart
    print("\nGenerating chart...")
    chart_path = generate_roc_calibration_chart(data, out_dir)

    print(f"\nDone — 1 chart generated:")
    print(f"  {chart_path.name}")


if __name__ == "__main__":
    main()
