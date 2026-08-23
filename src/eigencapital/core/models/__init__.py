"""EigenCapital domain models.

All domain models are frozen dataclasses with:
- Invariant validation in __post_init__
- Deterministic to_dict / from_dict serialization
- Class-level registry for uniqueness enforcement
- Canonical serialization support via canonical_sort()
"""

from .instrument import Instrument
from .bar import Bar, BarInterval
from .market_snapshot import MarketSnapshot
from .strategy_intent import StrategyIntent, Horizon
from .position import Position
from .order import Order, OrderSide
from .fill import Fill
from .risk_check_result import RiskCheckResult
from .risk_decision import RiskDecision
from .portfolio_target import PortfolioTarget
from .approved_target import ApprovedTarget
from .order_plan import OrderPlan, Urgency
from .order_lifecycle import OrderLifecycle
from .decision_snapshot import DecisionSnapshot
from .experiment import Experiment, ExperimentStatus
from .errors import (
    EigenCapitalError,
    InvariantViolation,
    InvalidInput,
    DuplicateResource,
    ConfigurationError,
    ProvenanceError,
)

__all__ = [
    # Data models
    "Instrument",
    "Bar",
    "BarInterval",
    "MarketSnapshot",
    # Strategy
    "StrategyIntent",
    "Horizon",
    # Position & Orders
    "Position",
    "Order",
    "OrderSide",
    "Fill",
    "OrderLifecycle",
    "OrderPlan",
    "Urgency",
    # Risk
    "RiskCheckResult",
    "RiskDecision",
    # Portfolio
    "PortfolioTarget",
    "ApprovedTarget",
    # Audit
    "DecisionSnapshot",
    # Research
    "Experiment",
    "ExperimentStatus",
    # Errors
    "EigenCapitalError",
    "InvariantViolation",
    "InvalidInput",
    "DuplicateResource",
    "ConfigurationError",
    "ProvenanceError",
]
