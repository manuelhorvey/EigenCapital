"""Temporal stability of the volatility taxonomy.

Measures (each has a stated purpose, per brief §13):
  - adjusted Rand index (ARI): agreement of subsample cluster labels with
    full-sample labels on the common assets — membership stability;
  - pairwise co-membership stability: how often asset pairs that cluster
    together in the full sample remain together in rolling windows;
  - feature-distance stability: correlation of pairwise distance matrices
    between periods — geometric stability independent of k.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from research.volatility import clustering as CL


def subsample_bounds(index: pd.DatetimeIndex, n: int = 3) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Equal-count chronological thirds of a date index."""
    idx = pd.DatetimeIndex(sorted(index.unique()))
    edges = np.array_split(idx, n)
    return [(b[0], b[-1]) for b in edges if len(b)]


def ari_vs_full(full_labels: pd.Series, sub_labels: pd.Series) -> float:
    """ARI on assets present in both label sets; NaN if <3 common assets."""
    common = full_labels.index.intersection(sub_labels.index)
    if len(common) < 3:
        return float("nan")
    return float(adjusted_rand_score(full_labels.loc[common], sub_labels.loc[common]))


def stability_report(
    features_by_window: dict[str, pd.DataFrame],
    full_labels: pd.Series,
) -> dict:
    """ARI of each window's clustering vs full-sample labels."""
    out: dict = {"ari": {}, "k_by_window": {}}
    for name, feats in features_by_window.items():
        res = CL.cluster_features(feats)
        out["k_by_window"][name] = int(res.k)
        out["ari"][name] = ari_vs_full(full_labels, res.labels)
    aris = [v for v in out["ari"].values() if np.isfinite(v)]
    out["ari_mean"] = float(np.mean(aris)) if aris else float("nan")
    out["ari_min"] = float(np.min(aris)) if aris else float("nan")
    out["stable"] = bool(aris and out["ari_min"] >= 0.5)
    return out


def rolling_co_membership(
    feature_windows: list[tuple[str, pd.DataFrame]],
    full_labels: pd.Series,
) -> dict:
    """For full-sample cluster pairs, fraction of windows keeping them together."""
    pair_stats: dict[tuple[str, str], dict[str, int]] = {}
    for a in full_labels.index:
        for b in full_labels.index:
            if a >= b:
                continue
            pair_stats[(a, b)] = {
                "together_full": int(full_labels[a] == full_labels[b]),
                "together_windows": 0,
                "windows": 0,
            }
    for _, feats in feature_windows:
        res = CL.cluster_features(feats)
        labs = res.labels
        for (a, b), st in pair_stats.items():
            if a in labs.index and b in labs.index:
                st["windows"] += 1
                if labs[a] == labs[b]:
                    st["together_windows"] += 1
    together = [(a, b, st) for (a, b), st in pair_stats.items() if st["together_full"]]
    if not together:
        return {"n_full_pairs": 0, "mean_co_membership": float("nan"), "pairs": {}}
    rates = {
        f"{a}|{b}": (st["together_windows"] / st["windows"] if st["windows"] else float("nan")) for a, b, st in together
    }
    vals = [v for v in rates.values() if np.isfinite(v)]
    return {
        "n_full_pairs": len(together),
        "mean_co_membership": float(np.mean(vals)) if vals else float("nan"),
        "min_co_membership": float(np.min(vals)) if vals else float("nan"),
        "pairs": rates,
    }


def distance_stability(feature_a: pd.DataFrame, feature_b: pd.DataFrame) -> float:
    """Pearson correlation of pairwise feature-distance matrices on common assets.

    Purpose: detect geometric drift independent of cluster-count choice.
    """
    common = feature_a.index.intersection(feature_b.index)
    if len(common) < 4:
        return float("nan")
    da = CL._distance(CL.standardize(feature_a.loc[common]), "euclidean")
    db = CL._distance(CL.standardize(feature_b.loc[common]), "euclidean")
    iu = np.triu_indices(len(common), k=1)
    x, y = da[iu], db[iu]
    if np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])
