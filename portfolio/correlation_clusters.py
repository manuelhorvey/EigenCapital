import pandas as pd
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from typing import List, Dict, Optional, Tuple


def compute_correlation_matrix(returns: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    if method == "spearman":
        return returns.corr(method="spearman")
    return returns.corr(method="pearson")


def correlation_to_distance(corr: pd.DataFrame) -> pd.DataFrame:
    dist = np.sqrt(2 * (1 - corr.clip(-1, 1)))
    return pd.DataFrame(dist, index=corr.index, columns=corr.columns)


def cluster_assets(
    returns: pd.DataFrame,
    method: str = "ward",
    n_clusters: Optional[int] = None,
    threshold: Optional[float] = None,
) -> Dict[str, int]:
    corr = compute_correlation_matrix(returns)
    dist = correlation_to_distance(corr)
    condensed = squareform(dist.values, checks=False)
    linkage_matrix = linkage(condensed, method=method)
    if n_clusters is not None:
        labels = fcluster(linkage_matrix, n_clusters, criterion="maxclust")
    elif threshold is not None:
        labels = fcluster(linkage_matrix, threshold, criterion="distance")
    else:
        labels = fcluster(linkage_matrix, 0.5 * max(linkage_matrix[:, 2]), criterion="distance")
    return dict(zip(corr.index, labels))


def get_cluster_summary(returns: pd.DataFrame, cluster_labels: Dict[str, int]) -> pd.DataFrame:
    labels = pd.Series(cluster_labels)
    summary = []
    for cluster_id in sorted(labels.unique()):
        members = labels[labels == cluster_id].index.tolist()
        if len(members) < 2:
            continue
        cluster_returns = returns[members]
        intra_corr = cluster_returns.corr().values
        mean_intra_corr = (intra_corr.sum() - len(members)) / (len(members) * (len(members) - 1))
        summary.append({
            "cluster": cluster_id,
            "n_assets": len(members),
            "members": members,
            "mean_intra_correlation": mean_intra_corr,
        })
    return pd.DataFrame(summary)
