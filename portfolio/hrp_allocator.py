import pandas as pd
import numpy as np
from scipy.cluster.hierarchy import linkage
from typing import Dict, List, Optional, Tuple


def _get_quasi_diag(link: np.ndarray) -> List[int]:
    link = link.astype(int)
    n = link.shape[0] + 1
    items = [[i] for i in range(n)]
    for i in range(link.shape[0]):
        left = int(link[i, 0])
        right = int(link[i, 1])
        items.append(items[left] + items[right])
    return items[-1]


def _get_cluster_variance(cov: pd.DataFrame, cluster_indices: List[int]) -> float:
    cluster_cov = cov.iloc[cluster_indices, cluster_indices]
    w = np.ones(len(cluster_indices)) / len(cluster_indices)
    return w @ cluster_cov.values @ w


def _hrp_weights(cov: pd.DataFrame, link: np.ndarray) -> pd.Series:
    weights = pd.Series(1.0, index=cov.index)
    n = link.shape[0] + 1
    for i in range(link.shape[0]):
        left = int(link[i, 0])
        right = int(link[i, 1])
        left_items = [j for j in range(n) if j in _get_quasi_diag(link[:i+1])]
        right_items = [j for j in range(n) if j not in left_items]
        if not left_items or not right_items:
            continue
        var_left = _get_cluster_variance(cov, left_items)
        var_right = _get_cluster_variance(cov, right_items)
        alpha = 1 - var_left / (var_left + var_right)
        alpha = np.clip(alpha, 0.0, 1.0)
        for j in left_items:
            weights.iloc[j] *= alpha
        for j in right_items:
            weights.iloc[j] *= (1 - alpha)
    return weights / weights.sum()


def hrp_allocation(returns: pd.DataFrame, method: str = "single") -> Dict[str, float]:
    cov = returns.cov()
    corr = returns.corr()
    dist = np.sqrt(2 * (1 - corr.clip(-1, 1)))
    link = linkage(dist.values, method=method)
    w = _hrp_weights(cov, link)
    return dict(w)


def hrp_allocation_with_vol_target(
    returns: pd.DataFrame,
    target_vol: float = 0.15,
    method: str = "single",
) -> Dict[str, float]:
    w = hrp_allocation(returns, method=method)
    cov = returns.cov() * 252
    assets = list(w.keys())
    weights = np.array([w[a] for a in assets])
    portfolio_var = weights @ cov.values @ weights
    portfolio_vol = np.sqrt(portfolio_var) if portfolio_var > 0 else 1.0
    leverage = target_vol / portfolio_vol
    leverage = min(leverage, 1.0)
    scaled = {a: w[a] * leverage for a in assets}
    return scaled
