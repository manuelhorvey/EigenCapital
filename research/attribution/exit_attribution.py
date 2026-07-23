"""Exit attribution — adaptive lifecycle vs static TP/SL baseline.

Uses the existing ``counterfactual_fixed_tp_r`` from the attribution
collector's ExitAttribution when available.

Layer formula::

    exit_alpha_r = realized_r - static_exit_r

    static_exit_r = counterfactual_fixed_tp_r  (from collector)
                    | entry risk * static RR   (fallback)

Attribution status:

    APPLIED       — static_exit_r available, contribution computed
    NOT_AVAILABLE — no static baseline to compare against
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COUNTERFACTUAL_VERSION_EXIT = "exit_baseline_v1"


def compute(
    realized_r: float,
    static_exit_r: float | None,
    collector_record: dict[str, Any] | None = None,
) -> tuple[float | None, str, float | None]:
    """Compute exit attribution.

    Returns (exit_alpha_r, status, static_exit_r).
    """
    sr = static_exit_r

    # Fallback: read from collector if not provided directly
    if sr is None and collector_record is not None:
        try:
            sr = collector_record.get("exit_info", {}).get("counterfactual_fixed_tp_r", None)
            if sr is not None:
                sr = float(sr)
        except (TypeError, ValueError, KeyError):
            sr = None

    if sr is None or not isinstance(sr, (int, float)):
        return None, "NOT_AVAILABLE", None

    alpha = realized_r - sr
    return alpha, "APPLIED", sr
