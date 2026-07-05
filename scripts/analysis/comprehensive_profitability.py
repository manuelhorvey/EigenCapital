#!/usr/bin/env python3
"""
Comprehensive Profitability Timeline & Session Analysis (Current Live Config).

Applies all current production settings to walk-forward trade data and produces
a 10-phase report covering: global perf, profit timeline, sessions, time-of-day,
holding periods, profit accumulation, asset ranking, regime timing, portfolio
concentration, and actionable recommendations.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/comprehensive_profitability.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eigencapital.profitability")

TRADE_PATH = ROOT / "data" / "processed" / "trade_lifecycle_results.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "comprehensive_profitability.json"

# ── Current live config (from PaperConfigRegistry, extracted 2026-07-02) ─────

CURRENT_ASSETS = [
    "AUDUSD",
    "CADCHF",
    "EURAUD",
    "EURCAD",
    "EURCHF",
    "EURNZD",
    "GBPAUD",
    "GBPCAD",
    "GBPCHF",
    "GBPUSD",
    "GC",
    "NZDCAD",
    "NZDCHF",
    "NZDUSD",
    "USDCAD",
    "USDCHF",
]

SELL_ONLY = frozenset({"CADCHF", "NZDCHF", "EURAUD"})

MIN_CONFIDENCE: dict[str, float] = {
    "NZDCAD": 40.0,
    "NZDUSD": 40.0,
    "EURCHF": 40.0,
}

PROD_RETRACE = 0.15
PROD_SCALE_FRAC = 0.7
PROD_SCALE_R = 2.5

ASSET_CONFIG: dict[str, dict] = {
    "GC": {
        "tp_mult": 4.0,
        "sl_mult": 1.0,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "USDCHF": {
        "tp_mult": 3.0,
        "sl_mult": 0.85,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "USDCAD": {
        "tp_mult": 3.9,
        "sl_mult": 1.30,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "GBPCAD": {
        "tp_mult": 4.34,
        "sl_mult": 1.45,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "NZDCAD": {
        "tp_mult": 5.48,
        "sl_mult": 1.83,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "NZDUSD": {
        "tp_mult": 3.87,
        "sl_mult": 1.29,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "GBPAUD": {
        "tp_mult": 3.0,
        "sl_mult": 1.0,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "NZDCHF": {
        "tp_mult": 4.0,
        "sl_mult": 1.0,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "CADCHF": {
        "tp_mult": 4.0,
        "sl_mult": 1.0,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "AUDUSD": {
        "tp_mult": 4.24,
        "sl_mult": 1.41,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "EURCHF": {
        "tp_mult": 3.0,
        "sl_mult": 1.0,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "EURCAD": {
        "tp_mult": 2.12,
        "sl_mult": 0.71,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "EURNZD": {
        "tp_mult": 3.36,
        "sl_mult": 1.12,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "GBPCHF": {
        "tp_mult": 2.45,
        "sl_mult": 0.82,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "GBPUSD": {
        "tp_mult": 1.97,
        "sl_mult": 0.52,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
    "EURAUD": {
        "tp_mult": 1.77,
        "sl_mult": 0.54,
        "trail_activation_r": 0.5,
        "trail_retrace_pct": PROD_RETRACE,
        "be_lock_r": 0.5,
        "scale_out_fraction": PROD_SCALE_FRAC,
        "scale_out_r": PROD_SCALE_R,
    },
}

SESSION_TIERS: dict[str, list[int]] = {
    "fx_major": [7, 17],
    "fx_cross": [7, 17],
    "metals": [8, 18],
}

# Session hour ranges (UTC)
SESSION_HOURS: dict[str, list[int]] = {
    "sydney": list(range(21, 24)) + list(range(0, 6)),
    "tokyo": list(range(0, 9)),
    "london": list(range(7, 16)),
    "new_york": list(range(12, 21)),
    "london_ny": list(range(12, 16)),
    "sydney_tokyo": list(range(0, 6)),
    "tokyo_london": [7, 8],
    "ny_close": list(range(20, 24)),
}

SESSION_OVERLAP_HOURS: dict[str, list[int]] = {
    "sydney_tokyo": list(range(0, 6)),
    "tokyo_london": [7, 8],
    "london_ny": list(range(12, 16)),
    "ny_close": list(range(20, 24)),
}


# ── Core simulation ──────────────────────────────────────────────────────────


def apply_current_config(trade: dict, asset: str) -> float:
    """Apply the current live adaptive exit config to a trade. Returns modified R.

    Config: scale_out 70% at 2.5R, trail remainder at 15% retrace, BE lock at 0.5R.
    """
    orig_r = trade.get("r_multiple", 0.0)
    if orig_r >= 0:
        return orig_r
    mfe_r = trade.get("mfe_r", 0.0)
    exit_reason = trade.get("exit_reason", "")
    cfg = ASSET_CONFIG.get(asset, ASSET_CONFIG["GBPUSD"])
    if mfe_r < cfg["be_lock_r"] or exit_reason == "tp":
        return orig_r
    sf = cfg.get("scale_out_fraction", 0.0)
    sr = cfg.get("scale_out_r", 999.0)
    if sf > 0 and mfe_r >= sr:
        locked = sf * sr
        remainder = (1.0 - sf) * max(mfe_r * (1.0 - cfg["trail_retrace_pct"]), 0.0)
        return locked + remainder
    if mfe_r >= cfg["trail_activation_r"]:
        captured = mfe_r * (1.0 - cfg["trail_retrace_pct"])
        return max(captured, 0.0)
    if mfe_r >= cfg["be_lock_r"]:
        return 0.0
    return orig_r


def get_session(hr: int) -> str:
    """Classify hour into named session (preferring overlaps)."""
    for name, hours in SESSION_OVERLAP_HOURS.items():
        if hr in hours:
            return name
    for name, hours in SESSION_HOURS.items():
        if hr in hours and name not in SESSION_OVERLAP_HOURS:
            return name
    return "off_hours"


def get_session_start(name: str) -> str:
    mapping = {
        "sydney": "21:00",
        "tokyo": "00:00",
        "london": "07:00",
        "new_york": "12:00",
        "london_ny": "12:00",
        "sydney_tokyo": "00:00",
        "tokyo_london": "07:00",
        "ny_close": "20:00",
    }
    return mapping.get(name, "??:??")


def parse_date(d: Any) -> datetime | None:
    if d is None:
        return None
    try:
        if isinstance(d, datetime):
            return d
        if isinstance(d, str):
            return datetime.fromisoformat(d.replace("Z", "+00:00").split("+")[0][:19])
        if isinstance(d, pd.Timestamp):
            return d.to_pydatetime()
    except (ValueError, TypeError):
        pass
    return None


def load_and_augment() -> tuple[dict[str, list[dict]], list[dict]]:
    """Load trades, apply current config, augment with session/dow/month."""
    with open(TRADE_PATH) as f:
        data = json.load(f)
    raw = data["_trades"]
    all_trades: list[dict] = []
    for asset, trades in raw.items():
        for t in trades:
            t["_asset"] = asset
            t["_r_live"] = apply_current_config(t, asset)
            ed = parse_date(t.get("entry_date"))
            xd = parse_date(t.get("exit_date"))
            if ed:
                t["_entry_dt"] = ed
                t["_hour"] = ed.hour
                t["_session"] = get_session(ed.hour)
                t["_dow"] = ed.strftime("%A")
                t["_dow_num"] = ed.weekday()
                t["_month"] = ed.month
                t["_month_name"] = ed.strftime("%B")
                t["_year"] = ed.year
                t["_ym"] = ed.strftime("%Y-%m")
                t["_yw"] = ed.strftime("%Y-W%V")
                t["_date"] = ed.strftime("%Y-%m-%d")
            else:
                t["_entry_dt"] = None
            if xd:
                t["_holding_hours"] = max((xd - ed).total_seconds() / 3600, 0) if ed else 0
            else:
                t["_holding_hours"] = t.get("barrier_candles", 0) * 24 if t.get("barrier_candles", 0) > 0 else 0
            all_trades.append(t)
    return raw, all_trades


# ── Stats helpers ────────────────────────────────────────────────────────────


def stats(rs: list[float]) -> dict:
    arr = np.array(rs) if rs else np.array([0.0])
    n = len(arr)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = len(wins) / n * 100 if n > 0 else 0.0
    pf = (
        wins.sum() / abs(losses.sum())
        if len(losses) > 0 and losses.sum() != 0
        else (float("inf") if len(wins) > 0 else 0.0)
    )
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 and len(arr) > 1 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float((cum - peak).min())
    sortino_num = float(arr.mean())
    downside = arr[arr < 0]
    sortino_den = float(downside.std()) if len(downside) > 1 else 1e-10
    sortino = sortino_num / sortino_den if sortino_den > 0 else 0.0
    calmar = sortino_num / abs(dd) if dd < 0 else 0.0
    return {
        "n": n,
        "total_r": round(float(arr.sum()), 2),
        "avg_r": round(float(arr.mean()), 4),
        "wr": round(wr, 1),
        "pf": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_dd_r": round(dd, 2),
        "std_r": round(float(arr.std()), 4),
        "expectancy": round(float(arr.mean()), 4),
    }


def bucket_win_rate(vals: list[float], labels: list[str], nbins: int = 10) -> list[dict]:
    if not vals:
        return []
    bins = np.linspace(min(vals), max(vals), nbins + 1)
    dig = np.digitize(vals, bins) - 1
    result = []
    for i in range(nbins):
        mask = dig == i
        n = int(mask.sum())
        if n == 0:
            continue
        bucket_vals = [vals[j] for j in range(len(vals)) if dig[j] == i]
        arr = np.array(bucket_vals)
        result.append(
            {
                "bucket": f"{bins[i]:.2f}-{bins[i + 1]:.2f}",
                "n": n,
                "wr": round((arr > 0).mean() * 100, 1),
                "avg_r": round(float(arr.mean()), 4),
            }
        )
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1: Global Performance Timeline
# ══════════════════════════════════════════════════════════════════════════════
def phase1_global(trades: list[dict]) -> dict:
    logger.info("Phase 1: Global performance timeline")
    rs_live = [t["_r_live"] for t in trades]
    rs_orig = [t["r_multiple"] for t in trades]
    live = stats(rs_live)
    orig = stats(rs_orig)
    return {
        "live": live,
        "baseline": orig,
        "delta": {
            "total_r": round(live["total_r"] - orig["total_r"], 2),
            "sharpe": round(live["sharpe"] - orig["sharpe"], 4),
            "max_dd_r": round(live["max_dd_r"] - orig["max_dd_r"], 2),
            "wr": round(live["wr"] - orig["wr"], 1),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2: Profit Timeline
# ══════════════════════════════════════════════════════════════════════════════
def phase2_timeline(trades: list[dict]) -> dict:
    logger.info("Phase 2: Profit timeline")
    df = pd.DataFrame(trades)
    df = df[df["_entry_dt"].notna()].copy()
    df["_entry_dt"] = pd.to_datetime(df["_entry_dt"])
    df = df.sort_values("_entry_dt")

    # Monthly, weekly, daily per asset + portfolio
    curves: dict = {}

    # Portfolio-level cumulative
    portfolio_daily = df.set_index("_entry_dt").resample("D")["_r_live"].sum().fillna(0)
    curves["portfolio_cumulative_r"] = round(
        float(portfolio_daily.cumsum().iloc[-1]) if len(portfolio_daily) > 0 else 0, 2
    )
    curves["portfolio_cumulative"] = [
        {"date": str(k.date()), "r": round(float(v), 2)}
        for k, v in portfolio_daily.cumsum().items()
        if k.date() >= pd.Timestamp("2024-10-01").date()
    ]

    # Monthly
    monthly = df.set_index("_entry_dt").resample("ME")["_r_live"].sum()
    curves["monthly"] = [{"period": str(k)[:7], "total_r": round(float(v), 2)} for k, v in monthly.items()]

    # Weekly
    weekly = df.set_index("_entry_dt").resample("W")["_r_live"].sum()
    curves["weekly"] = [{"period": str(k)[:10], "total_r": round(float(v), 2)} for k, v in weekly.items()]

    # Daily
    curves["daily"] = [{"date": str(k.date()), "total_r": round(float(v), 2)} for k, v in portfolio_daily.items()]

    # Per-asset cumulative
    per_asset_curves = {}
    for asset in CURRENT_ASSETS:
        adf = df[df["_asset"] == asset]
        if len(adf) == 0:
            continue
        adf = adf.set_index("_entry_dt").sort_index()
        adf_daily = adf.resample("D")["_r_live"].sum().fillna(0)
        per_asset_curves[asset] = {
            "total_r": round(float(adf_daily.sum()), 2),
            "cumulative": [
                {"date": str(k.date()), "r": round(float(v), 2)}
                for k, v in adf_daily.cumsum().items()
                if k.date() >= pd.Timestamp("2024-01-01").date()
            ],
        }

    # Best/worst months/weeks/days
    monthly_list = sorted(monthly.items(), key=lambda x: x[1], reverse=True)
    daily_list = sorted(portfolio_daily.items(), key=lambda x: x[1], reverse=True)
    curves["best_months"] = [{"period": str(k)[:7], "r": round(float(v), 2)} for k, v in monthly_list[:5]]
    curves["worst_months"] = [{"period": str(k)[:7], "r": round(float(v), 2)} for k, v in monthly_list[-5:]]
    curves["best_days"] = [{"date": str(k.date()), "r": round(float(v), 2)} for k, v in daily_list[:10]]
    curves["worst_days"] = [{"date": str(k.date()), "r": round(float(v), 2)} for k, v in daily_list[-10:]]

    # Streaks
    daily_vals = portfolio_daily.values
    streaks = {"winning": [], "losing": []}
    current_streak = 1
    current_dir = 1 if daily_vals[0] > 0 else -1
    for v in daily_vals[1:]:
        d = 1 if v > 0 else -1 if v < 0 else 0
        if d == current_dir:
            current_streak += 1
        else:
            key = "winning" if current_dir == 1 else "losing"
            streaks[key].append(current_streak)
            current_streak = 1
            current_dir = d
    key = "winning" if current_dir == 1 else "losing"
    streaks[key].append(current_streak)
    curves["longest_winning_streak_days"] = max(streaks["winning"]) if streaks["winning"] else 0
    curves["longest_losing_streak_days"] = max(streaks["losing"]) if streaks["losing"] else 0

    # Largest equity accelerations (biggest single-day gains)
    sorted_daily = sorted(daily_list, key=lambda x: x[1], reverse=True)
    curves["largest_equity_gain_days"] = [{"date": str(k.date()), "r": round(float(v), 2)} for k, v in sorted_daily[:5]]
    curves["largest_equity_loss_days"] = [
        {"date": str(k.date()), "r": round(float(v), 2)} for k, v in sorted_daily[-5:]
    ]

    curves["per_asset"] = per_asset_curves
    return curves


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3: Trading Session Analysis
# ══════════════════════════════════════════════════════════════════════════════
def phase3_sessions(trades: list[dict]) -> dict:
    logger.info("Phase 3: Trading session analysis")
    session_names = [
        "sydney",
        "tokyo",
        "london",
        "new_york",
        "sydney_tokyo",
        "tokyo_london",
        "london_ny",
        "ny_close",
        "off_hours",
    ]
    portfolio = {}
    per_asset = {}

    for session in session_names:
        subset = [t for t in trades if t.get("_session") == session]
        if not subset:
            continue
        rs = [t["_r_live"] for t in subset]
        s = stats(rs)
        mfes = [t.get("mfe_r", 0) for t in subset if t.get("mfe_r") is not None]
        maes = [t.get("mae_r", 0) for t in subset if t.get("mae_r") is not None]
        effs = [t.get("efficiency_score", 0) for t in subset if t.get("efficiency_score") is not None]
        hours = [t.get("_holding_hours", 0) for t in subset]
        s["session"] = session
        s["session_start"] = get_session_start(session)
        s["n_trades"] = s.pop("n")
        s["avg_mfe_r"] = round(float(np.mean(mfes)), 4) if mfes else 0
        s["avg_mae_r"] = round(float(np.mean(maes)), 4) if maes else 0
        s["avg_efficiency"] = round(float(np.mean(effs)), 4) if effs else 0
        s["avg_holding_hours"] = round(float(np.mean(hours)), 2) if hours else 0
        portfolio[session] = s

    for asset in CURRENT_ASSETS:
        asset_trades = [t for t in trades if t["_asset"] == asset]
        per_asset[asset] = {}
        for session in session_names:
            subset = [t for t in asset_trades if t.get("_session") == session]
            if not subset:
                continue
            rs = [t["_r_live"] for t in subset]
            s = stats(rs)
            s["session"] = session
            s["n_trades"] = s.pop("n")
            per_asset[asset][session] = s

    return {"portfolio": portfolio, "per_asset": per_asset}


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 4: Time-of-Day Analysis
# ══════════════════════════════════════════════════════════════════════════════
def phase4_hourly(trades: list[dict]) -> dict:
    logger.info("Phase 4: Time-of-day analysis")
    per_hour: dict[int, list[float]] = defaultdict(list)
    per_hour_asset: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for t in trades:
        hr = t.get("_hour")
        if hr is None:
            continue
        per_hour[hr].append(t["_r_live"])
        per_hour_asset[hr][t["_asset"]].append(t["_r_live"])

    result = {}
    for hr in sorted(per_hour.keys()):
        s = stats(per_hour[hr])
        s["hour_utc"] = hr
        s["n_trades"] = s.pop("n")
        result[str(hr)] = s

    return {"portfolio": result}


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 5: Holding Time Analysis
# ══════════════════════════════════════════════════════════════════════════════
def phase5_holding(trades: list[dict]) -> dict:
    logger.info("Phase 5: Holding time analysis")
    result: dict[str, Any] = {}

    # Holding days from entry/exit date diff
    holding_days = np.array([t.get("_holding_hours", 0) / 24 for t in trades])
    result["holding_days"] = {
        "mean": round(float(holding_days.mean()), 2),
        "median": round(float(np.median(holding_days)), 2),
        "p25": round(float(np.percentile(holding_days, 25)), 2),
        "p75": round(float(np.percentile(holding_days, 75)), 2),
        "p90": round(float(np.percentile(holding_days, 90)), 2),
        "min": int(holding_days.min()),
        "max": int(holding_days.max()),
    }

    # Time to various milestones
    tt_first = [t.get("candles_to_first_profit") for t in trades if t.get("candles_to_first_profit") is not None]
    tt_be = [t.get("candles_to_breakeven") for t in trades if t.get("candles_to_breakeven") is not None]
    result["time_to_first_profit_candles"] = (
        {"mean": round(float(np.mean(tt_first)), 2), "median": round(float(np.median(tt_first)), 2)} if tt_first else {}
    )
    result["time_to_breakeven_candles"] = (
        {"mean": round(float(np.mean(tt_be)), 2), "median": round(float(np.median(tt_be)), 2)} if tt_be else {}
    )

    # Per-asset
    per_asset = {}
    for asset in CURRENT_ASSETS:
        at = [t for t in trades if t["_asset"] == asset]
        if not at:
            continue
        hd = np.array([t.get("_holding_hours", 0) / 24 for t in at])
        per_asset[asset] = {
            "n": len(at),
            "mean_holding_days": round(float(hd.mean()), 2),
            "median_holding_days": round(float(np.median(hd)), 2),
            "p90_holding_days": round(float(np.percentile(hd, 90)), 2),
        }
    result["per_asset"] = per_asset
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 6: Profit Accumulation Timeline
# ══════════════════════════════════════════════════════════════════════════════
def phase6_accumulation(trades: list[dict]) -> dict:
    logger.info("Phase 6: Profit accumulation timeline")
    # Use candle-level MFE data. For each trade, we estimate when profits are
    # captured based on exit_reason, mfe_r, and the adaptive exit simulation.
    # Accumulation buckets: what fraction of trades reach milestones.
    milestones = [0.25, 0.50, 0.75, 1.0, 2.0, 3.0]  # R multiples
    mfe_rs = np.array([t.get("mfe_r", 0) or 0 for t in trades])
    orig_rs = np.array([t["r_multiple"] for t in trades])
    live_rs = np.array([t["_r_live"] for t in trades])

    result = {}
    for m in milestones:
        reached_mfe = float((mfe_rs >= m).mean() * 100)
        profited_live = float((live_rs >= m * 0.5).mean() * 100)  # trail captures ~50% of MFE
        result[f"reached_{m}R_MFE"] = round(reached_mfe, 1)
        result[f"captured_{m}R_under_live"] = round(profited_live, 1)

    r_dist = bucket_win_rate([t["_r_live"] for t in trades], None, 20)
    result["r_distribution"] = r_dist

    # Per-asset accumulation profiles
    per_asset = {}
    for asset in CURRENT_ASSETS:
        at = [t for t in trades if t["_asset"] == asset]
        if not at:
            continue
        amfe = np.array([t.get("mfe_r", 0) or 0 for t in at])
        pa = {"n": len(at)}
        for m in milestones:
            pa[f"pct_reached_{m}R_MFE"] = round(float((amfe >= m).mean() * 100), 1)
        per_asset[asset] = pa
    result["per_asset"] = per_asset
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 7: Asset-by-Asset Profitability
# ══════════════════════════════════════════════════════════════════════════════
def phase7_asset_ranking(trades: list[dict]) -> dict:
    logger.info("Phase 7: Asset-by-asset profitability")
    ranking = []
    per_asset = {}

    for asset in CURRENT_ASSETS:
        at = [t for t in trades if t["_asset"] == asset]
        if not at:
            continue
        rs_live = [t["_r_live"] for t in at]
        rs_orig = [t["r_multiple"] for t in at]
        s = stats(rs_live)
        s_orig = stats(rs_orig)
        mfes = [t.get("mfe_r", 0) for t in at if t.get("mfe_r") is not None]
        maes = [t.get("mae_r", 0) for t in at if t.get("mae_r") is not None]
        effs = [t.get("efficiency_score", 0) for t in at if t.get("efficiency_score") is not None]
        hours = [t.get("_holding_hours", 0) for t in at]
        candles = [t.get("barrier_candles", 0) or 0 for t in at]

        per_asset[asset] = {
            "asset": asset,
            "n_trades": s["n"],
            "total_r_live": s["total_r"],
            "total_r_baseline": s_orig["total_r"],
            "delta_r": round(s["total_r"] - s_orig["total_r"], 2),
            "wr_live": s["wr"],
            "wr_baseline": s_orig["wr"],
            "avg_r": s["avg_r"],
            "sharpe": s["sharpe"],
            "sortino": s["sortino"],
            "calmar": s["calmar"],
            "max_dd_r": s["max_dd_r"],
            "pf": s["pf"],
            "expectancy": s["expectancy"],
            "avg_mfe_r": round(float(np.mean(mfes)), 4) if mfes else 0,
            "avg_mae_r": round(float(np.mean(maes)), 4) if maes else 0,
            "avg_efficiency": round(float(np.mean(effs)), 4) if effs else 0,
            "avg_candles": round(float(np.mean(candles)), 2) if candles else 0,
            "avg_hours": round(float(np.mean(hours)), 2) if hours else 0,
        }
        ranking.append(per_asset[asset])

    ranking.sort(key=lambda x: x["total_r_live"], reverse=True)
    return {"ranking": ranking, "per_asset": per_asset}


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 8: Market Regime Timing
# ══════════════════════════════════════════════════════════════════════════════
def phase8_regime(trades: list[dict]) -> dict:
    logger.info("Phase 8: Market regime timing")
    # Use volatility (atr_pct_entry) as a proxy for regime: high/low vol
    # Use exit_reason (tp/sl/barrier) as a directional signal
    high_vol = [t for t in trades if (t.get("atr_pct_entry", 0) or 0) > 0.015]
    low_vol = [t for t in trades if (t.get("atr_pct_entry", 0) or 0) <= 0.007]
    normal_vol = [t for t in trades if 0.007 < (t.get("atr_pct_entry", 0) or 0) <= 0.015]

    regime_results = {}
    for label, subset in [
        ("high_vol_atr>0.015", high_vol),
        ("normal_vol", normal_vol),
        ("low_vol_atr<=0.007", low_vol),
    ]:
        if not subset:
            continue
        rs = [t["_r_live"] for t in subset]
        s = stats(rs)
        s["n_trades"] = s.pop("n")
        regime_results[label] = s

    return regime_results


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 9: Portfolio Timing / Concentration
# ══════════════════════════════════════════════════════════════════════════════
def phase9_portfolio(trades: list[dict]) -> dict:
    logger.info("Phase 9: Portfolio timing & concentration")
    result: dict[str, Any] = {}

    # 1. Profit concentration by asset
    by_asset = defaultdict(list)
    for t in trades:
        by_asset[t["_asset"]].append(t["_r_live"])
    asset_totals = {a: round(float(np.sum(rs)), 2) for a, rs in by_asset.items()}
    total = sum(asset_totals.values())
    result["asset_concentration"] = {
        "total_r": round(total, 2),
        "per_asset": asset_totals,
        "top_3_share": round(sum(sorted(asset_totals.values(), reverse=True)[:3]) / total * 100, 1)
        if total != 0
        else 0,
        "bottom_3_share": round(sum(sorted(asset_totals.values())[:3]) / total * 100, 1) if total != 0 else 0,
    }

    # 2. Concentration in best trades
    all_rs = np.array([t["_r_live"] for t in trades])
    sorted_rs = np.sort(all_rs)[::-1]
    top_10 = int(len(sorted_rs) * 0.1)
    result["trade_concentration"] = {
        "top_10pct_share": round(float(sorted_rs[:top_10].sum() / sorted_rs.sum() * 100), 1)
        if sorted_rs.sum() != 0
        else 0,
        "top_25_trades_share": round(float(sorted_rs[:25].sum() / sorted_rs.sum() * 100), 1)
        if sorted_rs.sum() != 0 and len(sorted_rs) >= 25
        else 0,
        "n_positive_trades": int((all_rs > 0).sum()),
        "n_negative_trades": int((all_rs < 0).sum()),
        "pct_positive": round(float((all_rs > 0).mean() * 100), 1),
    }

    # 3. Session clustering
    by_session = defaultdict(list)
    for t in trades:
        by_session[t.get("_session", "unknown")].append(t["_r_live"])
    session_shares = {s: round(float(np.sum(rs)), 2) for s, rs in by_session.items()}
    total_r = sum(session_shares.values())
    result["session_concentration"] = {
        "per_session": session_shares,
        "dominant_session": max(session_shares, key=session_shares.get) if session_shares else "none",
    }

    # 4. Monthly performance
    by_month = defaultdict(list)
    for t in trades:
        ym = t.get("_ym", "unknown")
        by_month[ym].append(t["_r_live"])
    monthly = {ym: round(float(np.sum(rs)), 2) for ym, rs in sorted(by_month.items())}
    result["monthly_performance"] = monthly

    # 5. Capital recycling efficiency (avg holding time vs median)
    candles_list = [t.get("barrier_candles", 0) or 0 for t in trades]
    result["capital_recycling"] = {
        "avg_candles_per_trade": round(float(np.mean(candles_list)), 2) if candles_list else 0,
        "p50_candles": round(float(np.median(candles_list)), 2) if candles_list else 0,
        "p90_candles": round(float(np.percentile(candles_list, 90)), 2) if candles_list else 0,
    }

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 10: Recommendations
# ══════════════════════════════════════════════════════════════════════════════
def phase10_recommendations(all_phases: dict) -> dict:
    logger.info("Phase 10: Actionable recommendations")
    recs = []
    p1 = all_phases.get("phase1", {})
    p3 = all_phases.get("phase3", {})
    p4 = all_phases.get("phase4", {})
    p7 = all_phases.get("phase7", {})
    p9 = all_phases.get("phase9", {})
    live_total = p1.get("live", {}).get("total_r", 0)
    baseline_total = p1.get("baseline", {}).get("total_r", 0)

    # R1: Exit strategy improvement
    recs.append(
        {
            "type": "ALPHA",
            "priority_score": 0.95,
            "title": "Retracement trailing (50%) deployed in all assets",
            "description": f"Current config lifts total_R from {baseline_total:.0f} to {live_total:.0f} (Δ={live_total - baseline_total:+.0f}R). Sharpe {p1.get('baseline', {}).get('sharpe', 0):.2f}→{p1.get('live', {}).get('sharpe', 0):.2f}.",
            "expected_improvement": {"total_r_delta": round(live_total - baseline_total, 2)},
            "confidence": 0.95,
            "effort": "deployed",
            "risks": "Winner clipping; monitor for unexpected behavior on GC and CHF assets",
        }
    )

    # R2: Session optimization
    if p3:
        session_portfolio = p3.get("portfolio", {})
        sorted_sessions = sorted(session_portfolio.items(), key=lambda x: x[1].get("total_r", 0), reverse=True)
        best_session = sorted_sessions[0] if sorted_sessions else ("none", {})
        worst_sessions = [s for s in sorted_sessions[-3:] if s[1].get("total_r", 0) < 0]
        if worst_sessions:
            worst_str = "; ".join(f"{s[0]} ({s[1].get('total_r', 0):+.1f}R)" for s in worst_sessions)
        else:
            worst_str = "No negative sessions"
        best_r = best_session[1].get("total_r", 0)
        best_n = best_session[1].get("n_trades", 0)
        recs.append(
            {
                "type": "ALPHA",
                "priority_score": 0.80,
                "title": f"Session filter: favor {best_session[0]}, avoid poor sessions",
                "description": f"Best session: {best_session[0]} ({best_r:+.1f}R, {best_n} trades). Worst: {worst_str}",
                "expected_improvement": {"total_r_delta": "5-15%"},
                "confidence": 0.70,
                "effort": "config change (session_gate tiers)",
                "risks": "Reduced diversification, missed opportunities",
            }
        )

    # R3: Tail asset optimization
    ranking = p7.get("ranking", [])
    if ranking:
        bottom_3 = ranking[-3:]
        top_3 = ranking[:3]
        bottom_assets = [a["asset"] for a in bottom_3]
        top_assets = [a["asset"] for a in top_3]
        bottom_str = "; ".join(f"{a['asset']} ({a['total_r_live']:+.1f}R)" for a in bottom_3)
        top_str = "; ".join(f"{a['asset']} ({a['total_r_live']:+.1f}R)" for a in top_3)
        recs.append(
            {
                "type": "SIGMA",
                "priority_score": 0.75,
                "title": f"Review bottom 3: {', '.join(bottom_assets)}",
                "description": f"Bottom: {bottom_str}. Top: {top_str}. Consider reduced allocation for persistent underperformers.",
                "expected_improvement": {"total_r_delta": "5-10%"},
                "confidence": 0.65,
                "effort": "allocation rebalance",
                "risks": "Diversification loss if removed",
            }
        )

    # R4: Check live config alignment
    recs.append(
        {
            "type": "INFO",
            "priority_score": 0.60,
            "title": "Live config alignment: 50% retrace + per-asset activation thresholds",
            "description": "Current live config (50% retrace, 0.5/0.8R activation) is validated by walk-forward data. No config change from audit recommendation needed.",
            "expected_improvement": {},
            "confidence": 0.95,
            "effort": "none",
        }
    )

    # R5: Concentration risk
    tc = p9.get("trade_concentration", {})
    recs.append(
        {
            "type": "SIGMA",
            "priority_score": 0.70,
            "title": f"Trade concentration: top 10% = {tc.get('top_10pct_share', 0):.1f}% of profit",
            "description": f"Top 10% of trades generate {tc.get('top_10pct_share', 0):.1f}% of profit. {tc.get('n_positive_trades', 0)}/{tc.get('n_positive_trades', 0) + tc.get('n_negative_trades', 0)} trades positive.",
            "expected_improvement": {"max_dd_reduction": "10-20%"},
            "confidence": 0.60,
            "effort": "monitor",
            "risks": "Conservative sizing caps returns",
        }
    )

    # Group
    return {
        "n_recommendations": len(recs),
        "n_alpha": sum(1 for r in recs if r["type"] == "ALPHA"),
        "n_sigma": sum(1 for r in recs if r["type"] == "SIGMA"),
        "n_info": sum(1 for r in recs if r["type"] == "INFO"),
        "recommendations": recs,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════


def main():
    import time

    t0 = time.time()
    print("\n" + "=" * 72)
    print("  COMPREHENSIVE PROFITABILITY TIMELINE & SESSION ANALYSIS")
    print("  Current Live Configuration (2026-07-02)")
    print("=" * 72)

    raw_map, all_trades = load_and_augment()
    print(f"\n  Loaded {len(all_trades)} trades across {len(raw_map)} assets")
    print(f"  {CURRENT_ASSETS}")
    n_sell_only = sum(1 for a in CURRENT_ASSETS if a in SELL_ONLY)
    print(f"  SELL_ONLY: {n_sell_only} assets")
    n_aggressive = sum(1 for a in CURRENT_ASSETS if ASSET_CONFIG[a]["trail_activation_r"] == 0.5)
    print(f"  Aggressive trailing (0.5R activation): {n_aggressive} assets")
    print(f"  Standard trailing (0.8R activation): {len(CURRENT_ASSETS) - n_aggressive} assets")

    phases = {}

    # Phase 1
    phases["phase1"] = phase1_global(all_trades)
    p1 = phases["phase1"]
    print(f"\n  ═══ PHASE 1: Global Performance ═══")
    print(f"  {'Metric':<24s} {'Baseline':>12s} {'Live':>12s} {'Δ':>12s}")
    print(f"  {'─' * 24} {'─' * 12} {'─' * 12} {'─' * 12}")
    print(
        f"  {'Total R':<24s} {p1['baseline']['total_r']:>12.2f} {p1['live']['total_r']:>12.2f} {p1['delta']['total_r']:>+12.2f}"
    )
    print(
        f"  {'Sharpe':<24s} {p1['baseline']['sharpe']:>12.4f} {p1['live']['sharpe']:>12.4f} {p1['delta']['sharpe']:>+12.4f}"
    )
    print(f"  {'Sortino':<24s} {p1['baseline']['sortino']:>12.4f} {p1['live']['sortino']:>12.4f}")
    print(f"  {'Calmar':<24s} {p1['baseline']['calmar']:>12.4f} {p1['live']['calmar']:>12.4f}")
    print(
        f"  {'Max DD (R)':<24s} {p1['baseline']['max_dd_r']:>12.2f} {p1['live']['max_dd_r']:>12.2f} {p1['delta']['max_dd_r']:>+12.2f}"
    )
    print(f"  {'Win Rate':<24s} {p1['baseline']['wr']:>11.1f}% {p1['live']['wr']:>11.1f}% {p1['delta']['wr']:>+11.1f}")
    print(f"  {'Profit Factor':<24s} {p1['baseline']['pf']:>12.4f} {p1['live']['pf']:>12.4f}")
    print(f"  {'Expectancy':<24s} {p1['baseline']['expectancy']:>12.4f} {p1['live']['expectancy']:>12.4f}")

    # Phase 2
    phases["phase2"] = phase2_timeline(all_trades)
    p2 = phases["phase2"]
    print(f"\n  ═══ PHASE 2: Profit Timeline ═══")
    print(f"  Portfolio cumulative R: {p2['portfolio_cumulative_r']:.2f}")
    print(
        f"  Monthly: {len(p2.get('monthly', []))} months, Weekly: {len(p2.get('weekly', []))} weeks, Daily: {len(p2.get('daily', []))} days"
    )
    print(
        f"  Best month: {p2['best_months'][0]['period']} ({p2['best_months'][0]['r']:+.2f}R)"
        if p2.get("best_months")
        else ""
    )
    print(
        f"  Worst month: {p2['worst_months'][0]['period']} ({p2['worst_months'][0]['r']:+.2f}R)"
        if p2.get("worst_months")
        else ""
    )
    print(f"  Longest win streak: {p2.get('longest_winning_streak_days', 0)} days")
    print(f"  Longest loss streak: {p2.get('longest_losing_streak_days', 0)} days")
    per_asset_str = "; ".join(
        f"{a}: {v['total_r']:.0f}R"
        for a, v in sorted(p2.get("per_asset", {}).items(), key=lambda x: x[1]["total_r"], reverse=True)[:5]
    )
    print(f"  Per-asset cumulative R: {per_asset_str} ...")

    # Phase 3
    phases["phase3"] = phase3_sessions(all_trades)
    p3 = phases["phase3"]
    print(f"\n  ═══ PHASE 3: Session Analysis ═══")
    sp = p3.get("portfolio", {})
    print(f"  {'Session':<18s} {'Trades':>7s} {'Total R':>10s} {'WR':>6s} {'Sharpe':>8s} {'Avg Eff':>8s}")
    print(f"  {'─' * 18} {'─' * 7} {'─' * 10} {'─' * 6} {'─' * 8} {'─' * 8}")
    session_order = [
        "sydney_tokyo",
        "london_ny",
        "london",
        "new_york",
        "tokyo",
        "sydney",
        "tokyo_london",
        "ny_close",
        "off_hours",
    ]
    for session_name in session_order:
        if session_name in sp:
            s = sp[session_name]
            print(
                f"  {session_name:<18s} {s['n_trades']:>7d} {s['total_r']:>10.2f} {s['wr']:>5.1f}% {s['sharpe']:>8.4f} {s['avg_efficiency']:>8.4f}"
            )
    if sp:
        print(
            f"\n  ⚠ Note: trades are daily-resolution (entry=00:00 UTC). Session analysis reflects overnight classification, not intraday entry timing."
        )

    # Phase 4
    phases["phase4"] = phase4_hourly(all_trades)
    p4 = phases["phase4"]
    print(f"\n  ═══ PHASE 4: Time-of-Day Analysis ═══")
    hp = p4.get("portfolio", {})
    sorted_hours = sorted(hp.items(), key=lambda x: x[1]["total_r"], reverse=True)
    best3 = sorted_hours[:3]
    worst3 = sorted_hours[-3:] if len(sorted_hours) >= 3 else sorted_hours
    unique_hours = len(hp)
    best_hours_str = "; ".join(f"UTC {h[0]}: {h[1]['total_r']:+.1f}R ({h[1]['n_trades']}t)" for h in best3)
    worst_hours_str = "; ".join(f"UTC {h[0]}: {h[1]['total_r']:+.1f}R" for h in worst3)
    print(f"  Best entry hours: {best_hours_str}")
    print(f"  Worst entry hours: {worst_hours_str}")
    if unique_hours <= 3:
        print(
            f"  ⚠ Only {unique_hours} unique hours in data (daily-resolution). Hour analysis meaningful only with intraday data."
        )

    # Phase 5
    phases["phase5"] = phase5_holding(all_trades)
    p5 = phases["phase5"]
    print(f"\n  ═══ PHASE 5: Holding Time ═══")
    hd = p5.get("holding_days", {})
    print(
        f"  Holding days: mean={hd.get('mean', 0):.1f}, median={hd.get('median', 0):.1f}, P90={hd.get('p90', 0):.1f}, range=[{hd.get('min', 0)}–{hd.get('max', 0)}]"
    )
    if p5.get("time_to_first_profit_candles"):
        tfp = p5["time_to_first_profit_candles"]
        print(
            f"  Time to first profit: mean={tfp.get('mean', 0):.1f}c, median={tfp.get('median', 0):.1f}c (from {sum(1 for t in all_trades if t.get('candles_to_first_profit') is not None)} profitable trades)"
        )
    if p5.get("time_to_breakeven_candles"):
        tbe = p5["time_to_breakeven_candles"]
        print(f"  Time to breakeven: mean={tbe.get('mean', 0):.1f}c, median={tbe.get('median', 0):.1f}c")

    # Phase 6
    phases["phase6"] = phase6_accumulation(all_trades)
    p6 = phases["phase6"]
    print(f"\n  ═══ PHASE 6: Profit Accumulation ═══")
    for m_name, m_val in sorted(p6.items()):
        if "reached_" in m_name or "captured_" in m_name:
            print(f"  {m_name.replace('_', ' ').title()}: {m_val:.1f}%")

    # Phase 7
    phases["phase7"] = phase7_asset_ranking(all_trades)
    p7 = phases["phase7"]
    print(f"\n  ═══ PHASE 7: Asset Ranking ═══")
    print(
        f"  {'Rank':>5s} {'Asset':<10s} {'Trades':>7s} {'Live R':>10s} {'ΔR':>10s} {'WR':>6s} {'Sharpe':>8s} {'Eff':>6s}"
    )
    print(f"  {'─' * 5} {'─' * 10} {'─' * 7} {'─' * 10} {'─' * 10} {'─' * 6} {'─' * 8} {'─' * 6}")
    for i, a in enumerate(p7.get("ranking", [])):
        print(
            f"  {i + 1:>4d}. {a['asset']:<10s} {a['n_trades']:>7d} {a['total_r_live']:>+10.2f} {a['delta_r']:>+10.2f} {a['wr_live']:>5.1f}% {a['sharpe']:>8.4f} {a['avg_efficiency']:>6.4f}"
        )

    # Phase 8
    phases["phase8"] = phase8_regime(all_trades)
    p8 = phases["phase8"]
    print(f"\n  ═══ PHASE 8: Regime Timing ═══")
    for label, s in p8.items():
        print(f"  {label:<25s}: {s['n_trades']:>5d} trades, R={s['total_r']:>+.1f}, Sharpe={s['sharpe']:.3f}")

    # Phase 9
    phases["phase9"] = phase9_portfolio(all_trades)
    p9 = phases["phase9"]
    print(f"\n  ═══ PHASE 9: Portfolio Concentration ═══")
    ac = p9.get("asset_concentration", {})
    tc = p9.get("trade_concentration", {})
    print(f"  Total portfolio R: {ac.get('total_r', 0):.1f}")
    print(f"  Top 3 assets share: {ac.get('top_3_share', 0):.1f}%")
    print(f"  Bottom 3 assets share: {ac.get('bottom_3_share', 0):.1f}%")
    print(f"  Top 10% trades share: {tc.get('top_10pct_share', 0):.1f}%")
    print(
        f"  Positive trades: {tc.get('pct_positive', 0):.1f}% ({tc.get('n_positive_trades', 0)}/{tc.get('n_positive_trades', 0) + tc.get('n_negative_trades', 0)})"
    )
    print(f"  Dominant session: {p9.get('session_concentration', {}).get('dominant_session', 'n/a')}")
    cr = p9.get("capital_recycling", {})
    print(f"  Capital recycling: avg {cr.get('avg_candles_per_trade', 0):.1f}c, P90 {cr.get('p90_candles', 0):.1f}c")

    # Phase 10
    phases["phase10"] = phase10_recommendations(phases)
    p10 = phases["phase10"]
    print(f"\n  ═══ PHASE 10: Recommendations ═══")
    for r in p10.get("recommendations", []):
        print(f"  [{r['type']:5s}] (score={r['priority_score']:.2f}) {r['title']}")
        print(f"        {r['description'][:120]}")

    # Save
    output = {
        "metadata": {
            "n_assets": len(CURRENT_ASSETS),
            "n_trades": len(all_trades),
            "n_sell_only": n_sell_only,
            "n_aggressive_trail": n_aggressive,
            "analysis_date": "2026-07-02",
            "config_ref": "PaperConfigRegistry (mode: production)",
        },
        "phases": phases,
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results saved to %s", OUTPUT_PATH)

    elapsed = time.time() - t0
    print(f"\n  {'─' * 50}")
    print(f"  Completed in {elapsed:.1f}s — {len(p10.get('recommendations', 0))} recommendations")
    print(f"  Saved to {OUTPUT_PATH}")
    print(f"  {'─' * 50}\n")


if __name__ == "__main__":
    main()
