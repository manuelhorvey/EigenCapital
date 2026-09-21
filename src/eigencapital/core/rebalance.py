"""Core rebalance policy constants and types — shared by research and live.

Extracted from :mod:`eigencapital.live.rebalance_policy` so that research
code can import without crossing the research/live boundary (S6 security
boundary).  Only the minimal set required by
:mod:`~eigencapital.research.rebalance.replay` is exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass

CANONICAL_MIN_WEIGHT: float = 0.005


@dataclass(frozen=True)
class PolicyConfig:
    """Configuration for a rebalance policy type."""

    policy_type: str = "CANONICAL"
    threshold: float = 0.01
    max_daily_interventions: int | None = None
    max_weekly_interventions: int | None = None
    weekday: int | None = None
    hour: int | None = None


@dataclass(frozen=True)
class RebalanceEvents:
    """Event types emitted during rebalance intervention."""

    new_entry: bool = False
    full_exit: bool = False
    reversal: bool = False
    adjustment_out: bool = False
    adjustment_in: bool = False
    no_target: bool = False
