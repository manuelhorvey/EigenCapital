#!/usr/bin/env python3
"""Generate equity curve chart for 70%@2.5R + 15% retrace production config."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
CHART_PATH = ROOT / "data" / "processed" / "equity_curve_production_7025.png"

# Production config: 70% scale-out at 2.5R, 15% trail on remainder
PROD_CONFIG = {
    "be_lock_r": 0.5,
    "trail_activation_r": 0.5,
    "trail_retrace_pct": 0.15,
    "scale_out_fraction": 0.7,
    "scale_out_r": 2.5,
}


def simulate(trade, asset):
    """Apply 70%/2.5R/15% production adaptive exit to a trade."""
    orig = trade.get("r_multiple", 0.0)
    if orig >= 0:
        return orig
    mfe = trade.get("mfe_r", 0.0)
    if mfe < 0.5 or trade.get("exit_reason") == "tp":
        return orig

    # Scale-out portion
    so_pct = PROD_CONFIG["scale_out_fraction"]  # 0.7
    so_r = PROD_CONFIG["scale_out_r"]  # 2.5
    captured = so_pct * (so_r if mfe >= so_r else mfe)
    rem = 1.0 - so_pct  # 0.3

    # Trailing remainder
    if mfe >= PROD_CONFIG["trail_activation_r"]:
        trail = mfe * (1.0 - PROD_CONFIG["trail_retrace_pct"])  # 85% capture
        captured += rem * max(trail, 0)
    elif mfe >= PROD_CONFIG["be_lock_r"]:
        pass  # breakeven on remainder
    return max(captured, 0)


def _clean(trades: list[dict]) -> None:
    """Replace NaN r_multiple and mfe_r with 0.0 in-place."""
    for t in trades:
        rm = t.get("r_multiple")
        if rm is None or (isinstance(rm, float) and math.isnan(rm)):
            t["r_multiple"] = 0.0
        mfe = t.get("mfe_r")
        if mfe is None or (isinstance(mfe, float) and math.isnan(mfe)):
            t["mfe_r"] = 0.0


def main():
    with open(TRADE_PATH) as f:
        data = json.load(f)

    all_trades = []
    for asset, trades in data["_trades"].items():
        _clean(trades)
        for t in trades:
            t["_asset"] = asset
            all_trades.append(t)

    # Compute R series for all configs
    def sim_all(config_fn, label):
        rs = np.array([config_fn(t, t["_asset"]) for t in all_trades])
        cum = np.cumsum(rs)
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        return {
            "label": label,
            "rs": rs,
            "cum": cum,
            "dd": dd,
            "total_r": cum[-1],
            "sharpe": rs.mean() / rs.std() if rs.std() > 0 else 0,
            "max_dd": dd.min(),
            "wr": (rs > 0).mean() * 100,
        }

    baseline = sim_all(lambda t, a: t["r_multiple"], "Fixed barriers")
    prod = sim_all(simulate, "70%@2.5R + 15% trail (PRODUCTION)")

    # Also simulate old 50% trail for comparison
    old = [simulate(t, t["_asset"]) for t in all_trades]

    print(f"\n{'=' * 72}")
    print(f"  EQUITY CURVE: Production config vs baseline")
    print(f"  {len(all_trades)} trades, {len(data['_trades'])} assets")
    print(f"{'=' * 72}")

    for s in [baseline, prod]:
        print(f"\n  {s['label']}")
        print(f"  Total R: {s['total_r']:.2f}   Sharpe: {s['sharpe']:.4f}")
        print(f"  Win rate: {s['wr']:.1f}%   Max DD: {s['max_dd']:.2f}R")

    delta = prod["total_r"] - baseline["total_r"]
    print(f"\n  Δ vs baseline: +{delta:.2f}R ({delta / baseline['total_r'] * 100:+.1f}%)")

    # Per-asset breakdown
    print(f"\n  Per-asset breakdown:")
    print(f"  {'Asset':<10s} {'Trades':>7s} {'Baseline':>10s} {'Production':>12s} {'ΔR':>10s}")
    print(f"  {'─'*10} {'─'*7} {'─'*10} {'─'*12} {'─'*10}")
    for asset in sorted(data["_trades"].keys()):
        ts = data["_trades"][asset]
        br = sum(t["r_multiple"] for t in ts)
        pr = sum(simulate(t, asset) for t in ts)
        print(f"  {asset:<10s} {len(ts):>7d} {br:>10.2f}R {pr:>12.2f}R {pr-br:>+10.2f}R")

    # ── Chart ──
    import matplotlib  # noqa: E402
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: E402
    import matplotlib.dates as mdates  # noqa: E402
    from matplotlib.ticker import FuncFormatter  # noqa: E402

    # Build timeline from trade entry dates
    dates = []
    for t in all_trades:
        ed = t.get("entry_date")
        if ed:
            try:
                dates.append(ed[:10])
            except Exception:
                dates.append("")
        else:
            dates.append("")

    # Aggregate to daily
    from collections import OrderedDict
    daily_base = OrderedDict()
    daily_prod = OrderedDict()
    for d, t in zip(dates, all_trades):
        if d:
            daily_base[d] = daily_base.get(d, 0) + t["r_multiple"]
            daily_prod[d] = daily_prod.get(d, 0) + simulate(t, t["_asset"])

    daily_dates = sorted(set(d for d in dates if d))
    base_cum = np.cumsum([daily_base.get(d, 0) for d in daily_dates])
    prod_cum = np.cumsum([daily_prod.get(d, 0) for d in daily_dates])
    base_peak = np.maximum.accumulate(base_cum)
    prod_peak = np.maximum.accumulate(prod_cum)
    base_dd = base_cum - base_peak
    prod_dd = prod_cum - prod_peak

    x = [pd.Timestamp(d) for d in daily_dates]

    # Per-asset cumulative for overlay
    asset_cum = {}
    for asset in sorted(data["_trades"].keys()):
        ad = OrderedDict()
        for t in data["_trades"][asset]:
            ed = t.get("entry_date", "")
            if ed:
                d = ed[:10]
                ad[d] = ad.get(d, 0) + simulate(t, asset)
        a_dates = sorted(ad.keys())
        asset_cum[asset] = np.cumsum([ad[d] for d in a_dates]) if a_dates else np.array([0])

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                                         gridspec_kw={"height_ratios": [3, 1, 1.5]})
    fig.patch.set_facecolor("#0f1119")

    for ax in [ax1, ax2, ax3]:
        ax.set_facecolor("#0f1119")
        ax.tick_params(colors="#888899")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#333344")
        ax.spines["bottom"].set_color("#333344")

    # Panel 1: Cumulative R
    ax1.plot(x, base_cum, color="#555566", linewidth=0.8, alpha=0.7, label="Fixed barriers")
    ax1.plot(x, prod_cum, color="#3dd9ae", linewidth=1.6, label=f"70%@2.5R + 15% trail (prod)")
    ax1.fill_between(x, prod_cum, alpha=0.08, color="#3dd9ae")
    ax1.set_ylabel("Cumulative R", color="#ccccdd", fontsize=11)
    ax1.legend(loc="upper left", labelcolor=["#555566", "#3dd9ae"],
               facecolor="#1a1c2a", edgecolor="#333344", fontsize=10)
    ax1.set_title("Equity Curve — Production Config (70%@2.5R + 15% trail)",
                  color="#ccccdd", fontsize=13, fontweight="bold", pad=12)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:.0f}R"))

    # Panel 2: Drawdown
    ax2.fill_between(x, 0, base_dd, color="#555566", alpha=0.5, label="Fixed barriers DD")
    ax2.fill_between(x, 0, prod_dd, color="#3dd9ae", alpha=0.6, label="Production DD")
    ax2.set_ylabel("Drawdown (R)", color="#ccccdd", fontsize=11)
    ax2.legend(loc="lower left", labelcolor=["#555566", "#3dd9ae"],
               facecolor="#1a1c2a", edgecolor="#333344", fontsize=10)

    # Panel 3: Per-asset overlay (top 5)
    top5 = sorted(data["_trades"].keys(),
                  key=lambda a: sum(simulate(t, a) for t in data["_trades"][a]),
                  reverse=True)[:5]
    colors = ["#3dd9ae", "#5b8def", "#f59e0b", "#ef4444", "#a78bfa"]
    for asset, color in zip(top5, colors):
        ad = OrderedDict()
        for t in data["_trades"][asset]:
            ed = t.get("entry_date", "")
            if ed:
                d = ed[:10]
                ad[d] = ad.get(d, 0) + simulate(t, asset)
        a_dates = sorted(ad.keys())
        if len(a_dates) > 1:
            ax3.plot([pd.Timestamp(d) for d in a_dates],
                     np.cumsum([ad[d] for d in a_dates]),
                     color=color, linewidth=1.0, alpha=0.8, label=asset)

    ax3.set_ylabel("Cumulative R (per asset)", color="#ccccdd", fontsize=11)
    ax3.set_xlabel("Date", color="#ccccdd", fontsize=11)
    ax3.legend(loc="upper left", facecolor="#1a1c2a", edgecolor="#333344",
               labelcolor=[c for c in ["#3dd9ae", "#5b8def", "#f59e0b", "#ef4444", "#a78bfa"]],
               fontsize=9)

    # Date formatting
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45, color="#888899")

    # Annotation
    textstr = f"Total R: {prod['total_r']:+.0f}   Sharpe: {prod['sharpe']:.3f}   WR: {prod['wr']:.0f}%   Max DD: {prod['max_dd']:.1f}R"
    ax1.text(0.5, -0.18, textstr, transform=ax1.transAxes, ha="center", fontsize=11,
             color="#888899", family="monospace")

    plt.tight_layout()
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight", facecolor="#0f1119")
    print(f"\n  Chart saved: {CHART_PATH}")


if __name__ == "__main__":
    main()
