"""LabelDistributionAnalyzer — count and expectancy statistics per label class."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class LabelDistributionAnalyzer:
    """Analyze label class distribution, expectancy, and regime decomposition."""

    def analyze(self, df: pd.DataFrame, params: dict | None = None) -> dict[str, Any]:
        """Run label distribution analysis on a fully labeled DataFrame.

        Parameters
        ----------
        df:
            Must have columns ``label``, ``hit_side``, ``forward_return``,
            ``vol_at_label``, and a ``DatetimeIndex``.
        params:
            Label parameters (unused here, accepted for API consistency).

        Returns
        -------
        dict with keys:

            - ``overall`` — raw counts and percentages
            - ``per_year`` — label distribution grouped by year
            - ``per_vol_bucket`` — label distribution in low/medium/high vol
            - ``expectancy`` — mean forward_return per label class
            - ``timeout_analysis`` — timeout rate and characteristics
        """
        labels = df["label"].values
        hit_side = df["hit_side"].values
        fwd_ret = df["forward_return"].values
        vol = df["vol_at_label"].values
        index = df.index

        mask_complete = hit_side != "incomplete"

        buy_mask = (labels == 1) & mask_complete
        sell_mask = (labels == -1) & mask_complete
        timeout_mask = (labels == 0) & (hit_side == "timeout")

        n_buy = int(buy_mask.sum())
        n_sell = int(sell_mask.sum())
        n_timeout = int(timeout_mask.sum())
        n_total = n_buy + n_sell + n_timeout
        n_dropped = len(df) - n_total

        buy_pct = round(n_buy / n_total * 100, 2) if n_total else 0.0
        sell_pct = round(n_sell / n_total * 100, 2) if n_total else 0.0
        timeout_pct = round(n_timeout / n_total * 100, 2) if n_total else 0.0

        overall = {
            "buy": n_buy, "buy_pct": buy_pct,
            "sell": n_sell, "sell_pct": sell_pct,
            "timeout": n_timeout, "timeout_pct": timeout_pct,
            "dropped": n_dropped, "total_labeled": n_total,
        }

        # ── Per year ──
        years = index.year
        per_year = {}
        for year in sorted(years.unique()):
            ym = years == year
            by = int((buy_mask & ym).sum())
            sy = int((sell_mask & ym).sum())
            ty = int((timeout_mask & ym).sum())
            tot = by + sy + ty
            per_year[str(year)] = {
                "buy": by, "buy_pct": round(by / tot * 100, 2) if tot else 0.0,
                "sell": sy, "sell_pct": round(sy / tot * 100, 2) if tot else 0.0,
                "timeout": ty, "timeout_pct": round(ty / tot * 100, 2) if tot else 0.0,
                "total": tot,
            }

        # ── Per volatility bucket ──
        valid_vol = vol[mask_complete | timeout_mask]
        if len(valid_vol) > 0:
            lo, hi = np.percentile(valid_vol, [33.3, 66.7])
        else:
            lo = hi = 0.0
        vol_bucket = np.full(len(df), "medium", dtype=object)
        vol_bucket[vol <= lo] = "low"
        vol_bucket[vol >= hi] = "high"
        vol_bucket[~mask_complete & (labels == 0)] = "n/a"

        per_vol = {}
        for bucket in ["low", "medium", "high"]:
            bm = vol_bucket == bucket
            by = int((buy_mask & bm).sum())
            sy = int((sell_mask & bm).sum())
            ty = int((timeout_mask & bm).sum())
            tot = by + sy + ty
            per_vol[bucket] = {
                "buy": by, "buy_pct": round(by / tot * 100, 2) if tot else 0.0,
                "sell": sy, "sell_pct": round(sy / tot * 100, 2) if tot else 0.0,
                "timeout": ty, "timeout_pct": round(ty / tot * 100, 2) if tot else 0.0,
                "total": tot,
            }

        # ── Expectancy ──
        expectancy = {}
        for label_name, mask in [("buy", buy_mask), ("sell", sell_mask), ("timeout", timeout_mask)]:
            vals = fwd_ret[mask]
            expectancy[label_name] = {
                "mean": round(float(np.mean(vals)), 6) if len(vals) else 0.0,
                "median": round(float(np.median(vals)), 6) if len(vals) else 0.0,
                "std": round(float(np.std(vals)), 6) if len(vals) else 0.0,
                "min": round(float(np.min(vals)), 6) if len(vals) else 0.0,
                "max": round(float(np.max(vals)), 6) if len(vals) else 0.0,
                "count": int(len(vals)),
            }

        return {
            "overall": overall,
            "per_year": per_year,
            "per_vol_bucket": per_vol,
            "expectancy": expectancy,
        }
