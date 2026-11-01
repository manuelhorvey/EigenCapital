"""Probability of Backtest Overfitting (PBO) via CSCV.

PBO measures how frequently the best in-sample configuration becomes mediocre
or poor out-of-sample. The estimator implemented here is Combinatorially
Symmetric Cross-Validation (CSCV; Bailey, Borwein, López de Prado & Zhu, 2014):

1. Split the performance history into an even number of contiguous blocks.
2. For every combination of half the blocks as in-sample (IS) and the
   complement as out-of-sample (OOS), rank the candidates on both sides.
3. Record whether the IS-best candidate falls below the OOS median.
4. PBO is the fraction of partitions in which that happens.

CSCV requires a performance *time series* per candidate. A single summary
in-sample/out-of-sample pair cannot be split and therefore cannot estimate
PBO; such input is reported as ``UNSUPPORTED_INPUT`` instead of manufacturing
a number.

Usage:
    result = compute_pbo(performance_matrix=returns_by_period)
    result = compute_pbo(candidate_results=[
        {"returns": [0.01, -0.02, ...]},
        {"returns": [0.00,  0.01, ...]},
    ])
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class PBOResult:
    """Results of Probability of Backtest Overfitting analysis.

    Attributes:
        pbo: Estimated probability of backtest overfitting
        n_candidates: Number of candidate configurations
        n_partitions: Number of CSCV partitions evaluated
        sufficient_experiments: Whether enough candidates/history exist
        overfit_count: Number of partitions where the IS-best candidate
            fell below the OOS median
        total_partitions: Total CSCV partitions evaluated
        message: Explanation of result
        method: Estimator identifier
        n_blocks: Number of contiguous blocks used by CSCV
    """

    pbo: float = 0.0
    n_candidates: int = 0
    n_partitions: int = 0
    sufficient_experiments: bool = False
    overfit_count: int = 0
    total_partitions: int = 0
    message: str = ""
    method: str = "CSCV"
    n_blocks: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pbo": round(self.pbo, 4),
            "n_candidates": self.n_candidates,
            "sufficient_experiments": self.sufficient_experiments,
            "overfit_count": self.overfit_count,
            "total_partitions": self.total_partitions,
            "method": self.method,
            "n_blocks": self.n_blocks,
            "message": self.message,
        }


def _coerce_matrix(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    """Validate a period x candidate performance matrix."""
    if matrix is None or len(matrix) == 0:
        raise ValueError("performance_matrix must contain at least one period")

    n_candidates = len(matrix[0])
    if n_candidates < 2:
        raise ValueError("performance_matrix must contain at least two candidates")

    rows: List[List[float]] = []
    for period, row in enumerate(matrix):
        if len(row) != n_candidates:
            raise ValueError(
                f"performance_matrix row {period} has {len(row)} values; "
                f"expected {n_candidates}"
            )
        values: List[float] = []
        for column, value in enumerate(row):
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"performance_matrix[{period}][{column}] is not numeric: {value!r}"
                ) from exc
            if not math.isfinite(number):
                raise ValueError(
                    f"performance_matrix[{period}][{column}] is not finite: {value!r}"
                )
            values.append(number)
        rows.append(values)
    return rows


def _block_bounds(n_periods: int, n_blocks: int) -> List[tuple[int, int]]:
    """Return contiguous, near-equal block boundaries."""
    base, remainder = divmod(n_periods, n_blocks)
    if base == 0:
        raise ValueError("n_blocks cannot exceed the number of periods")

    bounds: List[tuple[int, int]] = []
    start = 0
    for block in range(n_blocks):
        size = base + (1 if block < remainder else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def _statistic(values: Sequence[float], kind: str) -> float:
    """Compute the ranking statistic for one candidate over a set of periods."""
    n = len(values)
    if n == 0:
        return float("-inf")

    mean = sum(values) / n
    if kind == "mean":
        return mean
    if kind != "sharpe":
        raise ValueError(f"Unknown statistic: {kind}")

    if n < 2:
        return mean
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    if variance <= 0.0:
        # Undefined Sharpe; rank by location and keep the result finite.
        return mean * math.sqrt(n)
    return mean / math.sqrt(variance) * math.sqrt(n)


def _average_ranks(values: Sequence[float]) -> List[float]:
    """Ranks with ties averaged, ascending (rank 1 = worst, N = best)."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while (
            end + 1 < len(order)
            and values[order[end + 1]] == values[order[position]]
        ):
            end += 1
        average = ((position + 1) + (end + 1)) / 2.0
        for offset in range(position, end + 1):
            ranks[order[offset]] = average
        position = end + 1
    return ranks


