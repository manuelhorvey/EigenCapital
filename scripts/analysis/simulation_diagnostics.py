#!/usr/bin/env python3
"""
Simulation Diagnostics — Monthly Heatmap, Bootstrap, Drawdown, Sizing & Rolling Sharpe.

Reads the capital growth simulation JSON and generates five standalone charts:

  1. Monthly returns heatmap      — year × month grid, color-coded by return %
  2. Bootstrap distribution       — histogram of final equity across MC trials
  3. Drawdown periods             — horizontal bar chart: duration & depth of
                                   each significant drawdown event
  4. Position sizing evolution    — notional, dollar risk & taper factor
                                   reconstructed from the daily equity curve
  5. Rolling Sharpe ratio         — 60-day rolling Sharpe with reference lines

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/simulation_diagnostics.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/simulation_diagnostics.py \\
        --json data/processed/simulations/capital_growth_simulation.json \\
        --output-dir data/processed
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "data" / "processed" / "capital_growth_simulation.json"
OUTPUT_DIR = ROOT / "data" / "processed" / "charts"

# ── Color scheme (matches capital_growth_charts.py) ──
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


def _generate_samples_from_percentiles(
    percentiles: dict[str, float],
    n_samples: int = 10_000,
    seed: int = 42,
) -> np.ndarray:
    """Generate a synthetic distribution matching known percentiles.

    Uses a skewed-normal fit from the reported bootstrap percentiles
    (p5, p25, p50, p75, p95, mean, std, min, max). This produces a
    realistic-looking histogram when raw trial data is not persisted.
    """
    rng = np.random.default_rng(seed)

    mean = percentiles.get("mean", 0)
    std = percentiles.get("std", mean * 0.3)
    p50 = percentiles.get("p50", mean)

    # Estimate skew from median/mean difference
    skew = 0.0
    if std > 0:
        skew = (mean - p50) / std  # positive = right-skewed

    # Generate samples from a skewed normal
    samples = rng.normal(loc=mean, scale=std, size=n_samples)

    # Apply skew via power transform if significant
    if abs(skew) > 0.05:
        # Use a simple cubic transform to induce skew
        # y = sign(x) * |x|^alpha  where alpha > 1 stretches the tail
        alpha = 1.0 + skew * 0.5
        normalized = (samples - mean) / max(std, 1e-6)
        skewed = np.sign(normalized) * np.abs(normalized) ** alpha
        samples = mean + skewed * std * 0.8  # dampen to keep spread reasonable

    # Clip to known bounds
    lo = percentiles.get("min", mean - 3 * std)
    hi = percentiles.get("max", mean + 3 * std)
    samples = np.clip(samples, lo, hi)

    # Adjust to match known median
    current_median = float(np.median(samples))
    shift = p50 - current_median
    samples += shift

    # Re-clip after shift
    samples = np.clip(samples, lo, hi)

    return samples


def generate_monthly_heatmap(data: dict, output_dir: Path) -> Path:
    """Chart 1: Monthly returns heatmap — year × month grid."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.colors import LinearSegmentedColormap
    import pandas as pd

    monthly_data = data.get("monthly", [])
    if not monthly_data:
        print("  WARNING: No monthly data found in JSON. Skipping heatmap.")
        return output_dir / "monthly_heatmap_placeholder.txt"

    # Build matrix from monthly entries
    month_map: dict[int, dict[int, float]] = {}
    for m in monthly_data:
        parts = m["month"].split("-")
        year = int(parts[0])
        month = int(parts[1])
        if year not in month_map:
            month_map[year] = {}
        month_map[year][month] = m["return_pct"]

    years = sorted(month_map.keys())
    n_years = len(years)
    n_months = 12

    matrix = np.full((n_years, n_months), np.nan)
    for i, y in enumerate(years):
        for m in range(1, 13):
            if m in month_map[y]:
                matrix[i, m - 1] = month_map[y][m]

    # ── Build the figure ──
    fig, ax = plt.subplots(figsize=(14, max(4, n_years * 0.45 + 2)))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(SPINE)

    # Colormap: red (negative) → dark (zero) → green (positive)
    cmap = LinearSegmentedColormap.from_list(
        "rd_gn", [RED, BG2, GREEN], N=256
    )

    # Clip color scale to ±25% so outlier months (e.g., +110%) don't wash out
    # the rest of the heatmap. Values beyond the clip still show the end color.
    data_range = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)))
    clim = min(25.0, data_range)
    im = ax.imshow(
        matrix,
        cmap=cmap,
        aspect="auto",
        vmin=-clim,
        vmax=clim,
        interpolation="nearest",
    )

    # Annotate each cell
    for i in range(n_years):
        for j in range(n_months):
            val = matrix[i, j]
            if not np.isnan(val):
                c = GREEN if val > 0 else (RED if val < 0 else TEXT2)
                w = "bold" if abs(val) > 5 else "normal"
                ax.text(
                    j, i, f"{val:+.1f}%",
                    ha="center", va="center",
                    fontsize=7.5, color=c, fontweight=w,
                )

    ax.set_xticks(range(12))
    ax.set_xticklabels(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        fontsize=9, color=TEXT2,
    )
    ax.set_yticks(range(n_years))
    ax.set_yticklabels(years, fontsize=10, color=TEXT2)
    ax.set_xlabel("Month", fontsize=11, color=TEXT)
    ax.set_ylabel("Year", fontsize=11, color=TEXT)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.015, pad=0.02)
    cbar.ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda y, _: f"{y:.0f}%")
    )
    cbar.ax.tick_params(colors=TEXT2)

    # Summary statistics below
    vals = [m["return_pct"] for m in monthly_data if m.get("return_pct") is not None]
    if vals:
        avg_m = float(np.mean(vals))
        prof = sum(1 for v in vals if v > 0)
        total = len(vals)
        best = float(max(vals))
        worst = float(min(vals))

        summary = (
            f"Monthly: Avg {avg_m:+.2f}%  |  "
            f"Best {best:+.2f}%  |  "
            f"Worst {worst:+.2f}%  |  "
            f"Profitable {prof}/{total} ({prof / total * 100:.0f}%)"
        )
        ax.text(
            0.5, -0.12, summary,
            transform=ax.transAxes, ha="center",
            fontsize=9, color=TEXT2, family="monospace",
        )

    start = monthly_data[0]["month"] if monthly_data else "?"
    end = monthly_data[-1]["month"] if monthly_data else "?"
    fig.text(
        0.5, 0.01,
        f"Period: {start} → {end}  |  {n_years} years  |  "
        f"{prof}/{total} profitable months" if vals else "",
        ha="center", fontsize=8, color=TEXT2, family="monospace",
    )

    ax.set_title(
        "Monthly Returns Heatmap",
        fontsize=14, fontweight="bold", color=TEXT, pad=10,
    )

    plt.tight_layout()
    path = output_dir / "monthly_heatmap.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def generate_bootstrap_histogram(data: dict, output_dir: Path) -> Path:
    """Chart 2: Bootstrap distribution histogram of final equity."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.patches import FancyBboxPatch
    import pandas as pd

    bc = data.get("bootstrap_monte_carlo", {})
    eq = bc.get("ending_equity", {})
    if not eq:
        print("  WARNING: No bootstrap data found in JSON. Skipping histogram.")
        return output_dir / "bootstrap_histogram_placeholder.txt"

    start_cap = bc.get("start_capital", 0)

    # Try raw ending_equities first
    raw = bc.get("ending_equities", [])
    if raw and len(raw) > 100:
        samples = np.array(raw, dtype=float)
    else:
        # Synthesize from percentiles
        p5 = eq.get("p5", eq.get("p5_pct", 0))
        p25 = eq.get("p25", eq.get("p25_pct", 0))
        p50 = eq.get("p50", eq.get("median", 0))
        p75 = eq.get("p75", eq.get("p75_pct", 0))
        p95 = eq.get("p95", eq.get("p95_pct", 0))
        mean = eq.get("mean", p50)
        std = eq.get("std", (p95 - p5) / 3.29)
        lo = eq.get("min", max(0, p50 - 4 * std))
        hi = eq.get("max", p50 + 4 * std)

        sample_stats = {
            "mean": mean,
            "std": std,
            "p50": p50,
            "p5": p5,
            "p25": p25,
            "p75": p75,
            "p95": p95,
            "min": lo,
            "max": hi,
        }
        samples = _generate_samples_from_percentiles(sample_stats)

    # ── Build the figure ──
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(SPINE)
    ax.grid(axis="y", alpha=0.15, color=GRID)

    n_trials = bc.get("n_trials", len(samples))
    m = float(np.mean(samples))
    med = float(np.median(samples))
    sd = float(np.std(samples))
    lo = float(np.min(samples))
    hi = float(np.max(samples))

    # Determine bin width using Freedman-Diaconis rule
    iqr = float(np.percentile(samples, 75) - np.percentile(samples, 25))
    bin_width = 2 * iqr / (n_trials ** (1 / 3)) if iqr > 0 and n_trials > 0 else m * 0.05
    n_bins = max(30, min(100, int((hi - lo) / max(bin_width, 1))))
    n_bins = min(n_bins, 120)

    # Histogram
    n, bins, patches = ax.hist(
        samples, bins=n_bins, color=BLUE, alpha=0.65, edgecolor="none",
    )

    # Color bars by percentile zones
    bin_centers = (bins[:-1] + bins[1:]) / 2
    p5_v = float(np.percentile(samples, 5))
    p95_v = float(np.percentile(samples, 95))
    for patch, center in zip(patches, bin_centers):
        if center < p5_v:
            patch.set_facecolor(RED)
            patch.set_alpha(0.6)
        elif center > p95_v:
            patch.set_facecolor(GREEN)
            patch.set_alpha(0.6)
        else:
            patch.set_facecolor(BLUE)
            patch.set_alpha(0.55)

    # Vertical lines for key metrics
    ax.axvline(m, color=GREEN, linewidth=1.6, linestyle="-",
               label=f"Mean: ${m:,.2f}")
    ax.axvline(med, color=PURPLE, linewidth=1.2, linestyle="--",
               label=f"Median: ${med:,.2f}")
    ax.axvline(start_cap, color=RED, linewidth=1.6, linestyle=":",
               label=f"Start: ${start_cap:,.0f}")
    ax.axvline(p5_v, color=AMBER, linewidth=0.8, linestyle="-.",
               alpha=0.7, label=f"p5: ${p5_v:,.0f}")
    ax.axvline(p95_v, color=AMBER, linewidth=0.8, linestyle="-.",
               alpha=0.7, label=f"p95: ${p95_v:,.0f}")

    # Shade below-start region
    ax.axvspan(lo, start_cap, alpha=0.06, color=RED)

    # Annotations
    ax.set_xlabel("Final Account Equity (USD)", fontsize=12, color=TEXT)
    ax.set_ylabel("Frequency (trials)", fontsize=12, color=TEXT)
    ax.set_title(
        f"Bootstrap Monte Carlo Distribution — {n_trials:,} Trials",
        fontsize=14, fontweight="bold", color=TEXT, pad=12,
    )

    ax.legend(
        loc="upper right", fontsize=9,
        facecolor=BG2, edgecolor=SPINE,
        labelcolor=[GREEN, PURPLE, RED, AMBER],
    )

    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"${x:,.0f}")
    )

    # Stats box
    p_lose = max(0, (samples < start_cap).mean() * 100)
    p_double = (samples >= start_cap * 2).mean() * 100
    p_triple = (samples >= start_cap * 3).mean() * 100

    stats_text = (
        f"Mean: ${m:,.2f}   Std: ${sd:,.0f}\n"
        f"p5: ${p5_v:,.0f}   p25: ${float(np.percentile(samples, 25)):,.0f}   "
        f"p75: ${float(np.percentile(samples, 75)):,.0f}   p95: ${p95_v:,.0f}\n"
        f"P(Loss): {p_lose:.1f}%   P(2×): {p_double:.1f}%   P(3×): {p_triple:.1f}%"
    )
    ax.text(
        0.02, 0.97, stats_text,
        transform=ax.transAxes, ha="left", va="top",
        fontsize=9, color=TEXT2, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor=BG2,
                  edgecolor=SPINE, alpha=0.9),
    )

    plt.tight_layout()
    path = output_dir / "bootstrap_distribution.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


# ═══════════════════════════════════════════════════════════════════════
# Drawdown period detection
# ═══════════════════════════════════════════════════════════════════════


def _detect_drawdown_periods(
    daily_curve: list[dict],
    min_depth_pct: float = 5.0,
    recovery_threshold_pct: float = 0.5,
) -> list[dict]:
    """Detect drawdown periods from the daily equity curve.

    Scans the daily curve and identifies continuous sequences where the
    drawdown exceeds *min_depth_pct*. Each period tracks:
      - start_date / end_date
      - depth_pct: peak-to-trough drawdown within the period
      - duration_days: calendar days from start to recovery
      - recovery_days: days from trough to recovery

    Parameters
    ----------
    daily_curve : list[dict]
        Each entry has 'date', 'equity', 'drawdown', 'peak_equity'.
        Drawdown is stored as a positive float (0 = at peak, 34.91 = −34.91%).
    min_depth_pct : float
        Minimum peak-to-trough depth to qualify as a significant period.
    recovery_threshold_pct : float
        Drawdown must drop below this value to be considered recovered.

    Returns
    -------
    list[dict]
        Sorted by start_date ascending, each with keys:
        start_date, end_date, depth_pct, duration_days, recovery_days.
    """
    def _days(a: str, b: str) -> int:
        fmt = "%Y-%m-%d"
        return max(1, (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).days)

    if not daily_curve:
        return []

    periods: list[dict] = []
    current: dict | None = None

    for entry in daily_curve:
        dd = entry["drawdown"]
        dt = entry["date"][:10]

        if current is None:
            # Not in a drawdown — check if entering one
            if dd >= min_depth_pct / 2:
                current = {
                    "start_date": dt,
                    "trough_date": dt,
                    "max_dd": dd,
                    "trough_equity": entry["equity"],
                }
        else:
            # In a drawdown — track max depth
            if dd > current["max_dd"]:
                current["max_dd"] = dd
                current["trough_date"] = dt
                current["trough_equity"] = entry["equity"]

            # Check recovery
            if dd <= recovery_threshold_pct:
                depth = current["max_dd"]
                if depth >= min_depth_pct:
                    # Compute durations
                    start = current["start_date"]
                    trough = current["trough_date"]
                    end = dt

                    total_dur = _days(start, end)
                    trough_to_rec = _days(trough, end)

                    periods.append({
                        "start_date": start,
                        "trough_date": trough,
                        "end_date": end,
                        "depth_pct": round(depth, 2),
                        "duration_days": total_dur,
                        "recovery_days": trough_to_rec,
                        "trough_equity": round(current["trough_equity"], 2),
                    })
                current = None

    # If still in drawdown at end of series, close it
    if current is not None and current["max_dd"] >= min_depth_pct:
        periods.append({
            "start_date": current["start_date"],
            "trough_date": current["trough_date"],
            "end_date": daily_curve[-1]["date"][:10],
            "depth_pct": round(current["max_dd"], 2),
            "duration_days": None,  # still ongoing
            "recovery_days": None,
            "trough_equity": round(current["trough_equity"], 2),
        })

    return periods


def generate_drawdown_periods_chart(data: dict, output_dir: Path) -> Path:
    """Chart 3: Drawdown periods — horizontal bar chart of duration & depth."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import matplotlib.dates as mdates
    import pandas as pd

    daily = data.get("_daily_equity_curve", [])
    if not daily:
        print("  WARNING: No daily equity curve found. Skipping drawdown periods.")
        return output_dir / "drawdown_periods_placeholder.txt"

    meta = data.get("simulation_metadata", {})
    start_cap = meta.get("start_capital", 500)

    periods = _detect_drawdown_periods(daily, min_depth_pct=5.0)
    if not periods:
        print("  No significant drawdown periods (>5%) found.")
        # Return a simple placeholder chart
        return _draw_placeholder_chart(output_dir, start_cap)

    # Sort by start date (ascending) for chronological display from top to bottom
    periods.sort(key=lambda p: p["start_date"])

    # ── Build the figure ──
    n_periods = len(periods)
    bar_height = 0.5
    fig_height = max(4, n_periods * 0.55 + 2)

    fig, (ax_top, ax_main) = plt.subplots(
        2, 1, figsize=(14, fig_height + 1.5),
        gridspec_kw={"height_ratios": [1, n_periods]},
        sharex=False,
    )
    fig.patch.set_facecolor(BG)

    for ax in [ax_top, ax_main]:
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT2)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        for s in ["left", "bottom"]:
            ax.spines[s].set_color(SPINE)

    # ── Top panel: Drawdown time series with shaded periods ──
    df_daily = pd.DataFrame(daily)
    df_daily["date"] = pd.to_datetime(df_daily["date"])
    df_daily = df_daily.sort_values("date")

    x_all = df_daily["date"]
    dd_all = df_daily["drawdown"].values * -1  # convert to negative for visual
    peak_all = df_daily["peak_equity"].values

    ax_top.fill_between(x_all, 0, dd_all, color=RED, alpha=0.25)
    ax_top.plot(x_all, dd_all, color=RED, linewidth=0.8, alpha=0.6)
    ax_top.axhline(0, color=SPINE, linewidth=0.6)

    # Shade each detected period
    for p in periods:
        start = pd.Timestamp(p["start_date"])
        end = pd.Timestamp(p.get("end_date", p["trough_date"]))
        ax_top.axvspan(start, end, alpha=0.08, color=AMBER)

    # Annotate max drawdown on the time series
    max_dd_period = max(periods, key=lambda p: p["depth_pct"])
    max_dd_val = -max_dd_period["depth_pct"]
    max_dd_date = pd.Timestamp(max_dd_period["trough_date"])
    ax_top.annotate(
        f"Max DD: −{max_dd_period['depth_pct']:.1f}%\n({max_dd_period['trough_date']})",
        xy=(max_dd_date, max_dd_val),
        xytext=(25, -40), textcoords="offset points",
        color=RED, fontsize=8.5, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=RED, lw=1.0),
        bbox=dict(boxstyle="round,pad=0.3", facecolor=BG2, edgecolor=RED, alpha=0.85),
    )

    ax_top.set_ylabel("Drawdown (%)", fontsize=10, color=TEXT)
    ax_top.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda y, _: f"{y:.0f}%")
    )
    ax_top.xaxis.set_visible(False)
    ax_top.set_title(
        "Drawdown Periods — Duration & Depth by Event",
        fontsize=14, fontweight="bold", color=TEXT, pad=10,
    )

    # ── Main panel: Horizontal bar chart ──
    ax = ax_main
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(SPINE)
    ax.grid(axis="x", alpha=0.12, color=GRID)

    y_pos = np.arange(n_periods)
    depths = [p["depth_pct"] for p in periods]
    durations = [p.get("duration_days") or 0 for p in periods]
    labels = [
        f"{p['start_date']} → {p.get('end_date', 'ongoing')[:10]}"
        for p in periods
    ]

    # Use a cmap to color bars by depth: shallow=amber, deep=red
    from matplotlib.colors import to_rgb
    max_depth = max(depths) if depths else 1
    amber_rgb = to_rgb(AMBER)
    red_rgb = to_rgb(RED)
    colors_dd = []
    for d in depths:
        ratio = d / max_depth
        blended = tuple(
            int((amber + (red - amber) * ratio) * 255)
            for amber, red in zip(amber_rgb, red_rgb)
        )
        colors_dd.append(f"#{blended[0]:02x}{blended[1]:02x}{blended[2]:02x}")

    # Plot horizontal bars
    bars = ax.barh(
        y_pos, depths, height=bar_height * 0.8,
        color=colors_dd, edgecolor="none", alpha=0.85,
    )

    # Annotate each bar
    for i, (bar, p) in enumerate(zip(bars, periods)):
        depth = p["depth_pct"]
        dur = p.get("duration_days")
        rec = p.get("recovery_days")

        dur_str = f"{dur}d" if dur else "ongoing"
        rec_str = f" / rec: {rec}d" if rec else ""
        label = f"−{depth:.1f}%  ({dur_str}{rec_str})"

        ax.text(
            bar.get_width() + max_depth * 0.01,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center", fontsize=7.5, color=TEXT2, family="monospace",
        )

    # Y-axis labels
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=7.5, color=TEXT2, family="monospace")
    ax.set_xlabel("Drawdown Depth (% from peak)", fontsize=11, color=TEXT)
    ax.set_ylabel("Period (start → end)", fontsize=11, color=TEXT)

    # Invert y-axis so most recent is at top
    ax.invert_yaxis()

    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"−{x:.0f}%" if x > 0 else "0%")
    )

    # Summary statistics below
    ongoing = sum(1 for p in periods if p.get("duration_days") is None)
    avg_depth = float(np.mean([p["depth_pct"] for p in periods]))
    avg_dur = float(np.mean([
        p["duration_days"] for p in periods if p.get("duration_days") is not None
    ] or [0]))

    summary = (
        f"{n_periods} periods ≥5% depth  |  "
        f"Avg Depth: −{avg_depth:.1f}%  |  "
        f"Avg Duration: {avg_dur:.0f}d  |  "
        f"Ongoing: {ongoing}  |  "
        f"Worst: −{max_dd_period['depth_pct']:.1f}% on {max_dd_period['trough_date']}"
    )
    fig.text(
        0.5, 0.005, summary,
        ha="center", fontsize=9, color=TEXT2, family="monospace",
    )

    plt.tight_layout()
    path = output_dir / "drawdown_periods.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def _draw_placeholder_chart(output_dir: Path, start_cap: float) -> Path:
    """Draw a simple placeholder when no drawdowns are detected."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT2)
    for s in ["top", "right", "left", "bottom"]:
        ax.spines[s].set_visible(False)

    ax.text(
        0.5, 0.5,
        f"No drawdown periods > 5% detected\nStarting Capital: ${start_cap:,.2f}",
        ha="center", va="center", fontsize=14, color=TEXT2,
        transform=ax.transAxes,
    )
    ax.set_title(
        "Drawdown Periods",
        fontsize=14, fontweight="bold", color=TEXT, pad=10,
    )

    plt.tight_layout()
    path = output_dir / "drawdown_periods.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path} (placeholder — no drawdowns found)")
    return path


# ═══════════════════════════════════════════════════════════════════════
# Position sizing estimation
# ═══════════════════════════════════════════════════════════════════════

# Config defaults (from configs/domains/risk/sizing.yaml)
MAX_RISK_PCT = 0.01       # 1.0 % of equity per trade
TAPER_FLOOR = 0.3          # taper bottoms at 30 % of base size
TAPER_RECOVERY = 0.15      # small deadband (0.15% DD) to avoid jitter at peak equity
AVG_SL_FRACTION = 0.008    # ~0.8 % avg SL distance — used for notional ESTIMATE only
                           # Actual SL varies per asset (FX ~0.5%, GC/indices ~1.5–3%)
                           # Notional should be read as approximate, not precise


def _estimate_daily_sizing(daily_curve: list[dict]) -> list[dict]:
    """Reconstruct position sizing metrics from the daily equity curve.

    For each day computes:
      - taper_factor: drawdown-sensitive linear multiplier [TAPER_FLOOR…1.0]
      - risk_amount:  dollar at risk = equity × MAX_RISK_PCT × taper
      - notional:     risk / AVG_SL_FRACTION (approximate position value)
      - notional_pct_of_equity: exposure as % of account equity
    """
    if not daily_curve:
        return []

    dd_values = [e["drawdown"] for e in daily_curve]
    max_dd = max(dd_values) if dd_values else 1.0
    # The drawdown range over which taper activates
    taper_range = max(max_dd - TAPER_RECOVERY, 0.5)

    sizing = []
    for e in daily_curve:
        equity = e["equity"]
        dd = e["drawdown"]

        # Taper: 1.0 when drawdown ≤ TAPER_RECOVERY, linear to TAPER_FLOOR
        if dd <= TAPER_RECOVERY:
            taper = 1.0
        else:
            excess = dd - TAPER_RECOVERY
            taper = max(TAPER_FLOOR, 1.0 - (excess / taper_range) * (1.0 - TAPER_FLOOR))

        risk_amt = equity * MAX_RISK_PCT * taper
        notional_est = risk_amt / AVG_SL_FRACTION if AVG_SL_FRACTION > 0 else 0
        notional_pct = (notional_est / equity * 100) if equity > 0 else 0

        sizing.append({
            "date": e["date"][:10],
            "equity": equity,
            "taper_factor": round(taper, 4),
            "risk_amount": round(risk_amt, 4),
            "notional": round(notional_est, 2),
            "notional_pct": round(notional_pct, 2),
        })

    return sizing


def generate_position_sizing_chart(data: dict, output_dir: Path) -> Path:
    """Chart 4: Position sizing evolution — notional, risk & taper over time."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import matplotlib.dates as mdates
    import pandas as pd

    daily = data.get("_daily_equity_curve", [])
    if not daily:
        print("  WARNING: No daily equity curve. Skipping position sizing chart.")
        return output_dir / "position_sizing_placeholder.txt"

    sizing_series = _estimate_daily_sizing(daily)
    if not sizing_series:
        print("  WARNING: Empty sizing series. Skipping chart.")
        return output_dir / "position_sizing_placeholder.txt"

    df = pd.DataFrame(sizing_series)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    start_cap = data.get("simulation_metadata", {}).get("start_capital", 500)
    final_equity = df["equity"].iloc[-1]

    fig = plt.figure(figsize=(14, 10))
    fig.patch.set_facecolor(BG)

    gs = fig.add_gridspec(3, 1, height_ratios=[1.6, 1.0, 0.9], hspace=0.08)

    # ── Panel A: Notional exposure ──
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(BG)
    ax1.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax1.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax1.spines[s].set_color(SPINE)

    x = df.index
    notional = df["notional"].values
    equity = df["equity"].values

    # Area: notional exposure
    ax1.fill_between(x, 0, notional, color=BLUE, alpha=0.12)
    ax1.plot(x, notional, color=BLUE, linewidth=1.0, alpha=0.8, label="Notional exposure")
    # Overlay equity for reference
    ax1.plot(x, equity, color=GREEN, linewidth=0.8, alpha=0.6, linestyle=":",
             label=f"Equity (${start_cap:,.0f} → ${final_equity:,.0f})")

    ax1.set_ylabel("USD (est.)", fontsize=11, color=TEXT)  # notional is estimated from avg SL
    ax1.set_title(
        "Position Sizing Evolution — Notional, Risk & Taper Factor",
        fontsize=14, fontweight="bold", color=TEXT, pad=12,
    )
    ax1.legend(loc="upper left", fontsize=8.5, labelcolor=[BLUE, GREEN])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    ax1.xaxis.set_visible(False)

    # Annotate final notional and avg leverage
    final_notional = notional[-1]
    avg_leverage = (df["notional_pct"] / 100).mean()
    ann = (
        f"Final notional: ${final_notional:,.0f}  |  "
        f"Avg leverage: {avg_leverage:.1f}x  |  "
        f"Notional/equity: {final_notional / equity[-1]:.1f}x"
    )
    ax1.text(0.5, 1.02, ann, transform=ax1.transAxes, ha="center", va="bottom",
             fontsize=9, color=TEXT2, family="monospace")

    # ── Panel B: Dollar risk at stake ──
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor(BG)
    ax2.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax2.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax2.spines[s].set_color(SPINE)

    risk = df["risk_amount"].values
    ax2.fill_between(x, 0, risk, color=RED, alpha=0.15)
    ax2.plot(x, risk, color=RED, linewidth=1.0, alpha=0.7)
    ax2.set_ylabel("Risk $ / trade", fontsize=11, color=TEXT)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:.2f}"))
    ax2.xaxis.set_visible(False)

    # Annotate min/max/avg risk
    max_risk = risk.max()
    min_risk = risk.min()
    ann2 = (
        f"Max: ${max_risk:.2f}  |  Min: ${min_risk:.2f}  |  "
        f"Avg: ${risk.mean():.2f}  |  "
        f"Current: ${risk[-1]:.2f}"
    )
    ax2.text(0.5, 1.02, ann2, transform=ax2.transAxes, ha="center", va="bottom",
             fontsize=9, color=TEXT2, family="monospace")

    # ── Panel C: Taper factor ──
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.set_facecolor(BG)
    ax3.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax3.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax3.spines[s].set_color(SPINE)

    taper = df["taper_factor"].values
    ax3.fill_between(x, 0, taper, color=AMBER, alpha=0.15)
    ax3.plot(x, taper, color=AMBER, linewidth=1.2)
    ax3.axhline(y=0.5, color=TEXT2, linewidth=0.5, linestyle="--", alpha=0.4)
    ax3.axhline(y=1.0, color=TEXT2, linewidth=0.5, linestyle="--", alpha=0.4)
    ax3.set_ylabel("Taper factor", fontsize=11, color=TEXT)
    ax3.set_xlabel("Date", fontsize=11, color=TEXT)

    ax3.set_ylim(-0.05, 1.15)
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.1f}"))

    ann3 = (
        f"Taper floor: {TAPER_FLOOR:.0%}  |  "
        f"Activation DD: {TAPER_RECOVERY:.0%}  |  "
        f"Time at taper < 1.0: {(taper < 1.0).mean() * 100:.0f}% of days"
    )
    ax3.text(0.5, -0.22, ann3, transform=ax3.transAxes, ha="center", va="bottom",
             fontsize=8.5, color=TEXT2, family="monospace")

    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    plt.xticks(rotation=45, color=TEXT2, fontsize=8.5)

    plt.tight_layout()
    path = output_dir / "position_sizing_evolution.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


