"""Phase 14 — Regime Transition Analysis.

Evaluates performance around regime transitions:
  - Trend → Range
  - Range → Trend
  - Low → High Volatility
  - High → Low Volatility
  - Bull → Bear
  - Bear → Bull

Determines whether exits should adapt to regime transitions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase14_regime")


def _compute_atr(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    h = ohlcv["high"].astype(float)
    l = ohlcv["low"].astype(float)
    c = ohlcv["close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr / c.replace(0, np.nan)


def _classify_regime(c: float, ma50: float, atr_pct: float, atr_median: float) -> dict[str, str]:
    """Classify the current regime into trend and volatility dimensions."""
    trend = "bull" if c > ma50 else "bear" if c < ma50 else "range"
    vol = "high" if atr_pct > atr_median else "low" if atr_median > 0 else "normal"
    direction = "trending" if trend in ("bull", "bear") else "ranging"
    return {"trend": trend, "vol": vol, "direction": direction}


def run(trades_map: dict[str, list[dict]], ohlcv_map: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    logger.info("Phase 14: Regime transition analysis")
    if ohlcv_map is None:
        return {"error": "no_ohlcv"}

    # Track regime at entry and see how trades perform after regime changes
    transitions: dict[str, dict] = {}
    all_transitions: list[dict] = []

    for asset, trades in trades_map.items():
        ohlcv = ohlcv_map.get(asset)
        if ohlcv is None or ohlcv.empty:
            continue

        ohlcv = ohlcv.copy()
        if hasattr(ohlcv.index, "tz") and ohlcv.index.tz is not None:
            ohlcv.index = ohlcv.index.tz_localize(None)
        ohlcv.index = pd.DatetimeIndex(ohlcv.index).normalize()

        close = ohlcv["close"].astype(float)
        ma50 = close.rolling(50).mean()
        atr_pct = _compute_atr(ohlcv)
        atr_median = float(atr_pct.median())

        # Classify regime for each bar
        regimes: pd.DataFrame = pd.DataFrame(index=ohlcv.index)
        regimes["trend"] = "range"
        regimes["vol"] = "normal"
        regimes["direction"] = "ranging"

        valid_idx = close.notna() & ma50.notna() & atr_pct.notna()
        for i in ohlcv.index[valid_idx]:
            c = float(close.loc[i])
            m = float(ma50.loc[i])
            a = float(atr_pct.loc[i])
            r = _classify_regime(c, m, a, atr_median)
            regimes.at[i, "trend"] = r["trend"]
            regimes.at[i, "vol"] = r["vol"]
            regimes.at[i, "direction"] = r["direction"]

        # Find regime transition dates (trend bull/bear, vol high/low, direction trending/ranging)
        prev_trend = None
        prev_vol = None
        prev_direction = None
        transition_dates: list[str] = []

        for i in ohlcv.index[valid_idx]:
            trend = regimes.at[i, "trend"]        # bull, bear, range
            vol = regimes.at[i, "vol"]            # high, low, normal
            direction = regimes.at[i, "direction"] # trending, ranging

            # Detect bull↔bear trend changes (more useful than trending↔ranging)
            if prev_trend is not None and trend != prev_trend and trend != "range" and prev_trend != "range":
                transition_dates.append(i.strftime("%Y-%m-%d"))
            # Also detect vol regime changes
            if prev_vol is not None and vol != prev_vol and vol != "normal" and prev_vol != "normal":
                transition_dates.append(i.strftime("%Y-%m-%d"))
            prev_trend = trend
            prev_vol = vol
            prev_direction = direction

        # Categorize trades by proximity to transitions
        pre_transition: list[float] = []
        post_transition: list[float] = []

        for t in trades:
            entry_dt = t.get("entry_date")
            if entry_dt is None:
                continue
            try:
                if isinstance(entry_dt, pd.Timestamp):
                    dt_str = entry_dt.strftime("%Y-%m-%d")
                else:
                    dt_str = str(entry_dt)[:10]
            except (ValueError, TypeError):
                continue

            # Check if trade entered within 5 days of a transition
            delta_days = None
            for td in transition_dates:
                try:
                    from datetime import datetime, timedelta
                    td_dt = datetime.strptime(td, "%Y-%m-%d")
                    edt = datetime.strptime(dt_str[:10], "%Y-%m-%d")
                    delta = (edt - td_dt).days
                    if abs(delta) <= 5:
                        delta_days = delta
                        break
                except ValueError:
                    continue

            if delta_days is not None:
                if delta_days <= 0:  # entered before transition
                    pre_transition.append(t.get("r_multiple", 0.0))
                else:
                    post_transition.append(t.get("r_multiple", 0.0))

        if not pre_transition and not post_transition:
            continue

        def period_stats(rs):
            arr = np.array(rs) if rs else np.array([0.0])
            return {"n": len(rs), "avg_r": round(float(arr.mean()), 4), "total_r": round(float(arr.sum()), 2),
                    "wr": round((arr > 0).mean() * 100, 1)}

        transitions[asset] = {
            "n_transitions": len(transition_dates),
            "pre_transition": period_stats(pre_transition) if pre_transition else None,
            "post_transition": period_stats(post_transition) if post_transition else None,
            "n_trades_near_transitions": len(pre_transition) + len(post_transition),
        }

        all_transitions.extend(pre_transition + post_transition)

    if not transitions:
        return {"error": "no transition data"}

    # Portfolio-level
    pre_rs = [v["pre_transition"]["avg_r"] for v in transitions.values() if v.get("pre_transition")]
    post_rs = [v["post_transition"]["avg_r"] for v in transitions.values() if v.get("post_transition")]

    return {
        "per_asset": transitions,
        "portfolio": {
            "n_assets_with_transitions": len(transitions),
            "avg_pre_transition_r": round(float(np.mean(pre_rs)), 4) if pre_rs else 0,
            "avg_post_transition_r": round(float(np.mean(post_rs)), 4) if post_rs else 0,
            "pct_assets_worse_post_transition": round(
                sum(1 for v in transitions.values()
                    if v.get("pre_transition") and v.get("post_transition")
                    and v["post_transition"]["avg_r"] < v["pre_transition"]["avg_r"])
                / max(len([v for v in transitions.values() if v.get("pre_transition") and v.get("post_transition")]), 1)
                * 100, 1),
        },
    }
