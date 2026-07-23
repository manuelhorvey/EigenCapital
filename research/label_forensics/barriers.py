"""BarrierMechanicsAnalyzer — barrier distance, hit timing, and efficiency."""

from __future__ import annotations

from typing import Any

import numpy as np


class BarrierMechanicsAnalyzer:
    """Analyze barrier distances, hit timing, and first-touch distribution."""

    def analyze(self, df, params: dict | None = None) -> dict[str, Any]:
        """Run barrier mechanics analysis.

        Parameters
        ----------
        df:
            Must have columns ``label``, ``hit_side``, ``hit_bar``,
            ``upper_dist_pct``, ``lower_dist_pct``, ``vol_at_label``, and
            ``forward_return``.
        params:
            Label parameters (unused here).

        Returns
        -------
        dict with keys:

            - ``upper_barrier`` — distance statistics for upper barrier
            - ``lower_barrier`` — distance statistics for lower barrier
            - ``time_to_hit`` — bars to hit per outcome
            - ``first_touch_distribution`` — fraction upper/lower/timeout
            - ``efficiency`` — barrier efficiency metrics
        """
        hit_side = df["hit_side"].values
        hit_bar = df["hit_bar"].values
        upper_dist = df["upper_dist_pct"].values
        lower_dist = df["lower_dist_pct"].values
        vol = df["vol_at_label"].values
        fwd_ret = df["forward_return"].values
        labels = df["label"].values

        complete = hit_side != "incomplete"
        upper_hits = (hit_side == "upper") & complete
        lower_hits = (hit_side == "lower") & complete
        timeouts = (hit_side == "timeout") & complete

        n_total = int(complete.sum())
        n_upper = int(upper_hits.sum())
        n_lower = int(lower_hits.sum())
        n_timeout = int(timeouts.sum())

        def _stats(arr):
            vals = arr[~np.isnan(arr) & np.isfinite(arr)]
            if len(vals) == 0:
                return {"mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
            return {
                "mean": round(float(np.mean(vals)), 6),
                "median": round(float(np.median(vals)), 6),
                "std": round(float(np.std(vals)), 6),
                "min": round(float(np.min(vals)), 6),
                "max": round(float(np.max(vals)), 6),
                "count": int(len(vals)),
            }

        # ── Barrier distances (in percent) ──
        upper_distance_stats = {
            **_stats(upper_dist[upper_hits]),
            "pct_of_vol": round(
                float(np.mean(upper_dist[upper_hits] / (vol[upper_hits] + 1e-10))), 4
            ) if n_upper else 0.0,
        }
        lower_distance_stats = {
            **_stats(lower_dist[lower_hits]),
            "pct_of_vol": round(
                float(np.mean(lower_dist[lower_hits] / (vol[lower_hits] + 1e-10))), 4
            ) if n_lower else 0.0,
        }

        # ── Time to hit (in bars) ──
        hit_bars_upper = hit_bar[upper_hits]
        hit_bars_lower = hit_bar[lower_hits]
        time_to_hit = {
            "upper_mean_bars": round(float(np.mean(hit_bars_upper)), 2) if n_upper else 0.0,
            "upper_median_bars": round(float(np.median(hit_bars_upper)), 2) if n_upper else 0.0,
            "upper_std_bars": round(float(np.std(hit_bars_upper)), 2) if n_upper else 0.0,
            "lower_mean_bars": round(float(np.mean(hit_bars_lower)), 2) if n_lower else 0.0,
            "lower_median_bars": round(float(np.median(hit_bars_lower)), 2) if n_lower else 0.0,
            "lower_std_bars": round(float(np.std(hit_bars_lower)), 2) if n_lower else 0.0,
            "timeout_bars": 20,
        }

        # ── First-touch distribution ──
        first_touch = {
            "upper_pct": round(n_upper / n_total * 100, 2) if n_total else 0.0,
            "lower_pct": round(n_lower / n_total * 100, 2) if n_total else 0.0,
            "timeout_pct": round(n_timeout / n_total * 100, 2) if n_total else 0.0,
        }

        # ── Efficiency: how quickly each barrier is hit ──
        # Efficiency = 1 - (hit_bar / vertical_barrier)
        # 1.0 = hit immediately, 0.0 = hit at last bar
        efficiency = {}
        if n_upper > 0:
            eff_u = 1.0 - hit_bars_upper.astype(float) / 20.0
            efficiency["upper"] = {
                "mean": round(float(np.mean(eff_u)), 4),
                "median": round(float(np.median(eff_u)), 4),
                "std": round(float(np.std(eff_u)), 4),
            }
        if n_lower > 0:
            eff_l = 1.0 - hit_bars_lower.astype(float) / 20.0
            efficiency["lower"] = {
                "mean": round(float(np.mean(eff_l)), 4),
                "median": round(float(np.median(eff_l)), 4),
                "std": round(float(np.std(eff_l)), 4),
            }

        # ── Asymmetry ratio: upper hit rate / lower hit rate ──
        ratio = round(n_upper / n_lower, 4) if n_lower else float("inf")

        return {
            "upper_barrier": upper_distance_stats,
            "lower_barrier": lower_distance_stats,
            "time_to_hit": time_to_hit,
            "first_touch_distribution": first_touch,
            "asymmetry_ratio_upper_over_lower": ratio,
            "efficiency": efficiency,
        }
