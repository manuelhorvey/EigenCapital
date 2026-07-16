from dataclasses import dataclass
from enum import Enum
from typing import Literal

from eigencapital.domain.entities.position import PositionIntent, PositionSide  # noqa: F401
from eigencapital.domain.entities.signal import SignalType, TradeDecision  # noqa: F401
from features.types import MarketStructureState  # noqa: F401  — canonical home

ExitReason = Literal["SL", "TP", "BREAKEVEN", "EXPIRY", "FLIP", "MANUAL", "TRAILING_SL"]


class ValidityState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class EntryAction(str, Enum):
    ENTER = "ENTER"
    DEFER = "DEFER"
    SKIP = "SKIP"
    EXIT = "EXIT"


@dataclass(frozen=True)
class PolicyDecision:
    """
    Immutable execution instruction packet.
    Frozen orchestration of signal, timing, and reward.
    """

    action: EntryAction
    entry_plan: object | None  # PositionIntent | DeferredEntry
    exit_plan: object | None  # TPGeometry
    reason: str
    archetype: str
    metadata: dict


@dataclass(frozen=True)
class TPGeometry:
    """
    Immutable reward geometry generated at entry.
    Locked and path-independent execution schedule.
    """

    tp_distance: float
    scale_out_tiers: list[tuple[float, float]]  # [(fraction, multiplier)]
    convexity_score: float
    metadata: dict
