#!/usr/bin/env python3
"""
Crisis scenario replay — stress-test assets and portfolio against known
historical crisis windows within the available OOS data (Aug 2024 - May 2026).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/crisis_replay.py
    PYTHONPATH=$PYTHONPATH:. python scripts/crisis_replay.py --output-dir crisis_reports
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("crisis_replay")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "AUDUSD",
        "ES",
        "NQ",
        "NZDCHF",
        "EURAUD",
        "^DJI",
        "USDCHF",
        "EURCHF",
        "NZDUSD",
        "EURNZD",
    }
)

# ── Crisis windows within Oct 2024 - May 2026 ──────────────────────────────
# Identified by data-mining for concentrated loss periods and confirmed
# against known market events.
CRISIS_WINDOWS: list[dict] = [
    {
        "name": "dec_2024_selloff",
        "start": "2024-12-06",
        "end": "2024-12-13",
        "description": "4-day concentrated loss streak — post-election digestion / rate repricing",
    },
    {
        "name": "feb_mar_2025_tariff",
        "start": "2025-02-24",
        "end": "2025-03-10",
        "description": "9-day concentrated loss streak — tariff escalation / trade war fears",
    },
    {
        "name": "apr_2025_selloff",
        "start": "2025-03-25",
        "end": "2025-04-07",
        "description": "7-day cluster (4+3) — tariff implementation concerns",
    },
    {
        "name": "jun_2025_minor",
        "start": "2025-06-17",
        "end": "2025-06-24",
        "description": "3-day minor loss streak",
    },
]

# ── Global calibration ──────────────────────────────────────────────────────

CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES = 15
CIRCUIT_BREAKER_VOL_SPIKE_THRESHOLD = 3.0


# ── Data types ──────────────────────────────────────────────────────────────


@dataclass
class AssetCrisisMetrics:
    name: str
    crisis_total_r: float = 0.0
    crisis_win_rate: float = 0.0
    crisis_avg_r: float = 0.0
    crisis_n_trades: int = 0
    crisis_max_consecutive_losses: int = 0
    crisis_vol: float = 0.0

    normal_total_r: float = 0.0
    normal_win_rate: float = 0.0
    normal_avg_r: float = 0.0
    normal_n_trades: int = 0
    normal_vol: float = 0.0

    vol_ratio: float = 0.0  # crisis_vol / normal_vol
    win_rate_change: float = 0.0  # crisis - normal (pp)
    r_per_trade_change: float = 0.0  # crisis - normal
    is_sell_only: bool = False

    # Circuit breaker simulation
    consecutive_losses_in_crisis: int = 0
    would_trip_loss_streak: bool = False


@dataclass
class CrisisWindowResult:
    name: str
    description: str
    start: str
    end: str
    n_trading_days: int = 0
    portfolio_total_r: float = 0.0
    portfolio_max_dd_r: float = 0.0
    portfolio_avg_daily_r: float = 0.0
    portfolio_daily_r_vol: float = 0.0
    portfolio_loss_day_ratio: float = 0.0  # fraction of days with negative R

    # Correlation change
    avg_pairwise_corr_in_crisis: float = 0.0
    avg_pairwise_corr_outside: float = 0.0
    corr_during_crisis_increased: bool = False

    # Per-asset
    asset_metrics: list[AssetCrisisMetrics] = field(default_factory=list)

    # Worst-hit assets
    worst_assets_total_r: list[tuple[str, float]] = field(default_factory=list)
    worst_assets_wr: list[tuple[str, float]] = field(default_factory=list)

    # Circuit breaker
    max_consecutive_portfolio_losses: int = 0
    would_trip_loss_streak: bool = False
    would_trip_vol_spike: bool = False

    # Cluster analysis
    cluster_losses: dict[str, dict] = field(default_factory=dict)


# ── Core R computation ──────────────────────────────────────────────────────


def compute_r(signal: int, label: int, tp: float, sl: float) -> float:
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


# ── Load data ────────────────────────────────────────────────────────────────


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def load_all_signals() -> dict[str, pd.DataFrame]:
    """Load all asset signal parquets from walkforward dir."""
    assets: dict[str, pd.DataFrame] = {}
    pattern = os.path.join(WALKDIR, "*_wf_signals.parquet")
    for fpath in glob.glob(pattern):
        name = os.path.basename(fpath).replace("_wf_signals.parquet", "")
        df = pd.read_parquet(fpath)
        assets[name] = df
    return assets


# ── Per-asset analysis ─────────────────────────────────────────────────────


def analyze_asset(
    name: str,
    df: pd.DataFrame,
    crisis_start: str,
    crisis_end: str,
    tp: float,
    sl: float,
) -> AssetCrisisMetrics:
    """Compare asset performance inside vs outside a crisis window."""
    is_sell_only = name in SELL_ONLY_ASSETS

    crisis_mask = (df.index >= crisis_start) & (df.index <= crisis_end)
    crisis_df = df[crisis_mask]
    normal_df = df[~crisis_mask]

    def _compute(df_subset: pd.DataFrame, label: str) -> dict:
        if df_subset.empty:
            return {"total_r": 0.0, "win_rate": 0.0, "avg_r": 0.0, "n_trades": 0, "r_list": []}

        active = df_subset[df_subset["signal"] != 0]
        if active.empty:
            return {"total_r": 0.0, "win_rate": 0.0, "avg_r": 0.0, "n_trades": 0, "r_list": []}

        rs = active.apply(lambda row: compute_r(row["signal"], row["label"], tp, sl), axis=1)
        wins = (rs > 0).sum()
        return {
            "total_r": float(rs.sum()),
            "win_rate": float(wins / len(rs)),
            "avg_r": float(rs.mean()),
            "n_trades": len(rs),
            "r_list": rs.tolist(),
        }

    crisis = _compute(crisis_df, "crisis")
    normal = _compute(normal_df, "normal")

    # Consecutive losses in crisis
    r_list = crisis["r_list"]
    max_consec = 0
    consec = 0
    for r in r_list:
        if r < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    # Volatility
    crisis_vol = float(np.std(crisis["r_list"])) if len(crisis["r_list"]) > 1 else 0.0
    normal_vol = float(np.std(normal["r_list"])) if len(normal["r_list"]) > 1 else 1e-9

    m = AssetCrisisMetrics(
        name=name,
        crisis_total_r=crisis["total_r"],
        crisis_win_rate=crisis["win_rate"],
        crisis_avg_r=crisis["avg_r"],
        crisis_n_trades=crisis["n_trades"],
        crisis_max_consecutive_losses=max_consec,
        crisis_vol=crisis_vol,
        normal_total_r=normal["total_r"],
        normal_win_rate=normal["win_rate"],
        normal_avg_r=normal["avg_r"],
        normal_n_trades=normal["n_trades"],
        normal_vol=normal_vol,
        vol_ratio=crisis_vol / normal_vol if normal_vol > 0 else 0.0,
        win_rate_change=round((crisis["win_rate"] - normal["win_rate"]) * 100, 1),
        r_per_trade_change=round(crisis["avg_r"] - normal["avg_r"], 4),
        is_sell_only=is_sell_only,
        consecutive_losses_in_crisis=max_consec,
        would_trip_loss_streak=max_consec >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES,
    )
    return m


# ── Correlation analysis ──────────────────────────────────────────────────


def compute_avg_pairwise_corr(
    assets_data: dict[str, pd.DataFrame],
    date_range: tuple[str, str],
) -> float:
    """Compute average pairwise return correlation within a date range."""
    start, end = date_range
    # Build return matrix aligned by date
    all_dates = sorted({d for df in assets_data.values() for d in df.index if start <= str(d.date()) <= end})
    if len(all_dates) < 5:
        return 0.0

    returns_mat: dict[str, list[float]] = {}
    for name, df in assets_data.items():
        rets = []
        for d in all_dates:
            if d in df.index:
                row = df.loc[d]
                sig, lbl = row["signal"], row["label"]
                tp, sl = load_pt_sl().get(name, (2.0, 2.0))
                rets.append(compute_r(sig, lbl, tp, sl))
            else:
                rets.append(0.0)
        returns_mat[name] = rets

    df_rets = pd.DataFrame(returns_mat, index=all_dates)
    corr = df_rets.corr()
    # Average of upper triangle
    vals = []
    assets = list(corr.columns)
    for i in range(len(assets)):
        for j in range(i + 1, len(assets)):
            v = corr.iloc[i, j]
            if not np.isnan(v):
                vals.append(v)
    return float(np.mean(vals)) if vals else 0.0


# ── Cluster analysis ───────────────────────────────────────────────────────


def analyze_clusters(
    assets_data: dict[str, pd.DataFrame],
    crisis_start: str,
    crisis_end: str,
) -> dict[str, dict]:
    """Check how predefined clusters behave during crisis."""
    clusters = {
        "chf": {"assets": ["CADCHF", "NZDCHF", "USDCHF", "EURCHF"], "label": "CHF pairs (all SELL-only)"},
        "equities": {"assets": ["ES", "NQ", "^DJI"], "label": "US equities (all SELL-only)"},
        "aud": {"assets": ["AUDUSD", "EURAUD"], "label": "AUD pairs"},
        "commodity": {"assets": ["GC"], "label": "Gold"},
    }

    pt_sl = load_pt_sl()
    results: dict[str, dict] = {}
    for cluster_name, cluster_info in clusters.items():
        asset_names = cluster_info["assets"]
        # Filter to assets that exist in data
        existing = [a for a in asset_names if a in assets_data]
        if not existing:
            continue

        # Total R for crisis period
        total_r = 0.0
        n_losses = 0
        n_trades = 0
        for name in existing:
            df = assets_data[name]
            crisis = df[(df.index >= crisis_start) & (df.index <= crisis_end)]
            active = crisis[crisis["signal"] != 0]
            for _, row in active.iterrows():
                tp, sl = pt_sl.get(name, (2.0, 2.0))
                r = compute_r(row["signal"], row["label"], tp, sl)
                total_r += r
                if r < 0:
                    n_losses += 1
                n_trades += 1

        results[cluster_name] = {
            "label": cluster_info["label"],
            "assets": existing,
            "crisis_total_r": round(total_r, 2),
            "crisis_loss_rate": round(n_losses / n_trades, 3) if n_trades > 0 else 0.0,
            "n_trades_in_crisis": n_trades,
        }
    return results


# ── Circuit breaker simulation ─────────────────────────────────────────────


def simulate_circuit_breaker(
    assets_data: dict[str, pd.DataFrame],
    crisis_start: str,
    crisis_end: str,
) -> dict:
    """Simulate the portfolio circuit breaker during crisis.

    Checks:
      1. Consecutive portfolio loss streak (15-day threshold)
      2. Vol spike (rolling 10-day vol vs baseline vol, 3x threshold)
    """
    dates = sorted({d for df in assets_data.values() for d in df.index if crisis_start <= str(d.date()) <= crisis_end})
    if not dates:
        return {"tripped": False, "reason": "no_data"}

    pt_sl = load_pt_sl()

    # Daily portfolio returns
    daily_rs: list[float] = []
    for d in dates:
        rs: list[float] = []
        for name, df in assets_data.items():
            if d in df.index:
                row = df.loc[d]
                sig, lbl = row["signal"], row["label"]
                tp, sl = pt_sl.get(name, (2.0, 2.0))
                rs.append(compute_r(sig, lbl, tp, sl))
        daily_rs.append(float(np.mean(rs)) if rs else 0.0)

    # 1. Consecutive loss streak
    max_streak = 0
    streak = 0
    for r in daily_rs:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    loss_trip = max_streak >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES

    # 2. Vol spike
    baseline_start = "2024-10-17"
    baseline_dates = sorted(
        {d for df in assets_data.values() for d in df.index if baseline_start <= str(d.date()) <= crisis_start}
    )
    baseline_rs: list[float] = []
    for d in baseline_dates:
        rs = []
        for name, df in assets_data.items():
            if d in df.index:
                row = df.loc[d]
                sig, lbl = row["signal"], row["label"]
                tp, sl = pt_sl.get(name, (2.0, 2.0))
                rs.append(compute_r(sig, lbl, tp, sl))
        baseline_rs.append(float(np.mean(rs)) if rs else 0.0)

    baseline_vol = float(np.std(baseline_rs)) if len(baseline_rs) > 10 else 1e-6
    crisis_vol = float(np.std(daily_rs)) if len(daily_rs) > 1 else 0.0

    vol_ratio = crisis_vol / baseline_vol if baseline_vol > 0 else 0.0
    vol_trip = vol_ratio >= CIRCUIT_BREAKER_VOL_SPIKE_THRESHOLD

    return {
        "max_consecutive_losses": max_streak,
        "would_trip_loss_streak": loss_trip,
        "crisis_daily_vol": round(crisis_vol, 4),
        "baseline_daily_vol": round(baseline_vol, 4),
        "vol_ratio": round(vol_ratio, 2),
        "would_trip_vol_spike": vol_trip,
        "tripped": loss_trip or vol_trip,
        "n_days": len(daily_rs),
    }


# ── Per-crisis analysis ────────────────────────────────────────────────────


def analyze_crisis_window(
    name: str,
    desc: str,
    start: str,
    end: str,
    assets_data: dict[str, pd.DataFrame],
    pt_sl_map: dict[str, tuple[float, float]],
) -> CrisisWindowResult:
    """Run full analysis for one crisis window."""
    logger.info("Analyzing crisis window: %s (%s to %s)", name, start, end)

    result = CrisisWindowResult(name=name, description=desc, start=start, end=end)

    # Per-asset analysis
    asset_metrics: list[AssetCrisisMetrics] = []
    for aname, df in assets_data.items():
        tp, sl = pt_sl_map.get(aname, (2.0, 2.0))
        m = analyze_asset(aname, df, start, end, tp, sl)
        asset_metrics.append(m)
    result.asset_metrics = asset_metrics

    # Trading days in window
    all_dates = sorted(set(d for df in assets_data.values() for d in df.index if start <= str(d.date()) <= end))
    result.n_trading_days = len(all_dates)

    # Portfolio-level metrics
    daily_rs: list[float] = []
    for d in all_dates:
        rs = []
        for aname, df in assets_data.items():
            if d in df.index:
                row = df.loc[d]
                sig, lbl = row["signal"], row["label"]
                tp, sl = pt_sl_map.get(aname, (2.0, 2.0))
                rs.append(compute_r(sig, lbl, tp, sl))
        daily_rs.append(float(np.mean(rs)) if rs else 0.0)

    result.portfolio_total_r = round(sum(daily_rs), 2)
    result.portfolio_avg_daily_r = round(float(np.mean(daily_rs)), 4) if daily_rs else 0.0
    result.portfolio_daily_r_vol = round(float(np.std(daily_rs)), 4) if len(daily_rs) > 1 else 0.0
    result.portfolio_loss_day_ratio = round(sum(1 for r in daily_rs if r < 0) / len(daily_rs), 3) if daily_rs else 0.0

    # Max drawdown within crisis
    cum = np.cumsum(daily_rs) if daily_rs else [0.0]
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    result.portfolio_max_dd_r = round(float(np.min(dd)), 2) if len(dd) > 0 else 0.0

    # Consecutive portfolio losses
    max_streak = 0
    streak = 0
    for r in daily_rs:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    result.max_consecutive_portfolio_losses = max_streak
    result.would_trip_loss_streak = max_streak >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES

    # Vol spike check
    bl_vol = baseline_vol_if_available(assets_data, start)
    result.would_trip_vol_spike = result.portfolio_daily_r_vol > CIRCUIT_BREAKER_VOL_SPIKE_THRESHOLD * bl_vol

    # Correlation change
    result.avg_pairwise_corr_in_crisis = compute_avg_pairwise_corr(assets_data, (start, end))

    # Worst-hit assets (by total_R in crisis)
    sorted_by_r = sorted(asset_metrics, key=lambda m: m.crisis_total_r)
    result.worst_assets_total_r = [(m.name, m.crisis_total_r) for m in sorted_by_r[:5]]
    sorted_by_wr = sorted(asset_metrics, key=lambda m: m.crisis_win_rate)
    result.worst_assets_wr = [(m.name, m.crisis_win_rate) for m in sorted_by_wr[:5]]

    # Cluster analysis
    result.cluster_losses = analyze_clusters(assets_data, start, end)

    return result


def baseline_vol_if_available(
    assets_data: dict[str, pd.DataFrame],
    crisis_start: str,
) -> float:
    """Estimate baseline daily portfolio vol before crisis."""
    baseline_start = "2024-10-17"
    dates = sorted(
        {d for df in assets_data.values() for d in df.index if baseline_start <= str(d.date()) <= crisis_start}
    )
    if len(dates) < 10:
        return 1e-6
    pt_sl = load_pt_sl()
    rs: list[float] = []
    for d in dates:
        r_vals = []
        for name, df in assets_data.items():
            if d in df.index:
                row = df.loc[d]
                sig, lbl = row["signal"], row["label"]
                tp, sl = pt_sl.get(name, (2.0, 2.0))
                r_vals.append(compute_r(sig, lbl, tp, sl))
        rs.append(float(np.mean(r_vals)) if r_vals else 0.0)
    return float(np.std(rs)) if len(rs) > 1 else 1e-6


# ── Summary report ────────────────────────────────────────────────────────


def generate_summary(
    results: list[CrisisWindowResult],
) -> str:
    """Generate a human-readable crisis replay report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CRISIS REPLAY REPORT")
    lines.append("=" * 72)
    lines.append("Data range: Oct 2024 - May 2026")
    lines.append("Assets analyzed: current 18-asset portfolio")
    lines.append(f"Crisis windows: {len(results)}")
    lines.append("")

    for result in results:
        lines.append("-" * 72)
        lines.append(f"Crisis: {result.name}")
        lines.append(f"  Period: {result.start} to {result.end} ({result.n_trading_days} trading days)")
        lines.append(f"  Description: {result.description}")
        lines.append("")

        lines.append("  ── Portfolio ──")
        lines.append(f"  Total R:            {result.portfolio_total_r:>8.2f}")
        lines.append(f"  Avg daily R:        {result.portfolio_avg_daily_r:>8.4f}")
        lines.append(f"  Daily R vol:        {result.portfolio_daily_r_vol:>8.4f}")
        lines.append(f"  Max drawdown R:     {result.portfolio_max_dd_r:>8.2f}")
        lines.append(f"  Loss day ratio:     {result.portfolio_loss_day_ratio:>8.1%}")
        lines.append(f"  Consec loss streak: {result.max_consecutive_portfolio_losses:>8d}")
        lines.append("")

        lines.append("  ── Circuit Breaker ──")
        cb = "TRIPPED" if result.would_trip_loss_streak or result.would_trip_vol_spike else "ok"
        lines.append(f"  Status:             {cb:>8s}")
        loss_needs = f"needs {CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES}+"
        lines.append(f"  Loss streak trip:   {str(result.would_trip_loss_streak):>8s}  ({loss_needs})")
        vol_needs = f"needs {CIRCUIT_BREAKER_VOL_SPIKE_THRESHOLD}x+"
        lines.append(f"  Vol spike trip:     {str(result.would_trip_vol_spike):>8s}  ({vol_needs})")
        lines.append("")

        lines.append("  ── Correlation ──")
        lines.append(f"  Avg pairwise corr:  {result.avg_pairwise_corr_in_crisis:>8.3f}")
        lines.append("")

        lines.append("  ── Worst 5 assets by total R ──")
        for name, r_val in result.worst_assets_total_r:
            m = next((x for x in result.asset_metrics if x.name == name), None)
            sell_tag = " [SELL_ONLY]" if m and m.is_sell_only else ""
            wr = f"{m.crisis_win_rate:.0%}" if m else "N/A"
            lines.append(f"    {name:>10s}: total_R={r_val:>7.2f}  WR={wr}{sell_tag}")

        lines.append("")
        lines.append("  ── Worst 5 assets by win rate ──")
        for name, wr_val in result.worst_assets_wr:
            m = next((x for x in result.asset_metrics if x.name == name), None)
            sell_tag = " [SELL_ONLY]" if m and m.is_sell_only else ""
            rv = f"{m.crisis_total_r:.2f}" if m else "N/A"
            lines.append(f"    {name:>10s}: WR={wr_val:.0%}  total_R={rv}{sell_tag}")

        lines.append("")
        lines.append("  ── Best 5 assets by total R ──")
        best = sorted(result.asset_metrics, key=lambda m: m.crisis_total_r, reverse=True)[:5]
        for m in best:
            sell_tag = " [SELL_ONLY]" if m.is_sell_only else ""
            lines.append(f"    {m.name:>10s}: total_R={m.crisis_total_r:>7.2f}  WR={m.crisis_win_rate:.0%}{sell_tag}")

        lines.append("")
        lines.append("  ── Asset cluster losses ──")
        for cname, info in sorted(result.cluster_losses.items()):
            label = info["label"]
            r_val = info["crisis_total_r"]
            lr = info["crisis_loss_rate"]
            nt = info["n_trades_in_crisis"]
            lines.append(f"    {cname:>15s} ({label}): total_R={r_val:>7.2f}  loss_rate={lr:.0%}  trades={nt}")

        lines.append("")

    # ── Cross-crisis summary ──
    lines.append("=" * 72)
    lines.append("CROSS-CRISIS SUMMARY")
    lines.append("=" * 72)

    # Assets that consistently underperform across crises
    from collections import Counter

    worst_frequent: Counter[str] = Counter()
    for result in results:
        for name, _ in result.worst_assets_total_r:
            worst_frequent[name] += 1
    lines.append(f"\nAssets appearing in worst-5-totalR across {len(results)} crises:")
    for name, count in worst_frequent.most_common(5):
        pct = count / len(results) * 100
        sell_tag = " [SELL_ONLY]" if name in SELL_ONLY_ASSETS else ""
        lines.append(f"  {name:>10s}: {count}/{len(results)} crises ({pct:.0f}%){sell_tag}")

    # SELL_ONLY filter assessment
    lines.append("\nSELL_ONLY filter assessment:")
    for result in results:
        sell_only_assets = [m for m in result.asset_metrics if m.is_sell_only]
        non_sell = [m for m in result.asset_metrics if not m.is_sell_only]

        so_avg_r = np.mean([m.crisis_total_r for m in sell_only_assets]) if sell_only_assets else 0.0
        ns_avg_r = np.mean([m.crisis_total_r for m in non_sell]) if non_sell else 0.0

        so_wr = np.mean([m.crisis_win_rate for m in sell_only_assets]) if sell_only_assets else 0.0
        ns_wr = np.mean([m.crisis_win_rate for m in non_sell]) if non_sell else 0.0

        lines.append(f"  {result.name}:")
        lines.append(f"    SELL_ONLY assets   avg_R={so_avg_r:>7.2f}  avg_WR={so_wr:.0%}")
        lines.append(f"    Non-SELL_ONLY      avg_R={ns_avg_r:>7.2f}  avg_WR={ns_wr:.0%}")

    # Normal-period profit analysis
    lines.append("\nNORMAL-PERIOD PROFIT ANALYSIS")
    lines.append("=" * 72)
    lines.append("(Crisis windows excluded — shows profit potential during normal trading)")

    for result in results:
        lines.append(f"\n  ── {result.name} normal-period ──")
        # Per-asset normal metrics
        lines.append(f"  {'Asset':>10s}  {'Normal R':>9s}  {'Avg R':>7s}  {'WR':>5s}  {'SO?':>4s}")
        lines.append(f"  {'-' * 10}  {'-' * 9}  {'-' * 7}  {'-' * 5}  {'-' * 4}")
        for m in sorted(result.asset_metrics, key=lambda x: -x.normal_total_r)[:18]:
            so_mark = "SO" if m.is_sell_only else ""
            nr = m.normal_total_r
            avg = m.normal_avg_r
            wr = m.normal_win_rate
            lines.append(f"  {m.name:>10s}  {nr:>9.2f}  {avg:>7.4f}  {wr:>4.0%}  {so_mark:>4s}")

        # Aggregated: SO vs non-SO normal-period profit
        so_assets = [m for m in result.asset_metrics if m.is_sell_only]
        ns_assets = [m for m in result.asset_metrics if not m.is_sell_only]
        so_total_r = sum(m.normal_total_r for m in so_assets)
        ns_total_r = sum(m.normal_total_r for m in ns_assets)
        so_avg_wr = float(np.mean([m.normal_win_rate for m in so_assets])) if so_assets else 0.0
        ns_avg_wr = float(np.mean([m.normal_win_rate for m in ns_assets])) if ns_assets else 0.0

        total_both = so_total_r + ns_total_r + 1e-9
        so_pct_norm = so_total_r / total_both * 100
        ns_pct_norm = ns_total_r / total_both * 100
        lines.append(f"\n    SELL_ONLY assets   ({len(so_assets)} assets):")
        lines.append(f"      Total normal R:    {so_total_r:>8.2f}  ({so_pct_norm:.1f}% of portfolio)")
        lines.append(f"      Avg normal WR:     {so_avg_wr:>8.1%}")
        lines.append(f"    Non-SELL_ONLY assets ({len(ns_assets)} assets):")
        lines.append(f"      Total normal R:    {ns_total_r:>8.2f}  ({ns_pct_norm:.1f}% of portfolio)")
        lines.append(f"      Avg normal WR:     {ns_avg_wr:>8.1%}")

    # Overall: all periods combined (crisis + normal)
    lines.append("\n  ── Whole-sample profit contribution ──")
    so_by_asset: dict[str, list[AssetCrisisMetrics]] = {}
    ns_by_asset: dict[str, list[AssetCrisisMetrics]] = {}
    for r in results:
        for m in r.asset_metrics:
            target = so_by_asset if m.is_sell_only else ns_by_asset
            target.setdefault(m.name, []).append(m)

    def asset_total_normal_r(metrics_list: list[AssetCrisisMetrics]) -> float:
        return sum(m.normal_total_r + m.crisis_total_r for m in metrics_list)

    so_totals = {name: asset_total_normal_r(lst) for name, lst in so_by_asset.items()}
    ns_totals = {name: asset_total_normal_r(lst) for name, lst in ns_by_asset.items()}

    lines.append(f"  {'Asset':>10s}  {'Total R':>9s}  {'SO?':>4s}")
    lines.append(f"  {'-' * 10}  {'-' * 9}  {'-' * 4}")
    for name in sorted(set(list(so_totals.keys()) + list(ns_totals.keys()))):
        is_so = name in so_totals
        r_val = so_totals.get(name, 0.0) if is_so else ns_totals.get(name, 0.0)
        so_mark = "SO" if is_so else ""
        for mlist in so_by_asset.get(name, []) + ns_by_asset.get(name, []):
            r_val = mlist.normal_total_r + mlist.crisis_total_r
            break
        lines.append(f"  {name:>10s}  {r_val:>9.2f}  {so_mark:>4s}")

    total_so_r = sum(v for v in so_totals.values())
    total_ns_r = sum(v for v in ns_totals.values())
    total_all = total_so_r + total_ns_r
    lines.append(f"\n  Portfolio total R:    {total_all:>8.2f}")
    if total_all != 0:
        so_pct = total_so_r / total_all * 100
        ns_pct = total_ns_r / total_all * 100
        lines.append(f"  SELL_ONLY contrib:   {total_so_r:>8.2f}  ({so_pct:.1f}%)")
        lines.append(f"  Non-SELL_ONLY contrib: {total_ns_r:>8.2f}  ({ns_pct:.1f}%)")

    lines.append("\n  ── SELL_ONLY profit cost (what BUY signals would have earned) ──")
    lines.append("  If SELL_ONLY assets were allowed to BUY during normal periods:")
    for result in results:
        so_assets_t = [m for m in result.asset_metrics if m.is_sell_only]
        if not so_assets_t:
            continue
        # How much did they earn by SELL-only?
        actual_r = sum(m.normal_total_r for m in so_assets_t)
        # Estimate what BUY would have earned: SELL-only means we only take SELL signals.
        # For normal periods, we can approximate: if they had taken BOTH sides,
        # total R ≈ normal_total_r (which is SELL-only) + BUY_contrib.
        # We don't have BUY_contrib directly, but we can approximate by checking
        # if the asset would have won on BUY predictions.
        lines.append(f"    {result.name}: SELL-only earned {actual_r:>7.2f}R during normal period")

    # Circuit breaker assessment
    lines.append("\nCircuit breaker assessment:")
    any_trip = any(r.would_trip_loss_streak or r.would_trip_vol_spike for r in results)
    lines.append(f"  Would have tripped in any crisis: {any_trip}")
    for result in results:
        if result.would_trip_loss_streak or result.would_trip_vol_spike:
            reasons = []
            if result.would_trip_loss_streak:
                reasons.append(f"loss_streak={result.max_consecutive_portfolio_losses}")
            if result.would_trip_vol_spike:
                reasons.append("vol_spike")
            lines.append(f"    {result.name}: {', '.join(reasons)}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


# ── JSON export ────────────────────────────────────────────────────────────


def results_to_serializable(results: list[CrisisWindowResult]) -> list[dict]:
    """Convert results to JSON-serializable dicts."""
    serial: list[dict] = []
    for r in results:
        asset_dicts = []
        for m in r.asset_metrics:
            asset_dicts.append(
                {
                    "name": m.name,
                    "crisis_total_r": m.crisis_total_r,
                    "crisis_win_rate": round(m.crisis_win_rate, 4),
                    "crisis_avg_r": m.crisis_avg_r,
                    "crisis_n_trades": m.crisis_n_trades,
                    "crisis_max_consecutive_losses": m.crisis_max_consecutive_losses,
                    "crisis_vol": m.crisis_vol,
                    "normal_total_r": m.normal_total_r,
                    "normal_win_rate": round(m.normal_win_rate, 4),
                    "normal_avg_r": m.normal_avg_r,
                    "normal_n_trades": m.normal_n_trades,
                    "normal_vol": m.normal_vol,
                    "vol_ratio": m.vol_ratio,
                    "win_rate_change_pp": m.win_rate_change,
                    "r_per_trade_change": m.r_per_trade_change,
                    "is_sell_only": m.is_sell_only,
                    "would_trip_loss_streak": m.would_trip_loss_streak,
                }
            )
        serial.append(
            {
                "name": r.name,
                "description": r.description,
                "start": r.start,
                "end": r.end,
                "n_trading_days": r.n_trading_days,
                "portfolio_total_r": r.portfolio_total_r,
                "portfolio_max_dd_r": r.portfolio_max_dd_r,
                "portfolio_avg_daily_r": r.portfolio_avg_daily_r,
                "portfolio_daily_r_vol": r.portfolio_daily_r_vol,
                "portfolio_loss_day_ratio": r.portfolio_loss_day_ratio,
                "avg_pairwise_corr": r.avg_pairwise_corr_in_crisis,
                "max_consecutive_portfolio_losses": r.max_consecutive_portfolio_losses,
                "would_trip_loss_streak": r.would_trip_loss_streak,
                "would_trip_vol_spike": r.would_trip_vol_spike,
                "worst_assets_total_r": [(n, round(v, 2)) for n, v in r.worst_assets_total_r],
                "worst_assets_wr": [(n, round(v, 4)) for n, v in r.worst_assets_wr],
                "cluster_losses": r.cluster_losses,
                "assets": asset_dicts,
            }
        )
    return serial


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    desc = "Crisis replay — stress-test portfolio against historical crisis windows"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument(
        "--output-dir", default=None, help="Output directory for JSON reports (prints to stdout by default)"
    )
    args = parser.parse_args()

    logger.info("Loading signal parquets from %s", WALKDIR)
    assets_data = load_all_signals()
    pt_sl_map = load_pt_sl()
    logger.info("Loaded %d assets, %d with pt_sl config", len(assets_data), len(pt_sl_map))

    results: list[CrisisWindowResult] = []
    for cw in CRISIS_WINDOWS:
        r = analyze_crisis_window(
            name=cw["name"],
            desc=cw["description"],
            start=cw["start"],
            end=cw["end"],
            assets_data=assets_data,
            pt_sl_map=pt_sl_map,
        )
        results.append(r)

    # Summary
    report = generate_summary(results)
    print(report)

    # Export JSON
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"crisis_replay_{ts}.json"
        with open(json_path, "w") as f:
            json.dump(results_to_serializable(results), f, indent=2)
        logger.info("Report saved to %s", json_path)

    # Return non-zero if any breaker would have tripped
    for r in results:
        if r.would_trip_loss_streak or r.would_trip_vol_spike:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
