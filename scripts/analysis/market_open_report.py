#!/usr/bin/env python3
"""
Market Open Comparative Performance Report.

Segments 6,646 historical trades into "Open" (Monday / post-weekend gap) vs
"Regular" (Tuesday–Friday) and analyzes:

  1. Slippage Variance    — exit_price vs tp/sl target deviation
  2. Trade Frequency      — Monday vs hourly avg Tue–Fri
  3. Drawdown Sensitivity — Roughness Index + archetype clustering
  4. Volatility Metrics   — ATR, MAE/MFE by equity-curve segment

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/market_open_report.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.market_open")

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "market_open_report.json"

# ── Asset session tier mapping (mirrors configs/domains/execution/sessions.yaml) ──
SESSION_TIERS: dict[str, str] = {
    "AUDUSD": "fx_major", "GBPUSD": "fx_major", "NZDUSD": "fx_major",
    "USDCAD": "fx_major", "USDCHF": "fx_major", "USDJPY": "fx_major",
    "AUDJPY": "fx_cross",
    "^DJI": "indices",
    "GC": "metals",
    "BTCUSD": "crypto",
}
# All remaining assets default to fx_cross
DEFAULT_TIER = "fx_cross"

SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    "fx_major": (7, 17),
    "fx_cross": (7, 17),
    "indices": (13, 20),
    "metals": (8, 18),
    "crypto": (0, 24),
}

# ── Constants for analysis ──
ROUGHNESS_WINDOW = 20
MIN_SAMPLE_FOR_BUCKET = 20
DOW_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ═══════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════

def compute_slippage_bps(trade: dict) -> float | None:
    """Compute slippage proxy: % deviation of exit_price from tp/sl target.

    Positive = better fill (exit beyond target), negative = worse fill.
    Barrier exits return None (no target-based slippage).
    """
    reason = trade.get("exit_reason", "")
    if reason == "barrier":
        return None

    side = trade.get("side", "BUY")
    exit_px = trade.get("exit_price")
    target_px = trade.get("tp_price" if reason == "tp" else "sl_price")

    if not exit_px or not target_px or target_px == 0:
        return None

    raw_bps = (exit_px / target_px - 1.0) * 10000.0

    # For SHORT trades, invert sign: exit < tp is good (sell high, buy back lower)
    if side == "SHORT":
        raw_bps = -raw_bps
    # For SL exits, invert sign: exit beyond sl is bad
    if reason == "sl":
        raw_bps = -raw_bps

    return round(raw_bps, 2)


def compute_trade_archetype(trade: dict) -> str:
    """Classify trade into archetype using exit_reason as proxy.

    - breakout: hit TP (trend continuation)
    - mean_reversion_fail: hit SL (entry was in wrong direction)
    - neutral_expiry: barrier hit (market exit, no conviction)
    """
    r = trade.get("exit_reason", "")
    if r == "tp":
        return "breakout"
    elif r == "sl":
        return "mean_reversion_fail"
    else:
        return "neutral_expiry"


def parse_date_utc(d: Any) -> datetime | None:
    """Parse date string; strip timezone info and assume UTC."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    try:
        s = str(d).replace("Z", "+00:00")
        if "+" in s:
            s = s.split("+")[0]
        return datetime.fromisoformat(s[:19]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


def get_asset_tier(asset: str) -> str:
    return SESSION_TIERS.get(asset, DEFAULT_TIER)


def stats_from_arr(arr: list[float]) -> dict:
    arr = np.array(arr) if len(arr) > 0 else np.array([0.0])
    n = len(arr)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = len(wins) / n * 100 if n > 0 else 0.0
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) > 0 and losses.sum() != 0
          else (float("inf") if len(wins) > 0 else 0.0))
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 and len(arr) > 1 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    return {
        "n": n,
        "total_r": round(float(arr.sum()), 4),
        "avg_r": round(float(arr.mean()), 4),
        "wr": round(wr, 2),
        "pf": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "max_dd_r": round(dd, 2),
        "std_r": round(float(arr.std()), 4),
    }


# ═══════════════════════════════════════════════════════════════════════
# Core analysis
# ═══════════════════════════════════════════════════════════════════════

def load_trades() -> list[dict]:
    """Load and augment trades with parsed dates, bucket, archetype, slippage."""
    with open(TRADE_PATH) as f:
        data = json.load(f)
    raw = data["_trades"]
    all_trades: list[dict] = []
    for asset, trades in raw.items():
        for t in trades:
            t["_asset"] = asset
            t["_tier"] = get_asset_tier(asset)
            ed = parse_date_utc(t.get("entry_date"))
            if ed is None:
                continue
            t["_entry_dt"] = ed
            t["_dow"] = ed.strftime("%A")
            t["_dow_num"] = ed.weekday()
            t["_hour"] = ed.hour
            t["_date"] = ed.strftime("%Y-%m-%d")
            t["_slippage_bps"] = compute_slippage_bps(t)
            t["_archetype"] = compute_trade_archetype(t)

            # Bucket: Monday = OPEN proxy, Tue–Fri = REGULAR
            t["_bucket"] = "OPEN" if ed.weekday() == 0 else "REGULAR"

            all_trades.append(t)
    all_trades.sort(key=lambda t: (t["_entry_dt"], t["_asset"]))
    logger.info("Loaded %d trades across %d assets", len(all_trades), len(raw))
    return all_trades


