"""CounterfactualLabelingEngine — barrier sensitivity and causal analysis."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from labels.triple_barrier import _ewm_vol
from research.label_forensics.engine import apply_labels_and_compute_details
from research.label_forensics.distribution import LabelDistributionAnalyzer
from research.label_forensics.barriers import BarrierMechanicsAnalyzer


def _compute_vol_target(df: pd.DataFrame, vol_primitive=None):
    from shared.volatility import compute_atr_pct
    if vol_primitive is not None:
        return compute_atr_pct(df, period=vol_primitive.period)
    return _ewm_vol(df["close"])


class CounterfactualLabelingEngine:
    """Sweep barrier parameters to separate geometry effects from market structure.

    For each configuration, re-labels the same historical candles and
    measures label distribution, expectancy, and hit mechanics.
    """

    PT_SL_SWEEP = [
        (1.0, 1.0),
        (1.5, 1.0),
        (2.0, 1.0),
        (3.0, 1.0),
        (4.0, 1.0),
        (5.0, 1.0),
    ]

    VERTICAL_BARRIER_SWEEP = [10, 20, 40, 80]

    def __init__(self):
        self._dist_analyzer = LabelDistributionAnalyzer()
        self._barrier_analyzer = BarrierMechanicsAnalyzer()

    def analyze(
        self,
        df: pd.DataFrame,
        pt_sl: tuple[float, float] | None = None,
        vol_primitive=None,
        label_params: dict | None = None,
    ) -> dict[str, Any]:
        """Run counterfactual barrier sensitivity analysis.

        Parameters
        ----------
        df:
            Raw OHLCV DataFrame.
        pt_sl:
            If provided, the current production (pt, sl) is highlighted
            in the sweep results. If None, all PT_SL_SWEEP are shown
            without a baseline marker.
        vol_primitive:
            Volatility primitive to use.
        label_params:
            Passed through for consistency.

        Returns
        -------
        dict with keys:

            - ``pt_sl_sweep`` — list of results varying PT with SL=1
            - ``vertical_barrier_sweep`` — list at PT=SL varying VB
        """
        return {
            "pt_sl_sweep": self._sweep_pt_sl(df, baseline_pt_sl=pt_sl, vol_primitive=vol_primitive),
            "vertical_barrier_sweep": self._sweep_vertical_barrier(df, vol_primitive=vol_primitive),
        }

    def _label_and_report(
        self, df: pd.DataFrame, pt: float, sl: float, vb: int, vol_primitive=None,
    ) -> dict[str, Any]:
        labeled = apply_labels_and_compute_details(
            df, pt_sl=[pt, sl], vertical_barrier=vb, vol_primitive=vol_primitive,
        )
        complete = labeled[labeled["hit_side"] != "incomplete"].copy()
        if len(complete) == 0:
            return {"pt": pt, "sl": sl, "vb": vb, "error": "no complete labels"}

        dist = self._dist_analyzer.analyze(complete)
        barrier = self._barrier_analyzer.analyze(complete)

        overall = dist["overall"]
        expect = dist["expectancy"]
        bm = barrier

        return {
            "pt": pt,
            "sl": sl,
            "ratio": round(pt / sl, 2),
            "vb": vb,
            "n_total": overall["total_labeled"],
            "buy_pct": overall["buy_pct"],
            "sell_pct": overall["sell_pct"],
            "timeout_pct": overall["timeout_pct"],
            "asymmetry_ratio": bm["asymmetry_ratio_upper_over_lower"],
            "upper_hit_mean_bars": bm["time_to_hit"]["upper_mean_bars"],
            "lower_hit_mean_bars": bm["time_to_hit"]["lower_mean_bars"],
            "expectancy_buy_mean": expect["buy"]["mean"],
            "expectancy_sell_mean": expect["sell"]["mean"],
            "expectancy_timeout_mean": expect["timeout"]["mean"],
            "label_distribution_detail": overall,
            "barrier_detail": barrier,
            "expectancy_detail": expect,
        }

    def _sweep_pt_sl(
        self, df: pd.DataFrame, baseline_pt_sl=None, vol_primitive=None, vb: int = 20,
    ) -> list[dict[str, Any]]:
        results = []
        for pt, sl in self.PT_SL_SWEEP:
            try:
                r = self._label_and_report(df, pt, sl, vb, vol_primitive=vol_primitive)
                if baseline_pt_sl and abs(pt - baseline_pt_sl[0]) < 0.01 and abs(sl - baseline_pt_sl[1]) < 0.01:
                    r["is_baseline"] = True
                results.append(r)
            except Exception:
                results.append({"pt": pt, "sl": sl, "error": True})
        return results

    def _sweep_vertical_barrier(
        self, df: pd.DataFrame, vol_primitive=None,
    ) -> list[dict[str, Any]]:
        results = []
        for vb in self.VERTICAL_BARRIER_SWEEP:
            try:
                r = self._label_and_report(df, 1.0, 1.0, vb, vol_primitive=vol_primitive)
                if vb == 20:
                    r["is_baseline"] = True
                results.append(r)
            except Exception:
                results.append({"vb": vb, "error": True})
        return results
