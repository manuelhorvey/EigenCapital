"""Domain model: DecisionSnapshot.

The audit backbone: reconstructible record of every production decision.

Purpose: If six months later you ask:
    "Why did EigenCapital buy NQ at 14:32?"
You reconstruct the answer from the DecisionSnapshot, not by grepping logs.

Mandatory: Every StrategyIntent generation must be accompanied by a DecisionSnapshot.
No signal is submitted to the portfolio without one.

The snapshot spans the entire decision pipeline with three distinct timestamps:

    signal_timestamp_utc    when strategy generated the signal
    risk_decision_timestamp_utc when risk engine made its decision
    execution_timestamp_utc   when order was submitted/fill occurred

Plus full provenance chain (versions, hashes, git commit, dataset, etc.).

Hash fields (Correction #8):
    strategy_config_hash   = hash(strategy parameters + strategy configuration)
    strategy_artifact_hash = hash(strategy implementation / code)
    provenance_hash        = hash(code version, strategy artifact, strategy config,
                                  dataset, risk policy, execution policy, environment)

Flow: StrategyIntent + MarketState → DecisionSnapshot → PortfolioTarget → RiskDecision → ApprovedTarget → OrderPlan → Order → Fill → Position → Reconciliation → AccountSnapshot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class DecisionSnapshot:
    """The audit backbone: reconstructible record of every production decision.

    Purpose: Forensic reproducibility. If six months later someone asks
    "Why did EigenCapital buy NQ at 14:32 on 2024-03-15?", the answer
    is reconstructed from the DecisionSnapshot, not by grepping logs.

    The snapshot captures the complete decision pipeline with three timestamps:

        signal_timestamp_utc        when strategy generated the signal
        risk_decision_timestamp_utc when risk engine made its decision
        execution_timestamp_utc     when order was submitted/fill occurred

    Plus:
        - Full version lineage (code, dataset, risk, execution policies)
        - Provenance hash chain for cross-model traceability
        - Market state and features at signal time
        - Portfolio and risk state at decision time
        - Linked experiment (if any)

    Hash fields (three-layer provenance):
        strategy_config_hash   = hash(strategy parameters + configuration)
        strategy_artifact_hash = hash(strategy implementation / code)
        provenance_hash        = hash(code version, strategy artifact, strategy config,
                                      dataset, risk policy, execution policy, environment)

    Critical: No downstream subsystem may infer upstream intent from
    downstream state when the upstream decision object should exist.
    Every transition is explicit.
    """

    snapshot_id: str  # Unique identifier (UUID)
    signal_timestamp_utc: str  # when strategy generated the signal
    risk_decision_timestamp_utc: str  # when risk engine made its decision
    execution_timestamp_utc: str  # when order was submitted/fill occurred
    strategy_id: str
    strategy_version: str
    strategy_config_hash: str  # hash(strategy parameters + configuration)
    strategy_artifact_hash: str  # hash(strategy implementation / code)
    provenance_hash: str  # hash(full provenance chain)
    instrument_id: str
    experiment_id: str | None = None  # linked experiment (if any)

    # Market state at signal generation time
    market_state: Dict[str, Any] = field(default_factory=dict)  # free-form: regime, flags, etc.
    features: Dict[str, float] = field(default_factory=dict)  # computed feature vector at signal time
    signal: object = None  # the StrategyIntent that was generated
    portfolio_state: Dict[str, Any] = field(default_factory=dict)  # positions, equity at signal time
    risk_state: object = None  # the RiskDecision outcome

    # Explicit rationale
    risk_decision_reason: str = ""  # why approved/rejected/reduced

    # Execution context
    execution_context: str = "PAPER"  # PAPER, LIVE, BACKTEST

    # Provenance chain
    git_commit: str = ""
    dataset_version: str = ""
    random_seed: int | None = None  # if stochastic strategy

    # Version chain for provenance
    parent_snapshot_ids: list | None = None  # → parent snapshots, for provenance

    # Internal tracking

    def __post_init__(self) -> None:
        # Validate snapshot_id is non-empty
        if not self.snapshot_id:
            raise ValueError("snapshot_id must be non-empty")

        # Validate timestamps are ISO-8601 UTC format
        for ts_name in (
            "signal_timestamp_utc",
            "risk_decision_timestamp_utc",
            "execution_timestamp_utc",
        ):
            ts = getattr(self, ts_name, None)
            if ts is not None and "T" not in ts:
                raise ValueError(f"{ts_name} should be ISO-8601 format, got: {ts}")

        # Validate strategy_id is non-empty
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")

        # Validate strategy_version is non-empty
        if not self.strategy_version:
            raise ValueError("strategy_version must be non-empty")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate strategy_config_hash is non-empty
        if not self.strategy_config_hash:
            raise ValueError("strategy_config_hash must be non-empty")

        # Validate strategy_artifact_hash is non-empty
        if not self.strategy_artifact_hash:
            raise ValueError("strategy_artifact_hash must be non-empty")

        # Validate provenance_hash is non-empty
        if not self.provenance_hash:
            raise ValueError("provenance_hash must be non-empty")

        # Validate risk_decision_reason is non-empty
        if not self.risk_decision_reason or not self.risk_decision_reason.strip():
            raise ValueError("risk_decision_reason must be non-empty text")

        # Validate execution_context is known
        valid_contexts = {"PAPER", "LIVE", "BACKTEST"}
        if self.execution_context not in valid_contexts:
            raise ValueError(f"Invalid execution_context: {self.execution_context}. Must be one of {valid_contexts}")

        # Validate git_commit is non-empty
        if not self.git_commit:
            raise ValueError("git_commit must be non-empty")

        # Validate dataset_version is non-empty
        if not self.dataset_version:
            raise ValueError("dataset_version must be non-empty")

        # Validate features is a dict (can be empty)
        if not isinstance(self.features, dict):
            raise ValueError("features must be a dict")

        # Validate market_state is a dict
        if not isinstance(self.market_state, dict):
            raise ValueError("market_state must be a dict")

        # Validate portfolio_state is a dict
        if not isinstance(self.portfolio_state, dict):
            raise ValueError("portfolio_state must be a dict")

        # INVARIANT: risk_state must be a RiskDecision instance
        from .risk_decision import RiskDecision

        if not isinstance(self.risk_state, RiskDecision):
            raise ValueError(f"risk_state must be a RiskDecision instance, got {type(self.risk_state)}")

        # INVARIANT: signal must not be None
        if self.signal is None:
            raise ValueError("signal must not be None (StrategyIntent required)")

        # Registry check for duplicate snapshot_ids
        if self.snapshot_id in self._registry:
            raise ValueError(
                f"Duplicate snapshot_id: {self.snapshot_id}. Snapshot IDs must be unique (audit trail requirement)."
            )
        self._registry[self.snapshot_id] = True

        # INVARIANT: signal.instrument_id matches this snapshot's instrument_id
        if self.signal.instrument_id != self.instrument_id:
            raise ValueError(
                f"Invariant violated: signal.instrument_id "
                f"({self.signal.instrument_id}) != snapshot.instrument_id "
                f"({self.instrument_id})"
            )

    def __hash__(self) -> int:
        return hash((self.snapshot_id, self.strategy_id, self.instrument_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DecisionSnapshot):
            return NotImplemented
        return self.snapshot_id == other.snapshot_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing.

        Returns a dict (consistent with all other domain models).
        Key sorting for canonical hashing is applied via canonical_sort().
        """
        return {
            "snapshot_id": self.snapshot_id,
            "signal_timestamp_utc": self.signal_timestamp_utc,
            "risk_decision_timestamp_utc": self.risk_decision_timestamp_utc,
            "execution_timestamp_utc": self.execution_timestamp_utc,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_artifact_hash": self.strategy_artifact_hash,
            "provenance_hash": self.provenance_hash,
            "instrument_id": self.instrument_id,
            "experiment_id": self.experiment_id,
            "market_state": dict(self.market_state),
            "features": dict(self.features),
            "signal": self.signal.to_dict() if hasattr(self.signal, "to_dict") else {},
            "portfolio_state": dict(self.portfolio_state),
            "risk_state": self.risk_state.to_dict() if hasattr(self.risk_state, "to_dict") else {},
            "risk_decision_reason": self.risk_decision_reason,
            "execution_context": self.execution_context,
            "git_commit": self.git_commit,
            "dataset_version": self.dataset_version,
            "random_seed": self.random_seed,
            "parent_snapshot_ids": self.parent_snapshot_ids,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DecisionSnapshot:
        """Deserialize from dict (deterministic, keys sorted)."""
        from .risk_decision import RiskDecision

        return DecisionSnapshot(
            snapshot_id=str(d["snapshot_id"]),
            signal_timestamp_utc=str(d["signal_timestamp_utc"]),
            risk_decision_timestamp_utc=str(d["risk_decision_timestamp_utc"]),
            execution_timestamp_utc=str(d["execution_timestamp_utc"]),
            strategy_id=str(d["strategy_id"]),
            strategy_version=str(d["strategy_version"]),
            strategy_config_hash=str(d.get("strategy_config_hash", d.get("config_hash", ""))),
            strategy_artifact_hash=str(d.get("strategy_artifact_hash", "")),
            provenance_hash=str(d.get("provenance_hash", "")),
            instrument_id=str(d["instrument_id"]),
            experiment_id=d.get("experiment_id"),
            market_state=d.get("market_state", {}),
            features=d.get("features", {}),
            signal=None,  # Caller must set signal after deserialization
            portfolio_state=d.get("portfolio_state", {}),
            risk_state=RiskDecision.from_dict(d.get("risk_state", {})),
            risk_decision_reason=str(d.get("risk_decision_reason", "")),
            execution_context=str(d.get("execution_context", "PAPER")),
            git_commit=str(d.get("git_commit", "")),
            dataset_version=str(d.get("dataset_version", "")),
            random_seed=int(d["random_seed"]) if d.get("random_seed") is not None else None,
            parent_snapshot_ids=d.get("parent_snapshot_ids"),
        )

    @property
    def is_approved(self) -> bool:
        """Check if risk decision was APPROVED."""
        return self.risk_state.is_approved

    @property
    def is_rejected(self) -> bool:
        """Check if risk decision was REJECTED."""
        return self.risk_state.is_rejected

    @property
    def is_reduced(self) -> bool:
        """Check if risk decision was REDUCED."""
        return self.risk_state.is_reduced

    @property
    def signal_direction(self) -> str:
        """Get signal direction from the contained StrategyIntent."""
        if hasattr(self.signal, "direction_enum"):
            return self.signal.direction_enum
        elif hasattr(self.signal, "direction"):
            d = self.signal.direction
            return {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(d, str(d))
        return "UNKNOWN"

    @property
    def target_risk(self) -> float:
        """Get target risk from the contained StrategyIntent features or signal."""
        if hasattr(self.signal, "target_risk"):
            return self.signal.target_risk
        if "target_risk" in self.features:
            return float(self.features["target_risk"])
        return 0.0

    @property
    def summary(self) -> str:
        """Human-readable summary of the decision snapshot."""
        return (
            f"DecisionSnapshot[{self.snapshot_id}]:\n"
            f"  signal_time={self.signal_timestamp_utc}\n"
            f"  risk_decision_time={self.risk_decision_timestamp_utc}\n"
            f"  execution_time={self.execution_timestamp_utc}\n"
            f"  strategy={self.strategy_id}/{self.strategy_version}\n"
            f"  instrument={self.instrument_id}\n"
            f"  decision={self.risk_state.decision}\n"
            f"  direction={self.signal_direction}\n"
            f"  target_risk={self.target_risk}\n"
            f"  reason={self.risk_decision_reason[:60]}...\n"
            f"  context={self.execution_context}\n"
            f"  git={self.git_commit[:8]}...\n"
            f"  dataset={self.dataset_version}"
        )


DecisionSnapshot._registry = {}
