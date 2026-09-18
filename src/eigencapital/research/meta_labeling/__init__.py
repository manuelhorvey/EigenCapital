"""EigenCapital research package: meta-labeling research (R6).

Research-only. Baselines first; no ML in B1; the logistic stage (B2) is a
separate preregistered slot gated on B1. Nothing here touches R4 production.
"""

from eigencapital.research.meta_labeling.baseline import (
    BLOCK_LENGTH,
    BOOTSTRAP_N,
    BOOTSTRAP_SEED,
    B1Result,
    BaselineError,
    FilterSplit,
    OosWindowSlice,
    evaluate_b1,
    filter_split,
    paired_block_bootstrap_ci,
    rate_difference,
    summarize,
)

__all__ = [
    "BLOCK_LENGTH",
    "BOOTSTRAP_N",
    "BOOTSTRAP_SEED",
    "B1Result",
    "BaselineError",
    "FilterSplit",
    "OosWindowSlice",
    "evaluate_b1",
    "filter_split",
    "paired_block_bootstrap_ci",
    "rate_difference",
    "summarize",
]
