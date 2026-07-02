from __future__ import annotations

import logging

logger = logging.getLogger("eigencapital.drawdown_controls")


def compute_drawdown(current_value: float, peak_value: float) -> float:
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
    if drawdown >= soft_limit:
        return 1.0, False
    if drawdown <= drawdown_limit:
        return 0.0, True
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
