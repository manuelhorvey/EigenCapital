"""Parameter Stability Grid — R3 Phase B1 robustness-study machinery.

R3 Phase B1 (docs/research/R3_PARAMETER_STABILITY.md): preregistered grid
machinery for the robustness study around the frozen R4 configuration.

Contract (frozen in the ledger BEFORE any code — see
R3_PARAMETER_STABILITY.md, "Frozen R3 research contract"):

1. This is a robustness study, NOT a parameter search. Output semantics are
   "frozen config INSIDE / OUTSIDE a historically stable region" /
   "inconclusive" — never "optimal parameters".
2. The grid is preregistered: axes, ranges, steps fixed in the ledger.
3. Bounded perturbations only (narrow ranges around the frozen values).
4. The frozen configuration is the grid CENTER, never a point under test.
5. Every grid point runs the full pipeline; identical data across points.
6. Per-point metric list is fixed; no post-hoc additions.
11. Region classification is preregistered: FRAGILE thresholds, von-Neumann
    adjacency, connected component of non-FRAGILE points containing the
    center, STABLE fraction. Operational thresholds were frozen in the
    ledger's "Operational definitions" section before grid execution:
    FRAGILE iff max_drawdown >= 0.40 OR sharpe <= 0.0.

This module is PURE and domain-agnostic: it knows nothing about R4, data
files, or the exporter. `evaluate.py` supplies per-point results; this
module classifies, aggregates, and applies the preregistered falsification
criteria. Deterministic everywhere — no RNG, no resampling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Sequence, Tuple, cast

from eigencapital.analytics.validation.multiple_testing import multiple_testing_correction
from eigencapital.analytics.validation.walk_forward import WalkForwardResult

# ── Preregistered operational thresholds (ledger, "Operational definitions") ──

FRAGILE_MAX_DRAWDOWN = 0.40
FRAGILE_SHARPE_MAX = 0.0
STABLE_FRACTION_F1 = 0.60
MIN_AXES_FLAGGED_F1 = 2

# Preregistered WF geometry (ledger, experiment table)
WF_TRAIN_BARS = 750
WF_TEST_BARS = 250
WF_PURGE_BARS = 10
WF_EMBARGO_BARS = 5


class GridError(ValueError):
    """Raised for preregistration violations and malformed grids."""


# ── Axes and points ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GridAxis:
    """One preregistered perturbation axis.

    Attributes:
        name: Axis name (must match the exporter's parameter key).
        values: Preregistered values, ascending, finite.
    """

    name: str
    values: Tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise GridError(f"axis {self.name!r}: no values")
        if any(not math.isfinite(v) for v in self.values):
            raise GridError(f"axis {self.name!r}: non-finite values")
        if list(self.values) != sorted(set(self.values)):
            raise GridError(f"axis {self.name!r}: values must be ascending and unique")


@dataclass(frozen=True)
class GridPoint:
    """One grid coordinate: parameter name → value, plus its axis index."""

    params: Dict[str, float]
    indices: Tuple[int, ...] = ()

    def key(self) -> Tuple[Tuple[str, float], ...]:
        """Hashable identity of the parameter combination."""
        return tuple(sorted(self.params.items()))


def build_grid(
    axes: Sequence[GridAxis],
    center: Dict[str, float],
) -> List[GridPoint]:
    """Enumerate the full-factorial preregistered grid.

    Args:
        axes: The preregistered axes.
        center: The frozen configuration. Every center value MUST appear in
            its axis (contract item 4: the frozen config is inside the grid —
            otherwise "is the frozen config inside a stable region?" is
            unanswerable).

    Returns:
        Grid points in lexicographic axis-index order (deterministic).

    Raises:
        GridError: if a center value is missing from its axis.
    """
    for axis in axes:
        if axis.name not in center:
            raise GridError(f"axis {axis.name!r}: center value missing")
        if center[axis.name] not in axis.values:
            raise GridError(
                f"axis {axis.name!r}: frozen center value {center[axis.name]} "
                f"not in preregistered values {list(axis.values)} — the frozen "
                f"configuration must be a grid point"
            )
    points = []
    for combo in product(*(range(len(a.values)) for a in axes)):
        params = {a.name: a.values[i] for a, i in zip(axes, combo)}
        points.append(GridPoint(params=params, indices=combo))
    return points


# ── Adjacency, classification, component ─────────────────────────────────────


def von_neumann_neighbors(a: GridPoint, b: GridPoint) -> bool:
    """True iff a and b differ by one step on exactly one axis."""
    if len(a.indices) != len(b.indices) or not a.indices:
        return False
    diffs = sum(1 for x, y in zip(a.indices, b.indices) if x != y)
    if diffs != 1:
        return False
    i = next(k for k, (x, y) in enumerate(zip(a.indices, b.indices)) if x != y)
    return abs(a.indices[i] - b.indices[i]) == 1


def classify_point(metrics: PointMetrics) -> str:
    """Preregistered classification (ledger thresholds, frozen pre-execution)."""
    if metrics.max_drawdown >= FRAGILE_MAX_DRAWDOWN or metrics.sharpe <= FRAGILE_SHARPE_MAX:
        return "FRAGILE"
    return "NON_FRAGILE"


def stable_region_metrics(
    grid: Sequence[GridPoint],
    classifications: Dict[Tuple[Tuple[str, float], ...], str],
    center: Dict[str, float],
) -> Dict[str, object]:
    """Component, adjacency, and STABLE fraction per the preregistered rules.

    Component: all points reachable from the center through pairwise-adjacent
    non-FRAGILE points. STABLE: non-FRAGILE and not adjacent to any FRAGILE
    point; TRANSITIONAL: non-FRAGILE and adjacent to ≥ 1 FRAGILE point.
    """
    by_indices: Dict[Tuple[int, ...], GridPoint] = {p.indices: p for p in grid}
    if not grid:
        raise GridError("empty grid")
    axes = _axes_of(grid)
    center_idx = tuple(_index_of_value(a, center[a.name]) for a in axes)
    if center_idx not in by_indices:
        raise GridError("center not present in grid — preregistration violation")
    center_key = _key_of(by_indices[center_idx])

    if classifications.get(center_key) == "FRAGILE":
        return {
            "center_classification": "FRAGILE",
            "component_size": 0,
            "stable_fraction": 0.0,
            "center_all_neighbors_fragile": _all_neighbors_fragile(by_indices[center_idx], by_indices, classifications),
        }

    # BFS through pairwise-adjacent non-FRAGILE points from the center.
    component: set[Tuple[int, ...]] = {center_idx}
    frontier = [center_idx]
    while frontier:
        cur = frontier.pop()
        for idx, point in by_indices.items():
            if idx in component:
                continue
            if classifications[_key_of(point)] != "FRAGILE" and von_neumann_neighbors(by_indices[cur], point):
                component.add(idx)
                frontier.append(idx)

    # STABLE vs TRANSITIONAL within the component.
    stable = 0
    for idx in component:
        adjacent_fragile = any(
            j not in component
            and classifications[_key_of(p)] == "FRAGILE"
            and von_neumann_neighbors(by_indices[idx], p)
            for j, p in by_indices.items()
        )
        if not adjacent_fragile:
            stable += 1

    return {
        "center_classification": "NON_FRAGILE",
        "component_size": len(component),
        "stable_fraction": stable / len(component) if component else 0.0,
        "stable_count": stable,
        "center_all_neighbors_fragile": _all_neighbors_fragile(by_indices[center_idx], by_indices, classifications),
    }


def _index_of_value(axis: GridAxis, value: float) -> int:
    """Index of `value` in the axis, or GridError — never a bare StopIteration
    (PEP 479 turns that into an opaque RuntimeError at the call boundary)."""
    for i, v in enumerate(axis.values):
        if v == value:
            return i
    raise GridError(
        f"center value {value!r} not on preregistered axis {axis.name!r} {axis.values} — preregistration violation"
    )


def _axes_of(grid: Sequence[GridPoint]) -> List[GridAxis]:
    """Reconstruct axes (name + value list) from the grid's own variation."""
    names: List[str] = list(grid[0].params.keys())
    per_axis: Dict[str, set[float]] = {n: set() for n in names}
    for p in grid:
        for n, v in p.params.items():
            per_axis[n].add(v)
    return [GridAxis(name=n, values=tuple(sorted(per_axis[n]))) for n in names]


def _key_of(point: GridPoint) -> Tuple[Tuple[str, float], ...]:
    return point.key()


def _all_neighbors_fragile(
    center: GridPoint,
    by_indices: Dict[Tuple[int, ...], GridPoint],
    classifications: Dict[Tuple[Tuple[str, float], ...], str],
) -> bool:
    neighbors = [p for p in by_indices.values() if von_neumann_neighbors(center, p)]
    return bool(neighbors) and all(classifications[_key_of(p)] == "FRAGILE" for p in neighbors)


# ── Per-point record ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PointMetrics:
    """Preregistered per-point metric list (contract item 6)."""

    params: Dict[str, float]
    cagr: float
    ann_vol: float
    max_drawdown: float
    sharpe: float
    total_pnl: float
    trade_count: int
    turnover: float
    hit_rate: float
    payoff_ratio: float
    # WF aggregate (preregistered geometry) — zeros when windows cannot fit
    wf_total_windows: int = 0
    wf_mean_oos_sharpe: float = 0.0
    wf_pct_profitable_windows: float = 0.0
    wf_oos_return_mean: float = 0.0
    wf_oos_return_std: float = 0.0
    wf_note: str = ""  # reason when geometry cannot fit


@dataclass(frozen=True)
class PointError:
    """Explicit error record for a failed grid point (never a silent drop)."""

    params: Dict[str, float]
    exception: str


# ── Axis-level association tests (pre-execution addendum) ────────────────────


def _normal_two_sided_p(z: float) -> float:
    """Two-sided p from a standard-normal statistic via math.erf."""
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    return max(0.0, min(1.0, p))


def axis_association_tests(
    grid: Sequence[GridPoint],
    metrics_by_key: Dict[Tuple[Tuple[str, float], ...], PointMetrics],
) -> List[Dict[str, object]]:
    """Preregistered axis-level association: Spearman(axis coordinate, Sharpe).

    Computed across ALL grid points (marginal association). The returned
    per-axis records include the raw two-sided p; the Holm correction over
    the family is applied by `stability_verdict`.
    """
    records: List[Dict[str, object]] = []
    names = list(grid[0].params.keys())
    n = len(grid)
    for name in names:
        coords = [p.params[name] for p in grid]
        sharpes = [metrics_by_key[p.key()].sharpe for p in grid]
        rho = _spearman(coords, sharpes)
        if abs(rho) >= 1.0 or n < 3:
            p = 0.0 if abs(rho) >= 1.0 else 1.0
            t = math.copysign(math.inf, rho) if abs(rho) >= 1.0 else 0.0
        else:
            t = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
            p = _normal_two_sided_p(t)
        records.append(
            {
                "axis": name,
                "spearman_rho": rho,
                "t_stat": t,
                "raw_p": p,
                "n_points": n,
            }
        )
    return records


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation (average ranks for ties)."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0

    def _avg_ranks(vals: Sequence[float]) -> List[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _avg_ranks(list(xs)), _avg_ranks(list(ys))
    mean_rx = sum(rx) / len(rx)
    mean_ry = sum(ry) / len(ry)
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    denom = math.sqrt(var_x * var_y)
    if denom <= 1e-15:
        return 0.0
    return max(-1.0, min(1.0, cov / denom))


# ── Verdict (preregistered falsification criteria F1/F2) ─────────────────────


@dataclass(frozen=True)
class StabilityVerdict:
    """Outcome of the preregistered falsification criteria.

    Output semantics (contract item 1): INSIDE / OUTSIDE / INCONCLUSIVE —
    never "optimal parameters", never a recommendation.
    """

    outcome: str  # "INSIDE_STABLE_REGION" | "OUTSIDE_STABLE_REGION" | "INCONCLUSIVE"
    stable_fraction: float
    component_size: int
    axes_flagged: List[str]
    region_statement: str  # exact ledger-mandated sentence
    center_classification: str
    center_all_neighbors_fragile: bool
    holm_adjusted_p: Dict[str, float] = field(default_factory=dict)


def stability_verdict(
    region: Dict[str, object],
    axis_records: Sequence[Dict[str, object]],
) -> StabilityVerdict:
    """Apply preregistered F1/F2 exactly as frozen in the ledger.

    F1: OUTSIDE when center's component STABLE fraction < 0.60 AND ≥ 2 axes
    flagged by the Holm family.
    F2: when the center is FRAGILE — report exactly that; if all immediate
    neighbours are FRAGILE, that fact is carried in the statement.
    """
    adjusted = multiple_testing_correction(
        p_values=[float(cast(float, r["raw_p"])) for r in axis_records],
        method="holm",
        alpha=0.05,
        family_definition="R3-B1 axis-level Spearman association (5 axes, one family)",
    )
    axis_names = [str(r["axis"]) for r in axis_records]
    holm_by_axis = dict(zip(axis_names, (float(p) for p in adjusted.adjusted_p_values)))
    flagged = [n for n, p in holm_by_axis.items() if p <= 0.05]

    center_class = str(region.get("center_classification", "FRAGILE"))
    fraction = float(cast(float, region.get("stable_fraction", 0.0)))
    comp_size = int(cast(int, region.get("component_size", 0)))
    neighbors_fragile = bool(region.get("center_all_neighbors_fragile", False))

    if center_class == "FRAGILE":
        statement = "the frozen configuration itself classifies as FRAGILE on this data (preregistered thresholds)"
        if neighbors_fragile:
            statement += "; all its immediate grid neighbours are also FRAGILE"
        statement += " — no recommendation is made"
        return StabilityVerdict(
            outcome="OUTSIDE_STABLE_REGION",
            stable_fraction=0.0,
            component_size=0,
            axes_flagged=flagged,
            region_statement=statement,
            center_classification="FRAGILE",
            center_all_neighbors_fragile=neighbors_fragile,
            holm_adjusted_p=holm_by_axis,
        )

    if fraction < STABLE_FRACTION_F1 and len(flagged) >= MIN_AXES_FLAGGED_F1:
        return StabilityVerdict(
            outcome="OUTSIDE_STABLE_REGION",
            stable_fraction=fraction,
            component_size=comp_size,
            axes_flagged=flagged,
            region_statement=("the frozen configuration does not sit inside a historically stable region on this data"),
            center_classification=center_class,
            center_all_neighbors_fragile=neighbors_fragile,
            holm_adjusted_p=holm_by_axis,
        )

    if comp_size == 0:
        return StabilityVerdict(
            outcome="INCONCLUSIVE",
            stable_fraction=0.0,
            component_size=0,
            axes_flagged=flagged,
            region_statement="insufficient component evidence — inconclusive",
            center_classification=center_class,
            center_all_neighbors_fragile=neighbors_fragile,
            holm_adjusted_p=holm_by_axis,
        )

    return StabilityVerdict(
        outcome="INSIDE_STABLE_REGION",
        stable_fraction=fraction,
        component_size=comp_size,
        axes_flagged=flagged,
        region_statement=(
            "the frozen configuration lies inside a historically stable region on this data (preregistered thresholds)"
        ),
        center_classification=center_class,
        center_all_neighbors_fragile=neighbors_fragile,
        holm_adjusted_p=holm_by_axis,
    )


__all__ = [
    "GridAxis",
    "GridError",
    "GridPoint",
    "PointError",
    "PointMetrics",
    "StabilityVerdict",
    "WF_EMBARGO_BARS",
    "WF_PURGE_BARS",
    "WF_TEST_BARS",
    "WF_TRAIN_BARS",
    "WalkForwardResult",
    "axis_association_tests",
    "build_grid",
    "classify_point",
    "stable_region_metrics",
    "stability_verdict",
    "von_neumann_neighbors",
]
