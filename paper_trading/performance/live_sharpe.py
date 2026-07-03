"""Live Sharpe ratio tracker from equity history.

Reads the engine's equity_history (SQLite) and computes rolling
Sharpe ratios from both cycle-level and daily-aggregated returns.

Output is consumed by engine_state_service.py for state.json and by
the dashboard API.

Methodology
-----------
- Cycle-level Sharpe uses all raw 30s-cycle returns with Lo (2002)
  autocorrelation adjustment.
- Daily Sharpe aggregates cycle returns into daily total returns.
- Both are presented as 7-day, 30-day, and all-time windows where
  sufficient data exists.
- Slippage is estimated as the bid-ask spread contribution
  (from current market data) plus the RMS gap between signal price
  and current price from trace.jsonl (historical).

References
----------
Lo, A. W. (2002). The statistics of Sharpe ratios.
Financial Analysts Journal, 58(4), 36-52.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from eigencapital.domain.value_objects.statistical_metrics import probabilistic_sharpe_ratio
from paper_trading.state_store import StateStore

logger = logging.getLogger("eigencapital.live_sharpe")

SECONDS_PER_CYCLE = 30
CYCLES_PER_DAY = int(24 * 3600 / SECONDS_PER_CYCLE)  # 2880

MIN_CYCLES_FOR_SHARPE = 100
MIN_DAYS_FOR_SHARPE = 5
MIN_CYCLES_FOR_ROLLING = CYCLES_PER_DAY  # 1 day minimum


class LiveSharpeTracker:
    """Computes live Sharpe ratios from the equity history database.

    Usage
    -----
    tracker = LiveSharpeTracker(base_dir="data/live")
    result = tracker.compute()  # returns dict for state.json
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = base_dir
        self._store = StateStore(base_dir=base_dir) if base_dir else None
        self._equity_history: list[dict] | None = None
        self._trace_file_pos: int = 0
        self._slippage_gaps: list[float] = []

    def load_history(self) -> list[dict]:
        if self._store is not None:
            self._equity_history = self._store.read_equity_history()
        if not self._equity_history:
            logger.warning("No equity history available")
            return []
        return self._equity_history

    def compute(self) -> dict[str, Any]:
        history = self.load_history()
        if not history:
            result = self._empty_result()
            result["slippage"] = self.compute_slippage_estimate()
            return result

        df = pd.DataFrame(history)
        if df.empty or "portfolio_value" not in df.columns:
            return self._empty_result()

        df = df.sort_values("timestamp")
        df["ts"] = pd.to_datetime(df["timestamp"])
        df["portfolio_value"] = pd.to_numeric(df["portfolio_value"], errors="coerce")

        if len(df) < 2:
            return self._empty_result()

        # Cycle-level returns (consecutive cycle PnL)
        df["cycle_return"] = df["portfolio_value"].pct_change().fillna(0.0)
        df["date"] = df["ts"].dt.date

        # Daily aggregation
        daily = (
            df.groupby("date")
            .agg(
                daily_return=("cycle_return", lambda x: (1 + x).prod() - 1),
                n_cycles=("cycle_return", "count"),
                end_value=("portfolio_value", "last"),
                drawdown=("drawdown", "last"),
            )
            .reset_index()
        )
        daily["date"] = pd.to_datetime(daily["date"])

        # Per-cycle stats
        cycle_rets = df["cycle_return"].values
        n_cycles = len(cycle_rets)

        # Cycle-level Sharpe (autocorrelation adjusted)
        cycle_mean = float(np.mean(cycle_rets))
        cycle_std = float(np.std(cycle_rets, ddof=1))
        if cycle_std > 0 and n_cycles >= MIN_CYCLES_FOR_SHARPE:
            raw_cycle_sharpe = cycle_mean / cycle_std * math.sqrt(CYCLES_PER_DAY)
            rho = float(pd.Series(cycle_rets).autocorr()) if n_cycles > 1 else 0.0
            lo_adj = math.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else 1.0
            cycle_sharpe_adj = raw_cycle_sharpe * lo_adj
        else:
            raw_cycle_sharpe = 0.0
            cycle_sharpe_adj = 0.0
            rho = 0.0

        # Cycle-level stats
        cycle_metrics = {
            "n_cycles": n_cycles,
            "mean_return": round(cycle_mean * 100, 6),
            "std_return": round(cycle_std * 100, 6),
            "sharpe_raw": round(raw_cycle_sharpe, 4),
            "sharpe_adj": round(cycle_sharpe_adj, 4),
            "autocorrelation": round(rho, 4),
        }

        # Daily return metrics
        daily_rets = daily["daily_return"].values
        n_days = len(daily_rets)

        rolling_daily: dict[str, Any] = {}
        for window_days, label in [(7, "7d"), (30, "30d"), (n_days, "all")]:
            if window_days > n_days or window_days < MIN_DAYS_FOR_SHARPE:
                rolling_daily[label] = None
                continue

            window_rets = daily_rets[-window_days:]
            w_mean = float(np.mean(window_rets))
            w_std = float(np.std(window_rets, ddof=1))
            if w_std > 0:
                w_sharpe = w_mean / w_std * math.sqrt(252)
                w_skew = float(pd.Series(window_rets).skew())
                w_kurt = float(pd.Series(window_rets).kurtosis())
                w_rho = float(pd.Series(window_rets).autocorr()) if len(window_rets) > 1 else 0.0
                w_sharpe_adj = w_sharpe * math.sqrt((1.0 - w_rho) / (1.0 + w_rho)) if abs(w_rho) < 1.0 else w_sharpe
                psr = probabilistic_sharpe_ratio(w_sharpe, len(window_rets), w_skew, w_kurt, 0.0)
            else:
                w_sharpe = 0.0
                w_sharpe_adj = 0.0
                psr = 0.0

            rolling_daily[label] = {
                "n_days": len(window_rets),
                "mean_daily_return_pct": round(w_mean * 100, 4),
                "std_daily_return_pct": round(w_std * 100, 4),
                "sharpe": round(w_sharpe, 4),
                "sharpe_adj": round(w_sharpe_adj, 4),
                "psr_gt_0": round(psr, 4),
            }

        # Cumulative PnL + drawdown
        current_value = float(df["portfolio_value"].iloc[-1])
        initial_value = float(df["portfolio_value"].iloc[0])
        total_return_pct = (current_value / initial_value - 1.0) * 100
        max_dd = float((df["portfolio_value"] / df["portfolio_value"].cummax() - 1).min() * 100)

        return {
            "available": True,
            "n_cycles": n_cycles,
            "n_days": n_days,
            "date_range": {
                "start": str(df["ts"].iloc[0]),
                "end": str(df["ts"].iloc[-1]),
            },
            "portfolio": {
                "initial_value": round(initial_value, 2),
                "current_value": round(current_value, 2),
                "total_return_pct": round(total_return_pct, 4),
                "max_drawdown_pct": round(max_dd, 4),
            },
            "cycle_level": cycle_metrics,
            "daily_level": rolling_daily,
            "slippage": self.compute_slippage_estimate(),
        }

    def compute_slippage_estimate(self) -> dict[str, Any]:
        """Estimate slippage from signal price vs current price gap in trace.jsonl.

        Reads new trace entries since last call (max 2000 per invocation
        in the initial catch-up pass), computes RMS gap between
        close_price (model input) and current_price (live market).
        Accumulates samples across calls; capped at 50 000 to limit memory.
        """
        import json
        import os

        live_dir = os.path.join(self._base_dir, "data", "live") if self._base_dir else "data/live"
        trace_path = os.path.join(live_dir, "trace.jsonl")
        if not os.path.exists(trace_path):
            return {"available": False, "reason": "no trace file"}

        n_read = 0
        with open(trace_path, "rb") as f:
            file_size = os.fstat(f.fileno()).st_size
            if self._trace_file_pos >= file_size:
                self._trace_file_pos = 0
                self._slippage_gaps.clear()
                f.seek(0)
            elif self._trace_file_pos > 0:
                f.seek(self._trace_file_pos)

            while True:
                line = f.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line)
                    cp = entry.get("close_price")
                    mp = entry.get("current_price")
                    if cp and mp and cp > 0:
                        gap_pct = abs(mp - cp) / cp * 100
                        self._slippage_gaps.append(gap_pct)
                except (json.JSONDecodeError, KeyError):
                    pass
                n_read += 1
                if n_read >= 2000:
                    break

            self._trace_file_pos = f.tell()

        # Cap accumulator to prevent unbounded memory growth
        if len(self._slippage_gaps) > 50000:
            self._slippage_gaps = self._slippage_gaps[-50000:]

        if not self._slippage_gaps:
            return {"available": False, "reason": "no price data in trace"}

        gaps_arr = np.array(self._slippage_gaps)
        return {
            "available": True,
            "n_samples": len(self._slippage_gaps),
            "mean_gap_pct": round(float(np.mean(gaps_arr)), 4),
            "median_gap_pct": round(float(np.median(gaps_arr)), 4),
            "slippage_rms_pct": round(float(np.sqrt(np.mean(gaps_arr**2))), 4),
            "p90_gap_pct": round(float(np.percentile(gaps_arr, 90)), 4),
            "max_gap_pct": round(float(np.max(gaps_arr)), 4),
        }

    def _empty_result(self) -> dict[str, Any]:
        return {
            "available": False,
            "reason": "insufficient equity history",
            "n_cycles": 0,
            "n_days": 0,
            "portfolio": {},
            "cycle_level": {},
            "daily_level": {},
        }
