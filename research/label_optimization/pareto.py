"""Pareto frontier analysis for label optimization experiments."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def pareto_frontier(points: list[tuple[float, ...]], maximize: list[bool]) -> list[int]:
    n = len(points)
    if n == 0:
        return []
    is_dominated = np.zeros(n, dtype=bool)
    dirs = np.array([1 if m else -1 for m in maximize], dtype=float)
    arr = np.array(points) * dirs
    for i in range(n):
        for j in range(n):
            if i == j or is_dominated[i]:
                continue
            if all(arr[j] >= arr[i]) and any(arr[j] > arr[i]):
                is_dominated[i] = True
                break
    return [i for i in range(n) if not is_dominated[i]]


DEFAULT_OBJECTIVES = {
    "sharpe_mean": "maximize",
    "ece_mean": "minimize",
    "imbalance_ratio": "minimize",           # class balance
    "cal_inversion_rate_mean": "minimize",   # behavioral stability
}


def compute_pareto_rankings(
    experiments: list[dict[str, Any]],
    objectives: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if objectives is None:
        objectives = DEFAULT_OBJECTIVES

    # Resolve key names: try _mean/CI variants, fall back to plain
    def _resolve(exp: dict, key: str) -> float | None:
        for variant in [key, key.replace("_mean", ""), key.replace("_std", "")]:
            v = exp.get(variant)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return None

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
                v = _resolve(exp, k)
                if v is None or np.isnan(v):
                    ok = False
                    break
                vals.append(v)
            if ok:
                valid.append(tuple(vals))
                valid_indices.append(i)

        if not valid:
            continue

        pareto_idx = pareto_frontier(valid, maximize)
        pareto_set = set(pareto_idx)

        scores = np.array(valid)
        for j, m in enumerate(maximize):
            col = scores[:, j]
            rng = col.max() - col.min()
            if rng > 1e-10:
                if m:
                    scores[:, j] = (col - col.min()) / rng
                else:
                    scores[:, j] = (col.max() - col) / rng
            else:
                scores[:, j] = 0.5
        composite = scores.mean(axis=1)

        for local_i in range(len(group)):
            rank = 1 if local_i in pareto_set and len(pareto_idx) > 0 else 2
            exp = group[local_i]
            exp["pareto_rank"] = rank
            exp["pareto_front"] = local_i in pareto_set
            ci = valid_indices.index(local_i) if local_i in valid_indices else -1
            exp["composite_score"] = round(float(composite[ci]), 4) if ci >= 0 else 0.0
            ranked.append(exp)

    return ranked
