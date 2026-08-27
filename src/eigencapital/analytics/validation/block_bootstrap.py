"""Block Bootstrap — appropriate for serially dependent financial data.

IID bootstrap is inappropriate when returns exhibit autocorrelation.
Block bootstrap preserves local temporal structure.

Usage:
    result = block_bootstrap(
        returns=returns,
        block_size=21,
        n_bootstrap=1000,
    )
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class BlockBootstrapResult:
    """Results of block bootstrap analysis.

    Attributes:
        n_bootstrap: Number of bootstrap samples
        block_size: Block size used
        sharpe_mean: Mean Sharpe across bootstrap samples
        sharpe_std: Std of Sharpe
        sharpe_ci_lower: Lower confidence bound
        sharpe_ci_upper: Upper confidence bound
        confidence_level: Confidence level
        method: Bootstrap method used
        seed: Random seed
    """

    n_bootstrap: int = 0
    block_size: int = 1
    sharpe_mean: float = 0.0
    sharpe_std: float = 0.0
    sharpe_ci_lower: float = 0.0
    sharpe_ci_upper: float = 0.0
    confidence_level: float = 0.95
    method: str = "block"
    seed: int = 42

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_bootstrap": self.n_bootstrap,
            "block_size": self.block_size,
            "sharpe_mean": round(self.sharpe_mean, 4),
            "sharpe_std": round(self.sharpe_std, 4),
            "sharpe_ci_lower": round(self.sharpe_ci_lower, 4),
            "sharpe_ci_upper": round(self.sharpe_ci_upper, 4),
            "confidence_level": self.confidence_level,
            "method": self.method,
            "seed": self.seed,
        }


def _compute_sharpe(returns: List[float]) -> float:
    """Compute annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std < 1e-15:
        if abs(mean) < 1e-15:
            return 0.0
        return math.copysign(100.0, mean)
    return (mean * 252) / (std * math.sqrt(252))


def _extract_blocks(returns: List[float], block_size: int) -> List[List[float]]:
    """Extract non-overlapping blocks from returns."""
    blocks = []
    for i in range(0, len(returns) - block_size + 1, block_size):
        blocks.append(returns[i : i + block_size])
    # Handle remaining data
    remaining = len(returns) % block_size
    if remaining > 0:
        blocks.append(returns[-remaining:])
    return blocks


def block_bootstrap(
    returns: List[float],
    block_size: int = 21,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> BlockBootstrapResult:
    """Perform block bootstrap analysis.

    Preserves local temporal structure by resampling blocks of consecutive
    observations rather than individual observations.

    Args:
        returns: List of period returns
        block_size: Number of consecutive observations per block
        n_bootstrap: Number of bootstrap samples
        confidence_level: Confidence level for CI
        seed: Random seed

    Returns:
        BlockBootstrapResult with confidence intervals
    """
    if len(returns) < block_size * 2:
        return BlockBootstrapResult(n_bootstrap=0, block_size=block_size, seed=seed)

    rng = random.Random(seed)
    blocks = _extract_blocks(returns, block_size)
    n_blocks = len(blocks)
    target_length = len(returns)

    bootstrap_sharpes = []

    for _ in range(n_bootstrap):
        # Sample blocks with replacement
        sample_blocks = [blocks[rng.randint(0, n_blocks - 1)] for _ in range(n_blocks)]

        # Flatten and trim to original length
        sample = []
        for block in sample_blocks:
            sample.extend(block)
        sample = sample[:target_length]

        if len(sample) >= 2:
            bootstrap_sharpes.append(_compute_sharpe(sample))

    if not bootstrap_sharpes:
        return BlockBootstrapResult(n_bootstrap=0, block_size=block_size, seed=seed)

    bootstrap_sharpes.sort()
    n = len(bootstrap_sharpes)

    alpha = 1 - confidence_level
    lower_idx = max(0, int(alpha / 2 * n))
    upper_idx = min(n - 1, int((1 - alpha / 2) * n) - 1)

    mean_s = sum(bootstrap_sharpes) / n
    var_s = sum((s - mean_s) ** 2 for s in bootstrap_sharpes) / n

    return BlockBootstrapResult(
        n_bootstrap=n_bootstrap,
        block_size=block_size,
        sharpe_mean=mean_s,
        sharpe_std=math.sqrt(var_s),
        sharpe_ci_lower=bootstrap_sharpes[lower_idx],
        sharpe_ci_upper=bootstrap_sharpes[upper_idx],
        confidence_level=confidence_level,
        method="block",
        seed=seed,
    )
