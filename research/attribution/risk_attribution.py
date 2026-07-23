"""Risk attribution — risk controls vs unrestricted baseline.

Measures the contribution of risk management systems (drawdown breaker,
circuit breakers, halt states, leverage budget, exposure caps) to
outcome preservation.

Unlike other layers, risk attribution is **event-based** — the value
is measured when a risk control intervention prevents or limits a loss.
Per-trade attribution is approximated as the difference between actual
outcome and an estimated unrestricted outcome.

Layer formula::

    risk_alpha_r = restricted_outcome - unrestricted_outcome_estimate

Where the unrestricted estimate depends on:
    - Was the trade sized down due to drawdown state?
    - Was the trade prevented by a circuit breaker?
    - Was the position capped by leverage budget?

Attribution status:

    APPLIED           — risk intervention was active and measurable
    NOT_TRIGGERED     — no risk intervention occurred for this trade
    NOT_AVAILABLE     — risk state not captured in provenance
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_RISK = "risk_baseline_v1"


def compute(
    realized_r: float,
    risk_intervention_active: bool = False,
    unrestricted_estimate_r: float | None = None,
) -> tuple[float | None, str]:
    """Compute risk attribution.

    Args:
        realized_r: Actual exit R-multiple.
        risk_intervention_active: Whether a risk control was active
            during this trade (drawdown state, cap, halt, etc.).
        unrestricted_estimate_r: Estimated outcome without risk controls.

    Returns (risk_alpha_r, status).
    """
    if not risk_intervention_active:
        return None, "NOT_TRIGGERED"

    if unrestricted_estimate_r is None:
        return None, "NOT_AVAILABLE"

    alpha = realized_r - unrestricted_estimate_r
    return alpha, "APPLIED"
