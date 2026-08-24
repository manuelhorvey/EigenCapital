"""Bootstrap and Permutation Tests — statistical significance under null.

Bootstrap: Resample trades to estimate confidence intervals.
Permutation: Shuffle returns to test whether performance is random.

These tests attack the hypothesis from a different angle:
"Could these results have occurred by chance?"

Usage:
    bootstrap = bootstrap_test(
        returns=returns,
        n_bootstrap=1000,
        confidence_level=0.95,
    )

    permutation = permutation_test(
        returns=returns,
        n_permutations=1000,
    )
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass(frozen=True)
class BootstrapResult:
    """Results of bootstrap analysis.

    Attributes:
        n_bootstrap: Number of bootstrap samples
        sharpe_mean: Mean Sharpe across bootstrap samples
        sharpe_std: Std of Sharpe across bootstrap samples
        sharpe_ci_lower: Lower bound of confidence interval
        sharpe_ci_upper: Upper bound of confidence interval
        return_mean: Mean return across bootstrap samples
        return_std: Std of return across bootstrap samples
        return_ci_lower: Lower bound of return CI
        return_ci_upper: Upper bound of return CI
        pct_positive_sharpe: % of bootstrap samples with positive Sharpe
        confidence_level: Confidence level used
    """
    n_bootstrap: int = 0
    sharpe_mean: float = 0.0
    sharpe_std: float = 0.0
    sharpe_ci_lower: float = 0.0
    sharpe_ci_upper: float = 0.0
    return_mean: float = 0.0
    return_std: float = 0.0
    return_ci_lower: float = 0.0
    return_ci_upper: float = 0.0
    pct_positive_sharpe: float = 0.0
    confidence_level: float = 0.95

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "n_bootstrap": self.n_bootstrap,
            "sharpe_mean": round(self.sharpe_mean, 4),
            "sharpe_std": round(self.sharpe_std, 4),
            "sharpe_ci_lower": round(self.sharpe_ci_lower, 4),
            "sharpe_ci_upper": round(self.sharpe_ci_upper, 4),
            "return_mean": round(self.return_mean, 6),
            "return_std": round(self.return_std, 6),
            "return_ci_lower": round(self.return_ci_lower, 6),
            "return_ci_upper": round(self.return_ci_upper, 6),
            "pct_positive_sharpe": round(self.pct_positive_sharpe, 2),
            "confidence_level": self.confidence_level,
        }


@dataclass(frozen=True)
class PermutationResult:
    """Results of permutation test.

    Attributes:
        n_permutations: Number of permutations
        observed_sharpe: Actual Sharpe from original data
        p_value: Probability of observing this Sharpe under null
        permutation_sharpes: Distribution of shuffled Sharpes
        significant_at_5pct: Is result significant at 5%?
        significant_at_1pct: Is result significant at 1%?
    """
    n_permutations: int = 0
    observed_sharpe: float = 0.0
    p_value: float = 1.0
    permutation_sharpes: List[float] = field(default_factory=list)
    significant_at_5pct: bool = False
    significant_at_1pct: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "n_permutations": self.n_permutations,
            "observed_sharpe": round(self.observed_sharpe, 4),
            "p_value": round(self.p_value, 4),
            "significant_at_5pct": self.significant_at_5pct,
            "significant_at_1pct": self.significant_at_1pct,
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


def _compute_total_return(returns: List[float]) -> float:
    """Compute total cumulative return."""
    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r)
    return cumulative - 1.0


def bootstrap_test(
    returns: List[float],
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    sample_size: Optional[int] = None,
    seed: int = 42,
) -> BootstrapResult:
    """Perform bootstrap analysis on returns.

    Resamples with replacement to estimate confidence intervals.

    Args:
        returns: List of period returns
        n_bootstrap: Number of bootstrap samples
        confidence_level: Confidence level for CI (e.g., 0.95)
        sample_size: Size of each bootstrap sample (default: same as returns)
        seed: Random seed for reproducibility

    Returns:
        BootstrapResult with confidence intervals and statistics
    """
    if len(returns) < 2:
        return BootstrapResult(n_bootstrap=0)

    rng = random.Random(seed)
    sample_size = sample_size or len(returns)

    bootstrap_sharpes = []
    bootstrap_returns = []

    for _ in range(n_bootstrap):
        # Resample with replacement
        sample = [returns[rng.randint(0, len(returns) - 1)] for _ in range(sample_size)]
        bootstrap_sharpes.append(_compute_sharpe(sample))
        bootstrap_returns.append(_compute_total_return(sample))

    # Sort for percentile computation
    bootstrap_sharpes.sort()
    bootstrap_returns.sort()

    # Compute confidence intervals
    alpha = 1 - confidence_level
    lower_idx = int(alpha / 2 * n_bootstrap)
    upper_idx = int((1 - alpha / 2) * n_bootstrap) - 1
    lower_idx = max(0, lower_idx)
    upper_idx = min(n_bootstrap - 1, upper_idx)

    # Means and stds
    sharpe_mean = sum(bootstrap_sharpes) / n_bootstrap
    sharpe_var = sum((s - sharpe_mean) ** 2 for s in bootstrap_sharpes) / n_bootstrap
    sharpe_std = math.sqrt(sharpe_var)

    return_mean = sum(bootstrap_returns) / n_bootstrap
    return_var = sum((r - return_mean) ** 2 for r in bootstrap_returns) / n_bootstrap
    return_std = math.sqrt(return_var)

    pct_positive = sum(1 for s in bootstrap_sharpes if s > 0) / n_bootstrap * 100

    return BootstrapResult(
        n_bootstrap=n_bootstrap,
        sharpe_mean=sharpe_mean,
        sharpe_std=sharpe_std,
        sharpe_ci_lower=bootstrap_sharpes[lower_idx],
        sharpe_ci_upper=bootstrap_sharpes[upper_idx],
        return_mean=return_mean,
        return_std=return_std,
        return_ci_lower=bootstrap_returns[lower_idx],
        return_ci_upper=bootstrap_returns[upper_idx],
        pct_positive_sharpe=pct_positive,
        confidence_level=confidence_level,
    )


def permutation_test(
    returns: List[float],
    n_permutations: int = 1000,
    seed: int = 42,
) -> PermutationResult:
    """Perform sign-flip permutation test on returns.

    Under the null hypothesis (no edge), each return has equal probability
    of being positive or negative. We test whether the observed Sharpe is
    unusually high compared to randomly flipping the sign of each return.

    Args:
        returns: List of period returns
        n_permutations: Number of sign-flip permutations
        seed: Random seed for reproducibility

    Returns:
        PermutationResult with p-value and significance
    """
    if len(returns) < 2:
        return PermutationResult(n_permutations=0)

    rng = random.Random(seed)
    observed_sharpe = _compute_sharpe(returns)

    shuffled_sharpes = []
    for _ in range(n_permutations):
        # Sign-flip: randomly flip the sign of each return
        flipped = [r * (1 if rng.random() < 0.5 else -1) for r in returns]
        shuffled_sharpes.append(_compute_sharpe(flipped))

    # Compute p-value: fraction of shuffled Sharpes >= observed
    count_ge = sum(1 for s in shuffled_sharpes if s >= observed_sharpe)
    p_value = count_ge / n_permutations

    return PermutationResult(
        n_permutations=n_permutations,
        observed_sharpe=observed_sharpe,
        p_value=p_value,
        permutation_sharpes=sorted(shuffled_sharpes),
        significant_at_5pct=p_value < 0.05,
        significant_at_1pct=p_value < 0.01,
    )
