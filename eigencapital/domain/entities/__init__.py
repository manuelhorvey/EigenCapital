"""Domain entity layer (DDD) — canonical data structures.

This module defines the core domain entities shared across all system
layers. The entity layer follows Domain-Driven Design principles:
entities have identity, value objects are immutable, and domain logic
is colocated with the data structures that own it.

Submodules:
- asset: AssetContract (immutable), AssetSpec (mutable runtime config)
- portfolio: Portfolio (mutable state), PortfolioSummary (snapshot)
- position: PositionSide, PositionIntent, StackLayer, OrderType
- signal: SignalType, SignalResult, TradeDecision
- trade: Trade (historical record), TradeLog (collection + aggregates)

All entities are exposed through this __init__.py's __all__ for
convenient imports across paper_trading/, features/, and scripts/.
"""

from eigencapital.domain.entities.asset import AssetContract, AssetSpec
from eigencapital.domain.entities.position import PositionIntent, PositionSide, PositionState
from eigencapital.domain.entities.signal import SignalResult, SignalType, TradeDecision
from eigencapital.domain.entities.trade import Trade, TradeLog
from eigencapital.domain.entities.portfolio import Portfolio, PortfolioSummary

__all__ = [
    "AssetContract",
    "AssetSpec",
    "PositionIntent",
    "PositionSide",
    "PositionState",
    "SignalResult",
    "SignalType",
    "TradeDecision",
    "Trade",
    "TradeLog",
    "Portfolio",
    "PortfolioSummary",
]
