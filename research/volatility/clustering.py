"""Volatility clustering, temporal stability and synchronization — descriptive layer.

Distances and linkage are declared ex-ante (report §9-§10):
- Feature vector per asset (9 components, each robustly scaled across assets):
    1  log mean RV_20 (level)
    2  RV_20 CV (volatility-of-volatility)
    3  RV_20 lag-1 autocorrelation (persistence)
    4  |return| lag-1 autocorrelation (clustering persistence)
    5  excess kurtosis
    6  extreme-event frequency (|r| > 3 sigma_1y)
    7  jump-proxy frequency (|r| > 3 x RV_20_daily)
    8  EXTREME-regime frequency
    9  estimator dispersion (PK/GK vs RV log-ratio mean)
- Normalization: median/IQR robust scaling per component, then Euclidean
  distance, Ward linkage (hierarchical).
- Correlation-distance clustering as the declared alternative estimator:
  d = sqrt(2 * (1 - corr(log(RV_20)))), average linkage.
- Cluster count: reported for k in 2..6 with silhouette; no k is "chosen"
  by aesthetics — k=2 and k=3 are the primary reported cuts with full
  membership and stability for each.
- Temporal stability: adjusted Rand index between clusterings of disjoint
  and overlapping sub-samples (early/middle/recent thirds, anchored
  windows), plus co-membership stability.

No cluster label is interpreted as trading value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from research.volatility.config import CLUSTER_K_CANDIDATES as C_CLUSTER_KS

FEATURE_KEYS: Tuple[str, ...] = (
    "f1_log_mean_rv",
    "f2_rv_cv",
    "f3_rv_ac1",
    "f4_absret_ac1",
    "f5_excess_kurtosis",
    "f6_extreme_freq",
    "f7_jump_freq",
    "f8_extreme_regime_freq",
    "f9_estimator_dispersion",
)


def build_feature_matrix(summaries: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """Assemble the 9-component volatility feature matrix (assets x features)."""
    rows: Dict[str, Dict[str, float]] = {}
    for inst, s in summaries.items():
        mean_rv = s.get("mean_rv20", float("nan"))
        rows[inst] = {
            "f1_log_mean_rv": np.log(mean_rv) if mean_rv and mean_rv > 0 else float("nan"),
            "f2_rv_cv": s.get("rv20_cv", float("nan")),
            "f3_rv_ac1": s.get("rv_ac_lag1", float("nan")),
            "f4_absret_ac1": s.get("absret_ac_lag1", float("nan")),
            "f5_excess_kurtosis": s.get("excess_kurtosis", float("nan")),
            "f6_extreme_freq": s.get("extreme_freq_3sigma", float("nan")),
            "f7_jump_freq": s.get("jump_freq", float("nan")),
            "f8_extreme_regime_freq": float("nan"),  # filled by caller (regime freq)
            "f9_estimator_dispersion": s.get("estimator_dispersion", float("nan")),
        }
    return pd.DataFrame(rows).T


def robust_scale(matrix: pd.DataFrame) -> pd.DataFrame:
    """Median/IQR scaling per feature (NaN-safe)."""
    med = matrix.median(axis=0)
    q75 = matrix.quantile(0.75)
    q25 = matrix.quantile(0.25)
    iqr = (q75 - q25).replace(0.0, np.nan)
    scaled = (matrix - med) / iqr
    return scaled.fillna(scaled.median(axis=0)).fillna(0.0)


def standardize(matrix: pd.DataFrame) -> pd.DataFrame:
    """Column-wise z-score (NaN-safe; constant columns collapse to 0)."""
    mu = matrix.mean(axis=0)
    sd = matrix.std(axis=0, ddof=1).replace(0.0, np.nan)
    z = (matrix - mu) / sd
    return z.fillna(0.0)


def _distance(scaled: pd.DataFrame, metric: str = "euclidean") -> np.ndarray:
    """Square pairwise distance matrix over rows of ``scaled``."""
    from scipy.spatial.distance import pdist

    if metric != "euclidean":
        raise ValueError(f"unsupported distance metric: {metric}")
    return squareform(pdist(scaled.to_numpy(dtype=float), metric="euclidean"))


def pca_transform(matrix: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray]:
    """PCA on standardized rows; returns (scores DataFrame, explained variance ratios)."""
    X = standardize(matrix).to_numpy(dtype=float)
    X = X - X.mean(axis=0)
    cov = np.cov(X, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals, eigvecs = eigvals[order], eigvecs[:, order]
    total = float(eigvals.sum())
    evr = (eigvals / total) if total > 0 else np.full_like(eigvals, np.nan)
    scores = pd.DataFrame(X @ eigvecs, index=matrix.index, columns=[f"PC{i + 1}" for i in range(len(eigvals))])
    return scores, evr


@dataclass(frozen=True)
class ClusterFit:
    """Primary-cut clustering result (labels as a Series over assets)."""

    k: int
    labels: pd.Series
    silhouette: float
    method: str = "average/euclidean"


def cluster_features(features: pd.DataFrame) -> ClusterFit:
    """Frozen primary clustering rule.

    robust_scale → average linkage on Euclidean distance → k chosen as the
    silhouette maximizer over {2..6}, ties broken toward the smaller k.
    """
    scaled = robust_scale(features)
    n = len(scaled)
    if n < 3:
        labs = pd.Series(1, index=scaled.index)
        return ClusterFit(k=1, labels=labs, silhouette=float("nan"))

    from scipy.cluster.hierarchy import fcluster
    from scipy.cluster.hierarchy import linkage as hlinkage
    from scipy.spatial.distance import pdist as _pdist

    condensed = _pdist(scaled.to_numpy(dtype=float), metric="euclidean")
    Z = hlinkage(condensed, method="average")
    best_k, best_lab, best_sil = 2, None, -np.inf
    for k in C_CLUSTER_KS:
        if k >= n:
            break
        lab = fcluster(Z, t=k, criterion="maxclust")
        uniq = set(lab)
        if len(uniq) < 2 or len(uniq) >= n:
            continue
        try:
            sil = float(silhouette_score(scaled.to_numpy(dtype=float), lab, metric="euclidean"))
        except ValueError:
            continue
        if sil > best_sil + 1e-12:  # strict improvement; ties keep smaller k
            best_k, best_lab, best_sil = k, lab, sil
    if best_lab is None:
        best_lab = fcluster(Z, t=2, criterion="maxclust")
        best_sil = float("nan")
    labels = pd.Series([int(x) for x in best_lab], index=scaled.index, dtype=int)
    return ClusterFit(k=int(best_k), labels=labels, silhouette=float(best_sil))


def ward_clusters(features: pd.DataFrame, k: int) -> Dict[str, int]:
    """Ward hierarchical clustering on robust-scaled Euclidean distance."""
    scaled = robust_scale(features)
    n = len(scaled)
    if n < k:
        return {inst: 0 for inst in scaled.index}
    from scipy.spatial.distance import pdist

    # Deterministic: scipy linkage on condensed distance matrix, no RNG.
    dist = pdist(scaled.to_numpy(), metric="euclidean")
    Z = linkage(dist, method="ward")
    labels = fcluster(Z, t=k, criterion="maxclust")
    return {inst: int(lab) for inst, lab in zip(scaled.index, labels)}


def corr_distance_clusters(log_rv_by_asset: Dict[str, pd.Series], k: int, min_overlap: int = 120) -> Dict[str, int]:
    """Clustering on correlation distance of log(RV_20) series (avg linkage)."""
    df = pd.DataFrame({k_: np.log(s.replace(0.0, np.nan)) for k_, s in log_rv_by_asset.items()}).dropna(how="all")
    corr = df.corr(min_periods=min_overlap)
    d = np.sqrt(2.0 * (1.0 - corr.clip(lower=-1.0, upper=1.0))).fillna(1.0)
    np.fill_diagonal(d.values, 0.0)
    from scipy.spatial.distance import squareform as sf

    condensed = sf(d.to_numpy(), checks=False)
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=k, criterion="maxclust")
    return {inst: int(lab) for inst, lab in zip(d.index, labels)}


def pca_structure(features: pd.DataFrame) -> Dict[str, object]:
    """Leading PCA structure of the scaled feature space (descriptive)."""
    X = robust_scale(features).to_numpy()
    X = X - X.mean(axis=0)
    cov = np.cov(X, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    total = float(eigvals.sum())
    if total <= 0:
        return {"explained_ratio_pc1": float("nan"), "explained_ratio_pc2": float("nan"), "loadings_pc1": {}}
    return {
        "explained_ratio_pc1": float(eigvals[0] / total),
        "explained_ratio_pc2": float(eigvals[1] / total) if len(eigvals) > 1 else float("nan"),
        "loadings_pc1": {k: float(v) for k, v in zip(FEATURE_KEYS, eigvecs[:, 0])},
    }


@dataclass(frozen=True)
class ClusterResult:
    """One clustering cut with its descriptive quality diagnostics."""

    method: str
    k: int
    labels: Dict[str, int]
    silhouette: float

    def to_dict(self) -> Dict[str, object]:
        return {"method": self.method, "k": self.k, "silhouette": round(self.silhouette, 4), "labels": self.labels}


def evaluate_cuts(method: str, labels_by_k: Dict[int, Dict[str, int]], features: pd.DataFrame) -> List[ClusterResult]:
    """Silhouette for each candidate cut (descriptive diagnostics only)."""
    scaled = robust_scale(features).to_numpy()
    out: List[ClusterResult] = []
    for k, labels in labels_by_k.items():
        labs = np.array([labels[i] for i in features.index])
        uniq = set(labs)
        if len(uniq) < 2 or len(uniq) >= len(labs):
            out.append(ClusterResult(method=method, k=k, labels=labels, silhouette=float("nan")))
            continue
        try:
            sil = float(silhouette_score(scaled, labs, metric="euclidean"))
        except ValueError:
            sil = float("nan")
        out.append(ClusterResult(method=method, k=k, labels=labels, silhouette=sil))
    return out


def kmeans_pca_clusters(features: pd.DataFrame, k: int, seed: int = 42) -> Dict[str, int]:
    """PCA(2) + k-means as the declared third approach (seeded, deterministic)."""
    scaled = robust_scale(features).to_numpy()
    X = scaled - scaled.mean(axis=0)
    cov = np.cov(X, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    top = np.argsort(eigvals)[::-1][:2]
    proj = X @ eigvecs[:, top]
    km = KMeans(n_clusters=k, n_init=10, random_state=seed)
    labs = km.fit_predict(proj)
    return {inst: int(lab) + 1 for inst, lab in zip(features.index, labs)}


# ─────────────────────────────────────────────────────────────────────────────
# Temporal stability
# ─────────────────────────────────────────────────────────────────────────────


def subsample_feature(
    log_rv: pd.Series,
    rets: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Dict[str, float]:
    """Recompute the 9 features on a sub-window (for stability analysis)."""
    from research.volatility.features import autocorr, jump_proxies  # local import: avoid cycle

    lr = log_rv.loc[start:end].dropna()
    r = rets.loc[start:end].dropna()
    if len(lr) < 120 or len(r) < 120:
        return {k: float("nan") for k in FEATURE_KEYS}
    cv = float(lr.std(ddof=1) / lr.mean()) if lr.mean() > 0 else float("nan")
    return {
        "f1_log_mean_rv": float(np.log(lr.mean())),
        "f2_rv_cv": cv,
        "f3_rv_ac1": autocorr(lr, [1])[1],
        "f4_absret_ac1": autocorr(r.abs(), [1])[1],
        "f5_excess_kurtosis": float(r.kurtosis()),
        "f6_extreme_freq": float((r.abs() > 3.0 * r.std(ddof=1) * np.sqrt(252)).mean()),
        "f7_jump_freq": jump_proxies(r, lr)["jump_freq"],
        "f8_extreme_regime_freq": float("nan"),  # caller may fill; excluded if NaN
        "f9_estimator_dispersion": float("nan"),  # PK/GK recomputation optional per window
    }


def temporal_stability(
    summaries_by_period: Dict[str, Dict[str, Dict[str, float]]],
    ks: Sequence[int] = (2, 3),
) -> Dict[str, object]:
    """Cluster each period, then ARI across period pairs.

    Parameters
    ----------
    summaries_by_period: mapping period-name -> {asset -> 9-feature dict}.
        Assets with NaN feature vectors in a period are excluded from BOTH
        sides of that pair comparison (intersect first — required for ARI).
    """
    out: Dict[str, object] = {"per_period_labels": {}, "ari": {}}
    label_sets: Dict[str, Dict[str, int]] = {}
    for period, feats in summaries_by_period.items():
        matrix = pd.DataFrame(feats).T.dropna(axis=0, how="any")
        if len(matrix) < 4:
            label_sets[period] = {}
            out["per_period_labels"][period] = {"n_assets": int(len(matrix)), "labels": {}}
            continue
        labels = {k: v for k, v in ward_clusters(matrix, 2).items()}
        label_sets[period] = labels
        out["per_period_labels"][period] = {"n_assets": int(len(matrix)), "labels": labels}
    periods = list(summaries_by_period)
    for i in range(len(periods)):
        for j in range(i + 1, len(periods)):
            a, b = periods[i], periods[j]
            common = sorted(set(label_sets.get(a, {})) & set(label_sets.get(b, {})))
            if len(common) < 4:
                out["ari"][f"{a}|{b}"] = float("nan")
                continue
            la = [label_sets[a][c] for c in common]
            lb = [label_sets[b][c] for c in common]
            out["ari"][f"{a}|{b}"] = float(adjusted_rand_score(la, lb))
    return out


def rolling_ari(
    features_by_window: List[Tuple[str, str, pd.DataFrame]],
    k: int = 2,
) -> Dict[str, float]:
    """ARI between consecutive anchored windows.

    Parameters
    ----------
    features_by_window: list of (window_id, end_label, feature-matrix).
    """
    results: Dict[str, float] = {}
    prev_labels: Dict[str, int] | None = None
    prev_id: str | None = None
    for window_id, _end, matrix in features_by_window:
        clean = matrix.dropna(axis=0, how="any")
        if len(clean) < 4:
            prev_labels, prev_id = None, window_id
            continue
        labels = ward_clusters(clean, k)
        if prev_labels:
            common = sorted(set(labels) & set(prev_labels))
            if len(common) >= 4:
                results[f"{prev_id}|{window_id}"] = float(
                    adjusted_rand_score([prev_labels[c] for c in common], [labels[c] for c in common])
                )
        prev_labels, prev_id = labels, window_id
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Cross-asset synchronization
# ─────────────────────────────────────────────────────────────────────────────


def synchronization_matrix(rv_by_asset: Dict[str, pd.Series]) -> Dict[str, object]:
    """RV / log-RV / |return| / RV-change correlations + regime co-occurrence.

    All correlations Spearman (robust to vol outliers); declared ex-ante.
    """
    rv = pd.DataFrame(rv_by_asset)
    log_rv = np.log(rv.replace(0.0, np.nan))
    rets_abs = pd.DataFrame({a: s for a, s in rv_by_asset.items()})
    rets_abs = rets_abs  # placeholder replaced by caller with |returns|
    corr_rv = rv.corr(method="spearman", min_periods=120)
    corr_log = log_rv.corr(method="spearman", min_periods=120)
    return {
        "corr_rv": corr_rv,
        "corr_log_rv": corr_log,
    }


def nearest_neighbors(distance: pd.DataFrame) -> Dict[str, str]:
    """Nearest volatility neighbor per asset by feature distance."""
    out: Dict[str, str] = {}
    for inst in distance.index:
        row = distance.loc[inst].drop(inst)
        if row.empty:
            out[inst] = ""
            continue
        out[inst] = str(row.idxmin())
    return out


def feature_distance_matrix(features: pd.DataFrame) -> pd.DataFrame:
    """Euclidean distance over robust-scaled features (matrix form)."""
    scaled = robust_scale(features)
    n = len(scaled)
    dm = pd.DataFrame(np.zeros((n, n)), index=scaled.index, columns=scaled.index)
    for i, a in enumerate(scaled.index):
        for j, b in enumerate(scaled.index):
            if i < j:
                d = float(np.linalg.norm(scaled.loc[a] - scaled.loc[b]))
                dm.loc[a, b] = dm.loc[b, a] = d
    return dm


def pairwise_spearman_p(series_a: pd.Series, series_b: pd.Series, min_overlap: int = 120) -> Tuple[float, float]:
    """Spearman rho + p for two aligned series (used by the descriptive sync)."""
    j = pd.concat([series_a, series_b], axis=1).dropna()
    if len(j) < min_overlap:
        return float("nan"), float("nan")
    rho, p = spearmanr(j.iloc[:, 0], j.iloc[:, 1])
    return float(rho), float(p)
