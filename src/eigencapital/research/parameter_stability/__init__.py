"""EigenCapital research package: parameter stability / robustness studies.

R3 (docs/research/R3_PARAMETER_STABILITY.md): preregistered robustness-study
machinery around the frozen R4 configuration. Output semantics are
INSIDE / OUTSIDE / INCONCLUSIVE — never parameter recommendations.
"""

from eigencapital.research.parameter_stability.grid import (
    FRAGILE_MAX_DRAWDOWN,
    FRAGILE_SHARPE_MAX,
    MIN_AXES_FLAGGED_F1,
    STABLE_FRACTION_F1,
    GridAxis,
    GridError,
    GridPoint,
    PointError,
    PointMetrics,
    StabilityVerdict,
    axis_association_tests,
    build_grid,
    classify_point,
    stability_verdict,
    stable_region_metrics,
    von_neumann_neighbors,
)

__all__ = [
    "FRAGILE_MAX_DRAWDOWN",
    "FRAGILE_SHARPE_MAX",
    "MIN_AXES_FLAGGED_F1",
    "STABLE_FRACTION_F1",
    "GridAxis",
    "GridError",
    "GridPoint",
    "PointError",
    "PointMetrics",
    "StabilityVerdict",
    "axis_association_tests",
    "build_grid",
    "classify_point",
    "stable_region_metrics",
    "stability_verdict",
    "von_neumann_neighbors",
]
