"""Probability of Backtest Overfitting (PBO) — research diagnostic.

PBO measures how frequently the best in-sample configuration becomes
poor out-of-sample. With insufficient experiment history, returns
INSUFFICIENT_EXPERIMENTS rather than manufacturing results.

Usage:
    result = compute_pbo(candidate_results=[
        {"in_sample_sharpe": 2.0, "out_of_sample_sharpe": 0.3},
        {"in_sample_sharpe": 1.5, "out_of_sample_sharpe": 1.2},
    ])
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass(frozen=True)
class PBOResult:
    """Results of Probability of Backtest Overfitting analysis.

    Attributes:
        pbo: Estimated probability of backtest overfitting
        n_candidates: Number of candidate configurations
        n_partitions: Number of train/test partitions used
        sufficient_experiments: Whether enough experiments exist
        overfit_count: Number of partitions where best IS became worst OOS
        total_partitions: Total partitions evaluated
        message: Explanation of result
    """
    pbo: float = 0.0
    n_candidates: int = 0
    n_partitions: int = 0
    sufficient_experiments: bool = False
    overfit_count: int = 0
    total_partitions: int = 0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pbo": round(self.pbo, 4),
            "n_candidates": self.n_candidates,
            "sufficient_experiments": self.sufficient_experiments,
            "overfit_count": self.overfit_count,
            "total_partitions": self.total_partitions,
            "message": self.message,
        }


def compute_pbo(
    candidate_results: List[Dict[str, float]],
    min_candidates: int = 10,
    n_partitions: int = 16,
) -> PBOResult:
    """Compute Probability of Backtest Overfitting.

    Args:
        candidate_results: List of dicts with 'in_sample_sharpe' and
                          'out_of_sample_sharpe' for each candidate configuration
        min_candidates: Minimum candidates needed for meaningful PBO
        n_partitions: Number of train/test partitions (2^n_partitions total combos)

    Returns:
        PBOResult with PBO estimate or INSUFFICIENT_EXPERIMENTS
    """
    n = len(candidate_results)

    if n < min_candidates:
        return PBOResult(
            n_candidates=n,
            sufficient_experiments=False,
            message=(
                f"INSUFFICIENT_EXPERIMENTS: {n} candidates < {min_candidates} minimum. "
                f"PBO requires enough independent configurations to meaningfully "
                f"estimate overfitting probability. "
                f"Add {min_candidates - n} more independent strategy experiments "
                f"before computing PBO."
            ),
        )

    # Simple PBO estimation using rank correlation
    # Sort by in-sample, check if OOS follows same ranking
    is_sharpes = [c["in_sample_sharpe"] for c in candidate_results]
    oos_sharpes = [c["out_of_sample_sharpe"] for c in candidate_results]

    # Count how often best IS is not best OOS
    overfit_count = 0
    total_partitions = min(n_partitions, max(1, n // 2))

    for _ in range(total_partitions):
        # Simple bootstrap partition: random subset for "training"
        indices = list(range(n))
        split = n // 2
        # Use first half as "in-sample", second as "out-of-sample" (simplified)
        train = indices[:split]
        test = indices[split:]

        # Rank by in-sample
        train_is = [(i, is_sharpes[i]) for i in train]
        train_is.sort(key=lambda x: x[1], reverse=True)

        best_is_idx = train_is[0][0]

        # Check if this is also the best in the test set
        test_oos = [(i, oos_sharpes[i]) for i in test]
        test_oos.sort(key=lambda x: x[1], reverse=True)

        if test_oos and best_is_idx not in [i for i, _ in test_oos[:max(1, len(test_oos) // 4)]]:
            overfit_count += 1

    pbo = overfit_count / total_partitions if total_partitions > 0 else 0.0

    return PBOResult(
        pbo=pbo,
        n_candidates=n,
        n_partitions=total_partitions,
        sufficient_experiments=True,
        overfit_count=overfit_count,
        total_partitions=total_partitions,
        message=(
            f"PBO = {pbo:.2f} ({overfit_count}/{total_partitions} partitions). "
            f"{'High overfitting risk.' if pbo > 0.5 else 'Moderate overfitting risk.' if pbo > 0.3 else 'Low overfitting risk.'}"
        ),
    )
