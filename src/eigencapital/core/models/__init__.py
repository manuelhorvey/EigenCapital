"""EigenCapital domain models.

All domain models are frozen dataclasses with:
- Invariant validation in __post_init__
- Deterministic to_dict / from_dict serialization
- Class-level registry for uniqueness enforcement
- Canonical serialization support via canonical_sort()
"""

from .approved_target import ApprovedTarget
from .bar import Bar, BarInterval
from .decision_snapshot import DecisionSnapshot
from .errors import (
    ConfigurationError,
    DuplicateResource,
    EigenCapitalError,
    InvalidInput,
    InvariantViolation,
    ProvenanceError,
)
from .experiment import Experiment, ExperimentStatus
from .fill import Fill
from .instrument import Instrument
from .market_snapshot import MarketSnapshot
from .order import Order, OrderSide
from .order_lifecycle import OrderLifecycle
from .order_plan import OrderPlan, Urgency
from .portfolio_target import PortfolioTarget
from .position import Position
from .risk_check_result import RiskCheckResult
from .risk_decision import RiskDecision
from .strategy_intent import Horizon, StrategyIntent
from .trial_metadata import TrialMetadata

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
    "TrialMetadata",
    # Errors
    "EigenCapitalError",
    "InvariantViolation",
    "InvalidInput",
    "DuplicateResource",
    "ConfigurationError",
    "ProvenanceError",
]
