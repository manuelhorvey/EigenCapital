#!/usr/bin/env python3
"""Per-Asset Monthly AUC Time Series — Companion to the Correlation Heatmap.

Reads the trade lifecycle JSON, computes monthly AUC per asset (same logic as
auc_correlation_heatmap.py), and plots the top-N and bottom-N assets by average
AUC as overlaid time series. A horizontal reference line at 0.50 (random
discrimination) is drawn for context.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/auc_time_series.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/auc_time_series.py \\
        --n-top 3 --n-bottom 3
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/auc_time_series.py \\
        --assets GC AUDJPY NZDUSD GBPAUD
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

JSON_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
OUTPUT_DIR = ROOT / "data" / "processed" / "charts"

# ── Color palette for up to 8 overlaid assets ──
COLORS = [
    "#3dd9ae",  # green
    "#5b8def",  # blue
    "#f59e0b",  # amber
    "#a78bfa",  # purple
    "#ef4444",  # red
    "#f472b6",  # pink
    "#06b6d4",  # cyan
    "#84cc16",  # lime
]

# ── Dark theme constants ──
BG = "#0f1119"
BG2 = "#1a1c2a"
TEXT = "#ccccdd"
TEXT2 = "#888899"
GREEN = "#3dd9ae"
RED = "#ef4444"
SPINE = "#333344"
GRID = "#2a2a3a"


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
    """Compute AUC for a single asset-month."""
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

    Returns
    -------
    list[dict]
        Each entry: {'month': str (YYYY-MM), 'auc': float, 'n': int}.
        Sorted by month ascending.
    """
    if not trades:
        return []

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


def _build_series(
    trades: dict[str, list[dict]],
    min_total: int = 40,
    min_per_month: int = 10,
    min_months: int = 4,
) -> dict[str, list[dict]]:
    """Build monthly AUC series for all eligible assets.

    Returns
    -------
    dict[str, list[dict]]
        asset -> [{'month': str, 'auc': float, 'n': int}, ...]
    """
    result: dict[str, list[dict]] = {}
    for asset, ts in trades.items():
        if len(ts) < min_total:
            continue
        series = _compute_monthly_aucs(ts, min_per_month)
        if len(series) >= min_months:
            result[asset] = series
    return result


def _pick_assets(
    series: dict[str, list[dict]],
    explicit: list[str] | None,
    n_top: int,
    n_bottom: int,
) -> list[str]:
    """Pick assets to display.

    If *explicit* is provided, use that list (filtered to available).
    Otherwise select *n_top* highest and *n_bottom* lowest by average AUC.
    """
    if explicit:
        available = [a for a in explicit if a in series]
        if not available:
            print("  WARNING: None of the requested assets have sufficient data.")
            print(f"  Available: {', '.join(sorted(series.keys()))}")
            # Fall through to auto-select
        else:
            return available

    # Rank by average AUC
    ranked = sorted(
        series.items(),
        key=lambda kv: float(np.mean([e["auc"] for e in kv[1]])),
        reverse=True,
    )

    selected: list[str] = []
    for a, _ in ranked[:n_top]:
        if a not in selected:
            selected.append(a)
    for a, _ in ranked[-n_bottom:]:
        if a not in selected:
            selected.append(a)

    return selected


