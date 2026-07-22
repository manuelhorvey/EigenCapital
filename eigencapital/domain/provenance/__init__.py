"""Decision Provenance Layer — immutable record of every trading decision.

Each module in this package defines a frozen dataclass representing one
domain of the system state at the decision boundary:

- decision_id: Globally unique identifiers (UUID4 + lineage)
- market_context: OHLCV bars, spread, session, macro state
- feature_context: Feature vector, hash, schema version
- model_context: Model/calibration versions, raw/calibrated probabilities
- portfolio_context: Positions, PEK budget, exposure, equity
- execution_context: Halt state, circuit breakers, health, cycle metadata
- decision_trace: Gate trace, thresholds, final action, sizing, order
- decision_provenance: Aggregate root combining all six contexts
- provenance_store: Storage interface + SQLite implementation

Usage::

    from eigencapital.domain.provenance import (
        DecisionID,
        DecisionProvenance,
        DecisionTrace,
        ExecutionContext,
        FeatureContext,
        MarketContext,
        ModelContext,
        PortfolioContext,
        ProvenanceStore,
    )
"""

from eigencapital.domain.provenance.decision_id import DecisionID
from eigencapital.domain.provenance.decision_provenance import DecisionProvenance, PROVENANCE_SCHEMA_VERSION
from eigencapital.domain.provenance.decision_trace import DecisionTrace
from eigencapital.domain.provenance.execution_context import ExecutionContext
from eigencapital.domain.provenance.feature_context import FeatureContext
from eigencapital.domain.provenance.market_context import MarketContext
from eigencapital.domain.provenance.model_context import ModelContext
from eigencapital.domain.provenance.portfolio_context import PortfolioContext, PositionSnapshot
from eigencapital.domain.provenance.provenance_store import ProvenanceStore
from eigencapital.domain.provenance.counterfactual import CounterfactualEngine, CounterfactualDelta
from eigencapital.domain.provenance.validator import ProvenanceValidator, ValidationResult

__all__ = [
    "DecisionID",
    "DecisionProvenance",
    "DecisionTrace",
    "ExecutionContext",
    "FeatureContext",
    "MarketContext",
    "ModelContext",
    "PortfolioContext",
    "PositionSnapshot",
    "ProvenanceStore",
    "PROVENANCE_SCHEMA_VERSION",
]
