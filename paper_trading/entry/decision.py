from dataclasses import dataclass
from enum import Enum

from quantforge.domain.entities.position import PositionIntent, PositionSide  # noqa: F401
from quantforge.domain.entities.signal import SignalType, TradeDecision  # noqa: F401


class ValidityState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class LiquidityRegime(str, Enum):
    NORMAL = "NORMAL"
    THIN = "THIN"
    STRESSED = "STRESSED"


@dataclass
class MarketStructureState:
    """
    Structural snapshot of the market.
    Purely informational, no decision logic.
    """

    trend_strength: float
    compression_score: float
    distance_to_swing_high: float
    distance_to_swing_low: float
    volatility_regime: float
    breakout_pressure: float


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



