"""LabelDriftAnalyzer — rolling-window diagnostics over time."""

from __future__ import annotations

from typing import Any

import numpy as np


class LabelDriftAnalyzer:
    """Analyze label distribution stability over rolling windows.

    Detects structural breakpoints where the sell percentage crossed
    a significant threshold relative to its historical range.
    """

    WINDOW = 252

    def analyze(self, df, params: dict | None = None) -> dict[str, Any]:
        """Run drift analysis.

        Parameters
        ----------
        df:
            Must have columns ``label``, ``hit_side`` and a ``DatetimeIndex``.
        params:
            Label parameters (unused here).

        Returns
        -------
        dict with keys:

            - ``rolling_buy_pct`` — list of (date, pct) pairs
            - ``rolling_sell_pct`` — list of (date, pct) pairs
            - ``rolling_timeout_pct`` — list of (date, pct) pairs
            - ``window`` — window size in bars
            - ``breakpoints`` — dates where sell_pct crossed outside ±1 std
        """
        hit_side = df["hit_side"].values
        labels = df["label"].values
        dates = df.index

        complete = hit_side != "incomplete"
        n = int(complete.sum())
        if n < self.WINDOW:
            return {
                "window": self.WINDOW,
                "error": f"Insufficient data: {n} complete labels, need {self.WINDOW}",
            }

        buy_arr = np.zeros(n, dtype=float)
        sell_arr = np.zeros(n, dtype=float)
        to_arr = np.zeros(n, dtype=float)

        complete_idx = np.where(complete)[0]
        for i, idx in enumerate(complete_idx):
            lbl = labels[idx]
            buy_arr[i] = 1.0 if lbl == 1 else 0.0
            sell_arr[i] = 1.0 if lbl == -1 else 0.0
            to_arr[i] = 1.0 if lbl == 0 else 0.0

        # Rolling sums
        w = self.WINDOW
        cum_buy = np.cumsum(buy_arr)
        cum_sell = np.cumsum(sell_arr)
        cum_to = np.cumsum(to_arr)

        roll_buy = (cum_buy[w:] - cum_buy[:-w]) / w * 100.0
        roll_sell = (cum_sell[w:] - cum_sell[:-w]) / w * 100.0
        roll_to = (cum_to[w:] - cum_to[:-w]) / w * 100.0

        roll_dates = [str(d.date()) for d in dates[complete_idx][w - 1:]]

        # ── Breakpoints: when sell_pct deviates significantly ──
        sell_mean = float(np.mean(roll_sell))
        sell_std = float(np.std(roll_sell))
        threshold_hi = sell_mean + sell_std
        threshold_lo = sell_mean - sell_std

        breakpoints = []
        for i, sp in enumerate(roll_sell):
            if sp > threshold_hi or sp < threshold_lo:
                if not breakpoints or i - breakpoints[-1]["index"] > 5:
                    breakpoints.append({
                        "date": roll_dates[i],
                        "index": i,
                        "sell_pct": round(float(sp), 2),
                        "deviation": round(float(sp) - sell_mean, 2),
                    })

        # Trim to reasonable number of breakpoints
        if len(breakpoints) > 50:
            step = len(breakpoints) // 50
            breakpoints = breakpoints[::step]

        for bp in breakpoints:
            del bp["index"]

        return {
            "window": w,
            "rolling_buy_pct": [[d, round(float(v), 2)] for d, v in zip(roll_dates, roll_buy)],
            "rolling_sell_pct": [[d, round(float(v), 2)] for d, v in zip(roll_dates, roll_sell)],
            "rolling_timeout_pct": [[d, round(float(v), 2)] for d, v in zip(roll_dates, roll_to)],
            "sell_mean": round(sell_mean, 2),
            "sell_std": round(sell_std, 2),
            "breakpoints": breakpoints,
        }
