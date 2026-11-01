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

import math
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


def _validate_p_values(p_values: List[float]) -> List[float]:
    """Return p-values as floats, rejecting values outside [0, 1].

    A correction applied to a non-probability is meaningless and could hide a
    defective test. Fail closed instead of silently correcting a bad input.
    """
    values: List[float] = []
    for index, p in enumerate(p_values):
        try:
            value = float(p)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"p_values[{index}] is not numeric: {p!r}") from exc
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(f"p_values[{index}]={p!r} is outside [0, 1]")
        values.append(value)
    return values


def bonferroni(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Bonferroni correction.

    Adjusted p-value = min(raw_p * n_tests, 1.0)
    """
    values = _validate_p_values(p_values)
    n = len(values)
    return [min(p * n, 1.0) for p in values]


def holm(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Holm step-down correction (less conservative than Bonferroni).

    For raw p-values ordered ``p_(1) <= ... <= p_(n)``, the adjusted value is

        adj_(k) = max_{j <= k} min(1, (n - j + 1) * p_(j))

    The cumulative maximum is taken in rank order, before mapping back to the
    caller's ordering. Holm rejects ``p_(k)`` when ``adj_(k) <= alpha``.
    """
    values = _validate_p_values(p_values)
    n = len(values)
    if n == 0:
        return []

    order = sorted(range(n), key=lambda i: values[i])
    result = [0.0] * n
    running_max = 0.0

    for rank, index in enumerate(order):
        adjusted = min(1.0, values[index] * (n - rank))
        running_max = max(running_max, adjusted)
        result[index] = running_max

    return result


def benjamini_hochberg(p_values: List[float], alpha: float = 0.05) -> List[float]:
    """Benjamini-Hochberg FDR correction.

    For raw p-values ordered ``p_(1) <= ... <= p_(n)``, the adjusted value is

        adj_(k) = min_{j >= k} min(1, n * p_(j) / j)

    The cumulative minimum is taken from the largest p-value downwards, in rank
    order, before mapping back to the caller's ordering.
    """
    values = _validate_p_values(p_values)
    n = len(values)
    if n == 0:
        return []

    order = sorted(range(n), key=lambda i: values[i])
    result = [0.0] * n
    running_min = 1.0

    for rank in range(n - 1, -1, -1):
        index = order[rank]
        adjusted = min(1.0, values[index] * n / (rank + 1))
        running_min = min(running_min, adjusted)
        result[index] = running_min

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
