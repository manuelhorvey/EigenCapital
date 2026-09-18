"""Factor Laboratory — R2 research package.

R2-B1 (docs/research/R2_FACTOR_LAB.md): the observation/panel assembly layer
and the preregistered single-factor evaluation against the frozen 12-point
contract. The lab CONSUMES signals (it never constructs them); all diagnostics
(IC, quantiles, turnover) come from the verified
``eigencapital.analytics.validation.factor_evaluation`` infrastructure.

Contract highlights (frozen before implementation):
- forward-return alignment: close(t) → close(t+h), computed only from bars
  closing at or before the horizon boundary; factor(t) → return(t+1..t+h),
  never factor(t) → return(t)
- PIT invariant: availability_timestamp <= decision_timestamp everywhere
- missing data: exclusion per period, counted, never imputed
- one preregistered trial slot per experiment; Holm correction; no-silent-pass
  verdicts (missing evidence → INCONCLUSIVE)

Scope guard (frozen review §14): research-only; never touches R4 production.
"""

from eigencapital.research.factor_lab.evaluation import (
    EvaluationError,
    FactorEvaluation,
    evaluate_factor,
)
from eigencapital.research.factor_lab.observations import (
    FactorObservation,
    PanelBuildError,
    build_factor_panels,
)

__all__ = [
    "FactorObservation",
    "PanelBuildError",
    "build_factor_panels",
    "FactorEvaluation",
    "EvaluationError",
    "evaluate_factor",
]
