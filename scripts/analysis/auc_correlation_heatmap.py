#!/usr/bin/env python3
"""
Per-Asset AUC Correlation Heatmap.

Reads the trade lifecycle JSON, computes per-asset AUC per calendar month,
and generates a correlation heatmap showing which assets' prediction quality
co-moves over time.

Uses non-overlapping calendar-month windows instead of trade-count rolling
windows so that all assets are properly aligned in time.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/auc_correlation_heatmap.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/auc_correlation_heatmap.py \\
        --json data/processed/trade_data/trade_lifecycle_results.json \\
        --output-dir data/processed
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "data" / "processed" / "audits" / "trade_lifecycle_results.json"
OUTPUT_DIR = ROOT / "data" / "processed" / "charts"

# ── Color scheme (matches other diagnostics) ──
BG = "#0f1119"
BG2 = "#1a1c2a"
TEXT = "#ccccdd"
TEXT2 = "#888899"
GREEN = "#3dd9ae"
RED = "#ef4444"
BLUE = "#5b8def"
AMBER = "#f59e0b"
SPINE = "#333344"


def load_data(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _safe(val: float | None, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)) and not math.isnan(val) and math.isfinite(val):
        return float(val)
    return default


def _compute_auc(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_thresholds: int = 100,
) -> float:
    """Compute AUC for a single asset-period."""
    if len(y_true) < 5:
        return float("nan")
    order = np.argsort(-y_score)
    y_true = y_true[order]
    y_score = y_score[order]

    n_pos = int(y_true.sum())
    n_neg = len(y_true) - n_pos
    if n_pos < 2 or n_neg < 2:
        return float("nan")

    thresholds = np.linspace(0, 1, n_thresholds + 1)
    fpr = np.zeros(n_thresholds + 1)
    tpr = np.zeros(n_thresholds + 1)

    for i, th in enumerate(thresholds):
        pred = y_score >= th
        tp = int((pred & (y_true == 1)).sum())
        fp = int((pred & (y_true == 0)).sum())
        tpr[i] = tp / n_pos
        fpr[i] = fp / n_neg

    order_fpr = np.argsort(fpr)
    fpr = fpr[order_fpr]
    tpr = tpr[order_fpr]
    return float(np.trapz(tpr, fpr))


def _compute_monthly_aucs(
    trades: list[dict],
    min_per_month: int = 10,
) -> list[dict]:
    """Compute AUC per calendar month for a single asset.

    Uses non-overlapping calendar-month windows so that all assets are
    properly aligned in time. Months with fewer than *min_per_month* trades
    are skipped.

    Parameters
    ----------
    trades : list[dict]
        Trades for a single asset (any order — will be sorted internally).
    min_per_month : int
        Minimum trades per month to compute a reliable AUC.

    Returns
    -------
    list[dict]
        Each entry: {'month': str (YYYY-MM), 'auc': float, 'n': int}.
        Sorted by month ascending.
    """
    if not trades:
        return []

    # Group by calendar month
    monthly: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        ed = t.get("entry_date", "")
        month = ed[:7] if len(ed) >= 7 else ""
        if month:
            monthly[month].append(t)

    results = []
    for month in sorted(monthly.keys()):
        chunk = monthly[month]
        if len(chunk) < min_per_month:
            continue

        y_true = []
        y_score = []
        for t in chunk:
            rm = _safe(t.get("r_multiple"))
            pl = _safe(t.get("p_long"), 0.5)
            y_true.append(1.0 if rm > 0 else 0.0)
            y_score.append(pl)

        arr_true = np.array(y_true, dtype=float)
        arr_score = np.array(y_score, dtype=float)
        auc = _compute_auc(arr_true, arr_score)

        if not math.isnan(auc):
            results.append({
                "month": month,
                "auc": round(auc, 4),
                "n": len(chunk),
            })

    return results


def build_auc_series(
    trades: dict[str, list[dict]],
    min_total: int = 40,
    min_per_month: int = 10,
    min_months: int = 4,
) -> dict[str, list[dict]]:
    """Build monthly AUC series for all eligible assets.

    Parameters
    ----------
    trades : dict[str, list[dict]]
        Per-asset trade lists from the lifecycle JSON.
    min_total : int
        Minimum total trades for an asset to be considered.
    min_per_month : int
        Minimum trades per month for a reliable AUC.
    min_months : int
        Minimum number of months with AUC to include the asset.

    Returns
    -------
    dict[str, list[dict]]
        asset → [{'month': str, 'auc': float, 'n': int}, ...]
    """
    result: dict[str, list[dict]] = {}
    for asset, ts in trades.items():
        if len(ts) < min_total:
            continue
        series = _compute_monthly_aucs(ts, min_per_month)
        if len(series) >= min_months:
            result[asset] = series
    return result


def generate_auc_correlation_chart(
    auc_series: dict[str, list[dict]],
    output_dir: Path,
    corr_method: str = "pearson",
) -> Path:
    """Generate a per-asset AUC correlation heatmap with hierarchical clustering dendrogram.

    Parameters
    ----------
    auc_series : dict[str, list[dict]]
        asset → [{'month': str, 'auc': float, 'n': int}, ...]
    output_dir : Path
        Output directory for the chart PNG.
    corr_method : str
        "pearson" or "spearman". Spearman is rank-based and more robust to AUC outliers.

    Returns
    -------
    Path
        Path to the saved chart PNG.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from scipy.cluster.hierarchy import dendrogram as scipy_dendrogram, linkage
    from scipy.stats import spearmanr

    n_assets = len(auc_series)
    if n_assets < 3:
        print(f"  WARNING: Only {n_assets} assets have sufficient data. Skipping heatmap.")
        return output_dir / "auc_correlation_placeholder.txt"

    MIN_OVERLAP = 3  # minimum overlapping months to compute a correlation

    # Build a month-aligned matrix
    all_months = sorted(set(
        d["month"]
        for series in auc_series.values()
        for d in series
    ))

    month_to_idx = {m: i for i, m in enumerate(all_months)}
    n_months = len(all_months)
    asset_names = sorted(auc_series.keys())

    auc_matrix = np.full((n_months, n_assets), np.nan)
    for j, asset in enumerate(asset_names):
        for entry in auc_series[asset]:
            i = month_to_idx[entry["month"]]
            auc_matrix[i, j] = entry["auc"]

    # Compute pairwise correlation using overlapping months only
    corr_matrix = np.full((n_assets, n_assets), np.nan)
    for i in range(n_assets):
        for j in range(i, n_assets):
            col_i = auc_matrix[:, i]
            col_j = auc_matrix[:, j]
            valid = ~np.isnan(col_i) & ~np.isnan(col_j)
            if valid.sum() >= MIN_OVERLAP:
                with np.errstate(invalid="ignore"):
                    if corr_method == "spearman":
                        c, _ = spearmanr(col_i[valid], col_j[valid])
                    else:
                        c = float(np.corrcoef(col_i[valid], col_j[valid])[0, 1])
                if not math.isnan(c):
                    corr_matrix[i, j] = c
                    corr_matrix[j, i] = c

    if np.all(np.isnan(corr_matrix)):
        print("  WARNING: Could not compute any correlations. Skipping heatmap.")
        return output_dir / "auc_correlation_placeholder.txt"

    # ── Hierarchical clustering ──
    # Convert correlation to distance (1 - corr), replace NaN with 0
    dist_matrix = 1.0 - np.nan_to_num(corr_matrix, nan=0.0)
    # Ensure diagonal is 0
    np.fill_diagonal(dist_matrix, 0.0)
    # Condensed form
    condensed = dist_matrix[np.triu_indices(n_assets, k=1)]

    # Compute linkage (average / UPGMA is robust for correlation data)
    link = linkage(condensed, method="average")

    # Get leaf order from dendrogram
    dn = scipy_dendrogram(link, no_plot=True)
    leaf_order = dn["leaves"]  # indices into asset_names matching the clustered order

    # Reorder by dendrogram leaf order
    corr_sorted = corr_matrix[leaf_order][:, leaf_order]
    assets_sorted = [asset_names[i] for i in leaf_order]

    # ── Build figure with GridSpec: dendrogram | heatmap ──
    figsize = max(7, n_assets * 0.5)
    fig = plt.figure(figsize=(figsize + 1.5, figsize * 0.9))
    fig.patch.set_facecolor(BG)

    # GridSpec: dendrogram column is narrower
    gs = fig.add_gridspec(1, 2, width_ratios=[0.35, 1.0], wspace=0.02)
    ax_dendro = fig.add_subplot(gs[0])
    ax_heat = fig.add_subplot(gs[1])

    # ── Dendrogram ──
    ax_dendro.set_facecolor(BG)
    ax_dendro.tick_params(colors=TEXT2, labelsize=5)
    for s in ["top", "right", "left", "bottom"]:
        ax_dendro.spines[s].set_visible(False)

    # Render dendrogram with matching orientation
    scipy_dendrogram(
        link,
        ax=ax_dendro,
        orientation="left",
        leaf_font_size=0,  # labels on the heatmap instead
        link_color_func=lambda k: TEXT2,
        color_threshold=0,
    )
    ax_dendro.set_xticks([])
    ax_dendro.set_yticks([])
    ax_dendro.set_ylabel("Linkage distance", fontsize=7, color=TEXT2, labelpad=3)

    # ── Heatmap ──
    ax_heat.set_facecolor(BG)
    ax_heat.tick_params(colors=TEXT2)
    for s in ["top", "right", "left", "bottom"]:
        ax_heat.spines[s].set_visible(False)

    cmap = LinearSegmentedColormap.from_list(
        "diverging", [BLUE, BG2, RED], N=256
    )

    im = ax_heat.imshow(
        corr_sorted,
        cmap=cmap,
        aspect="equal",
        vmin=-1.0,
        vmax=1.0,
        interpolation="nearest",
    )

    # Annotate cells
    for i in range(n_assets):
        for j in range(n_assets):
            val = corr_sorted[i, j]
            if not np.isnan(val):
                c = GREEN if abs(val) > 0.5 else TEXT2
                w = "bold" if abs(val) > 0.5 else "normal"
                ax_heat.text(
                    j, i, f"{val:+.2f}",
                    ha="center", va="center",
                    fontsize=6.5, color=c, fontweight=w,
                )

    ax_heat.set_xticks(range(n_assets))
    ax_heat.set_xticklabels(
        assets_sorted, fontsize=7.5, color=TEXT2,
        rotation=45, ha="right",
    )
    ax_heat.set_yticks(range(n_assets))
    ax_heat.set_yticklabels(assets_sorted, fontsize=7.5, color=TEXT2)

    # Cluster brackets: find natural groups from the dendrogram
    # Count clusters at a threshold that gives 3-6 groups
    try:
        from scipy.cluster.hierarchy import fcluster
        # Cut at 60% of max linkage distance
        max_dist = link[-1, 2] if len(link) > 0 else 1.0
        clusters = fcluster(link, t=0.6 * max_dist, criterion="distance")
        n_clusters = len(set(clusters))
        # Draw bracket annotations on the dendrogram side
        cluster_info = f"{n_clusters} clusters"
    except Exception:
        cluster_info = ""

    title = (
        f"Per-Asset Monthly AUC Correlation — {n_assets} Assets"
        + (f"  |  {cluster_info}" if cluster_info else "")
    )
    ax_heat.set_title(
        title,
        fontsize=12, fontweight="bold", color=TEXT, pad=10,
    )

    cbar = fig.colorbar(im, ax=ax_heat, fraction=0.04, pad=0.02, shrink=0.8)
    cbar.ax.tick_params(colors=TEXT2)
    cbar_label = "Spearman ρ (monthly AUC)" if corr_method == "spearman" else "Pearson r (monthly AUC)"
    cbar.set_label(cbar_label, fontsize=9, color=TEXT)

    # Summary stats
    flat = corr_matrix[~np.isnan(corr_matrix)]
    off_diag = flat[flat < 0.99]
    best_r = float(np.nanmax(off_diag)) if len(off_diag) > 0 else 0
    worst_r = float(np.nanmin(corr_matrix))
    med_r = float(np.nanmedian(off_diag)) if len(off_diag) > 0 else 0
    n_strong = int((np.abs(off_diag) > 0.5).sum()) if len(off_diag) > 0 else 0
    n_pairs = len(off_diag)

    summary = (
        f"{n_assets} assets, {n_months} months  |  "
        f"Best pair: r={best_r:+.2f}  |  "
        f"Worst pair: r={worst_r:+.2f}  |  "
        f"Median off-diag: {med_r:+.2f}  |  "
        f"|r|>0.5: {n_strong}/{n_pairs}"
    )
    fig.text(0.5, 0.005, summary, ha="center", fontsize=8, color=TEXT2, family="monospace")

    plt.tight_layout()
    path = output_dir / "auc_correlation_heatmap.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def print_summary(auc_series: dict[str, list[dict]]) -> None:
    """Print per-asset monthly AUC summary."""
    print(f"\n  Monthly AUC Summary ({len(auc_series)} assets):")
    sep = "─" * 68
    print(f"  {sep}")
    print(f"  {'Asset':<10s} {'Months':>7s}  {'Avg AUC':>8s}  {'Min AUC':>8s}  {'Max AUC':>8s}  {'Avg n/mo':>9s}")
    print(f"  {sep}")
    for asset in sorted(auc_series.keys()):
        series = auc_series[asset]
        aucs = [s["auc"] for s in series]
        ns = [s["n"] for s in series]
        print(f"  {asset:<10s} {len(series):>7d}  {float(np.mean(aucs)):>8.3f}  "
              f"{float(np.min(aucs)):>8.3f}  {float(np.max(aucs)):>8.3f}  "
              f"{float(np.mean(ns)):>8.0f}")
    print(f"  {sep}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Per-Asset AUC Correlation Heatmap (monthly windows)"
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="Path to trade lifecycle JSON",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for chart",
    )
    parser.add_argument(
        "--method", type=str, default="pearson",
        choices=["pearson", "spearman"],
        help="Correlation method: pearson (linear) or spearman (rank-based, robust to outliers)",
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

    total = sum(len(ts) for ts in trades.values())
    print(f"Loaded {total:,} trades across {len(trades)} assets")

    print(f"\nCorrelation method: {args.method}")
    print(f"Computing monthly per-asset AUC (min 10 trades/month)...")
    auc_series = build_auc_series(trades, min_total=40, min_per_month=10, min_months=4)
    print(f"  Built series for {len(auc_series)} assets")

    if len(auc_series) < 3:
        print("  ERROR: Too few assets with sufficient data.")
        sys.exit(1)

    print_summary(auc_series)

    print("\nGenerating correlation heatmap...")
    chart_path = generate_auc_correlation_chart(auc_series, out_dir, corr_method=args.method)

    print(f"\nDone — 1 chart generated:")
    print(f"  {chart_path.name}")


if __name__ == "__main__":
    main()