def analyze_slippage(trades: list[dict]) -> dict:
    """Slippage Variance: compare OPEN vs REGULAR mean slippage (Welch's t-test)."""
    from scipy.stats import ttest_ind

    result: dict[str, Any] = {"overall": {}, "by_asset": {}, "by_reason": {}}
    buckets = {"OPEN": [], "REGULAR": []}
    for t in trades:
        s = t.get("_slippage_bps")
        if s is not None:
            buckets[t["_bucket"]].append(s)

    # Overall
    for bucket, vals in buckets.items():
        arr = np.array(vals)
        result["overall"][bucket] = {
            "n": len(vals),
            "mean_bps": round(float(arr.mean()), 2) if len(vals) > 0 else None,
            "std_bps": round(float(arr.std()), 2) if len(vals) > 1 else None,
            "p5_bps": round(float(np.percentile(arr, 5)), 2) if len(vals) >= 5 else None,
            "p95_bps": round(float(np.percentile(arr, 95)), 2) if len(vals) >= 5 else None,
            "sample_sufficient": len(vals) >= MIN_SAMPLE_FOR_BUCKET,
        }

    # Welch's t-test
    if len(buckets["OPEN"]) >= 2 and len(buckets["REGULAR"]) >= 2:
        t_stat, p_val = ttest_ind(buckets["OPEN"], buckets["REGULAR"], equal_var=False)
        result["overall"]["welch_ttest"] = {
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(p_val), 6),
            "significant_05": p_val < 0.05,
        }
    else:
        result["overall"]["welch_ttest"] = None

    # By asset
    for t in trades:
        s = t.get("_slippage_bps")
        if s is None:
            continue
        asset = t["_asset"]
        bucket = t["_bucket"]
        result["by_asset"].setdefault(asset, {}).setdefault(bucket, []).append(s)

    for asset, buckets_dict in result["by_asset"].items():
        for bucket, vals in buckets_dict.items():
            arr = np.array(vals)
            sufficient = len(vals) >= MIN_SAMPLE_FOR_BUCKET
            buckets_dict[bucket] = {
                "n": len(vals),
                "mean_bps": round(float(arr.mean()), 2) if sufficient else None,
                "std_bps": round(float(arr.std()), 2) if sufficient and len(vals) > 1 else None,
                "sample_sufficient": sufficient,
            }

    # By exit_reason
    for t in trades:
        s = t.get("_slippage_bps")
        if s is None:
            continue
        reason = t.get("exit_reason", "unknown")
        bucket = t["_bucket"]
        result["by_reason"].setdefault(reason, {}).setdefault(bucket, []).append(s)

    for reason, buckets_dict in result["by_reason"].items():
        for bucket, vals in buckets_dict.items():
            arr = np.array(vals)
            sufficient = len(vals) >= MIN_SAMPLE_FOR_BUCKET
            buckets_dict[bucket] = {
                "n": len(vals),
                "mean_bps": round(float(arr.mean()), 2) if sufficient else None,
                "std_bps": round(float(arr.std()), 2) if sufficient and len(vals) > 1 else None,
                "sample_sufficient": sufficient,
            }

    return result


def analyze_trade_frequency(trades: list[dict]) -> dict:
    """Trade Frequency: OPEN trades count vs hourly average in REGULAR.

    Daily-bar data: OPEN = Monday entries, REGULAR = Tue–Fri entries.
    We report total Monday trades and average Tue–Fri daily trades.
    """
    result: dict[str, Any] = {"overall": {}, "by_asset": {}}

    open_trades = [t for t in trades if t["_bucket"] == "OPEN"]
    regular_trades = [t for t in trades if t["_bucket"] == "REGULAR"]

    # Count distinct days in each bucket
    open_days = len(set(t["_date"] for t in open_trades))
    regular_days = len(set(t["_date"] for t in regular_trades))

    open_count = len(open_trades)
    regular_count = len(regular_trades)

    # Hourly equivalent: daily bar data has 1 bar/day, so "open" = 1 bar, "regular" = 4 bars
    open_bars = open_days  # Monday bars
    regular_bars = regular_days  # Tue-Fri bars

    trades_per_bar_open = open_count / max(open_bars, 1)
    trades_per_bar_regular = regular_count / max(regular_bars, 1)

    result["overall"] = {
        "open_days": open_days,
        "regular_days": regular_days,
        "open_trades": open_count,
        "regular_trades": regular_count,
        "trades_per_monday": round(trades_per_bar_open, 2),
        "avg_trades_per_tue_fri_day": round(trades_per_bar_regular, 2),
        "ratio_open_to_regular": round(
            trades_per_bar_open / max(trades_per_bar_regular, 0.001), 3
        ),
        "open_pct_of_all": round(open_count / max(len(trades), 1) * 100, 2),
    }

    # By asset
    for asset in sorted(set(t["_asset"] for t in trades)):
        at = [t for t in trades if t["_asset"] == asset]
        a_open = [t for t in at if t["_bucket"] == "OPEN"]
        a_regular = [t for t in at if t["_bucket"] == "REGULAR"]
        od = len(set(t["_date"] for t in a_open))
        rd_ = len(set(t["_date"] for t in a_regular))
        result["by_asset"][asset] = {
            "open_trades": len(a_open),
            "regular_trades": len(a_regular),
            "trades_per_monday": round(len(a_open) / max(od, 1), 2),
            "avg_trades_per_tue_fri_day": round(len(a_regular) / max(rd_, 1), 2),
            "ratio": round(
                (len(a_open) / max(od, 1)) / max(len(a_regular) / max(rd_, 1), 0.001), 3
            ),
        }

    return result