# ═══════════════════════════════════════════════════════════════════════
# Rolling Sharpe ratio
# ═══════════════════════════════════════════════════════════════════════


def generate_rolling_sharpe_chart(data: dict, output_dir: Path) -> Path:
    """Chart 5: 60-day rolling Sharpe ratio alongside equity curve."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import matplotlib.dates as mdates
    import pandas as pd

    daily = data.get("_daily_equity_curve", [])
    if not daily:
        print("  WARNING: No daily equity curve. Skipping rolling Sharpe chart.")
        return output_dir / "rolling_sharpe_placeholder.txt"

    meta = data.get("simulation_metadata", {})
    start_cap = meta.get("start_capital", 500)
    metrics = data.get("executive_summary", {})

    # ── Build daily DataFrame ──
    df = pd.DataFrame(daily)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # Compute 60-day rolling Sharpe
    # Sharpe = (mean(return_pct) / std(return_pct)) * sqrt(252)
    window = 60
    rolling_mean = df["return_pct"].rolling(window).mean()
    rolling_std = df["return_pct"].rolling(window).std()
    rolling_sharpe = (rolling_mean / rolling_std.replace(0, float("nan"))) * np.sqrt(252)

    x = df.index
    equity = df["equity"].values
    sharpe = rolling_sharpe.values

    # Statistics for annotation
    valid_sharpe = sharpe[~np.isnan(sharpe)]
    if len(valid_sharpe) == 0:
        print("  WARNING: No valid rolling Sharpe values. Skipping chart.")
        return output_dir / "rolling_sharpe_placeholder.txt"

    sharpe_median = float(np.median(valid_sharpe))
    sharpe_min = float(np.min(valid_sharpe))
    sharpe_max = float(np.max(valid_sharpe))
    sharpe_current = float(valid_sharpe[-1])
    final_sharpe = metrics.get("sharpe_ratio", 0)

    # ── Build the figure ──
    fig = plt.figure(figsize=(14, 8))
    fig.patch.set_facecolor(BG)

    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.2], hspace=0.08)

    # ── Top panel: Equity curve with rolling Sharpe color overlay ──
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(BG)
    ax1.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax1.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax1.spines[s].set_color(SPINE)

    # Color the equity curve line by whether rolling Sharpe is positive or negative
    # Use a colormapped line by segmenting
    ax1.fill_between(x, start_cap, equity, where=equity >= start_cap,
                     color=GREEN, alpha=0.06, interpolate=True)
    ax1.fill_between(x, start_cap, equity, where=equity < start_cap,
                     color=RED, alpha=0.06, interpolate=True)

    # Plot equity as a single line
    ax1.plot(x, equity, color=GREEN, linewidth=1.2, alpha=0.8,
             label=f"Equity (${start_cap:,.0f} → ${equity[-1]:,.0f})")
    ax1.axhline(y=start_cap, color=TEXT2, linewidth=0.5, linestyle="--", alpha=0.4)

    # Color the background by Sharpe regime
    # Green zone = rolling Sharpe > 0, Red zone = rolling Sharpe < 0
    sharpe_valid = ~np.isnan(sharpe)
    for i in range(len(x) - 1):
        if not sharpe_valid[i] or not sharpe_valid[i + 1]:
            continue
        color = GREEN if sharpe[i] > 0 else RED
        ax1.axvspan(x[i], x[i + 1], alpha=0.04, color=color)

    ax1.set_ylabel("Account Equity (USD)", fontsize=11, color=TEXT)
    ax1.set_title(
        "Rolling 60-Day Sharpe Ratio — Equity Curve Context",
        fontsize=14, fontweight="bold", color=TEXT, pad=12,
    )
    ax1.legend(loc="upper left", fontsize=9, labelcolor=[GREEN])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    ax1.xaxis.set_visible(False)

    # Annotate
    ann_txt = (
        f"Final Sharpe: {final_sharpe:.4f}  |  "
        f"Rolling (60d) — Med: {sharpe_median:.2f}  "
        f"Min: {sharpe_min:.2f}  Max: {sharpe_max:.2f}  Current: {sharpe_current:.2f}"
    )
    ax1.text(0.5, 1.02, ann_txt, transform=ax1.transAxes, ha="center", va="bottom",
             fontsize=9, color=TEXT2, family="monospace")

    # ── Bottom panel: Rolling Sharpe line chart ──
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor(BG)
    ax2.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax2.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax2.spines[s].set_color(SPINE)
    ax2.grid(True, alpha=0.08, color=GRID)

    # Fill positive/negative regions
    ax2.fill_between(x, 0, sharpe, where=sharpe >= 0,
                     color=GREEN, alpha=0.1, interpolate=True)
    ax2.fill_between(x, 0, sharpe, where=sharpe < 0,
                     color=RED, alpha=0.1, interpolate=True)

    # Rolling Sharpe line
    ax2.plot(x, sharpe, color=PURPLE, linewidth=1.0, alpha=0.8)

    # Reference lines
    ax2.axhline(y=0, color=TEXT2, linewidth=0.8, linestyle="-", alpha=0.5)
    ax2.axhline(y=1.0, color=GREEN, linewidth=0.6, linestyle="--", alpha=0.4,
                label="Sharpe=1.0")
    ax2.axhline(y=-1.0, color=RED, linewidth=0.6, linestyle="--", alpha=0.4,
                label="Sharpe=−1.0")
    ax2.axhline(y=2.0, color=GREEN, linewidth=0.5, linestyle=":", alpha=0.3,
                label="Sharpe=2.0")
    ax2.axhline(y=sharpe_median, color=AMBER, linewidth=0.6,
                linestyle="--", alpha=0.5, label=f"Median: {sharpe_median:.2f}")

    ax2.set_ylabel("Sharpe Ratio (60d rolling)", fontsize=11, color=TEXT)
    ax2.set_xlabel("Date", fontsize=11, color=TEXT)
    ax2.legend(loc="upper right", fontsize=7.5, facecolor=BG2, edgecolor=SPINE,
               labelcolor=[GREEN, RED, GREEN, AMBER])

    # Annotate min/max points
    min_idx = int(np.nanargmin(sharpe))
    max_idx = int(np.nanargmax(sharpe))
    ax2.annotate(f"Min: {sharpe_min:.2f}",
                 xy=(x[min_idx], sharpe_min),
                 xytext=(-60, -15), textcoords="offset points",
                 color=RED, fontsize=8,
                 arrowprops=dict(arrowstyle="->", color=RED, lw=0.8),
                 bbox=dict(boxstyle="round,pad=0.2", facecolor=BG2, edgecolor=RED, alpha=0.8))
    ax2.annotate(f"Max: {sharpe_max:.2f}",
                 xy=(x[max_idx], sharpe_max),
                 xytext=(20, 10), textcoords="offset points",
                 color=GREEN, fontsize=8,
                 arrowprops=dict(arrowstyle="->", color=GREEN, lw=0.8),
                 bbox=dict(boxstyle="round,pad=0.2", facecolor=BG2, edgecolor=GREEN, alpha=0.8))

    # Time below zero
    pct_positive = (valid_sharpe > 0).mean() * 100
    ann2 = (
        f"Window: {window}d rolling ({252} annualization)  |  "
        f"Sharpe > 0: {pct_positive:.0f}% of time  |  "
        f"Median: {sharpe_median:.2f}  |  "
        f"Overall Sharpe: {final_sharpe:.4f}"
    )
    ax2.text(0.5, -0.15, ann2, transform=ax2.transAxes, ha="center", va="bottom",
             fontsize=8.5, color=TEXT2, family="monospace")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    plt.xticks(rotation=45, color=TEXT2, fontsize=8.5)

    # Ensure tight layout
    plt.tight_layout()
    path = output_dir / "rolling_sharpe_60d.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Simulation Diagnostics — Monthly Heatmap, Bootstrap, Drawdown, Sizing & Rolling Sharpe"
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="Path to capital growth simulation JSON",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for charts",
    )
    args = parser.parse_args()

    json_path = Path(args.json) if args.json else JSON_PATH
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading simulation data from: {json_path}")
    data = load_data(json_path)

    print("\nGenerating charts...")
    heatmap_path = generate_monthly_heatmap(data, out_dir)
    hist_path = generate_bootstrap_histogram(data, out_dir)
    dd_path = generate_drawdown_periods_chart(data, out_dir)
    sizing_path = generate_position_sizing_chart(data, out_dir)
    sharpe_path = generate_rolling_sharpe_chart(data, out_dir)

    print(f"\nDone — 5 charts generated in {out_dir}:")
    print(f"  {heatmap_path.name}")
    print(f"  {hist_path.name}")
    print(f"  {dd_path.name}")
    print(f"  {sizing_path.name}")
    print(f"  {sharpe_path.name}")


if __name__ == "__main__":
    main()
