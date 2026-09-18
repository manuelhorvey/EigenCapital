"""EigenCapital research package: mean-reversion / stat-arb family (R4-MR).

Research-only. The frozen R4 production strategy is untouched by everything
in this package (see docs/research/R4_MEAN_REVERSION.md).
"""

from eigencapital.research.mean_reversion.estimation import (
    EstimationError,
    adf_pvalue,
    coint_pvalue,
    half_life,
    hedge_ratio,
    rolling_zscore,
    spread_from,
)
from eigencapital.research.mean_reversion.pipeline import (
    COST_ONE_WAY_PER_LEG,
    COST_PER_ROUND_TRIP,
    ESTIMATION_STEP,
    ESTIMATION_WINDOW,
    HL_MAX_DAYS,
    HL_MIN_DAYS,
    Z_ENTRY,
    Z_EXIT,
    Z_WINDOW,
    GateState,
    PairResult,
    PipelineError,
    run_pair,
)

__all__ = [
    "EstimationError",
    "PipelineError",
    "GateState",
    "PairResult",
    "adf_pvalue",
    "coint_pvalue",
    "half_life",
    "hedge_ratio",
    "rolling_zscore",
    "spread_from",
    "run_pair",
    "ESTIMATION_WINDOW",
    "ESTIMATION_STEP",
    "ADF_MAX_P",
    "COINT_MAX_P",
    "HL_MIN_DAYS",
    "HL_MAX_DAYS",
    "Z_WINDOW",
    "Z_ENTRY",
    "Z_EXIT",
    "COST_ONE_WAY_PER_LEG",
    "COST_PER_ROUND_TRIP",
]