def analyze_drawdown_sensitivity(trades: list[dict]) -> dict:
    """Drawdown Sensitivity via Roughness Index.

    Roughness = rolling std of trade-by-trade PnL (R-multiple differences)
    over a 20-trade window. Resets at day boundaries.

    Cross-tabulates high-roughness trades with archetype and session bucket.
    """
    result: dict[str, Any] = {
        "roughness_quantiles": {},
        "archetype_clustering": {},
        "roughness_by_bucket": {},
    }

    # ── Build chronological equity curve with R-multiples ──
    # Group trades by day, sort by (date, asset) within each day
    daily_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        daily_trades[t["_date"]].append(t)

    # Compute roughness per trade
    trade_roughness: list[tuple[float, dict]] = []

    for date_str in sorted(daily_trades.keys()):
        day_trds = daily_trades[date_str]
        day_trds.sort(key=lambda t: t["_asset"])
        r_vals = np.array([t.get("r_multiple", 0.0) for t in day_trds])
        if len(r_vals) < 2:
            for t in day_trds:
                trade_roughness.append((0.0, t))
            continue
        # Rolling std of PnL differences within this day
        diffs = np.diff(r_vals)
        for i, t in enumerate(day_trds):
            if i == 0:
                roughness = float(abs(diffs[0])) if len(diffs) > 0 else 0.0
            else:
                idx = max(0, i - 1)
                window = diffs[max(0, idx - ROUGHNESS_WINDOW + 1): idx + 1]
                roughness = float(np.std(window)) if len(window) > 1 else float(abs(diffs[idx]))
            trade_roughness.append((roughness, t))

    if not trade_roughness:
        return result

    roughness_vals = np.array([r for r, _ in trade_roughness])
    result["roughness_stats"] = {
        "mean": round(float(roughness_vals.mean()), 4),
        "std": round(float(roughness_vals.std()), 4),
        "p50": round(float(np.median(roughness_vals)), 4),
        "p90": round(float(np.percentile(roughness_vals, 90)), 4),
        "p95": round(float(np.percentile(roughness_vals, 95)), 4),
        "p99": round(float(np.percentile(roughness_vals, 99)), 4),
        "max": round(float(roughness_vals.max()), 4),
    }

    # Quantile thresholds
    quants = [20, 40, 60, 80, 100]
    thresholds = [0] + [round(float(np.percentile(roughness_vals, q)), 4) for q in quants]
    for i in range(len(thresholds) - 1):
        label = f"Q{i}_{thresholds[i]}_{thresholds[i+1]}"
        result["roughness_quantiles"][label] = {
            "low": thresholds[i],
            "high": thresholds[i + 1],
        }

    # Classify each trade into roughness quintile
    quintile_labels = []
    for r, _ in trade_roughness:
        q = 0
        for i in range(len(thresholds) - 2):
            if r > thresholds[i + 1]:
                q = i + 1
        quintile_labels.append(q)

    # Top-quintile (most erratic) trades
    top_quintile_threshold = thresholds[-2]  # 80th percentile
    erratic_trades = [(r, t) for r, t in trade_roughness if r >= top_quintile_threshold]
    smooth_trades = [(r, t) for r, t in trade_roughness if r < top_quintile_threshold]

    result["top_quintile_threshold"] = top_quintile_threshold
    result["n_erratic_trades"] = len(erratic_trades)
    result["n_smooth_trades"] = len(smooth_trades)

    # ── Archetype clustering ──
    # Cross-tab: roughness quintile × archetype × bucket
    archetype_tab: dict[str, dict] = {}
    for (r, t), q_idx in zip(trade_roughness, quintile_labels):
        arch = t["_archetype"]
        bucket = t["_bucket"]
        key = f"Q{q_idx}"
        archetype_tab.setdefault(key, {"n_total": 0, "archetypes": {}, "buckets": {}})
        archetype_tab[key]["n_total"] += 1
        archetype_tab[key]["archetypes"].setdefault(arch, {"n": 0, "total_r": 0.0, "wr_count": 0})
        archetype_tab[key]["archetypes"][arch]["n"] += 1
        archetype_tab[key]["archetypes"][arch]["total_r"] += t.get("r_multiple", 0.0)
        if t.get("r_multiple", 0.0) > 0:
            archetype_tab[key]["archetypes"][arch]["wr_count"] += 1
        archetype_tab[key]["buckets"].setdefault(bucket, 0)
        archetype_tab[key]["buckets"][bucket] += 1

    for q_key, q_data in archetype_tab.items():
        for arch, arch_data in q_data["archetypes"].items():
            arch_data["avg_r"] = round(arch_data["total_r"] / max(arch_data["n"], 1), 4)
            arch_data["wr"] = round(arch_data["wr_count"] / max(arch_data["n"], 1) * 100, 2)

    result["archetype_clustering"] = archetype_tab

    # ── Roughness by bucket (OPEN vs REGULAR) ──
    for bucket_name in ["OPEN", "REGULAR"]:
        bucket_rough = [r for r, t in trade_roughness if t["_bucket"] == bucket_name]
        if len(bucket_rough) >= 2:
            result["roughness_by_bucket"][bucket_name] = {
                "n": len(bucket_rough),
                "mean_roughness": round(float(np.mean(bucket_rough)), 4),
                "std_roughness": round(float(np.std(bucket_rough)), 4),
            }
        elif len(bucket_rough) == 1:
            result["roughness_by_bucket"][bucket_name] = {
                "n": 1,
                "mean_roughness": round(float(bucket_rough[0]), 4),
                "std_roughness": None,
            }
        else:
            result["roughness_by_bucket"][bucket_name] = {"n": 0}

    # ── Erratic trade profile ──
    # What archetypes dominate the erratic zone? Are they OPEN or REGULAR?
    erratic_arch_dist: dict[str, int] = defaultdict(int)
    erratic_bucket_dist: dict[str, int] = defaultdict(int)
    erratic_r_sum = 0.0
    for r, t in erratic_trades:
        erratic_arch_dist[t["_archetype"]] += 1
        erratic_bucket_dist[t["_bucket"]] += 1
        erratic_r_sum += t.get("r_multiple", 0.0)

    result["erratic_profile"] = {
        "archetype_distribution": dict(erratic_arch_dist),
        "bucket_distribution": dict(erratic_bucket_dist),
        "total_r": round(erratic_r_sum, 4),
    }

    # ── Check if erratic trades are predominantly from one bucket × archetype ──
    cross_tab: dict[str, dict[str, int]] = {}
    for r, t in erratic_trades:
        b = t["_bucket"]
        a = t["_archetype"]
        cross_tab.setdefault(b, {})
        cross_tab[b][a] = cross_tab[b].get(a, 0) + 1
    result["erratic_crosstab_bucket_archetype"] = cross_tab

    return result


