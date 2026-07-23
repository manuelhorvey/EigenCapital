"""Portfolio attribution — position sizing vs equal risk baseline.

Measures the contribution of position sizing, allocation, and exposure
decisions relative to an equal-risk baseline.

Layer formula::

    portfolio_alpha_r = sized_outcome_r - equal_risk_outcome_r

This component is event-based: attribution is computed per-trade but
the counterfactual adjusts the position size in the context of the
portfolio at entry time.

Attribution status:

    APPLIED           — sizing data available and differs from baseline
    NOT_TRIGGERED     — sizing matched equal risk baseline
    NOT_AVAILABLE     — no portfolio context available
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_PORTFOLIO = "portfolio_baseline_v1"


def compute(
    realized_r: float,
    actual_allocation_pct: float | None = None,
    baseline_allocation_pct: float = 1.0,
) -> tuple[float | None, str]:
    """Compute portfolio attribution.

    Args:
        realized_r: Actual exit R-multiple.
        actual_allocation_pct: Actual allocation weight for this trade.
        baseline_allocation_pct: Equal-risk baseline allocation weight.

    Returns (portfolio_alpha_r, status).
    """
    if actual_allocation_pct is None:
        return None, "NOT_AVAILABLE"

    if abs(actual_allocation_pct - baseline_allocation_pct) < 0.01:
        return None, "NOT_TRIGGERED"

    alpha = realized_r * (actual_allocation_pct / baseline_allocation_pct - 1.0)
    return alpha, "APPLIED"
