"""Drawdown controls — portfolio-level drawdown monitoring and circuit breaker.

Evaluates current drawdown from peak portfolio value against configured
threshold. When drawdown exceeds limit, reduces exposure across all assets
or halts trading entirely.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("quantforge.drawdown_controls")


def compute_drawdown(current_value: float, peak_value: float) -> float:
    """Compute current drawdown as a fraction (negative = loss).

    Returns
    -------
    float
        Drawdown ratio, e.g. -0.05 = 5% below peak.
        Returns 0.0 if peak is zero or current > peak (new high).
    """
    if peak_value <= 0:
        return 0.0
    if current_value >= peak_value:
        return 0.0
    return (current_value - peak_value) / peak_value


def compute_exposure_multiplier(
    drawdown: float,
    drawdown_limit: float = -0.15,
    soft_limit: float = -0.10,
) -> tuple[float, bool]:
    """Compute an exposure multiplier based on current drawdown.

    Parameters
    ----------
    drawdown : float
        Current drawdown as a fraction (negative).
    drawdown_limit : float
        Hard drawdown limit at which trading halts (default -15%).
    soft_limit : float
        Soft limit above which exposure is linearly reduced (default -10%).

    Returns
    -------
    tuple[float, bool]
        (exposure_multiplier, halted)
        - multiplier: 0.0 at or below hard limit, 1.0 at or above soft limit,
          linearly interpolated between soft and hard.
        - halted: True if hard limit breached.
    """
    if drawdown >= soft_limit:
        return 1.0, False

    if drawdown <= drawdown_limit:
        return 0.0, True

    # Linear interpolation between soft and hard limits
    t = (drawdown - soft_limit) / (drawdown_limit - soft_limit)
    multiplier = max(0.0, 1.0 - t)
    return multiplier, False


def check_drawdown_circuit_breaker(
    current_value: float,
    peak_value: float,
    drawdown_limit: float = -0.15,
    soft_limit: float = -0.10,
    halt_on_breach: bool = True,
) -> dict:
    """Portfolio-level drawdown check.

    Parameters
    ----------
    current_value : float
        Current total portfolio value.
    peak_value : float
        All-time high portfolio value.
    drawdown_limit : float
        Drawdown fraction that triggers halt.
    soft_limit : float
        Drawdown fraction above which exposure is reduced.
    halt_on_breach : bool
        If True, set halted=True when drawdown exceeds limit.

    Returns
    -------
    dict with keys:
        drawdown: float
        exposure_multiplier: float
        halted: bool
        breached: bool
    """
    dd = compute_drawdown(current_value, peak_value)
    multiplier, hard_halted = compute_exposure_multiplier(dd, drawdown_limit, soft_limit)
    halted = hard_halted and halt_on_breach

    if halted:
        logger.error(
            "DRAWDOWN CIRCUIT BREAKER: drawdown=%.2f%% exceeds limit=%.1f%% — halting",
            dd * 100,
            drawdown_limit * 100,
        )
    elif multiplier < 1.0:
        logger.info(
            "Drawdown=%.2f%%: reducing exposure to %.0f%%",
            dd * 100,
            multiplier * 100,
        )

    return {
        "drawdown": round(dd, 6),
        "exposure_multiplier": round(multiplier, 4),
        "halted": halted,
        "breached": dd <= drawdown_limit,
    }