def analyze_volatility(trades: list[dict], roughness_result: dict) -> dict:
    """Volatility Metrics: compare erratic vs smooth segments.

    Uses ATR at entry, MAE/MFE, and intra-trade price path volatility from highs/lows.
    """
    result: dict[str, Any] = {
        "by_equity_segment": {},
        "by_bucket": {},
    }

    # Recompute erratic classification at trade level
    # Rebuild roughness (same logic as analyze_drawdown_sensitivity)
    daily_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        daily_trades[t["_date"]].append(t)

    trade_roughness: list[tuple[float, dict]] = []
    for date_str in sorted(daily_trades.keys()):
        day_trds = daily_trades[date_str]
        day_trds.sort(key=lambda t: t["_asset"])
        r_vals = np.array([t.get("r_multiple", 0.0) for t in day_trds])
        if len(r_vals) < 2:
            for t in day_trds:
                trade_roughness.append((0.0, t))
            continue
        diffs = np.diff(r_vals)
        for i, t in enumerate(day_trds):
            if i == 0:
                roughness = float(abs(diffs[0])) if len(diffs) > 0 else 0.0
            else:
                idx = max(0, i - 1)
                window = diffs[max(0, idx - ROUGHNESS_WINDOW + 1): idx + 1]
                roughness = float(np.std(window)) if len(window) > 1 else float(abs(diffs[idx]))
            trade_roughness.append((roughness, t))

    top_threshold = roughness_result.get("top_quintile_threshold", 0)
    erratic_mask = [r >= top_threshold for r, _ in trade_roughness]

    # Segment metrics
    for seg_name, mask in [("erratic", erratic_mask), ("smooth", [not m for m in erratic_mask])]:
        seg_trades = [t for (r, t), m in zip(trade_roughness, mask) if m]
        if not seg_trades:
            result["by_equity_segment"][seg_name] = {"n": 0}
            continue

        atr_vals = [t.get("atr_pct_entry", 0) for t in seg_trades if t.get("atr_pct_entry") is not None]
        mae_r_vals = [t.get("mae_r", 0) for t in seg_trades if t.get("mae_r") is not None]
        mfe_r_vals = [t.get("mfe_r", 0) for t in seg_trades if t.get("mfe_r") is not None]
        mae_bar_vals = [t.get("mae_per_bar", 0) for t in seg_trades if t.get("mae_per_bar") is not None]
        mfe_bar_vals = [t.get("mfe_per_bar", 0) for t in seg_trades if t.get("mfe_per_bar") is not None]
        r_vals = [t.get("r_multiple", 0) for t in seg_trades]
        efficiency_vals = [t.get("efficiency_score", 0) for t in seg_trades if t.get("efficiency_score") is not None]

        # Intra-trade vol from highs/lows (price path range / entry_price)
        intra_vol_vals = []
        for t in seg_trades:
            highs = t.get("highs")
            lows = t.get("lows")
            entry = t.get("entry_price", 1)
            if highs and lows and entry and entry > 0:
                high_arr = np.array(highs) if isinstance(highs, list) else highs
                low_arr = np.array(lows) if isinstance(lows, list) else lows
                if len(high_arr) > 0 and len(low_arr) > 0:
                    avg_range = float(np.mean(high_arr - low_arr))
                    intra_vol_vals.append(round(avg_range / entry * 100, 4))

        result["by_equity_segment"][seg_name] = {
            "n": len(seg_trades),
            "atr_pct_entry_mean": round(float(np.mean(atr_vals)), 4) if len(atr_vals) > 0 else None,
            "atr_pct_entry_std": round(float(np.std(atr_vals)), 4) if len(atr_vals) > 1 else None,
            "mae_r_mean": round(float(np.mean(mae_r_vals)), 4) if len(mae_r_vals) > 0 else None,
            "mfe_r_mean": round(float(np.mean(mfe_r_vals)), 4) if len(mfe_r_vals) > 0 else None,
            "mae_per_bar_mean": round(float(np.mean(mae_bar_vals)), 4) if len(mae_bar_vals) > 0 else None,
            "mfe_per_bar_mean": round(float(np.mean(mfe_bar_vals)), 4) if len(mfe_bar_vals) > 0 else None,
            "r_multiple_mean": round(float(np.mean(r_vals)), 4) if len(r_vals) > 0 else None,
            "efficiency_mean": round(float(np.mean(efficiency_vals)), 4) if len(efficiency_vals) > 0 else None,
            "intra_trade_vol_pct_mean": round(float(np.mean(intra_vol_vals)), 4) if len(intra_vol_vals) > 0 else None,
            "intra_trade_vol_pct_std": round(float(np.std(intra_vol_vals)), 4) if len(intra_vol_vals) > 1 else None,
        }

    # By bucket (OPEN vs REGULAR)
    for bucket_name in ["OPEN", "REGULAR"]:
        bucket_trades = [t for t in trades if t["_bucket"] == bucket_name]
        if not bucket_trades:
            result["by_bucket"][bucket_name] = {"n": 0}
            continue
        atr_vals = [t.get("atr_pct_entry", 0) for t in bucket_trades if t.get("atr_pct_entry") is not None]
        r_vals = [t.get("r_multiple", 0) for t in bucket_trades]
        result["by_bucket"][bucket_name] = {
            "n": len(bucket_trades),
            "atr_pct_entry_mean": round(float(np.mean(atr_vals)), 4) if len(atr_vals) > 0 else None,
            "r_multiple_mean": round(float(np.mean(r_vals)), 4) if len(r_vals) > 0 else None,
            "total_r": round(float(np.sum(r_vals)), 4),
        }

    # ── Day-of-week volatility profile ──
    dow_r: dict[str, list[float]] = defaultdict(list)
    dow_atr: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        dow = t["_dow"]
        dow_r[dow].append(t.get("r_multiple", 0.0))
        atr = t.get("atr_pct_entry")
        if atr is not None:
            dow_atr[dow].append(atr)

    result["dow_profile"] = {}
    for dow in DOW_ORDER:
        if dow in dow_r:
            r_arr = np.array(dow_r[dow])
            atr_arr = np.array(dow_atr.get(dow, [0]))
            result["dow_profile"][dow] = {
                "n": len(r_arr),
                "total_r": round(float(r_arr.sum()), 4),
                "avg_r": round(float(r_arr.mean()), 4),
                "wr": round(float((r_arr > 0).sum() / len(r_arr) * 100), 2) if len(r_arr) > 0 else 0,
                "avg_atr_pct": round(float(atr_arr.mean()), 4) if len(atr_arr) > 0 else None,
            }

    return result