def _partitions(n_blocks: int, max_partitions: int) -> List[tuple[int, ...]]:
    """Enumerate balanced CSCV splits, deterministically capped if needed."""
    if max_partitions < 1:
        raise ValueError("max_partitions must be at least 1")

    all_partitions = list(combinations(range(n_blocks), n_blocks // 2))
    if len(all_partitions) <= max_partitions:
        return all_partitions

    stride = len(all_partitions) / max_partitions
    return [
        all_partitions[min(int(index * stride), len(all_partitions) - 1)]
        for index in range(max_partitions)
    ]


def _matrix_from_candidates(
    candidate_results: List[Dict[str, Any]],
) -> Optional[List[List[float]]]:
    """Transpose per-candidate return series, or None if absent/ragged."""
    series = [candidate.get("returns") for candidate in candidate_results]
    if any(not isinstance(item, (list, tuple)) or len(item) == 0 for item in series):
        return None
    length = len(series[0])
    if any(len(item) != length for item in series):
        raise ValueError("candidate return series must all have the same length")
    return [[float(series[column][period]) for column in range(len(series))]
            for period in range(length)]


def compute_pbo(
    candidate_results: Optional[List[Dict[str, Any]]] = None,
    min_candidates: int = 10,
    n_partitions: int = 512,
    *,
    performance_matrix: Optional[Sequence[Sequence[float]]] = None,
    n_blocks: Optional[int] = None,
    statistic: str = "sharpe",
) -> PBOResult:
    """Compute Probability of Backtest Overfitting with CSCV.

    Args:
        candidate_results: Optional list of dicts. If every dict carries a
            ``returns`` series, those series are used. Summary-only
            ``in_sample_sharpe``/``out_of_sample_sharpe`` input is rejected as
            ``UNSUPPORTED_INPUT`` because it cannot support CSCV.
        min_candidates: Minimum candidates for a meaningful estimate.
        n_partitions: Maximum CSCV partitions to evaluate (deterministic cap).
        performance_matrix: Periods x candidates performance matrix. Takes
            precedence over ``candidate_results``.
        n_blocks: Even number of contiguous blocks. Defaults to the largest
            even number up to 10 that the history supports.
        statistic: ``"sharpe"`` (default) or ``"mean"`` ranking statistic.

    Returns:
        PBOResult, or an explicit insufficient/unsupported result.
    """
    matrix: Optional[Sequence[Sequence[float]]] = performance_matrix

    if matrix is None and candidate_results is not None:
        matrix = _matrix_from_candidates(candidate_results)

    if matrix is None:
        n_candidates = len(candidate_results or [])
        if n_candidates < min_candidates:
            return PBOResult(
                n_candidates=n_candidates,
                sufficient_experiments=False,
                method="CSCV",
                message=(
                    f"INSUFFICIENT_EXPERIMENTS: {n_candidates} candidates < "
                    f"{min_candidates} minimum. PBO requires enough independent "
                    f"configurations to estimate overfitting probability."
                ),
            )
        return PBOResult(
            n_candidates=n_candidates,
            sufficient_experiments=False,
            method="UNSUPPORTED_INPUT",
            message=(
                "UNSUPPORTED_INPUT: CSCV requires a performance time series per "
                "candidate. Summary in-sample/out-of-sample values are a single "
                "split and cannot estimate PBO; no value is reported."
            ),
        )

    rows = _coerce_matrix(matrix)
    n_periods = len(rows)
    n_candidates = len(rows[0])

    if n_candidates < min_candidates:
        return PBOResult(
            n_candidates=n_candidates,
            sufficient_experiments=False,
            method="CSCV",
            message=(
                f"INSUFFICIENT_EXPERIMENTS: {n_candidates} candidates < "
                f"{min_candidates} minimum. Add {min_candidates - n_candidates} "
                f"more independent configurations before computing PBO."
            ),
        )

    if n_blocks is None:
        n_blocks = min(10, n_periods if n_periods % 2 == 0 else n_periods - 1)

    if n_blocks < 2:
        raise ValueError("n_blocks must be at least 2")
    if n_blocks % 2 != 0:
        raise ValueError("n_blocks must be even")
    if n_blocks > n_periods:
        raise ValueError("n_blocks cannot exceed the number of periods")

    bounds = _block_bounds(n_periods, n_blocks)
    splits = _partitions(n_blocks, n_partitions)
    if not splits:
        raise ValueError("no CSCV partitions available")

    overfit_count = 0
    for in_sample_blocks in splits:
        in_sample_set = set(in_sample_blocks)
        in_sample_rows = [
            row
            for block, (start, end) in enumerate(bounds)
            if block in in_sample_set
            for row in rows[start:end]
        ]
        out_of_sample_rows = [
            row
            for block, (start, end) in enumerate(bounds)
            if block not in in_sample_set
            for row in rows[start:end]
        ]

        in_sample_scores = [
            _statistic([row[column] for row in in_sample_rows], statistic)
            for column in range(n_candidates)
        ]
        out_of_sample_scores = [
            _statistic([row[column] for row in out_of_sample_rows], statistic)
            for column in range(n_candidates)
        ]

        best_is = max(range(n_candidates), key=lambda column: in_sample_scores[column])
        oos_rank = _average_ranks(out_of_sample_scores)[best_is]
        omega = oos_rank / (n_candidates + 1)
        logit = math.log(omega / (1.0 - omega))

        if logit <= 0.0:
            overfit_count += 1

    total = len(splits)
    pbo = overfit_count / total

    if pbo > 0.5:
        risk = "High overfitting risk."
    elif pbo > 0.3:
        risk = "Moderate overfitting risk."
    else:
        risk = "Low overfitting risk."

    return PBOResult(
        pbo=pbo,
        n_candidates=n_candidates,
        n_partitions=total,
        sufficient_experiments=True,
        overfit_count=overfit_count,
        total_partitions=total,
        message=(
            f"PBO = {pbo:.2f} ({overfit_count}/{total} partitions, CSCV, "
            f"{n_blocks} blocks). {risk}"
        ),
        method="CSCV",
        n_blocks=n_blocks,
    )
