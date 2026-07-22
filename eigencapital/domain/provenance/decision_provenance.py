"""DecisionProvenance — aggregate root of the Decision Provenance Layer.

Assembles all six immutable contexts into a single record that captures
the entire state of the system at the decision boundary.  This is the
canonical answer to "what did the system know and why did it act?"

Each provenance row is uniquely identified by a DecisionID and carries
a schema version for forward compatibility.

Usage::

    from eigencapital.domain.provenance.decision_provenance import DecisionProvenance
    from eigencapital.domain.provenance.decision_id import DecisionID

    provenance = DecisionProvenance(
        decision_id=DecisionID.generate(),
        schema_version=1,
        ...
    )
    event = provenance.to_dict()  # serializable via EigenCapitalJSONEncoder
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eigencapital.domain.provenance.decision_id import DecisionID
from eigencapital.domain.provenance.decision_trace import DecisionTrace
from eigencapital.domain.provenance.execution_context import ExecutionContext
from eigencapital.domain.provenance.feature_context import FeatureContext
from eigencapital.domain.provenance.market_context import MarketContext
from eigencapital.domain.provenance.model_context import ModelContext
from eigencapital.domain.provenance.portfolio_context import PortfolioContext

PROVENANCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DecisionProvenance:
    decision_id: DecisionID
    schema_version: int = PROVENANCE_SCHEMA_VERSION
    cycle_id: int = 0
    asset: str = ""
    decision_timestamp: str = ""
    decision_type: str = "LIVE"  # LIVE | SHADOW | COUNTERFACTUAL | REPLAY
    git_hash: str = ""
    config_hash: str = ""

    # Six immutable contexts
    market: MarketContext | None = None
    features: FeatureContext | None = None
    model: ModelContext | None = None
    portfolio: PortfolioContext | None = None
    runtime: ExecutionContext | None = None
    decision: DecisionTrace | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id.to_dict(),
            "schema_version": self.schema_version,
            "cycle_id": self.cycle_id,
            "asset": self.asset,
            "decision_timestamp": self.decision_timestamp,
            "decision_type": self.decision_type,
            "git_hash": self.git_hash,
            "config_hash": self.config_hash,
            "market": self.market.to_dict() if self.market else None,
            "features": self.features.to_dict() if self.features else None,
            "model": self.model.to_dict() if self.model else None,
            "portfolio": self.portfolio.to_dict() if self.portfolio else None,
            "runtime": self.runtime.to_dict() if self.runtime else None,
            "decision": self.decision.to_dict() if self.decision else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionProvenance:
        raw_id = data.get("decision_id", {})
        if isinstance(raw_id, dict):
            decision_id = DecisionID.from_dict(raw_id)
        else:
            decision_id = DecisionID(decision_id=str(raw_id), lineage_id=str(raw_id))
        return cls(
            decision_id=decision_id,
            schema_version=data.get("schema_version", PROVENANCE_SCHEMA_VERSION),
            cycle_id=data.get("cycle_id", 0),
            asset=data.get("asset", ""),
            decision_timestamp=data.get("decision_timestamp", ""),
            decision_type=data.get("decision_type", "LIVE"),
            git_hash=data.get("git_hash", ""),
            config_hash=data.get("config_hash", ""),
            market=MarketContext.from_dict(data["market"]) if data.get("market") else None,
            features=FeatureContext.from_dict(data["features"]) if data.get("features") else None,
            model=ModelContext.from_dict(data["model"]) if data.get("model") else None,
            portfolio=PortfolioContext.from_dict(data["portfolio"]) if data.get("portfolio") else None,
            runtime=ExecutionContext.from_dict(data["runtime"]) if data.get("runtime") else None,
            decision=DecisionTrace.from_dict(data["decision"]) if data.get("decision") else None,
        )