# ═══════════════════════════════════════════════════════════════════════
# Live SQLite data analysis (intraday-aware)
# ═══════════════════════════════════════════════════════════════════════

LIVE_DB_PATH = ROOT / "data" / "live" / "state.db"

# Intraday session definitions (same as config, but with open windows)
INTRADAY_OPEN_WINDOWS: dict[str, list[tuple[int, int]]] = {
    "fx_major": [(7, 8), (12, 13), (21, 22)],   # London open, NY open, Asia open
    "fx_cross": [(7, 8), (12, 13), (21, 22)],
    "indices": [(13, 14)],                         # US pre-market open
    "metals": [(8, 9)],                            # London fix open
    "crypto": [],
}

# 30-min intraday buckets
def _get_intraday_bucket(hour: int, minute: int, tier: str) -> str:
    """Classify an intraday timestamp into OPEN (first 30min of session) or REGULAR."""
    opens = INTRADAY_OPEN_WINDOWS.get(tier, [])
    for open_hour_start, open_hour_end in opens:
        if hour == open_hour_start and minute < 30:
            return "OPEN"
        if open_hour_start < hour < open_hour_end:
            return "OPEN"
        if hour == open_hour_end - 1 and minute >= 30:
            pass  # last 30min of open window is still open
        if hour == open_hour_start and minute >= 30:
            return "REGULAR"  # after first 30min
    # Not in any open window → use standard session check
    windows: dict[str, tuple[int, int]] = {
        "fx_major": (7, 17), "fx_cross": (7, 17),
        "indices": (13, 20), "metals": (8, 18), "crypto": (0, 24),
    }
    w = windows.get(tier)
    if w and w[0] <= hour < w[1]:
        if hour == w[0] and minute < 30:
            return "OPEN"
        return "REGULAR"
    return "OFF_HOURS"


