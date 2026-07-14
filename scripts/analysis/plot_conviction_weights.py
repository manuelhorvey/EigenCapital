#!/usr/bin/env python3
"""
Plot the time-varying conviction scores and portfolio weights for
``conviction_weighted_v2`` across the full backtest period.

Generates:
  1. A heatmap of rolling IC conviction scores (assets × months)
  2. A stacked-area chart of monthly portfolio weights as conviction drifts
  3. A combined dashboard panel

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/plot_conviction_weights.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/plot_conviction_weights.py --tag base
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("plot_conviction_weights")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

WALKDIR = ROOT / "scripts" / "walkforward"
OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_signal_parquets(tag: str = "base") -> dict[str, pd.DataFrame]:
    """Load all per-asset walk-forward signal parquets.

    Returns {asset_name: DataFrame with p_long, label, signal, and DatetimeIndex}.
    """
    from scripts.backtest.backtest_pnl import (
        _asset_pt_sl_from_config,
        load_asset_signals,
    )

    pt_sl_map = _asset_pt_sl_from_config()
    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    if not parquets:
        fallback = sorted(WALKDIR.glob("*_wf_signals.parquet"))
        if fallback:
            parquets = fallback
            logger.info("Using tag-less fallback (%d parquets)", len(parquets))
    if not parquets:
        logger.error("No signal parquets found in %s", WALKDIR)
        sys.exit(1)

    signal_dfs: dict[str, pd.DataFrame] = {}
    for pq in parquets:
        stem = pq.stem
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            continue
        df = load_asset_signals(str(pq))
        if df.empty or "p_long" not in df.columns or "label" not in df.columns:
            continue
        signal_dfs[asset] = df[["p_long", "label", "signal"]]

    logger.info("Loaded %d/%d assets with signal data", len(signal_dfs), len(parquets))
    return signal_dfs


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Plot conviction_weighted_v2 weight time series")
    parser.add_argument("--tag", default="base", help="Signal parquet tag (default: base)")
    parser.add_argument("--ic-window", type=int, default=60, help="Rolling IC window (default: 60)")
    parser.add_argument("--output", default=None, help="Output PNG path")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "conviction_weights_series.png"

    # ── 1. Load signal data ──────────────────────────────────────────────
    signal_dfs = load_signal_parquets(args.tag)
    if not signal_dfs:
        logger.error("No signal data loaded — exiting")
        sys.exit(1)

    # Collect all dates across assets and sort
    all_dates = sorted(
        set().union(*[set(df.index) for df in signal_dfs.values()])
    )
    all_dates_idx = pd.DatetimeIndex(all_dates)
    logger.info("Date range: %s → %s (%d days)", all_dates[0], all_dates[-1], len(all_dates))

    # ── 2. Compute rolling IC conviction matrix (monthly rebalance) ──────
    from shared.ic_conviction import rolling_conviction_matrix

    logger.info("Computing rolling IC conviction matrix (window=%d, freq=monthly)...", args.ic_window)
    conv_df_full = rolling_conviction_matrix(
        signal_dfs,
        list(all_dates_idx),
        ic_window=args.ic_window,
        rebalance_freq="monthly",
    )
    # Downsample to only unique conviction dates (where IC was actually recomputed).
    # ``rolling_conviction_matrix`` forward-fills to all trading days, but for
    # visualization we only need the dates where conviction actually changes.
    rebalance_mask = ~conv_df_full.duplicated(keep="first")
    conv_df = conv_df_full[rebalance_mask].copy()
    logger.info(
        "Conv matrix: %d/%d unique rebalance dates × %d assets",
        len(conv_df), len(conv_df_full), len(conv_df.columns),
    )

    # ── 3. Compute daily R series for each asset ──────────────────────────
    from scripts.backtest.backtest_pnl import (
        _asset_pt_sl_from_config,
        compute_asset_daily_r,
    )

    pt_sl_map = _asset_pt_sl_from_config()
    daily_r: dict[str, pd.Series] = {}
    for asset, df in signal_dfs.items():
        if asset not in pt_sl_map:
            continue
        tp, sl = pt_sl_map[asset]
        r = compute_asset_daily_r(df, tp, sl)
        daily_r[asset] = r

    combined = pd.DataFrame(daily_r)
    logger.info("Daily R matrix shape: %s", combined.shape)

    # ── 4. Compute weight time series using conviction_weighted_v2 ───────
    from shared.portfolio_weights import rolling_weight_matrix

    logger.info("Computing conviction_weighted_v2 weight matrix...")
    # Build date_specific_kwargs from conviction matrix
    date_specific_kwargs: dict[str, dict[str, object]] = {}
    for dt_str in conv_df.index:
        row = conv_df.loc[dt_str]
        score_dict = {a: float(row[a]) for a in conv_df.columns if a in row and not pd.isna(row[a])}
        if score_dict:
            date_specific_kwargs[dt_str] = {
                "ic_conviction": score_dict,
                "conviction_lambda": 0.35,
            }

    weights_df = rolling_weight_matrix(
        combined,
        "conviction_weighted_v2",
        window=252,
        date_specific_kwargs=date_specific_kwargs if date_specific_kwargs else None,
    )
    logger.info("Weight matrix shape: %s (dates × assets)", weights_df.shape)

    # ── 5. Plot ──────────────────────────────────────────────────────────
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle
    from matplotlib.lines import Line2D

    # Dark theme colors
    BG = "#0f1119"
    BG2 = "#1a1c2a"
    TEXT = "#ccccdd"
    TEXT2 = "#888899"
    SPINE = "#333344"

    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": SPINE,
        "axes.labelcolor": TEXT,
        "axes.titlecolor": TEXT,
        "xtick.color": TEXT2,
        "ytick.color": TEXT2,
        "grid.color": SPINE,
        "grid.alpha": 0.2,
        "legend.facecolor": BG2,
        "legend.edgecolor": SPINE,
        "legend.labelcolor": TEXT,
        "text.color": TEXT,
    })

    # Color palette for 22 assets — cycle through distinct hues
    ASSET_COLORS = [
        "#3dd9ae", "#5b8def", "#a78bfa", "#f59e0b", "#ef4444",
        "#ec4899", "#14b8a6", "#f97316", "#06b6d4", "#84cc16",
        "#d946ef", "#0ea5e9", "#eab308", "#22d3ee", "#fb923c",
        "#a3e635", "#c084fc", "#38bdf8", "#fae8ff", "#6ee7b7",
        "#fda4af", "#818cf8",
    ]
    asset_color_map = {a: ASSET_COLORS[i % len(ASSET_COLORS)] for i, a in enumerate(sorted(combined.columns))}

    fig = plt.figure(figsize=(18, 16))
    fig.patch.set_facecolor(BG)

    # Grid: IC heatmap (top 30%), weights (middle 40%), conviction bars (bottom 30%)
    gs = fig.add_gridspec(3, 1, height_ratios=[1.0, 1.6, 0.8], hspace=0.12)

    # ── Panel A: IC Conviction Heatmap ──
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(BG)
    ax1.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax1.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax1.spines[s].set_color(SPINE)

    # Transpose: assets as rows, months as columns
    conv_plot = conv_df.T
    # Only show every Nth month label to avoid clutter
    n_months = len(conv_df)
    month_labels = [d.strftime("%Y-%m") for d in pd.DatetimeIndex(conv_df.index)]

    cmap = LinearSegmentedColormap.from_list(
        "ic_cmap", ["#ef4444", "#1a1c2a", "#3dd9ae"], N=128
    )
    vmax = max(abs(conv_plot.values.min()), abs(conv_plot.values.max()))
    im = ax1.imshow(
        conv_plot.values,
        cmap=cmap,
        aspect="auto",
        vmin=-vmax,
        vmax=vmax,
        interpolation="nearest",
    )

    ax1.set_yticks(range(len(conv_plot.index)))
    ax1.set_yticklabels(conv_plot.index, fontsize=7, color=TEXT)

    label_step = max(1, n_months // 12)
    ax1.set_xticks(range(0, n_months, label_step))
    ax1.set_xticklabels([month_labels[i] for i in range(0, n_months, label_step)],
                         fontsize=7, color=TEXT2, rotation=30, ha="right")

    ax1.set_title("Rolling IC Conviction Scores (monthly, window=60)",
                  fontsize=12, fontweight="bold", color=TEXT, pad=8)

    cbar = fig.colorbar(im, ax=ax1, fraction=0.015, pad=0.02)
    cbar.ax.tick_params(colors=TEXT2)
    cbar.set_label("Conviction Score", fontsize=8, color=TEXT2)
    cbar.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.1f}"))

    # ── Panel B: Weight Stacked Area Chart ──
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor(BG)
    ax2.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax2.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax2.spines[s].set_color(SPINE)

    # Reindex weights to conviction dates so both panels align
    weights_aligned = weights_df.reindex(conv_df.index, method="ffill").fillna(0.0)

    # Stacked area chart
    x_idx = np.arange(len(weights_aligned))
    sorted_cols = sorted(weights_aligned.columns, key=lambda c: weights_aligned[c].sum(), reverse=True)
    colors_bar = [asset_color_map[c] for c in sorted_cols]

    ax2.stackplot(
        x_idx,
        weights_aligned[sorted_cols].values.T,
        labels=sorted_cols,
        colors=colors_bar,
        alpha=0.8,
        edgecolor="none",
    )

    # Mean weight line
    mean_weight = 1.0 / len(weights_aligned.columns) if len(weights_aligned.columns) > 0 else 0
    ax2.axhline(y=mean_weight, color=TEXT2, linewidth=0.6, linestyle="--", alpha=0.5)
    ax2.text(len(x_idx) - 1, mean_weight + 0.001,
             f"equal weight ({mean_weight:.1%})",
             fontsize=7, color=TEXT2, ha="right", va="bottom", alpha=0.6)

    ax2.set_ylabel("Portfolio Weight", fontsize=11, color=TEXT)
    ax2.set_title("Conviction-Weighted v2 — Portfolio Weights Over Time",
                  fontsize=12, fontweight="bold", color=TEXT, pad=8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax2.set_xlim(-0.5, len(weights_aligned) - 0.5)

    ax2.set_xticks(range(0, n_months, label_step))
    ax2.set_xticklabels([month_labels[i] for i in range(0, n_months, label_step)],
                         fontsize=7, color=TEXT2, rotation=30, ha="right")

    # Legend: top 6 assets by average weight
    legend_items = []
    for c in sorted_cols[:6]:
        patch = Rectangle((0, 0), 1, 1, facecolor=asset_color_map[c], edgecolor="none")
        avg_w = weights_aligned[c].mean()
        legend_items.append((patch, f"{c} ({avg_w:.1%})"))

    legend = ax2.legend(
        [item[0] for item in legend_items],
        [item[1] for item in legend_items],
        loc="upper left",
        fontsize=7,
        ncol=2,
        framealpha=0.8,
    )

    # ── Panel C: Per-Month Conviction Distribution (box-style) ──
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor(BG)
    ax3.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax3.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax3.spines[s].set_color(SPINE)

    # Show min/max/mean conviction per month
    conv_vals = conv_df.values  # dates × assets
    month_means = np.nanmean(conv_vals, axis=1)
    month_mins = np.nanmin(conv_vals, axis=1)
    month_maxs = np.nanmax(conv_vals, axis=1)
    n_negative = np.sum(conv_vals < 1.0, axis=1)  # conviction < 1 = below neutral
    n_positive = np.sum(conv_vals > 1.0, axis=1)

    x_range = np.arange(len(month_means))

    # Shaded range
    ax3.fill_between(
        x_range, month_mins, month_maxs,
        color="#5b8def", alpha=0.15, step="mid"
    )
    ax3.plot(x_range, month_means, color="#3dd9ae", linewidth=1.5, label="Mean conviction")
    ax3.axhline(y=1.0, color=TEXT2, linewidth=0.6, linestyle="--", alpha=0.4, label="Neutral (1.0)")

    # Highlight months where mean conviction drops below 1.0
    below_neutral = month_means < 1.0
    ax3.fill_between(
        x_range, month_means, 1.0,
        where=below_neutral,
        color="#ef4444", alpha=0.2, step="mid",
        label="Below neutral"
    )

    # Right y-axis: count of negative-IC assets per month
    ax3_twin = ax3.twinx()
    ax3_twin.set_facecolor(BG)
    ax3_twin.tick_params(colors=TEXT2)
    ax3_twin.spines["right"].set_color(SPINE)
    ax3_twin.bar(
        x_range, n_negative,
        width=0.6, color="#ef4444", alpha=0.2, label="# below-neutral assets"
    )
    ax3_twin.set_ylabel("# Assets < 1.0", fontsize=9, color=TEXT2)

    ax3.set_ylabel("Conviction Score", fontsize=11, color=TEXT)
    ax3.set_title("Conviction Score Distribution (min/mean/max per month)",
                  fontsize=12, fontweight="bold", color=TEXT, pad=8)
    ax3.set_ylim(0, 2.5)

    ax3.set_xticks(range(0, n_months, label_step))
    ax3.set_xticklabels([month_labels[i] for i in range(0, n_months, label_step)],
                         fontsize=7, color=TEXT2, rotation=30, ha="right")

    # Combined legend
    lines = [
        Line2D([0], [0], color="#3dd9ae", linewidth=1.5),
        Line2D([0], [0], color=TEXT2, linewidth=0.6, linestyle="--"),
        Rectangle((0, 0), 0, 0, color="#ef4444", alpha=0.2),
    ]
    ax3.legend(lines, ["Mean conviction", "Neutral (1.0)", "Below neutral"],
               fontsize=7, loc="upper left", framealpha=0.8)

    # ── Footer annotation ──
    n_assets = len(signal_dfs)
    fig.text(
        0.5, 0.005,
        f"Data: walk-forward signal parquets (tag={args.tag})  |  "
        f"{n_assets} assets  |  "
        f"IC window={args.ic_window}  |  "
        f"Rebalance: monthly  |  "
        f"Conviction λ=0.35",
        ha="center", fontsize=8, color=TEXT2, family="monospace",
    )

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    logger.info("Chart saved to %s", output_path)

    # ── Print weight evolution summary ──
    print(f"\n{'=' * 72}")
    print(f"  Conviction-Weighted v2 — Weight Evolution Summary")
    print(f"  Period: {conv_df.index[0]} → {conv_df.index[-1]} ({len(conv_df)} months)")
    print(f"{'=' * 72}")
    print(f"  Top 5 assets by average weight:")
    for c in sorted_cols[:5]:
        avg_w = weights_aligned[c].mean()
        min_w = weights_aligned[c].min()
        max_w = weights_aligned[c].max()
        print(f"    {c:>8}: avg={avg_w:.2%}  range=[{min_w:.2%}, {max_w:.2%}]")
    print()
    print(f"  Bottom 5 assets by average weight:")
    for c in sorted_cols[-5:]:
        avg_w = weights_aligned[c].mean()
        min_w = weights_aligned[c].min()
        max_w = weights_aligned[c].max()
        print(f"    {c:>8}: avg={avg_w:.2%}  range=[{min_w:.2%}, {max_w:.2%}]")
    print()

    # Monthly conviction drift analysis
    print(f"  Conviction drift by month:")
    for i in range(len(conv_df)):
        dt = conv_df.index[i]
        mean_c = month_means[i]
        frac_below = n_negative[i] / n_assets
        print(f"    {dt}: mean={mean_c:.2f}  below-neu={frac_below:.0%}  "
              f"range=[{month_mins[i]:.2f}, {month_maxs[i]:.2f}]")
    print(f"  Chart: {output_path}")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
