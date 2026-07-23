"""Calibration attribution — calibrated vs raw probability decision.

Uses the existing CounterfactualEngine to re-run the decision with the
uncalibrated probability, then compares the outcome.

Layer formula::

    calibration_alpha_r = calibrated_outcome_r - uncalibrated_outcome_r

This answers: did calibration improve trade selection enough to justify
the probability distortion it introduces?

Attribution status:

    APPLIED           — provenance has calibration data + counterfactual
    NOT_AVAILABLE     — no calibration applied or provenance missing
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_CALIBRATION = "calibration_baseline_v1"


def compute(
    realized_r: float,
    calibrated: bool,
    uncalibrated_signal_r: float | None = None,
) -> tuple[float | None, str, float | None]:
    """Compute calibration attribution.

    Args:
        realized_r: Actual exit R-multiple (with calibration if active).
        calibrated: Whether calibration was applied to this trade.
        uncalibrated_signal_r: What the outcome would have been without
            calibration. If None, not available.

    Returns (calibration_alpha_r, status, uncalibrated_signal_r).
    """
    if not calibrated:
        return None, "NOT_TRIGGERED", None

    if uncalibrated_signal_r is None:
        return None, "NOT_AVAILABLE", None

    alpha = realized_r - uncalibrated_signal_r
    return alpha, "APPLIED", uncalibrated_signal_r
