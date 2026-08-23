"""Domain model: StrategyIntent.

Read-only mapping from market data to trading intent.

The conceptual contract is:

    Market State
    +
    Strategy State (internal, declared)
    +
    Portfolio Context
    +
    Configuration
            ↓
    Strategy Decision
            ↓
    StrategyIntent

Critical constraints:
- Must NOT reference broker accounts, order types, or execution logic
- Must include config_hash for lineage tracking
- State must be declarative (never broker-dependent)
- Must be accompanied by a DecisionSnapshot on generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


class Horizon(str):
    """Strategy trading horizon enum."""

    INTRADAY = "intraday"
    SWING = "swing"


@dataclass(frozen=True)
class StrategyIntent:
    """Read-only mapping from market data to trading intent.

    This is the strategy's output: what it wants the portfolio to do.
    It must NOT contain broker/order execution information.

    Invariants:
    - direction in {LONG(1), SHORT(-1), FLAT(0)} or directional enums
    - target_risk >= 0 (policy decides upper bound)
    - config_hash links to strategy parameters + code version
    - expiry, if set, must be in the future relative to signal_timestamp_utc
    - strategy_id + strategy_version uniquely identify the strategy code/config
    """

    strategy_id: str  # e.g. "trend_v1"
    strategy_version: str  # e.g. "v1.2.0"
    instrument_id: str  # FK → Instrument
    timestamp_utc: str  # ISO-8601 UTC when signal generated
    direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    target_risk: float  # portfolio-relative risk >= 0
    horizon: Horizon  # intraday or swing
    confidence: Optional[float] = None  # 0.0-1.0, strategy-internal
    signal_metadata: Dict[str, Any] = field(default_factory=dict)  # free-form regime flags, etc.
    expiry: Optional[str] = None  # ISO-8601 UTC when this intent expires
    strategy_config_hash: str = ""  # SHA256(strategy parameters + strategy configuration)
    strategy_artifact_hash: str = ""  # SHA256(strategy implementation / code)
    decision_snapshot_id: Optional[str] = None  # back to DecisionSnapshot


    def __post_init__(self) -> None:
        # Validate direction: must be 1, -1, or 0
        if self.direction not in (1, -1, 0):
            raise ValueError(
                f"Invalid direction: {self.direction}. Must be 1 (LONG), -1 (SHORT), or 0 (FLAT)."
            )

        # Validate target_risk >= 0
        if self.target_risk < 0:
            raise ValueError(
                f"target_risk must be >= 0, got {self.target_risk}. "
                "Policy decides upper bound; domain only enforces non-negative."
            )

        # Validate timestamp is ISO-8601 UTC format
        if "T" not in self.timestamp_utc:
            raise ValueError(
                f"timestamp_utc should be ISO-8601 format, got: {self.timestamp_utc}"
            )

        # Validate strategy_config_hash is present (non-empty)
        if not self.strategy_config_hash:
            raise ValueError("strategy_config_hash must be non-empty (strategy parameters + config)")

        # Validate strategy_artifact_hash is present (non-empty)
        if not self.strategy_artifact_hash:
            raise ValueError("strategy_artifact_hash must be non-empty (strategy implementation hash)")

        # Validate expiry if set: must be ISO-8601 and in future logic is caller's responsibility,
        # but we at least check format
        if self.expiry is not None:
            if "T" not in self.expiry:
                raise ValueError(f"expiry should be ISO-8601 format, got: {self.expiry}")

        # Strategy ID must be non-empty
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")

        # Strategy version must be non-empty
        if not self.strategy_version:
            raise ValueError("strategy_version must be non-empty")

        # Instrument ID must be non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Check for duplicate strategy intent (same strategy_id + version + instrument + timestamp)
        key = (self.strategy_id, self.strategy_version, self.instrument_id, self.timestamp_utc)
        if key in self._registry:
            raise ValueError(
                f"Duplicate StrategyIntent: strategy_id={self.strategy_id}, "
                f"strategy_version={self.strategy_version}, "
                f"instrument={self.instrument_id}, timestamp={self.timestamp_utc}"
            )
        self._registry[key] = key

    def __hash__(self) -> int:
        return hash((self.strategy_id, self.strategy_version, self.instrument_id, self.timestamp_utc))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StrategyIntent):
            return NotImplemented
        return (
            self.strategy_id == other.strategy_id
            and self.strategy_version == other.strategy_version
            and self.instrument_id == other.instrument_id
            and self.timestamp_utc == other.timestamp_utc
        )

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "direction": self.direction,
            "target_risk": self.target_risk,
            "horizon": self.horizon,
            "confidence": self.confidence,
            "signal_metadata": self.signal_metadata,
            "expiry": self.expiry,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_artifact_hash": self.strategy_artifact_hash,
            "decision_snapshot_id": self.decision_snapshot_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StrategyIntent:
        """Deserialize from dict (deterministic, keys sorted)."""
        return StrategyIntent(
            strategy_id=d["strategy_id"],
            strategy_version=d["strategy_version"],
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            direction=int(d["direction"]),
            target_risk=float(d["target_risk"]),
            horizon=Horizon(d["horizon"]) if isinstance(d.get("horizon"), str) else d["horizon"],
            confidence=float(d["confidence"]) if d.get("confidence") is not None else None,
            signal_metadata=d.get("signal_metadata", {}),
            expiry=d.get("expiry"),
            strategy_config_hash=str(d.get("strategy_config_hash", d.get("config_hash", ""))),
            strategy_artifact_hash=str(d.get("strategy_artifact_hash", "")),
            decision_snapshot_id=d.get("decision_snapshot_id"),
        )

    @property
    def direction_enum(self) -> str:
        """Human-readable direction."""
        return {1: "LONG", -1: "SHORT", 0: "FLAT"}[self.direction]

    @property
    def is_flat(self) -> bool:
        """Check if direction is FLAT."""
        return self.direction == 0

    @property
    def is_long(self) -> bool:
        """Check if direction is LONG."""
        return self.direction == 1

    @property
    def is_short(self) -> bool:
        """Check if direction is SHORT."""
        return self.direction == -1

    def risk_check_dict(self) -> Dict[str, Any]:
        """Return risk-related fields as a dict for RiskDecision consumption."""
        return {
            "strategy_id": self.strategy_id,
            "instrument_id": self.instrument_id,
            "target_risk": self.target_risk,
            "direction": self.direction_enum,
            "horizon": self.horizon,
            "target_risk_value": self.target_risk,
        }


StrategyIntent._registry = {}
