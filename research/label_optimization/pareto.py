"""Pareto frontier analysis for label optimization experiments."""

from __future__ import annotations

from typing import Any

import numpy as np


def pareto_frontier(points: list[tuple[float, ...]], maximize: list[bool]) -> list[int]:
    """Find Pareto-optimal points.

    Args:
        points: List of n-dimensional tuples.
        maximize: True if dimension should be maximized, False if minimized.

    Returns:
        Indices of Pareto-optimal points.
    """
    n = len(points)
    if n == 0:
        return []
    is_dominated = np.zeros(n, dtype=bool)
    dirs = np.array([1 if m else -1 for m in maximize], dtype=float)
    arr = np.array(points) * dirs  # Transform: maximize=higher_better, minimize=higher_better_after_negation
    for i in range(n):
        for j in range(n):
            if i == j or is_dominated[i]:
                continue
            if all(arr[j] >= arr[i]) and any(arr[j] > arr[i]):
                is_dominated[i] = True
                break
    return [i for i in range(n) if not is_dominated[i]]


def compute_pareto_rankings(experiments: list[dict[str, Any]],
                             objectives: dict[str, str]) -> list[dict[str, Any]]:
    """Rank experiments within each asset group by Pareto optimality.

    Args:
        experiments: List of experiment result dicts (from get_experiment_results).
        objectives: Mapping of metric_key -> direction ('maximize' or 'minimize').

    Returns:
        Experiments augmented with 'pareto_rank', 'pareto_front', 'composite_score'.
    """
    from collections import defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for exp in experiments:
        grouped[exp["asset"]].append(exp)

    ranked = []
    for asset, group in grouped.items():
        metric_keys = list(objectives.keys())
        maximize = [objectives[k] == "maximize" for k in metric_keys]

        valid = []
        valid_indices = []
        for i, exp in enumerate(group):
            vals = []
            ok = True
            for k in metric_keys:
                v = exp.get(k)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    ok = False
                    break
                vals.append(float(v))
            if ok:
                valid.append(tuple(vals))
                valid_indices.append(i)

        if not valid:
            continue

        pareto_idx = pareto_frontier(valid, maximize)
        pareto_set = set(pareto_idx)

        # Compute composite score (simple rank-sum normalization)
        scores = np.array(valid)
        for j, m in enumerate(maximize):
            col = scores[:, j]
            if m:
                col = (col - col.min()) / max(col.max() - col.min(), 1e-10)
            else:
                col = (col.max() - col) / max(col.max() - col.min(), 1e-10)
            scores[:, j] = col
        composite = scores.mean(axis=1)

        for local_i in range(len(group)):
            if local_i in pareto_set and len(pareto_idx) > 0:
                rank = 1
            else:
                rank = 2
            exp = group[local_i]
            exp["pareto_rank"] = rank
            exp["pareto_front"] = local_i in pareto_set
            exp["composite_score"] = round(float(composite[valid_indices.index(local_i)]), 4) if local_i in valid_indices else 0.0
            ranked.append(exp)

    return ranked
