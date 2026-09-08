"""Shadow Portfolio Construction (R4-S) — correlation/exposure-aware selection experiment.

SHADOW-ONLY. This package is research and observation infrastructure.

GOVERNANCE INVARIANT (extends live/portfolio_analytics.py Phase 2 invariant):
    This package may observe R4 candidates, calculate alternative portfolio
    constructions, persist shadow evidence, and generate research records.
    It may NOT modify R4 signal generation, selection, sizing, risk gates,
    order generation, execution, or any frozen configuration. It contains
    NO execution path: nothing in this package can submit an order.

The experiment: the frozen R4 loop takes the top `MAX_CONCURRENT` candidates
by |signal weight|. This package asks, for the SAME candidate universe:
"What portfolio would an exposure/correlation-aware constructor have chosen,
and how much of R4's expected edge would it retain at what portfolio risk?"
"""

from eigencapital.shadow.portfolio.correlation import (
    CorrelationModel,
    CorrelationModelConfig,
    CorrelationSnapshot,
)
from eigencapital.shadow.portfolio.exposure import ExposureModel, ExposureModelConfig
from eigencapital.shadow.portfolio.metrics import PortfolioMetrics, compute_portfolio_metrics
from eigencapital.shadow.portfolio.selector import (
    SHADOW_SELECTOR_VERSION,
    ShadowCandidate,
    ShadowDecision,
    ShadowSelector,
    ShadowSelectorConfig,
)
from eigencapital.shadow.portfolio.tracker import (
    PROTECTED_R4_EVIDENCE_FILES,
    ShadowDecisionRecorder,
    ShadowPositionTracker,
)

SELECTOR_PACKAGE_VERSION = "0.1.0"

__all__ = [
    "SELECTOR_PACKAGE_VERSION",
    "SHADOW_SELECTOR_VERSION",
    "CorrelationModel",
    "CorrelationModelConfig",
    "CorrelationSnapshot",
    "ExposureModel",
    "ExposureModelConfig",
    "PortfolioMetrics",
    "PROTECTED_R4_EVIDENCE_FILES",
    "ShadowCandidate",
    "ShadowDecision",
    "ShadowDecisionRecorder",
    "ShadowPositionTracker",
    "ShadowSelector",
    "ShadowSelectorConfig",
    "compute_portfolio_metrics",
]
