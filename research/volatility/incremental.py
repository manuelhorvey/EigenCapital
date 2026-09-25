"""Candidate insertion and leave-one-out structural diagnostics.

Answers (brief §42/§43):
  - Does an asset occupy a unique region of volatility-feature space?
  - Does removing an asset materially change the taxonomy?

Classifications use the mandated vocabulary only. Nothing here ranks
assets for trading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from research.volatility import clustering as CL


def loo_report(features: pd.DataFrame) -> dict:
    """Remove each asset, recluster with the frozen rule, measure change."""
    base = CL.cluster_features(features)
    out: dict = {"base_k": int(base.k), "base_silhouette": base.silhouette, "assets": {}}
    aris = []
    sil_deltas = []
    for asset in features.index:
        sub = features.drop(index=asset)
        res = CL.cluster_features(sub)
        common = base.labels.index.intersection(res.labels.index)
        ari = (
            float(adjusted_rand_score(base.labels.loc[common], res.labels.loc[common]))
            if len(common) >= 3
            else float("nan")
        )
        k_change = int(res.k != base.k)
        sil_delta = float(res.silhouette - base.silhouette)
        out["assets"][asset] = {
            "ari_vs_base": ari,
            "k_after_removal": int(res.k),
            "k_changed": bool(k_change),
            "silhouette_delta": sil_delta,
        }
        if np.isfinite(ari):
            aris.append(ari)
        sil_deltas.append(sil_delta)
    out["ari_min"] = float(np.min(aris)) if aris else float("nan")
    out["ari_mean"] = float(np.mean(aris)) if aris else float("nan")
    out["max_abs_sil_delta"] = float(np.max(np.abs(sil_deltas))) if sil_deltas else float("nan")
    # Structural-importance flag: removal drops ARI below 0.8 or flips k.
    important = [
        a
        for a, v in out["assets"].items()
        if (np.isfinite(v["ari_vs_base"]) and v["ari_vs_base"] < 0.8) or v["k_changed"]
    ]
    out["structurally_influential"] = sorted(important)
    return out


def candidate_report(
    baseline_features: pd.DataFrame,
    candidate: str,
    candidate_features: pd.DataFrame,
) -> dict:
    """Insert one candidate into the baseline feature matrix and diagnose."""
    if candidate not in candidate_features.index:
        raise KeyError(candidate)
    merged = pd.concat([baseline_features, candidate_features.loc[[candidate]]])

    base = CL.cluster_features(baseline_features)
    with_c = CL.cluster_features(merged)

    # Nearest baseline neighbors of the candidate (standardized space).
    z = CL.standardize(merged)
    # Re-standardize jointly for fair distances (documented choice).
    diff = z.loc[candidate].to_numpy() - z.drop(index=candidate).to_numpy()
    d = np.sqrt((diff**2).sum(axis=1))
    order = np.argsort(d)
    neighbors = [(str(baseline_features.index[i]), float(d[i])) for i in order[:3]]

    # Distance to each baseline cluster centroid (computed in joint space
    # using baseline labels from the baseline-only clustering).
    centroid_d: dict[str, float] = {}
    for cid, grp in base.labels.groupby(base.labels):
        centroid = z.loc[grp.index].mean(axis=0)
        centroid_d[str(int(cid))] = float(np.sqrt(((z.loc[candidate] - centroid) ** 2).sum()))

    # Cluster assignment change among baseline assets.
    common = base.labels.index
    ari = float(adjusted_rand_score(base.labels.loc[common], with_c.labels.loc[common]))
    cand_cluster = int(with_c.labels.loc[candidate])
    cluster_members = sorted(with_c.labels[with_c.labels == cand_cluster].index)
    singleton = len(cluster_members) == 1

    # PCA-space change (fit jointly on merged, project baseline distance shift).
    pcs, evr = CL.pca_transform(merged)
    base_pcs = pcs.drop(index=candidate)
    cand_pc = pcs.loc[candidate]
    pc_dist = {pc: float(np.sqrt(((base_pcs[pc] - cand_pc[pc]) ** 2).min())) for pc in pcs.columns}
    min_pc_dist = float(min(pc_dist.values())) if pc_dist else float("nan")

    k_changed = int(with_c.k != base.k)
    sil_delta = float(with_c.silhouette - base.silhouette)

    # Mandated classification (deterministic rule, documented):
    # STRUCTURALLY DISTINCT if it changes k OR lands in a singleton OR its
    # nearest-baseline distance exceeds the baseline max pairwise distance
    # scaled... simpler: nearest-neighbor distance > 75th pct of baseline
    # pairwise distances AND (k_changed or ari < 0.95).
    z_base = CL.standardize(baseline_features)
    bd = CL._distance(z_base, "euclidean")
    iu = np.triu_indices(len(z_base), k=1)
    thr = float(np.percentile(bd[iu], 75)) if len(iu[0]) else float("nan")
    nn_dist = neighbors[0][1] if neighbors else float("nan")
    out_of_envelope = bool(np.isfinite(nn_dist) and np.isfinite(thr) and nn_dist > thr)

    if singleton or (k_changed and out_of_envelope):
        classification = "STRUCTURALLY DISTINCT"
    elif not k_changed and ari >= 0.95 and not out_of_envelope:
        classification = "STRUCTURALLY REDUNDANT"
    elif not k_changed and ari >= 0.8:
        classification = "STRUCTURALLY REDUNDANT"
    else:
        classification = "INCONCLUSIVE"

    return {
        "candidate": candidate,
        "base_k": int(base.k),
        "k_with_candidate": int(with_c.k),
        "k_changed": bool(k_changed),
        "ari_baseline_labels": ari,
        "silhouette_delta": sil_delta,
        "nearest_neighbors": neighbors,
        "assigned_cluster": cand_cluster,
        "cluster_members": cluster_members,
        "singleton_cluster": bool(singleton),
        "distance_to_baseline_centroids": centroid_d,
        "min_distance_to_baseline_pcs": min_pc_dist,
        "pca_variance_ratio": [float(x) for x in evr],
        "out_of_baseline_distance_envelope": out_of_envelope,
        "nn_distance_vs_baseline_p75": {"nn": nn_dist, "p75": thr},
        "classification": classification,
    }
