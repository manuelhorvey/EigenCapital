"""Profit floor attribution — protected vs unprotected exit comparison.

Uses the lifecycle telemetry records to compare the actual exit R against
the counterfactual unprotected R (the original barrier/TP exit without profit
floor intervention).

Layer formula::

    profit_floor_alpha_r = protected_exit_r - unprotected_exit_r

    protected_exit_r   = realized_r (floor enforced)
    unprotected_exit_r = actual_r from trade (what would have happened
                         without the floor — the trader's original exit)

Attribution status:

    APPLIED           — trade entered PROFIT_PROTECTED and floor prevented
                        additional erosion
    NOT_TRIGGERED     — trade never reached profit floor activation threshold
    NOT_AVAILABLE     — profit floor was disabled for this trade
"""

from __future__ import annotations

import logging

from paper_trading.lifecycle.telemetry import compute_snapshot

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_PROFIT_FLOOR = "profit_floor_baseline_v1"


def compute(
    realized_r: float,
    was_protected: bool,
    unprotected_exit_r: float | None = None,
) -> tuple[float | None, str, float | None]:
    """Compute profit floor attribution.

    Args:
        realized_r: Actual exit R-multiple (with profit floor if active).
        was_protected: Whether this trade entered PROFIT_PROTECTED state.
        unprotected_exit_r: What the exit R would have been without the floor.
            If None, uses realized_r as baseline (no floor impact).

    Returns (profit_floor_alpha_r, status, no_profit_floor_r).
    """
    if not was_protected:
        return None, "NOT_TRIGGERED", None

    # If we don't have the counterfactual unprotected R, we can attribute
    # the difference between the floor and what would have been worse
    if unprotected_exit_r is None or unprotected_exit_r >= realized_r:
        return None, "NOT_AVAILABLE", None

    alpha = realized_r - unprotected_exit_r
    return alpha, "APPLIED", unprotected_exit_r
