"""Volatility regime classification and transition analysis — descriptive layer.

Two regime constructions, both declared ex-ante (report §8), tested for
robustness against each other:

1. PERCENTILE — within-asset RV_20 percentile bands:
       LOW < P25, NORMAL P25-P75, HIGH P75-P95, EXTREME > P95
   Two variants are computed:
   - full-sample percentile: descriptive cross-sectional structure only
     (uses the whole history — NOT point-in-time).
   - expanding (PIT) percentile: percentile of the current RV within all RV
     values observed strictly BEFORE it. Used for every trade-level
     conditioning so no future information enters trade attribution.

2. Z-SCORE — z-score of log(RV_20) vs its trailing 252-day window:
       LOW < -1, NORMAL [-1, +1), HIGH [+1, +2), EXTREME >= +2
   Always PIT by construction (trailing window).

Transition matrices, persistence and durations are computed on the
full-sample percentile variant (descriptive structure), with the expanding
variant reported alongside for stability comparison.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

REGIMES: Tuple[str, ...] = ("LOW", "NORMAL", "HIGH", "EXTREME")


def percentile_regimes(rv: pd.Series, quantiles: Tuple[float, float, float] = (0.25, 0.75, 0.95)) -> pd.Series:
    """Full-sample within-asset percentile regime (descriptive only, non-PIT)."""
    s = rv.dropna()
    if s.empty:
        return pd.Series(index=rv.index, dtype="object")
    q25, q75, q95 = s.quantile(quantiles)
    out = pd.Series(index=rv.index, dtype="object")
    out[rv <= q25] = "LOW"
    out[(rv > q25) & (rv <= q75)] = "NORMAL"
    out[(rv > q75) & (rv <= q95)] = "HIGH"
    out[rv > q95] = "EXTREME"
    out[rv.isna()] = np.nan
    return out


def expanding_percentile_regimes(rv: pd.Series) -> pd.Series:
    """PIT variant: percentile of today's RV within all strictly-prior RV.

    Expanding quantiles computed on prior observations only; the first 60
    observations are left unlabeled (insufficient regime baseline) so no
    future information can leak into early labels.
    """
    s = rv.dropna()
    out = pd.Series(np.nan, index=rv.index, dtype="object")
    values = s.to_numpy()
    idx = s.index
    for pos in range(len(values)):
        if pos < 60:
            continue
        hist = values[:pos]
        q25, q75, q95 = np.quantile(hist, [0.25, 0.75, 0.95])
        v = values[pos]
        if v <= q25:
            out.iloc[out.index.get_loc(idx[pos])] = "LOW"
        elif v <= q75:
            out.iloc[out.index.get_loc(idx[pos])] = "NORMAL"
        elif v <= q95:
            out.iloc[out.index.get_loc(idx[pos])] = "HIGH"
        else:
            out.iloc[out.index.get_loc(idx[pos])] = "EXTREME"
    return out


def zscore_regimes(rv: pd.Series, window: int = 252) -> pd.Series:
    """PIT z-score of log(RV) vs trailing window (always causal)."""
    log_rv = np.log(rv.replace(0.0, np.nan))
    mu = log_rv.rolling(window, min_periods=60).mean()
    sd = log_rv.rolling(window, min_periods=60).std(ddof=1)
    z = (log_rv - mu) / sd.replace(0.0, np.nan)
    out = pd.Series(np.nan, index=rv.index, dtype="object")
    out[z < -1.0] = "LOW"
    out[(z >= -1.0) & (z < 1.0)] = "NORMAL"
    out[(z >= 1.0) & (z < 2.0)] = "HIGH"
    out[z >= 2.0] = "EXTREME"
    return out


def regime_frequencies(labels: pd.Series) -> Dict[str, float]:
    """Share of labeled days per regime."""
    s = labels.dropna()
    n = len(s)
    if n == 0:
        return {}
    return {r: float((s == r).sum() / n) for r in REGIMES}


def transition_matrix(labels: pd.Series) -> pd.DataFrame:
    """Row-normalized first-order transition probabilities between regimes.

    Descriptive only — no causality is inferred. Consecutive labeled days
    only (NaN boundaries break runs).
    """
    s = labels.dropna()
    counts = pd.DataFrame(0.0, index=REGIMES, columns=REGIMES)
    prev = None
    for lab in s:
        if prev is not None and prev in REGIMES and lab in REGIMES:
            counts.loc[prev, lab] += 1.0
        prev = lab
    row_sums = counts.sum(axis=1)
    return counts.div(row_sums.replace(0.0, np.nan), axis=0)


def regime_runs(labels: pd.Series) -> Dict[str, Dict[str, float]]:
    """Per-regime run statistics: count, mean duration, max duration, p50/p90."""
    s = labels.dropna()
    runs: Dict[str, List[int]] = {r: [] for r in REGIMES}
    current = None
    length = 0
    for lab in s:
        if lab == current:
            length += 1
        else:
            if current is not None and current in runs and length > 0:
                runs[current].append(length)
            current = lab
            length = 1
    if current is not None and current in runs and length > 0:
        runs[current].append(length)
    out: Dict[str, Dict[str, float]] = {}
    for r in REGIMES:
        arr = np.array(runs[r], dtype=float)
        if len(arr) == 0:
            out[r] = {
                "run_count": 0.0,
                "mean_duration": float("nan"),
                "median_duration": float("nan"),
                "p90_duration": float("nan"),
                "max_duration": float("nan"),
            }
        else:
            out[r] = {
                "run_count": float(len(arr)),
                "mean_duration": float(arr.mean()),
                "median_duration": float(np.median(arr)),
                "p90_duration": float(np.quantile(arr, 0.9)),
                "max_duration": float(arr.max()),
            }
    return out


def regimewise_sync(labels_by_asset: Dict[str, pd.Series], regime: str) -> pd.DataFrame:
    """Per-day count of assets simultaneously in ``regime`` (aligned index)."""
    df = pd.DataFrame(labels_by_asset)
    in_regime = df.eq(regime)
    valid = df.notna().sum(axis=1)
    return pd.DataFrame({"count": in_regime.sum(axis=1), "valid": valid})


def pairwise_regime_agreement(labels_a: pd.Series, labels_b: pd.Series) -> float:
    """Fraction of co-labeled days where both assets share the same regime."""
    joined = pd.concat([labels_a, labels_b], axis=1, keys=["a", "b"]).dropna()
    if len(joined) < 60:
        return float("nan")
    return float((joined["a"] == joined["b"]).mean())
