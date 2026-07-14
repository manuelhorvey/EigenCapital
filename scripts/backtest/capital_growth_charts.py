#!/usr/bin/env python3
"""
Capital Growth Simulation — Chart Generator.

Reads the simulation JSON output and generates a multi-panel PNG chart
with equity curve, drawdown, monthly returns, compounding comparison,
and sensitivity analysis.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/capital_growth_charts.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/capital_growth_charts.py --json data/processed/capital_growth_simulation.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "data" / "processed" / "capital_growth_simulation.json"
CHART_DIR = ROOT / "data" / "processed"


def load_data(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def generate_charts(data: dict, output_dir: Path) -> list[Path]:
    """Generate all chart panels and return the list of saved file paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as mticker
    from matplotlib.patches import FancyBboxPatch
    from matplotlib.colors import LinearSegmentedColormap
    import pandas as pd

    # ── Color scheme ──
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

    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": SPINE,
        "axes.labelcolor": TEXT,
        "axes.titlecolor": TEXT,
        "xtick.color": TEXT2,
        "ytick.color": TEXT2,
        "grid.color": GRID,
        "grid.alpha": 0.3,
        "legend.facecolor": BG2,
        "legend.edgecolor": SPINE,
        "legend.labelcolor": TEXT,
        "text.color": TEXT,
        "font.family": "sans-serif",
    })

    meta = data["simulation_metadata"]
    start_capital = meta["start_capital"]
    metrics = data["executive_summary"]

    # ── Build daily equity DataFrame ──
    daily = pd.DataFrame(data["_daily_equity_curve"])
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()

    start_date = daily.index[0].strftime("%Y-%m-%d")
    end_date = daily.index[-1].strftime("%Y-%m-%d")

    saved_paths: list[Path] = []

    # ══════════════════════════════════════════════════════════════════
    # PANEL 1: MASTER CHART — Equity Curve + Drawdown + Monthly Returns
    # ══════════════════════════════════════════════════════════════════
    fig = plt.figure(figsize=(16, 12))
    fig.patch.set_facecolor(BG)

    # Grid: equity curve (top 55%), drawdown (middle 20%), monthly returns (bottom 25%)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.8, 1.0, 1.8], hspace=0.08)

    # ── Panel A: Equity Curve ──
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(BG)
    ax1.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax1.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax1.spines[s].set_color(SPINE)

    x = daily.index
    equity = daily["equity"].values

    ax1.fill_between(x, start_capital, equity, where=equity >= start_capital,
                     color=GREEN, alpha=0.06, interpolate=True)
    ax1.fill_between(x, start_capital, equity, where=equity < start_capital,
                     color=RED, alpha=0.06, interpolate=True)
    ax1.plot(x, equity, color=GREEN, linewidth=1.4, label=f"Equity (${start_capital:,.0f} → ${equity[-1]:,.0f})")
    ax1.axhline(y=start_capital, color=TEXT2, linewidth=0.6, linestyle="--", alpha=0.5)

    # Peak equity line
    peak = np.maximum.accumulate(equity)
    ax1.plot(x, peak, color=AMBER, linewidth=0.6, linestyle=":", alpha=0.5, label="Peak equity")

    ax1.set_ylabel("Account Equity (USD)", fontsize=11, color=TEXT)
    ax1.set_title(f"Capital Growth Simulation — ${start_capital:,.0f} Initial Capital",
                  fontsize=14, fontweight="bold", color=TEXT, pad=12)

    # Key metrics annotation box
    ann_text = (
        f"Final: ${metrics['final_capital']:,.2f}  |  "
        f"Return: {metrics['total_return_pct']:+.2f}%  |  "
        f"CAGR: {metrics['cagr_pct']:+.2f}%\n"
        f"Sharpe: {metrics['sharpe_ratio']:.4f}  |  "
        f"Max DD: {metrics['max_drawdown_pct']:.2f}%  |  "
        f"Win Rate: {metrics['day_win_rate_pct']:.1f}%"
    )
    ax1.text(0.5, 1.02, ann_text, transform=ax1.transAxes, ha="center", va="bottom",
             fontsize=9.5, color=TEXT2, family="monospace")

    ax1.legend(loc="upper left", fontsize=9, labelcolor=[GREEN, AMBER])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    ax1.xaxis.set_visible(False)

    # ── Panel B: Drawdown ──
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor(BG)
    ax2.tick_params(colors=TEXT2)
    for s in ["top", "right"]:
        ax2.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax2.spines[s].set_color(SPINE)

    dd = daily["drawdown"].values
    ax2.fill_between(x, 0, dd, color=RED if dd.min() < -5 else AMBER, alpha=0.4)
    ax2.axhline(y=-10, color=TEXT2, linewidth=0.4, linestyle="--", alpha=0.3)
    ax2.axhline(y=-20, color=TEXT2, linewidth=0.4, linestyle="--", alpha=0.3)
    ax2.axhline(y=-dd.max(), color=RED, linewidth=0.7, linestyle=":", alpha=0.7)

    ax2.set_ylabel("Drawdown %", fontsize=11, color=TEXT)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    ax2.xaxis.set_visible(False)

    # Annotate max drawdown
    dd_min_idx = np.argmin(dd)
    ax2.annotate(f"Max DD: {dd[dd_min_idx]:.1f}%",
                 xy=(x[dd_min_idx], dd[dd_min_idx]),
                 xytext=(30, -20), textcoords="offset points",
                 color=RED, fontsize=9, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=RED, lw=1.2),
                 bbox=dict(boxstyle="round,pad=0.3", facecolor=BG2, edgecolor=RED, alpha=0.8))

    # ── Panel C: Monthly Returns Heatmap ──
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor(BG)
    ax3.tick_params(colors=TEXT2)
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(False)
    ax3.spines["left"].set_color(SPINE)
    ax3.spines["bottom"].set_color(SPINE)

    # Aggregate daily returns to monthly
    monthly = daily["return_pct"].resample("ME").sum()

    # Create year × month matrix
    month_data = {}
    for dt, val in monthly.items():
        y = dt.year
        m = dt.month
        if y not in month_data:
            month_data[y] = {}
        month_data[y][m] = val

    years_list = sorted(month_data.keys())
    months_list = list(range(1, 13))

    heatmap_data = np.zeros((len(years_list), 12))
    heatmap_data[:] = np.nan
    for i, y in enumerate(years_list):
        for m in months_list:
            if m in month_data[y]:
                heatmap_data[i, m - 1] = month_data[y][m]

    # Custom colormap: red (negative) → dark (zero) → green (positive)
    cmap = LinearSegmentedColormap.from_list("rd_gn", ["#ef4444", "#1a1c2a", "#3dd9ae"], N=128)

    im = ax3.imshow(heatmap_data, cmap=cmap, aspect="auto",
                    vmin=-max(abs(np.nanmin(heatmap_data)), abs(np.nanmax(heatmap_data))),
                    vmax=max(abs(np.nanmin(heatmap_data)), abs(np.nanmax(heatmap_data))),
                    interpolation="nearest")

    # Annotate each cell
    for i in range(len(years_list)):
        for j in range(12):
            val = heatmap_data[i, j]
            if not np.isnan(val):
                color = GREEN if val > 0 else (RED if val < 0 else TEXT2)
                ax3.text(j, i, f"{val:+.1f}%", ha="center", va="center",
                         fontsize=7, color=color, fontweight="bold" if abs(val) > 5 else "normal")

    ax3.set_xticks(range(12))
    ax3.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                         fontsize=8, color=TEXT2)
    ax3.set_yticks(range(len(years_list)))
    ax3.set_yticklabels(years_list, fontsize=9, color=TEXT2)
    ax3.set_xlabel("Month", fontsize=10, color=TEXT)
    ax3.set_ylabel("Year", fontsize=10, color=TEXT)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax3, fraction=0.02, pad=0.02)
    cbar.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    cbar.ax.tick_params(colors=TEXT2)

    # Summary stats below heatmap
    monthly_rets = monthly.dropna()
    avg_month = monthly_rets.mean()
    prof_months = (monthly_rets > 0).sum()
    total_months = len(monthly_rets)
    best_month = monthly_rets.max()
    worst_month = monthly_rets.min()

    summary_line = (
        f"Monthly: Avg {avg_month:+.2f}%  |  "
        f"Best {best_month:+.2f}%  |  "
        f"Worst {worst_month:+.2f}%  |  "
        f"Profitable {prof_months}/{total_months} ({prof_months/total_months*100:.0f}%)"
    )
    ax3.text(0.5, -0.25, summary_line, transform=ax3.transAxes, ha="center",
             fontsize=9, color=TEXT2, family="monospace")

    # Footer
    fig.text(0.5, 0.01,
             f"Period: {start_date} → {end_date}  |  "
             f"Trades: {meta['n_trades']:,}  |  "
             f"Assets: {meta['n_assets']}  |  "
             f"Simulation: {meta['timestamp'][:10]}",
             ha="center", fontsize=8, color=TEXT2, family="monospace")

    plt.tight_layout()
    master_path = output_dir / "equity_curve_master.png"
    fig.savefig(master_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    saved_paths.append(master_path)
    print(f"  Saved: {master_path}")

    # ══════════════════════════════════════════════════════════════════
    # PANEL 2: COMPOUNDING COMPARISON
    # ══════════════════════════════════════════════════════════════════
    if "compounding_analysis" in data:
        comp = data["compounding_analysis"]
        fig2, ax = plt.subplots(figsize=(10, 6))
        fig2.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT2)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        for s in ["left", "bottom"]:
            ax.spines[s].set_color(SPINE)

        scenarios = ["Compounded\n(production sizing)", "Fixed Position\nSize", "Fixed Dollar\nRisk"]
        final_vals = [comp["compounded_final"], comp["fixed_position_size_final"], comp["fixed_dollar_risk_final"]]
        returns = [comp["compounded_return_pct"], comp["fixed_position_size_return_pct"], comp["fixed_dollar_risk_return_pct"]]
        colors_bar = [GREEN, BLUE, AMBER]

        bars = ax.bar(scenarios, final_vals, color=colors_bar, edgecolor="none", alpha=0.85, width=0.5)
        for bar, val, ret in zip(bars, final_vals, returns):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(final_vals) * 0.01,
                    f"${val:,.2f}\n({ret:+.2f}%)", ha="center", va="bottom",
                    fontsize=10, color=TEXT, fontweight="bold")

        ax.axhline(y=start_capital, color=TEXT2, linewidth=0.8, linestyle="--", alpha=0.5)
        ax.text(len(scenarios) - 0.5, start_capital + max(final_vals) * 0.005,
                f"Start capital: ${start_capital:,.0f}", fontsize=9, color=TEXT2, ha="right")

        ax.set_ylabel("Final Account Equity (USD)", fontsize=11, color=TEXT)
        ax.set_title("Compounding Analysis — Growth Scenario Comparison",
                     fontsize=13, fontweight="bold", color=TEXT, pad=10)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))

        # Benefit annotation
        benefit = comp["compounding_benefit_pct"]
        factor = comp["compounding_factor"]
        ax.text(0.5, -0.12,
                f"Compounding Benefit (vs fixed position): {benefit:+.2f}%  |  "
                f"Compounding Factor: {factor:.4f}x",
                transform=ax.transAxes, ha="center", fontsize=9, color=TEXT2, family="monospace")

        plt.tight_layout()
        comp_path = output_dir / "compounding_comparison.png"
        fig2.savefig(comp_path, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig2)
        saved_paths.append(comp_path)
        print(f"  Saved: {comp_path}")

    # ══════════════════════════════════════════════════════════════════
    # PANEL 3: SENSITIVITY ANALYSIS
    # ══════════════════════════════════════════════════════════════════
    if "sensitivity_analysis" in data and len(data["sensitivity_analysis"]) > 1:
        sens = data["sensitivity_analysis"]
        starts = [s["start_capital"] for s in sens]
        returns_pct = [s["total_return_pct"] for s in sens]
        dds = [s["max_drawdown_pct"] for s in sens]
        sharpes = [s["sharpe_ratio"] for s in sens]
        cagrs = [s["cagr_pct"] for s in sens]

        fig3, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(14, 6))
        fig3.patch.set_facecolor(BG)

        for ax in [ax_left, ax_right]:
            ax.set_facecolor(BG)
            ax.tick_params(colors=TEXT2)
            for s in ["top", "right"]:
                ax.spines[s].set_visible(False)
            for s in ["left", "bottom"]:
                ax.spines[s].set_color(SPINE)

        # Left: Return and CAGR
        x_pos = np.arange(len(starts))
        width = 0.35
        bars1 = ax_left.bar(x_pos - width / 2, returns_pct, width, color=GREEN, alpha=0.85, label="Total Return %")
        bars2 = ax_left.bar(x_pos + width / 2, cagrs, width, color=BLUE, alpha=0.85, label="CAGR %")
        ax_left.set_xticks(x_pos)
        ax_left.set_xticklabels([f"${s:,.0f}" for s in starts], fontsize=9)
        ax_left.set_ylabel("Return (%)", fontsize=11, color=TEXT)
        ax_left.set_title("Return vs Starting Capital", fontsize=12, fontweight="bold", color=TEXT)
        ax_left.legend(fontsize=9, labelcolor=[GREEN, BLUE])
        ax_left.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))

        # Right: Sharpe and Max DD
        ax_right_twin = ax_right.twinx()
        ax_right_twin.set_facecolor(BG)
        ax_right_twin.tick_params(colors=TEXT2)
        ax_right_twin.spines["right"].set_color(SPINE)

        bars3 = ax_right.bar(x_pos - width / 2, sharpes, width, color=PURPLE, alpha=0.85, label="Sharpe")
        bars4 = ax_right_twin.bar(x_pos + width / 2, dds, width, color=RED, alpha=0.5, label="Max DD %")

        ax_right.set_xticks(x_pos)
        ax_right.set_xticklabels([f"${s:,.0f}" for s in starts], fontsize=9)
        ax_right.set_ylabel("Sharpe Ratio", fontsize=11, color=TEXT)
        ax_right_twin.set_ylabel("Max Drawdown (%)", fontsize=11, color=RED)
        ax_right.set_title("Risk-Adjusted Performance vs Starting Capital", fontsize=12, fontweight="bold", color=TEXT)

        # Combined legend
        lines = [bars3, bars4]
        labels = ["Sharpe Ratio", "Max Drawdown %"]
        ax_right.legend(lines, labels, fontsize=9,
                        labelcolor=[PURPLE, RED], loc="upper left")

        fig3.suptitle("Scalability Assessment — Sensitivity Analysis Across 7 Capital Levels",
                      fontsize=13, fontweight="bold", color=TEXT, y=1.02)

        plt.tight_layout()
        sens_path = output_dir / "sensitivity_analysis.png"
        fig3.savefig(sens_path, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig3)
        saved_paths.append(sens_path)
        print(f"  Saved: {sens_path}")

    # ══════════════════════════════════════════════════════════════════
    # PANEL 4: EQUITY CURVE BY STARTING CAPITAL (overlay)
    # ══════════════════════════════════════════════════════════════════
    if "sensitivity_analysis" in data:
        # We can only show the $500 baseline since we have its daily equity curve
        # For the overlay idea, we'd need daily curves from all capital levels
        # This isn't available, so skip this panel
        pass

    # ══════════════════════════════════════════════════════════════════
    # SUMMARY TEXT FILE
    # ══════════════════════════════════════════════════════════════════
    summary_path = output_dir / "simulation_summary.txt"
    with open(summary_path, "w") as f:
        f.write("=" * 64 + "\n")
        f.write(f"  CAPITAL GROWTH SIMULATION SUMMARY\n")
        f.write(f"  Initial Capital: ${start_capital:,.2f}\n")
        f.write(f"  Period: {start_date} → {end_date}\n")
        f.write(f"  Generated: {meta['timestamp'][:10]}\n")
        f.write("=" * 64 + "\n\n")
        f.write(f"  Final Capital:       ${metrics['final_capital']:>10,.2f}\n")
        f.write(f"  Net Profit:          ${metrics['net_profit']:>+10,.2f}\n")
        f.write(f"  Total Return:        {metrics['total_return_pct']:>+10.2f}%\n")
        f.write(f"  CAGR:                {metrics['cagr_pct']:>+10.2f}%\n")
        f.write(f"  Sharpe Ratio:        {metrics['sharpe_ratio']:>10.4f}\n")
        f.write(f"  Sortino Ratio:       {metrics['sortino_ratio']:>10.4f}\n")
        f.write(f"  Calmar Ratio:        {metrics['calmar_ratio']:>10.4f}\n")
        f.write(f"  Max Drawdown:        {metrics['max_drawdown_pct']:>10.2f}%\n")
        f.write(f"  Profit Factor:       {metrics['profit_factor']:>10.2f}\n")
        f.write(f"  Day Win Rate:        {metrics['day_win_rate_pct']:>10.1f}%\n")
        f.write(f"  Recovery Factor:     {metrics['recovery_factor']:>10.2f}\n")
        f.write(f"  Ulcer Index:         {metrics['ulcer_index_pct']:>10.2f}%\n")
        f.write(f"  Daily VaR (95%):     ${metrics['daily_value_at_risk_95pct']:>+10.2f}\n")
        f.write(f"  Max Consec Wins:     {metrics['max_consecutive_wins_days']:>10}\n")
        f.write(f"  Max Consec Losses:   {metrics['max_consecutive_losses_days']:>10}\n")
    saved_paths.append(summary_path)
    print(f"  Saved: {summary_path}")

    return saved_paths


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Capital Growth Simulation Chart Generator")
    parser.add_argument("--json", type=str, default=None, help="Path to simulation JSON")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for charts")
    args = parser.parse_args()

    json_path = Path(args.json) if args.json else JSON_PATH
    output_dir = Path(args.output_dir) if args.output_dir else CHART_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_data(json_path)

    print(f"Generating charts from: {json_path}")
    saved = generate_charts(data, output_dir)

    print(f"\nGenerated {len(saved)} files:")
    for p in saved:
        print(f"  {p}")

    # Also display an HTML preview path
    render_ui_button(saved)


def render_ui_button(paths: list[Path]):
    """Render open button for first PNG."""
    pngs = [p for p in paths if p.suffix == ".png"]
    if pngs:
        try:
            from IPython.display import display, Image
            for p in pngs[:1]:
                display(Image(filename=str(p)))
        except ImportError:
            pass


if __name__ == "__main__":
    main()