def _parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse ISO timestamp with timezone offset (e.g., -04:00)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def analyze_live_data() -> dict:
    """Query live SQLite DB for intraday-aware analysis.

    Reads ``attribution`` table (trades with slippage, timestamps) and
    ``equity_history`` (per-cycle PnL).  Falls back gracefully when DB
    is empty or unreachable.
    """
    result: dict[str, Any] = {
        "available": False,
        "note": "No live data available yet.",
        "intraday_slippage": {},
        "intraday_trade_frequency": {},
        "intraday_roughness": {},
    }

    if not LIVE_DB_PATH.exists():
        return result

    try:
        import sqlite3

        conn = sqlite3.connect(str(LIVE_DB_PATH))
        conn.row_factory = sqlite3.Row

        # ── Attribution trades ──
        attr_rows = conn.execute(
            "SELECT * FROM attribution ORDER BY entry_date DESC LIMIT 500"
        ).fetchall()
        trades = [dict(r) for r in attr_rows]

        if len(trades) < 5:
            conn.close()
            result["note"] = f"Only {len(trades)} live trades — insufficient for intraday analysis."
            return result

        # Augment with parsed timestamps and session buckets
        for t in trades:
            ed = _parse_iso_timestamp(t.get("entry_date", ""))
            if ed:
                t["_entry_dt"] = ed
                t["_hour"] = ed.hour
                t["_minute"] = ed.minute
                t["_dow"] = ed.strftime("%A")
                tier = get_asset_tier(t.get("asset", ""))
                t["_bucket"] = _get_intraday_bucket(ed.hour, ed.minute, tier)
            # Compute slippage
            t["_slippage_bps"] = compute_slippage_bps({
                "exit_reason": t.get("exit_reason") or t.get("exit_exit_reason", ""),
                "exit_price": t.get("exit_price"),
                "tp_price": t.get("entry_price") + (t.get("theoretical_r", 0) * t.get("entry_price", 0) * 0.01)
                            if t.get("exit_reason") == "tp" else None,
                "sl_price": None,
                "side": t.get("side", "BUY"),
            })
            t["_r_multiple"] = t.get("exit_realized_r") or t.get("realized_r", 0)
            t["_archetype"] = t.get("exit_archetype") or t.get("pred_archetype_at_entry", "unknown")

        # Compute per-asset tier for proper open window mapping
        for t in trades:
            t["_tier"] = get_asset_tier(t.get("asset", ""))

        # ── Intraday slippage by bucket (first 30min vs rest) ──
        from scipy.stats import ttest_ind

        buckets: dict[str, list[float]] = {"OPEN": [], "REGULAR": [], "OFF_HOURS": []}
        for t in trades:
            s = t.get("_slippage_bps")
            b = t.get("_bucket", "OFF_HOURS")
            if s is not None and b != "OFF_HOURS":
                buckets.setdefault(b, []).append(s)

        for bucket, vals in buckets.items():
            arr = np.array(vals) if vals else np.array([])
            result["intraday_slippage"][bucket] = {
                "n": len(vals),
                "mean_bps": round(float(arr.mean()), 2) if len(vals) >= 3 else None,
                "std_bps": round(float(arr.std()), 2) if len(vals) >= 3 else None,
            }

        if len(buckets.get("OPEN", [])) >= 3 and len(buckets.get("REGULAR", [])) >= 3:
            t_stat, p_val = ttest_ind(buckets["OPEN"], buckets["REGULAR"], equal_var=False)
            result["intraday_slippage"]["welch_ttest"] = {
                "t_statistic": round(float(t_stat), 4),
                "p_value": round(float(p_val), 6),
                "n_open": len(buckets["OPEN"]),
                "n_regular": len(buckets["REGULAR"]),
            }

        # ── Intraday trade frequency ──
        open_trades = [t for t in trades if t.get("_bucket") == "OPEN"]
        regular_trades = [t for t in trades if t.get("_bucket") == "REGULAR"]
        result["intraday_trade_frequency"] = {
            "n_live_trades": len(trades),
            "open_window_trades": len(open_trades),
            "regular_window_trades": len(regular_trades),
            "open_pct": round(len(open_trades) / max(len(trades), 1) * 100, 2),
        }

        # ── Intraday roughness (no day-boundary reset — use real chronology) ──
        sorted_trades = sorted(
            [t for t in trades if t.get("_entry_dt")],
            key=lambda t: t["_entry_dt"],
        )
        r_vals = np.array([t.get("_r_multiple", 0.0) for t in sorted_trades])
        if len(r_vals) > 5:
            roughness = []
            for i in range(len(r_vals)):
                w = r_vals[max(0, i - 19): i + 1]
                r_ = float(np.std(np.diff(w))) if len(w) > 1 else 0.0
                roughness.append(r_)
            result["intraday_roughness"] = {
                "n": len(roughness),
                "mean": round(float(np.mean(roughness)), 4),
                "p50": round(float(np.median(roughness)), 4),
                "p90": round(float(np.percentile(roughness, 90)), 4),
            }

        conn.close()
        result["available"] = True
        result["note"] = f"Analyzed {len(trades)} live trades with intraday timestamps."
        return result

    except ImportError:
        result["note"] = "sqlite3 not available."
        return result
    except Exception as exc:
        result["note"] = f"Error querying live DB: {exc}"
        logger.warning("Live data analysis failed: %s", exc)
        return result


