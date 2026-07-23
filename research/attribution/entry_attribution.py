"""Entry attribution — model signal correctness before lifecycle management.

Measures the directionally-correct component of the entry signal before
any lifecycle management (breakeven, trailing, profit floor) intervenes.

Layer formula::

    entry_alpha_r = price_movement_to_first_intervention

    Where first_intervention is the earlier of:
    - breakeven activation
    - profit floor trigger
    - trailing activation
    - barrier expiry

This isolates the ML model's contribution from the lifecycle engine's.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_ENTRY = "entry_baseline_v1"


def compute(
    realized_r: float,
    entry_price: float,
    first_intervention_price: float | None = None,
    side: str = "",
    risk: float = 1.0,
) -> tuple[float | None, str]:
    """Compute entry attribution.

    Args:
        realized_r: Final realized R-multiple.
        entry_price: Trade entry price.
        first_intervention_price: Price at first lifecycle intervention
            (breakeven, trail activation, profit floor trigger).
            If None, entry alpha is not available.
        side: "long" or "short".
        risk: Risk per trade in price units.

    Returns (entry_alpha_r, status).
    """
    if first_intervention_price is None or risk <= 0:
        return None, "NOT_AVAILABLE"

    mult = 1.0 if side == "long" else -1.0
    movement_r = mult * (first_intervention_price - entry_price) / risk

    entry_alpha = min(movement_r, realized_r) if movement_r > 0 else movement_r

    return entry_alpha, "APPLIED"
