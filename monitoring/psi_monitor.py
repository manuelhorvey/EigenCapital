from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("quantforge.psi_monitor")

PSI_TREND_EPSILON = 0.02


@dataclass
class PSIDriftEntry:
    feature: str
    psi: float
    classification: str
    trend: str
    importance_score: float


@dataclass
class PSISnapshot:
    asset: str
    per_feature: list[PSIDriftEntry]
    worst_classification: str
    moderate_count: int
    severe_count: int
    psi_ok: bool
    penalty: float
    timestamp: str


class PSIMonitor:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.baseline_dir = os.path.join(base_dir, "data", "live", "psi_baseline")
        self._prev_snapshots: dict[str, PSISnapshot] = {}

    def persist_baseline(
        self,
        asset: str,
        features: pd.DataFrame,
    ) -> None:
        if features.empty:
            logger.warning("%s: empty training data, skipping PSI baseline", asset)
            return
        os.makedirs(self.baseline_dir, exist_ok=True)
        path = os.path.join(self.baseline_dir, f"{asset}.parquet")
        features.to_parquet(path)
        logger.info("%s: PSI baseline persisted (%d rows, %d cols)", asset, len(features), len(features.columns))

    def load_baseline(self, asset: str) -> pd.DataFrame | None:
        path = os.path.join(self.baseline_dir, f"{asset}.parquet")
        if not os.path.exists(path):
            return None
        try:
            return pd.read_parquet(path)
        except Exception as e:
            logger.warning("%s: failed to load PSI baseline: %s", asset, e)
            return None

    @staticmethod
    def compute_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
        expected = expected.dropna()
        actual = actual.dropna()
        if len(expected) < bins or len(actual) < 2:
            return 0.0

        lo = float(expected.min())
        hi = float(expected.max())
        if hi - lo < 1e-12:
            return 0.0

        edges = np.linspace(lo, hi, bins + 1) + np.finfo(float).eps
        edges[0] = -np.inf
        edges[-1] = np.inf

        exp_counts, _ = np.histogram(expected, bins=edges)
        act_counts, _ = np.histogram(actual, bins=edges)

        exp_pct = exp_counts / max(exp_counts.sum(), 1)
        act_pct = act_counts / max(act_counts.sum(), 1)

        exp_pct = np.clip(exp_pct, 1e-6, 1.0)
        act_pct = np.clip(act_pct, 1e-6, 1.0)

        return float(((act_pct - exp_pct) * np.log(act_pct / exp_pct)).sum())

    @staticmethod
    def classify_drift(psi: float) -> str:
        if psi < 0.1:
            return "NO_DRIFT"
        elif psi < 0.2:
            return "MODERATE"
        else:
            return "SEVERE"

    @staticmethod
    def _compute_trend(prev_psi: float | None, current_psi: float) -> str:
        if prev_psi is None:
            return "STABLE"
        delta = current_psi - prev_psi
        if delta > PSI_TREND_EPSILON:
            return "INCREASING"
        elif delta < -PSI_TREND_EPSILON:
            return "DECREASING"
        else:
            return "STABLE"

    def compute_drift(
        self,
        asset: str,
        current_features: pd.DataFrame,
        top_features: list[tuple[str, float]],
    ) -> PSISnapshot | None:
        baseline = self.load_baseline(asset)
        if baseline is None:
            logger.debug("%s: no PSI baseline available", asset)
            return None

        prev = self._prev_snapshots.get(asset)

        entries: list[PSIDriftEntry] = []
        moderate_count = 0
        severe_count = 0

        for feat_name, imp_score in top_features:
            if feat_name not in baseline.columns or feat_name not in current_features.columns:
                continue
            expected_series = baseline[feat_name]
            actual_series = current_features[feat_name]

            psi = self.compute_psi(expected_series, actual_series)
            cls = self.classify_drift(psi)

            prev_entry = next((e for e in (prev.per_feature if prev else []) if e.feature == feat_name), None)
            trend = self._compute_trend(prev_entry.psi if prev_entry else None, psi)

            entries.append(
                PSIDriftEntry(
                    feature=feat_name,
                    psi=round(psi, 6),
                    classification=cls,
                    trend=trend,
                    importance_score=imp_score,
                )
            )

            if cls == "MODERATE":
                moderate_count += 1
            elif cls == "SEVERE":
                severe_count += 1

        if not entries:
            return None

        if severe_count > 0:
            worst = "SEVERE"
        elif moderate_count > 0:
            worst = "MODERATE"
        else:
            worst = "NO_DRIFT"

        penalty = 0.0
        if moderate_count > 0:
            penalty += -0.08
        if severe_count > 0:
            penalty += -0.20

        snapshot = PSISnapshot(
            asset=asset,
            per_feature=entries,
            worst_classification=worst,
            moderate_count=moderate_count,
            severe_count=severe_count,
            psi_ok=severe_count < 3,
            penalty=penalty,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )

        self._prev_snapshots[asset] = snapshot
        return snapshot
