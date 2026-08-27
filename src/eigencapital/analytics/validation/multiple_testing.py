"""Multiple-Testing Correction — Bonferroni, Holm, Benjamini-Hochberg/FDR.

The system must explicitly recognize that the more strategies, parameters,
and hypotheses we test, the greater the probability of false discoveries.

Usage:
    result = multiple_testing_correction(
        p_values=[0.01, 0.04, 0.03, 0.10, 0.50],
        method="benjamini-hochberg",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class MultipleTestingResult:
    """Results of multiple-testing correction.

    Attributes:
        method: Correction method used
        raw_p_values: Original p-values
        adjusted_p_values: Corrected p-values
        rejected: Which hypotheses are rejected (at alpha=0.05)
        n_tests: Number of tests
        alpha: Significance level
        family_definition: Description of the testing family
    """

    method: str = ""
    raw_p_values: List[float] = field(default_factory=list)
    adjusted_p_values: List[float] = field(default_factory=list)
    rejected: List[bool] = field(default_factory=list)
    n_tests: int = 0
    alpha: float = 0.05
    family_definition: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "n_tests": self.n_tests,
            "alpha": self.alpha,
            "family_definition": self.family_definition,
            "raw_p_values": [round(p, 6) for p in self.raw_p_values],
            "adjusted_p_values": [round(p, 6) for p in self.adjusted_p_values],
            "rejected": self.rejected,
            "n_rejected": sum(self.rejected),
        }


def bonferroni(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Bonferroni correction.

    Adjusted p-value = min(raw_p * n_tests, 1.0)
    """
    n = len(p_values)
    return [min(p * n, 1.0) for p in p_values]


def holm(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Holm step-down correction (less conservative than Bonferroni).

    Sort p-values, then adjust sequentially.
    """
    n = len(p_values)
    if n == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * n

    for rank, (orig_idx, p) in enumerate(indexed):
        adj = p * (n - rank)
        adjusted[orig_idx] = min(adj, 1.0)

    # Step-down: ensure monotonicity
    sorted_adj = sorted(adjusted)
    for i in range(1, n):
        sorted_adj[i] = max(sorted_adj[i], sorted_adj[i - 1])

    # Map back
    result = [0.0] * n
    for i, (orig_idx, _) in enumerate(indexed):
        result[orig_idx] = sorted_adj[i]

    return result


def benjamini_hochberg(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Benjamini-Hochberg FDR correction.

    Controls false discovery rate rather than family-wise error rate.
    """
    n = len(p_values)
    if n == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * n

    for rank, (orig_idx, p) in enumerate(indexed):
        adj = p * n / (rank + 1)
        adjusted[orig_idx] = min(adj, 1.0)

    # Enforce monotonicity (step-down)
    sorted_adj = sorted(adjusted)
    for i in range(n - 2, -1, -1):
        sorted_adj[i] = min(sorted_adj[i], sorted_adj[i + 1])

    result = [0.0] * n
    for i, (orig_idx, _) in enumerate(indexed):
        result[orig_idx] = sorted_adj[i]

    return result


def multiple_testing_correction(
    p_values: List[float],
    method: str = "benjamini-hochberg",
    alpha: float = 0.05,
    family_definition: str = "",
) -> MultipleTestingResult:
    """Apply multiple-testing correction.

    Args:
        p_values: List of raw p-values
        method: Correction method ("bonferroni", "holm", "benjamini-hochberg")
        alpha: Significance level
        family_definition: Description of the testing family

    Returns:
        MultipleTestingResult with corrected p-values
    """
    if not p_values:
        return MultipleTestingResult(
            method=method,
            n_tests=0,
            alpha=alpha,
            family_definition=family_definition,
        )

    if method == "bonferroni":
        adjusted = bonferroni(p_values, alpha)
    elif method == "holm":
        adjusted = holm(p_values, alpha)
    elif method in ("benjamini-hochberg", "bh", "fdr"):
        adjusted = benjamini_hochberg(p_values, alpha)
    else:
        raise ValueError(f"Unknown correction method: {method}")

    rejected = [p <= alpha for p in adjusted]

    return MultipleTestingResult(
        method=method,
        raw_p_values=list(p_values),
        adjusted_p_values=adjusted,
        rejected=rejected,
        n_tests=len(p_values),
        alpha=alpha,
        family_definition=family_definition,
    )