def generate_auc_time_series_chart(
    series: dict[str, list[dict]],
    output_dir: Path,
    assets: list[str],
) -> Path:
    """Generate overlaid monthly AUC time series for selected assets.

    Parameters
    ----------
    series : dict[str, list[dict]]
        Full series dict from _build_series().
    output_dir : Path
        Output directory.
    assets : list[str]
        Which assets to plot (must be keys in *series*).

    Returns
    -------
    Path
        Path to the saved PNG.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # Collect all months across selected assets
    all_months = sorted(set(
        d["month"]
        for a in assets
        for d in series[a]
    ))

    # Convert to datetime (mid-month) for x-axis
    x_dates = [np.datetime64(f"{m}-15") for m in all_months]

    # Build data matrix
    auc_map: dict[str, list[float | None]] = {}
    for a in assets:
        d = {e["month"]: e["auc"] for e in series[a]}
        auc_map[a] = [d.get(m) for m in all_months]

    # ── Figure ──
    fig, ax = plt.subplots(figsize=(14, 6.5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(SPINE)
    ax.grid(True, alpha=0.08, color=GRID)

    # Reference line at 0.50 (random discrimination)
    ax.axhline(0.50, color=TEXT2, linewidth=0.8, linestyle="--", alpha=0.5,
               label="Random (AUC=0.50)")

    # Plot each asset
    n_selected = len(assets)
    lines = []
    for idx, a in enumerate(assets):
        vals = auc_map[a]
        y = np.array([v if v is not None else np.nan for v in vals])
        color = COLORS[idx % len(COLORS)]

        ln, = ax.plot(x_dates, y, color=color, linewidth=1.6, alpha=0.85,
                      marker=".", markersize=5, label=a)

        # Annotate last non-NaN value
        valid_idx = np.where(~np.isnan(y))[0]
        if len(valid_idx) > 0:
            last_i = valid_idx[-1]
            last_x = x_dates[last_i]
            last_y = y[last_i]
            avg_auc = float(np.nanmean(y))
            ax.annotate(
                f"  {a} (avg {avg_auc:.3f})",
                xy=(last_x, last_y),
                fontsize=8.5, color=color, fontweight="bold",
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.15", facecolor=BG, edgecolor=color,
                          alpha=0.8),
            )
        lines.append(ln)

    # X-axis formatting
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=7.5)

    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Calendar Month", fontsize=10, color=TEXT)
    ax.set_ylabel("Monthly AUC", fontsize=10, color=TEXT)

    ax.set_title(
        f"Monthly AUC Time Series — {n_selected} Assets",
        fontsize=14, fontweight="bold", color=TEXT, pad=12,
    )

    # Legend
    ax.legend(
        loc="lower left", fontsize=8, facecolor=BG2, edgecolor=SPINE,
        labelcolor=TEXT, ncol=min(n_selected, 4),
    )

    # Summary annotation below x-axis
    n_total = len(series)
    summary = (
        f"{n_selected} of {n_total} eligible assets shown  |  "
        f"Horizontal dashed line: AUC 0.50 (no discrimination)"
    )
    fig.text(0.5, 0.005, summary, ha="center", fontsize=8, color=TEXT2,
             family="monospace")

    plt.tight_layout()
    path = output_dir / "auc_time_series.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Monthly AUC Time Series — Companion to Correlation Heatmap"
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
        "--assets", type=str, nargs="+", default=None,
        help="Explicit asset list (e.g. --assets GC AUDJPY NZDUSD). "
             "Overrides --n-top / --n-bottom.",
    )
    parser.add_argument(
        "--n-top", type=int, default=2,
        help="Number of highest-average-AUC assets to show (default 2)",
    )
    parser.add_argument(
        "--n-bottom", type=int, default=2,
        help="Number of lowest-average-AUC assets to show (default 2)",
    )
    args = parser.parse_args()

    json_path = Path(args.json) if args.json else JSON_PATH
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading trade data from: {json_path}")
    with open(json_path) as f:
        data = json.load(f)

    trades = data.get("_trades", {})
    if not trades:
        print("ERROR: No trade data found.")
        sys.exit(1)

    total = sum(len(ts) for ts in trades.values())
    print(f"Loaded {total:,} trades across {len(trades)} assets")

    print("\nComputing monthly per-asset AUC (min 10 trades/month)...")
    series = _build_series(trades, min_total=40, min_per_month=10, min_months=6)
    print(f"  Built series for {len(series)} assets")

    if len(series) < 2:
        print("  ERROR: Too few assets with sufficient data.")
        sys.exit(1)

    selected = _pick_assets(series, args.assets, args.n_top, args.n_bottom)
    print(f"\nSelected {len(selected)} assets for time series:")
    for a in selected:
        s = series[a]
        avg = float(np.mean([e["auc"] for e in s]))
        print(f"  {a:>8s}: {len(s):>2d} months, avg AUC {avg:.3f}")

    print("\nGenerating time series chart...")
    chart_path = generate_auc_time_series_chart(series, out_dir, selected)

    print(f"\nDone — 1 chart generated:")
    print(f"  {chart_path.name}")


if __name__ == "__main__":
    main()
