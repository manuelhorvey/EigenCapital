"""Cost Model — re-exported from core (A4).

The canonical implementation now lives in ``eigencapital.core.costs`` because
production backtest code imports it and the ``research`` package is not part of
the installed distribution. This module exists so existing research imports and
tests keep working unchanged.

Usage:
    from eigencapital.research.costs.model import MODERATE_COST, CostModel
"""

from __future__ import annotations

from eigencapital.core.costs import MODERATE_COST, STRESS_COST, ZERO_COST, CostModel

__all__ = ["CostModel", "ZERO_COST", "MODERATE_COST", "STRESS_COST"]