def analyze_monday_open_gap(trades: list[dict]) -> dict:
    """Analyze Monday entries using the 'prices' field to estimate weekend gap.

    For Monday-entered trades: the first price in the 'prices' series vs the
    previous trading day's close (Friday) to measure gap magnitude.
    Since all prices are daily closes, this captures the weekend gap effect.

    Note: prices field in the JSON is stored as a string repr of the pd.Series.
    We parse it carefully.
    """
    result: dict[str, Any] = {"monday_gap_analysis": {}, "by_asset_gap": {}}

    monday_trades = [t for t in trades if t["_bucket"] == "OPEN"]

    gap_effects = []
    for t in monday_trades:
        prices_str = t.get("prices", "")
        if not prices_str or not isinstance(prices_str, str):
            continue
        try:
            # Parse pd.Series string representation
            # Format: "0     1.234\n1     1.235\ndtype: float64"
            lines = prices_str.strip().split("\n")
            price_vals = []
            for line in lines:
                line = line.strip()
                if "dtype:" in line:
                    break
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        price_vals.append(float(parts[-1]))
                    except ValueError:
                        pass
            if len(price_vals) >= 1:
                first_price = price_vals[0]
                entry_price = t.get("entry_price", 0)
                if entry_price > 0:
                    gap_pct = (first_price / entry_price - 1) * 100
                    gap_effects.append({
                        "asset": t["_asset"],
                        "gap_pct": round(gap_pct, 4),
                        "r_multiple": t.get("r_multiple", 0),
                        "exit_reason": t.get("exit_reason", ""),
                        "date": t["_date"],
                    })
        except Exception:
            continue

    if not gap_effects:
        return result

    gap_pcts = np.array([g["gap_pct"] for g in gap_effects])
    result["monday_gap_analysis"] = {
        "n": len(gap_effects),
        "mean_gap_pct": round(float(gap_pcts.mean()), 4),
        "std_gap_pct": round(float(gap_pcts.std()), 4),
        "p5_gap": round(float(np.percentile(gap_pcts, 5)), 4),
        "p50_gap": round(float(np.percentile(gap_pcts, 50)), 4),
        "p95_gap": round(float(np.percentile(gap_pcts, 95)), 4),
        "positive_gap_pct": round(float((gap_pcts > 0).sum() / len(gap_pcts) * 100), 2),
    }

    # Correlation: gap_pct vs r_multiple
    r_vals = np.array([g["r_multiple"] for g in gap_effects])
    if len(gap_pcts) > 1:
        corr = float(np.corrcoef(gap_pcts, r_vals)[0, 1])
        result["monday_gap_analysis"]["gap_r_correlation"] = round(corr, 4)

    # Gap effect on exit reason
    gap_by_reason: dict[str, list[float]] = defaultdict(list)
    for g in gap_effects:
        gap_by_reason[g["exit_reason"]].append(g["gap_pct"])
    result["monday_gap_analysis"]["gap_by_exit_reason"] = {}
    for reason, gaps in gap_by_reason.items():
        arr = np.array(gaps)
        result["monday_gap_analysis"]["gap_by_exit_reason"][reason] = {
            "n": len(gaps),
            "mean_gap": round(float(arr.mean()), 4),
        }

    # Per-asset gap analysis
    asset_gaps: dict[str, list[float]] = defaultdict(list)
    for g in gap_effects:
        asset_gaps[g["asset"]].append(g["gap_pct"])
    for asset, gaps in asset_gaps.items():
        arr = np.array(gaps)
        result["by_asset_gap"][asset] = {
            "n": len(gaps),
            "mean_gap_pct": round(float(arr.mean()), 4),
            "std_gap_pct": round(float(arr.std()), 4) if len(gaps) > 1 else None,
        }

    return result


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("Market Open Comparative Performance Report")
    logger.info("=" * 60)

    trades = load_trades()
    logger.info("Trades: %d | OPEN (Monday): %d | REGULAR (Tue–Fri): %d",
                len(trades),
                sum(1 for t in trades if t["_bucket"] == "OPEN"),
                sum(1 for t in trades if t["_bucket"] == "REGULAR"))

    report: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_trades": len(trades),
            "n_assets": len(set(t["_asset"] for t in trades)),
            "date_range": {
                "start": min(t["_entry_dt"].isoformat() for t in trades),
                "end": max(t["_entry_dt"].isoformat() for t in trades),
            },
            "note": (
                "All timestamps in historical data are 00:00:00 UTC (daily-bar walk-forward). "
                "Intraday 'first 30 minutes' segmentation is not possible. "
                "OPEN = Monday entry (post-weekend gap proxy), REGULAR = Tuesday–Friday entry."
            ),
        }
    }

    # 1. Slippage Variance
    logger.info("Phase 1/5: Slippage Variance ...")
    report["slippage"] = analyze_slippage(trades)

    # 2. Trade Frequency
    logger.info("Phase 2/5: Trade Frequency ...")
    report["trade_frequency"] = analyze_trade_frequency(trades)

    # 3. Drawdown Sensitivity (Roughness Index + Archetype Clustering)
    logger.info("Phase 3/5: Drawdown Sensitivity (Roughness Index) ...")
    report["drawdown_sensitivity"] = analyze_drawdown_sensitivity(trades)

    # 4. Volatility Metrics
    logger.info("Phase 4/5: Volatility Metrics ...")
    report["volatility"] = analyze_volatility(trades, report["drawdown_sensitivity"])

    # 5. Monday Gap Analysis
    logger.info("Phase 5/5: Monday Gap Analysis ...")
    report["monday_gap"] = analyze_monday_open_gap(trades)

    # 6. Live SQLite Data (intraday-aware, available when live trades exist)
    logger.info("Phase 6/6: Live SQLite Intraday Analysis ...")
    report["live_data"] = analyze_live_data()

    # ── Write output ──
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, cls=EigenCapitalJSONEncoder, indent=2, default=str)
    logger.info("Report written to %s", OUTPUT_PATH)

    # ── Console summary ──
    print()
    print("=" * 70)
    print("MARKET OPEN COMPARATIVE PERFORMANCE REPORT — SUMMARY")
    print("=" * 70)
    print(f"  Total trades: {report['metadata']['n_trades']}")
    print(f"  Date range:   {report['metadata']['date_range']['start'][:10]} to {report['metadata']['date_range']['end'][:10]}")
    print(f"  Segmentation: Monday (OPEN) vs Tue–Fri (REGULAR)")
    print(f"  Note:         {report['metadata']['note']}")
    print()

    # Slippage summary
    s = report["slippage"]["overall"]
    print("── Slippage Variance ──")
    for bucket in ["OPEN", "REGULAR"]:
        b = s.get(bucket, {})
        mean_str = f"{b.get('mean_bps', 'N/A'):>8} bps" if b.get('mean_bps') is not None else "   N/A   "
        n_str = f"n={b.get('n', 0)}"
        suff = "" if b.get("sample_sufficient", True) else " [INSUFFICIENT SAMPLE]"
        print(f"  {bucket:8s}: {mean_str}  ({n_str}){suff}")
    if s.get("welch_ttest"):
        w = s["welch_ttest"]
        sig = "SIGNIFICANT" if w.get("significant_05") else "not significant"
        print(f"  Welch's t-test: t={w['t_statistic']:.4f}, p={w['p_value']:.6f} ({sig})")
    print()

    # Trade Frequency
    f = report["trade_frequency"]["overall"]
    print("── Trade Frequency ──")
    print(f"  Monday trades:           {f['open_trades']} ({f['open_pct_of_all']:.1f}% of total)")
    print(f"  Trades per Monday:       {f['trades_per_monday']:.2f}")
    print(f"  Avg trades Tue–Fri/day:  {f['avg_trades_per_tue_fri_day']:.2f}")
    print(f"  Ratio (Mon vs Tue–Fri):  {f['ratio_open_to_regular']:.3f}x")
    print()

    # Roughness
    r = report["drawdown_sensitivity"]
    rs = r.get("roughness_stats", {})
    print("── Roughness Index (Eq Curve Smoothness) ──")
    print(f"  Mean roughness:     {rs.get('mean', 'N/A'):>8.4f}")
    print(f"  P50 (median):       {rs.get('p50', 'N/A'):>8.4f}")
    print(f"  P90:                {rs.get('p90', 'N/A'):>8.4f}")
    print(f"  Top-quintile threshold: {r.get('top_quintile_threshold', 'N/A')}")
    print(f"  Erratic trades:     {r.get('n_erratic_trades', 0)} / {r.get('n_erratic_trades', 0) + r.get('n_smooth_trades', 0)}")

    # Roughness by bucket
    rbb = r.get("roughness_by_bucket", {})
    for bucket in ["OPEN", "REGULAR"]:
        b = rbb.get(bucket, {})
        if b.get("n", 0) > 0:
            print(f"  {bucket:8s} roughness: mean={b.get('mean_roughness', 'N/A'):>8.4f}  (n={b.get('n', 0)})")
    print()

    # Erratic profile
    ep = r.get("erratic_profile", {})
    print("── Erratic Trade Profile ──")
    if ep:
        print(f"  Total R in erratic zone: {ep.get('total_r', 0):+.2f}")
        print(f"  Archetype dist:  {ep.get('archetype_distribution', {})}")
        print(f"  Bucket dist:     {ep.get('bucket_distribution', {})}")
        if ep.get("archetype_distribution", {}):
            # Check if one archetype dominates
            total_erratic = sum(ep["archetype_distribution"].values())
            dominant = max(ep["archetype_distribution"], key=ep["archetype_distribution"].get)
            print(f"  Dominant archetype in erratic zone: '{dominant}' "
                  f"({ep['archetype_distribution'][dominant]}/{total_erratic} = "
                  f"{ep['archetype_distribution'][dominant]/max(total_erratic,1)*100:.0f}%)")
    print()

    # Volatility
    v = report["volatility"]
    v_eq = v.get("by_equity_segment", {})
    print("── Volatility by Equity Segment ──")
    for seg in ["erratic", "smooth"]:
        seg_data = v_eq.get(seg, {})
        if seg_data.get("n", 0) > 0:
            print(f"  {seg:8s}: n={seg_data['n']:4d}  "
                  f"ATR={seg_data.get('atr_pct_entry_mean', 'N/A'):>8}  "
                  f"MAE_r={seg_data.get('mae_r_mean', 'N/A'):>8}  "
                  f"MFE_r={seg_data.get('mfe_r_mean', 'N/A'):>8}  "
                  f"Eff={seg_data.get('efficiency_mean', 'N/A'):>8}  "
                  f"IntraVol={seg_data.get('intra_trade_vol_pct_mean', 'N/A'):>8}")
    print()

    # Day-of-week profile
    dow_p = v.get("dow_profile", {})
    print("── Day-of-Week Profile ──")
    print(f"  {'Day':12s} {'n':>5s} {'Total R':>10s} {'Avg R':>8s} {'WR%':>6s} {'ATR%':>8s}")
    for dow in DOW_ORDER:
        if dow in dow_p:
            d = dow_p[dow]
            print(f"  {dow:12s} {d['n']:5d} {d['total_r']:>+10.2f} {d['avg_r']:>+8.4f} "
                  f"{d['wr']:>5.1f}% {str(d.get('avg_atr_pct', 'N/A')):>8s}")

    # Monday gap
    mg = report.get("monday_gap", {}).get("monday_gap_analysis", {})
    if mg.get("n", 0) > 0:
        print()
        print("── Monday Open Gap Analysis ──")
        print(f"  Trades analyzed: {mg['n']}")
        print(f"  Mean gap:        {mg.get('mean_gap_pct', 'N/A'):>+8.4f}%")
        print(f"  P50 gap:         {mg.get('p50_gap', 'N/A'):>+8.4f}%")
        print(f"  P95 gap:         {mg.get('p95_gap', 'N/A'):>+8.4f}%")
        print(f"  Positive gaps:   {mg.get('positive_gap_pct', 'N/A')}%")
        if mg.get("gap_r_correlation") is not None:
            print(f"  Gap–R correlation: {mg['gap_r_correlation']:+.4f}")

    # Live data
    ld = report.get("live_data", {})
    if ld.get("available", False):
        print()
        print("── Live SQLite Intraday Data ──")
        print(f"  Live trades analyzed: {ld.get('intraday_trade_frequency', {}).get('n_live_trades', 0)}")
        print(f"  Intraday OPEN (first 30min) trades: {ld.get('intraday_trade_frequency', {}).get('open_window_trades', 0)}")
        if "intraday_slippage" in ld:
            for bucket in ["OPEN", "REGULAR"]:
                b = ld["intraday_slippage"].get(bucket, {})
                if b.get("mean_bps") is not None:
                    print(f"  {bucket:8s} slippage: {b['mean_bps']:>+8.2f} bps  (n={b.get('n', 0)})")
        if "intraday_roughness" in ld:
            ir = ld["intraday_roughness"]
            print(f"  Intraday roughness: mean={ir.get('mean', 'N/A')}, p50={ir.get('p50', 'N/A')}")
    else:
        print()
        print(f"── Live SQLite Data: {ld.get('note', 'Not available')}")

    print()
    print("=" * 70)
    print(f"Full report: {OUTPUT_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()
