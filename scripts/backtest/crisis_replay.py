#!/usr/bin/env python3
"""
Crisis scenario replay — stress-test assets and portfolio against known
historical crisis windows within the available OOS data.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/crisis_replay.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/crisis_replay.py --tag expanded_10yr
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/crisis_replay.py --output-dir data/crisis_reports
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("crisis_replay")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

# Current SELL_ONLY assets from configs/domain_models/risk.py
SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "EURCHF",
        "GBPCHF",
        "GBPJPY",
        "NZDCHF",
        "EURAUD",
    }
)

# ── Crisis windows within Oct 2024 - Jul 2026 ──────────────────────────────
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


# ── Vectorized R computation ──────────────────────────────────────────────


def _vectorized_compute_r(
    signal: pd.Series, label: pd.Series, tp: float, sl: float
) -> np.ndarray:
    """Compute R-multiple for all rows in one vectorized pass."""
    result = np.zeros(len(signal), dtype=np.float64)
    sig_vals = signal.values
    lbl_vals = label.values
    # BUY signals (signal == 1): won if label == 1
    buy_mask = sig_vals == 1
    result[buy_mask] = np.where(lbl_vals[buy_mask] == 1, tp, -sl)
    # SELL signals (signal == -1): won if label == 0
    sell_mask = sig_vals == -1
    result[sell_mask] = np.where(lbl_vals[sell_mask] == 0, tp, -sl)
    return result


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


def load_all_signals(tag: str | None = None) -> dict[str, pd.DataFrame]:
    """Load all asset signal parquets from walkforward dir, precomputing R
    values vectorized at load time."""
    assets: dict[str, pd.DataFrame] = {}
    suffix = f"_wf_signals{'_' + tag if tag else ''}.parquet"
    pattern = os.path.join(WALKDIR, f"*{suffix}")
    pt_sl_map = load_pt_sl()
    for fpath in glob.glob(pattern):
        name = os.path.basename(fpath).replace(suffix, "")
        df = pd.read_parquet(fpath)
        tp, sl = pt_sl_map.get(name, (2.0, 2.0))
        df["r"] = _vectorized_compute_r(df["signal"], df["label"], tp, sl)
        assets[name] = df
    return assets


# ── Per-asset analysis ─────────────────────────────────────────────────────


def analyze_asset(
    name: str,
    df: pd.DataFrame,
    crisis_start: str,
    crisis_end: str,
) -> AssetCrisisMetrics:
    """Compare asset performance inside vs outside a crisis window.
    Uses precomputed 'r' column from load_all_signals."""
    is_sell_only = name in SELL_ONLY_ASSETS

    crisis_mask = (df.index >= crisis_start) & (df.index <= crisis_end)
    crisis_df = df[crisis_mask]
    normal_df = df[~crisis_mask]

    def _subset_stats(subset: pd.DataFrame) -> dict:
        if subset.empty:
            return {"total_r": 0.0, "win_rate": 0.0, "avg_r": 0.0, "n_trades": 0, "r_list": []}
        active_mask = subset["signal"] != 0
        if not active_mask.any():
            return {"total_r": 0.0, "win_rate": 0.0, "avg_r": 0.0, "n_trades": 0, "r_list": []}
        rs = subset.loc[active_mask, "r"]
        return {
            "total_r": float(rs.sum()),
            "win_rate": float((rs > 0).sum() / len(rs)),
            "avg_r": float(rs.mean()),
            "n_trades": len(rs),
            "r_list": rs.tolist(),
        }

    crisis = _subset_stats(crisis_df)
    normal = _subset_stats(normal_df)

    # Consecutive losses in crisis
    max_consec = 0
    consec = 0
    for r_val in crisis["r_list"]:
        if r_val < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    crisis_vol = float(np.std(crisis["r_list"])) if len(crisis["r_list"]) > 1 else 0.0
    normal_vol = float(np.std(normal["r_list"])) if len(normal["r_list"]) > 1 else 1e-9

    return AssetCrisisMetrics(
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


# ── Correlation analysis ──────────────────────────────────────────────────


def compute_avg_pairwise_corr(
    assets_data: dict[str, pd.DataFrame],
    date_range: tuple[str, str],
) -> float:
    """Compute average pairwise return correlation within a date range
    using precomputed 'r' columns."""
    start, end = date_range
    # Build return matrix aligned by date
    all_dates = sorted(
        {
            d
            for df in assets_data.values()
            for d in df.index
            if start <= str(d.date()) <= end and "r" in df.columns
        }
    )
    if len(all_dates) < 5:
        return 0.0

    returns_dict: dict[str, pd.Series] = {}
    for name, df in assets_data.items():
        if "r" in df.columns:
            returns_dict[name] = df["r"].reindex(all_dates, fill_value=0.0)

    df_rets = pd.DataFrame(returns_dict, index=all_dates)
    corr = df_rets.corr()
    vals = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
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
        "equities": {"assets": ["^DJI"], "label": "US equities"},
        "aud": {"assets": ["AUDUSD", "EURAUD"], "label": "AUD pairs"},
        "commodity": {"assets": ["GC"], "label": "Gold"},
    }

    results: dict[str, dict] = {}
    for cluster_name, cluster_info in clusters.items():
        existing = [a for a in cluster_info["assets"] if a in assets_data]
        if not existing:
            continue

        total_r = 0.0
        n_losses = 0
        n_trades = 0
        for name in existing:
            df = assets_data[name]
            if "r" not in df.columns:
                continue
            crisis = df[(df.index >= crisis_start) & (df.index <= crisis_end)]
            active = crisis[crisis["signal"] != 0]
            rs = active["r"]
            total_r += rs.sum()
            n_losses += (rs < 0).sum()
            n_trades += len(rs)

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
    """Simulate the portfolio circuit breaker during crisis using precomputed R.

    Checks:
      1. Consecutive portfolio loss streak (15-day threshold)
      2. Vol spike (rolling 10-day vol vs baseline vol, 3x threshold)
    """
    dates = sorted(
        {
            d
            for df in assets_data.values()
            for d in df.index
            if crisis_start <= str(d.date()) <= crisis_end and "r" in df.columns
        }
    )
    if not dates:
        return {"tripped": False, "reason": "no_data"}

    # Daily portfolio returns from precomputed R
    daily_rs: list[float] = []
    for d in dates:
        rs = [
            assets_data[name].loc[d, "r"]
            for name in assets_data
            if d in assets_data[name].index and "r" in assets_data[name].columns
        ]
        daily_rs.append(float(np.mean(rs)) if rs else 0.0)

    # 1. Consecutive loss streak
    max_streak = 0
    streak = 0
    for r_val in daily_rs:
        if r_val < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    loss_trip = max_streak >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES

    # 2. Vol spike
    baseline_rs = _baseline_daily_rs(assets_data, crisis_start)
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


def _baseline_daily_rs(
    assets_data: dict[str, pd.DataFrame],
    crisis_start: str,
) -> list[float]:
    """Compute daily portfolio returns from precomputed R for baseline period."""
    baseline_start = "2024-10-17"
    dates = sorted(
        {
            d
            for df in assets_data.values()
            for d in df.index
            if baseline_start <= str(d.date()) <= crisis_start and "r" in df.columns
        }
    )
    if len(dates) < 10:
        return [0.0]
    rs: list[float] = []
    for d in dates:
        r_vals = [
            assets_data[name].loc[d, "r"]
            for name in assets_data
            if d in assets_data[name].index and "r" in assets_data[name].columns
        ]
        rs.append(float(np.mean(r_vals)) if r_vals else 0.0)
    return rs


def baseline_vol_if_available(
    assets_data: dict[str, pd.DataFrame],
    crisis_start: str,
) -> float:
    """Estimate baseline daily portfolio vol before crisis using precomputed R."""
    rs = _baseline_daily_rs(assets_data, crisis_start)
    return float(np.std(rs)) if len(rs) > 1 else 1e-6


# ── Per-crisis analysis ────────────────────────────────────────────────────


def analyze_crisis_window(
    name: str,
    desc: str,
    start: str,
    end: str,
    assets_data: dict[str, pd.DataFrame],
) -> CrisisWindowResult:
    """Run full analysis for one crisis window using precomputed R columns."""
    logger.info("Analyzing crisis window: %s (%s to %s)", name, start, end)

    result = CrisisWindowResult(name=name, description=desc, start=start, end=end)

    # Per-asset analysis
    asset_metrics: list[AssetCrisisMetrics] = []
    for aname, df in assets_data.items():
        m = analyze_asset(aname, df, start, end)
        asset_metrics.append(m)
    result.asset_metrics = asset_metrics

    # Trading days in window
    all_dates = sorted(
        {
            d
            for df in assets_data.values()
            for d in df.index
            if start <= str(d.date()) <= end and "r" in df.columns
        }
    )
    result.n_trading_days = len(all_dates)

    # Portfolio-level daily metrics from precomputed R
    daily_rs: list[float] = []
    for d in all_dates:
        rs = [
            assets_data[aname].loc[d, "r"]
            for aname in assets_data
            if d in assets_data[aname].index and "r" in assets_data[aname].columns
        ]
        daily_rs.append(float(np.mean(rs)) if rs else 0.0)

    result.portfolio_total_r = round(sum(daily_rs), 2)
    result.portfolio_avg_daily_r = round(float(np.mean(daily_rs)), 4) if daily_rs else 0.0
    result.portfolio_daily_r_vol = round(float(np.std(daily_rs)), 4) if len(daily_rs) > 1 else 0.0
    result.portfolio_loss_day_ratio = (
        round(sum(1 for r_val in daily_rs if r_val < 0) / len(daily_rs), 3) if daily_rs else 0.0
    )

    # Max drawdown within crisis
    cum = np.cumsum(daily_rs) if daily_rs else [0.0]
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    result.portfolio_max_dd_r = round(float(np.min(dd)), 2) if len(dd) > 0 else 0.0

    # Consecutive portfolio losses
    max_streak = 0
    streak = 0
    for r_val in daily_rs:
        if r_val < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    result.max_consecutive_portfolio_losses = max_streak
    result.would_trip_loss_streak = max_streak >= CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES

    # Vol spike check
    bl_vol = baseline_vol_if_available(assets_data, start)
    result.would_trip_vol_spike = result.portfolio_daily_r_vol > CIRCUIT_BREAKER_VOL_SPIKE_THRESHOLD * bl_vol

    # Correlation change (uses precomputed R)
    result.avg_pairwise_corr_in_crisis = compute_avg_pairwise_corr(assets_data, (start, end))

    # Worst-hit assets (by total_R in crisis)
    sorted_by_r = sorted(asset_metrics, key=lambda m: m.crisis_total_r)
    result.worst_assets_total_r = [(m.name, m.crisis_total_r) for m in sorted_by_r[:5]]
    sorted_by_wr = sorted(asset_metrics, key=lambda m: m.crisis_win_rate)
    result.worst_assets_wr = [(m.name, m.crisis_win_rate) for m in sorted_by_wr[:5]]

    # Cluster analysis (uses precomputed R)
    result.cluster_losses = analyze_clusters(assets_data, start, end)

    return result


# ── Summary report ────────────────────────────────────────────────────────


def generate_summary(
    results: list[CrisisWindowResult],
) -> str:
    """Generate a human-readable crisis replay report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CRISIS REPLAY REPORT")
    lines.append("=" * 72)
    lines.append("Data range: Oct 2024 - Jul 2026")
    lines.append(f"Assets analyzed: {len(results[0].asset_metrics) if results else 0} assets")
    lines.append(f"Crisis windows: {len(results)}")
    lines.append("")

    for result in results:
        lines.append("-" * 72)
        lines.append(f"Crisis: {result.name}")
        lines.append(
            f"  Period: {result.start} to {result.end} ({result.n_trading_days} trading days)"
        )
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
        for aname, r_val in result.worst_assets_total_r:
            m = next((x for x in result.asset_metrics if x.name == aname), None)
            sell_tag = " [SELL_ONLY]" if m and m.is_sell_only else ""
            wr = f"{m.crisis_win_rate:.0%}" if m else "N/A"
            lines.append(f"    {aname:>10s}: total_R={r_val:>7.2f}  WR={wr}{sell_tag}")

        lines.append("")
        lines.append("  ── Worst 5 assets by win rate ──")
        for aname, wr_val in result.worst_assets_wr:
            m = next((x for x in result.asset_metrics if x.name == aname), None)
            sell_tag = " [SELL_ONLY]" if m and m.is_sell_only else ""
            rv = f"{m.crisis_total_r:.2f}" if m else "N/A"
            lines.append(f"    {aname:>10s}: WR={wr_val:.0%}  total_R={rv}{sell_tag}")

        lines.append("")
        lines.append("  ── Best 5 assets by total R ──")
        best = sorted(result.asset_metrics, key=lambda m: m.crisis_total_r, reverse=True)[:5]
        for m in best:
            sell_tag = " [SELL_ONLY]" if m.is_sell_only else ""
            lines.append(
                f"    {m.name:>10s}: total_R={m.crisis_total_r:>7.2f}  WR={m.crisis_win_rate:.0%}{sell_tag}"
            )

        lines.append("")
        lines.append("  ── Asset cluster losses ──")
        for cname, info in sorted(result.cluster_losses.items()):
            label = info["label"]
            r_val = info["crisis_total_r"]
            lr = info["crisis_loss_rate"]
            nt = info["n_trades_in_crisis"]
            lines.append(
                f"    {cname:>15s} ({label}): total_R={r_val:>7.2f}  loss_rate={lr:.0%}  trades={nt}"
            )
        lines.append("")

    # ── Cross-crisis summary ──
    lines.append("=" * 72)
    lines.append("CROSS-CRISIS SUMMARY")
    lines.append("=" * 72)

    worst_frequent: Counter[str] = Counter()
    for result in results:
        for aname, _ in result.worst_assets_total_r:
            worst_frequent[aname] += 1
    lines.append(f"\nAssets appearing in worst-5-totalR across {len(results)} crises:")
    for aname, count in worst_frequent.most_common(5):
        pct = count / len(results) * 100
        sell_tag = " [SELL_ONLY]" if aname in SELL_ONLY_ASSETS else ""
        lines.append(f"  {aname:>10s}: {count}/{len(results)} crises ({pct:.0f}%){sell_tag}")

    # SELL_ONLY filter assessment
    lines.append("\nSELL_ONLY filter assessment:")
    for result in results:
        sell_only_assets = [m for m in result.asset_metrics if m.is_sell_only]
        non_sell = [m for m in result.asset_metrics if not m.is_sell_only]
        so_avg_r = float(np.mean([m.crisis_total_r for m in sell_only_assets])) if sell_only_assets else 0.0
        ns_avg_r = float(np.mean([m.crisis_total_r for m in non_sell])) if non_sell else 0.0
        so_wr = float(np.mean([m.crisis_win_rate for m in sell_only_assets])) if sell_only_assets else 0.0
        ns_wr = float(np.mean([m.crisis_win_rate for m in non_sell])) if non_sell else 0.0
        lines.append(f"  {result.name}:")
        lines.append(f"    SELL_ONLY assets   avg_R={so_avg_r:>7.2f}  avg_WR={so_wr:.0%}")
        lines.append(f"    Non-SELL_ONLY      avg_R={ns_avg_r:>7.2f}  avg_WR={ns_wr:.0%}")

    # Normal-period profit analysis
    lines.append("\nNORMAL-PERIOD PROFIT ANALYSIS")
    lines.append("=" * 72)
    lines.append("(Crisis windows excluded — shows profit potential during normal trading)")

    for result in results:
        lines.append(f"\n  ── {result.name} normal-period ──")
        lines.append(f"  {'Asset':>10s}  {'Normal R':>9s}  {'Avg R':>7s}  {'WR':>5s}  {'SO?':>4s}")
        lines.append(f"  {'-' * 10}  {'-' * 9}  {'-' * 7}  {'-' * 5}  {'-' * 4}")
        for m in sorted(result.asset_metrics, key=lambda x: -x.normal_total_r)[:18]:
            so_mark = "SO" if m.is_sell_only else ""
            lines.append(
                f"  {m.name:>10s}  {m.normal_total_r:>9.2f}  {m.normal_avg_r:>7.4f}  {m.normal_win_rate:>4.0%}  {so_mark:>4s}"
            )

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

    # Whole-sample profit contribution
    lines.append("\n  ── Whole-sample profit contribution ──")
    so_by_asset: dict[str, list[AssetCrisisMetrics]] = {}
    ns_by_asset: dict[str, list[AssetCrisisMetrics]] = {}
    for r in results:
        for m in r.asset_metrics:
            target = so_by_asset if m.is_sell_only else ns_by_asset
            target.setdefault(m.name, []).append(m)

    lines.append(f"  {'Asset':>10s}  {'Total R':>9s}  {'SO?':>4s}")
    lines.append(f"  {'-' * 10}  {'-' * 9}  {'-' * 4}")
    all_names = sorted(set(list(so_by_asset.keys()) + list(ns_by_asset.keys())))
    for aname in all_names:
        is_so = aname in so_by_asset
        lst = so_by_asset.get(aname, []) or ns_by_asset.get(aname, [])
        r_val = sum(m.normal_total_r + m.crisis_total_r for m in lst)
        so_mark = "SO" if is_so else ""
        lines.append(f"  {aname:>10s}  {r_val:>9.2f}  {so_mark:>4s}")

    total_so_r = sum(
        sum(m.normal_total_r + m.crisis_total_r for m in lst)
        for lst in so_by_asset.values()
    )
    total_ns_r = sum(
        sum(m.normal_total_r + m.crisis_total_r for m in lst)
        for lst in ns_by_asset.values()
    )
    total_all = total_so_r + total_ns_r
    lines.append(f"\n  Portfolio total R:    {total_all:>8.2f}")
    if total_all != 0:
        so_pct = total_so_r / total_all * 100
        ns_pct = total_ns_r / total_all * 100
        lines.append(f"  SELL_ONLY contrib:   {total_so_r:>8.2f}  ({so_pct:.1f}%)")
        lines.append(f"  Non-SELL_ONLY contrib: {total_ns_r:>8.2f}  ({ns_pct:.1f}%)")

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
        "--output-dir",
        default=None,
        help="Output directory for JSON reports (prints to stdout by default)",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="Signal parquet tag (e.g. 'expanded_10yr' → *_wf_signals_expanded_10yr.parquet)",
    )
    args = parser.parse_args()

    tag_desc = f" (tag='{args.tag}')" if args.tag else ""
    logger.info("Loading signal parquets from %s%s", WALKDIR, tag_desc)
    assets_data = load_all_signals(tag=args.tag)
    logger.info(
        "Loaded %d assets (R precomputed vectorized at load time)",
        len(assets_data),
    )

    results: list[CrisisWindowResult] = []
    for cw in CRISIS_WINDOWS:
        r = analyze_crisis_window(
            name=cw["name"],
            desc=cw["description"],
            start=cw["start"],
            end=cw["end"],
            assets_data=assets_data,
        )
        results.append(r)

    report = generate_summary(results)
    print(report)

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag_suffix = f"_{args.tag}" if args.tag else ""
        json_path = out_dir / f"crisis_replay{tag_suffix}_{ts}.json"
        with open(json_path, "w") as f:
            json.dump(results_to_serializable(results), f, indent=2)
        logger.info("Report saved to %s", json_path)

    for r in results:
        if r.would_trip_loss_streak or r.would_trip_vol_spike:
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
