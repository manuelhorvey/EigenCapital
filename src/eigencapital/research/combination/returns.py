"""Return stream extraction and dependence analysis.

Creates canonical return streams for eligible alpha candidates and
analyzes their dependence structure for portfolio combination research.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple


@dataclass(frozen=True)
class ReturnStream:
    """Canonical return stream for an alpha candidate.

    Attributes:
        stream_id: Unique identifier
        candidate_id: Link to AlphaCandidate
        returns: List of period returns
        timestamps: List of period-end timestamps
        period: Return period (e.g., "daily", "monthly")
        net_of_costs: Whether returns include transaction costs
        provenance_hash: Deterministic hash of the return stream
    """

    stream_id: str
    candidate_id: str
    returns: Tuple[float, ...]
    timestamps: Tuple[str, ...]
    period: str = "daily"
    net_of_costs: bool = True
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        if len(self.returns) != len(self.timestamps):
            raise ValueError(
                f"returns ({len(self.returns)}) and timestamps "
                f"({len(self.timestamps)}) must have same length"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "candidate_id": self.candidate_id,
            "returns": list(self.returns),
            "timestamps": list(self.timestamps),
            "period": self.period,
            "net_of_costs": self.net_of_costs,
            "provenance_hash": self.provenance_hash,
        }

    @property
    def length(self) -> int:
        return len(self.returns)

    @property
    def mean_return(self) -> float:
        if not self.returns:
            return 0.0
        return sum(self.returns) / len(self.returns)

    @property
    def volatility(self) -> float:
        if len(self.returns) < 2:
            return 0.0
        mean = self.mean_return
        variance = sum((r - mean) ** 2 for r in self.returns) / (len(self.returns) - 1)
        return math.sqrt(variance)

    @property
    def sharpe(self) -> float:
        vol = self.volatility
        if vol < 1e-15:
            return 0.0
        return self.mean_return / vol

    @property
    def cumulative_return(self) -> float:
        if not self.returns:
            return 0.0
        cum = 1.0
        for r in self.returns:
            cum *= 1.0 + r
        return cum - 1.0


@dataclass(frozen=True)
class DependenceMatrix:
    """Pairwise dependence matrix between return streams.

    Attributes:
        stream_ids: List of stream IDs in matrix order
        pearson: Pearson correlation matrix (flat)
        spearman: Spearman correlation matrix (flat)
        downside: Downside correlation matrix (flat)
        rolling_correlations: Rolling correlation summaries
    """

    stream_ids: Tuple[str, ...]
    pearson: Tuple[Tuple[float, ...], ...]
    spearman: Tuple[Tuple[float, ...], ...]
    downside: Tuple[Tuple[float, ...], ...]
    rolling_correlations: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_ids": list(self.stream_ids),
            "pearson": [list(row) for row in self.pearson],
            "spearman": [list(row) for row in self.spearman],
            "downside": [list(row) for row in self.downside],
            "rolling_correlations": self.rolling_correlations,
        }

    def get_correlation(self, id1: str, id2: str, method: str = "pearson") -> float:
        """Get correlation between two streams."""
        if method == "pearson":
            matrix = self.pearson
        elif method == "spearman":
            matrix = self.spearman
        elif method == "downside":
            matrix = self.downside
        else:
            raise ValueError(f"Unknown method: {method}")

        i = self.stream_ids.index(id1)
        j = self.stream_ids.index(id2)
        return matrix[i][j]


def compute_pearson_correlation(x: List[float], y: List[float]) -> float:
    """Compute Pearson correlation coefficient."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0

    mean_x = sum(x[:n]) / n
    mean_y = sum(y[:n]) / n

    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x[:n]) / (n - 1))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y[:n]) / (n - 1))

    if std_x < 1e-15 or std_y < 1e-15:
        return 0.0

    return cov / (std_x * std_y)


def compute_spearman_correlation(x: List[float], y: List[float]) -> float:
    """Compute Spearman rank correlation coefficient."""

    def _rank(values: List[float]) -> List[float]:
        sorted_vals = sorted(enumerate(values), key=lambda t: t[1])
        ranks = [0.0] * len(values)
        for rank, (idx, _) in enumerate(sorted_vals, 1):
            ranks[idx] = float(rank)
        return ranks

    n = min(len(x), len(y))
    if n < 2:
        return 0.0

    return compute_pearson_correlation(_rank(x[:n]), _rank(y[:n]))


def compute_downside_correlation(
    x: List[float], y: List[float], threshold: float = 0.0
) -> float:
    """Compute correlation only during downside periods."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0

    # Filter to periods where either stream is below threshold
    x_down = []
    y_down = []
    for i in range(n):
        if x[i] < threshold or y[i] < threshold:
            x_down.append(x[i])
            y_down.append(y[i])

    if len(x_down) < 2:
        return 0.0

    return compute_pearson_correlation(x_down, y_down)


def build_dependence_matrix(
    streams: List[ReturnStream],
    window: int = 63,
) -> DependenceMatrix:
    """Build full dependence matrix between return streams."""
    n = len(streams)
    if n == 0:
        return DependenceMatrix(
            stream_ids=(),
            pearson=(),
            spearman=(),
            downside=(),
        )

    ids = tuple(s.stream_id for s in streams)
    pearson = [[0.0] * n for _ in range(n)]
    spearman = [[0.0] * n for _ in range(n)]
    downside = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                pearson[i][j] = 1.0
                spearman[i][j] = 1.0
                downside[i][j] = 1.0
            else:
                ri = list(streams[i].returns)
                rj = list(streams[j].returns)
                pearson[i][j] = compute_pearson_correlation(ri, rj)
                spearman[i][j] = compute_spearman_correlation(ri, rj)
                downside[i][j] = compute_downside_correlation(ri, rj)

    # Rolling correlation summary (average absolute rolling correlation)
    rolling_summary: Dict[str, float] = {}
    if n >= 2 and streams[0].length >= window:
        for i in range(n):
            for j in range(i + 1, n):
                ri = list(streams[i].returns)
                rj = list(streams[j].returns)
                rolling_corrs = []
                for start in range(0, len(ri) - window + 1, window // 2):
                    end = start + window
                    rc = compute_pearson_correlation(ri[start:end], rj[start:end])
                    rolling_corrs.append(rc)
                if rolling_corrs:
                    key = f"{ids[i]}_{ids[j]}"
                    rolling_summary[key] = sum(rolling_corrs) / len(rolling_corrs)

    return DependenceMatrix(
        stream_ids=ids,
        pearson=tuple(tuple(row) for row in pearson),
        spearman=tuple(tuple(row) for row in spearman),
        downside=tuple(tuple(row) for row in downside),
        rolling_correlations=rolling_summary,
    )
