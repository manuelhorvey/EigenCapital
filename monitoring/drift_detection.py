import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from typing import Optional, Dict, List, Tuple


STRUCTURAL_PSI_COLUMNS = [
    "ema_spread", "adx", "rsi", "bb_zscore", "slope_20",
    "curvature_10", "path_efficiency_63", "skew", "kurt", "tail_ratio",
]

BEHAVIORAL_PSI_COLUMNS = [
    "P_trend", "P_range", "P_volatile", "regime_confidence",
]

INTERACTION_PSI_COLUMNS = [
    "regime_contrast", "regime_entropy", "transition_risk",
    "ema_contrast", "slope_contrast", "path_contrast",
]


def calculate_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    expected = expected.replace([np.inf, -np.inf], np.nan).dropna()
    actual = actual.replace([np.inf, -np.inf], np.nan).dropna()
    if len(expected) < bins or len(actual) == 0:
        return 0.0
    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(expected.quantile(quantiles).to_numpy())
    if len(edges) < 3:
        return 0.0
    expected_counts = pd.cut(expected, bins=edges, include_lowest=True).value_counts(sort=False)
    actual_counts = pd.cut(actual, bins=edges, include_lowest=True).value_counts(sort=False)
    expected_pct = expected_counts / max(expected_counts.sum(), 1)
    actual_pct = actual_counts / max(actual_counts.sum(), 1)
    expected_pct = expected_pct.replace(0, 1e-6)
    actual_pct = actual_pct.replace(0, 1e-6)
    return float(((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)).sum())


def column_group_psi(train: pd.DataFrame, oos: pd.DataFrame, columns: list[str]) -> float:
    cols = [c for c in columns if c in train.columns and c in oos.columns]
    if not cols:
        return 0.0
    return float(np.mean([calculate_psi(train[col], oos[col]) for col in cols]))


def grouped_feature_psi(train: pd.DataFrame, oos: pd.DataFrame) -> dict:
    structural = column_group_psi(train, oos, STRUCTURAL_PSI_COLUMNS)
    behavioral = column_group_psi(train, oos, BEHAVIORAL_PSI_COLUMNS)
    interaction = column_group_psi(train, oos, INTERACTION_PSI_COLUMNS)
    weighted = 0.2 * structural + 0.5 * behavioral + 0.3 * interaction
    return {
        "feature_psi": weighted,
        "structural_psi": structural,
        "behavioral_psi": behavioral,
        "interaction_psi": interaction,
    }


def signal_distribution_drift(
    live_signals: Dict[str, int],
    backtest_baseline: Dict[str, float],
) -> float:
    total = sum(live_signals.values())
    if total == 0:
        return 0.0
    live_pcts = {
        k: v / total for k, v in live_signals.items()
    }
    drift = 0.0
    for k in set(list(live_pcts.keys()) + list(backtest_baseline.keys())):
        lv = live_pcts.get(k, 0.0)
        bv = backtest_baseline.get(k, 0.0)
        drift += abs(lv - bv)
    return drift / len(set(list(live_pcts.keys()) + list(backtest_baseline.keys())))


def confidence_drift(mean_confidence: float, baseline_confidence: float) -> float:
    return abs(mean_confidence - baseline_confidence)


def ks_drift(train: pd.DataFrame, live: pd.DataFrame, feature: str) -> float:
    if feature not in train.columns or feature not in live.columns:
        return 0.0
    stat, _ = ks_2samp(train[feature].dropna(), live[feature].dropna())
    return float(stat)


class DriftDetector:
    def __init__(
        self,
        psi_threshold: float = 0.25,
        signal_drift_threshold: float = 0.15,
        confidence_drift_threshold: float = 0.15,
        ks_threshold: float = 0.20,
    ):
        self.psi_threshold = psi_threshold
        self.signal_drift_threshold = signal_drift_threshold
        self.confidence_drift_threshold = confidence_drift_threshold
        self.ks_threshold = ks_threshold

    def check_feature_psi(self, train: pd.DataFrame, live: pd.DataFrame) -> dict:
        psi = grouped_feature_psi(train, live)
        psi["passed"] = psi["feature_psi"] < self.psi_threshold
        return psi

    def check_signal_drift(
        self,
        live_signals: Dict[str, int],
        backtest_baseline: Dict[str, float],
    ) -> dict:
        drift = signal_distribution_drift(live_signals, backtest_baseline)
        return {"drift": drift, "passed": drift < self.signal_drift_threshold}

    def check_confidence_drift(
        self, mean_confidence: float, baseline_confidence: float
    ) -> dict:
        drift = confidence_drift(mean_confidence, baseline_confidence)
        return {"drift": drift, "passed": drift < self.confidence_drift_threshold}

    def check_ks_drift(self, train: pd.DataFrame, live: pd.DataFrame, features: Optional[list[str]] = None) -> dict:
        if features is None:
            features = [c for c in train.columns if c in live.columns]
        results = {}
        for f in features:
            d = ks_drift(train, live, f)
            results[f] = {"ks_stat": d, "passed": d < self.ks_threshold}
        return results

    def full_check(
        self,
        train: pd.DataFrame,
        live: pd.DataFrame,
        live_signals: Dict[str, int],
        backtest_baseline: Dict[str, float],
        mean_confidence: float,
        baseline_confidence: float,
        ks_features: Optional[list[str]] = None,
    ) -> dict:
        return {
            "feature_psi": self.check_feature_psi(train, live),
            "signal_distribution": self.check_signal_drift(live_signals, backtest_baseline),
            "confidence": self.check_confidence_drift(mean_confidence, baseline_confidence),
            "ks_drift": self.check_ks_drift(train, live, ks_features),
        }
