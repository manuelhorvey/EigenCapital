"""Domain model: PortfolioTarget.

What the strategy proposes: desired exposure in absolute terms.

Flow: StrategyIntent → PortfolioTarget → EigenRisk → ApprovedTarget

Invariants:
- target_quantity is signed (positive=LONG, negative=SHORT)
- target_market_value is the desired notional value (currency)
- target_risk is portfolio-relative risk
- justification explains the reason for the target
- config_hash links to strategy parameters
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import math


@dataclass(frozen=True)
class PortfolioTarget:
    """What the strategy proposes: desired exposure in absolute terms.

    Flow through the system:
        StrategyIntent
              ↓
        PortfolioTarget   ← "I propose this exposure"
              ↓
        EigenRisk         ← "Is this allowed?"
              ↓
        ApprovedTarget    ← "Approved/modified/denied"

    Invariants:
    - target_quantity is signed (positive=LONG, negative=SHORT, 0=flat)
    - target_market_value is the desired notional value (currency)
    - target_risk >= 0 (domain enforces non-negative; policy sets upper bound)
    - config_hash links to strategy parameters + version
    - justification is non-empty text explaining the rationale
    """

    target_id: str
    instrument_id: str  # FK → Instrument; "CASH" for cash targets
    target_quantity: float  # SIGNED: positive=LONG, negative=SHORT, 0=FLAT
    target_market_value: float  # Desired notional value (currency); 0 if cash/flat
    target_risk: float  # Portfolio-relative risk >= 0
    justification: str  # Non-empty: e.g. "breakout signal, ES exposure reduced"
    strategy_config_hash: str  # Linked strategy parameters + config hash
    strategy_artifact_hash: str  # Linked strategy implementation hash
    version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate target_quantity is finite
        if math.isnan(self.target_quantity) or math.isinf(self.target_quantity):
            raise ValueError("target_quantity must be finite (no NaN/infinity)")

        # Validate target_market_value is finite
        if math.isnan(self.target_market_value) or math.isinf(self.target_market_value):
            raise ValueError("target_market_value must be finite (no NaN/infinity)")

        # Validate target_risk >= 0
        if self.target_risk < 0:
            raise ValueError("target_risk must be >= 0 (domain enforces non-negative)")

        # Validate target_id is non-empty
        if not self.target_id:
            raise ValueError("target_id must be non-empty")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate justification is non-empty
        if not self.justification or not self.justification.strip():
            raise ValueError("justification must be non-empty text")

        # Validate strategy_config_hash is non-empty
        if not self.strategy_config_hash:
            raise ValueError("strategy_config_hash must be non-empty")

        # Validate strategy_artifact_hash is non-empty
        if not self.strategy_artifact_hash:
            raise ValueError("strategy_artifact_hash must be non-empty")

        # Registry check for duplicate target_ids
        if self.target_id in self._registry:
            raise ValueError(
                f"Duplicate target_id: {self.target_id}. Target IDs must be unique."
            )
        self._registry[self.target_id] = True

    def __hash__(self) -> int:
        return hash((self.target_id, self.target_quantity))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PortfolioTarget):
            return NotImplemented
        return self.target_id == other.target_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "target_id": self.target_id,
            "instrument_id": self.instrument_id,
            "target_quantity": self.target_quantity,
            "target_market_value": self.target_market_value,
            "target_risk": self.target_risk,
            "justification": self.justification,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_artifact_hash": self.strategy_artifact_hash,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PortfolioTarget:
        """Deserialize from dict (deterministic, keys sorted)."""
        return PortfolioTarget(
            target_id=d["target_id"],
            instrument_id=d["instrument_id"],
            target_quantity=float(d["target_quantity"]),
            target_market_value=float(d["target_market_value"]),
            target_risk=float(d["target_risk"]),
            justification=str(d["justification"]),
            strategy_config_hash=str(
                d.get("strategy_config_hash", d.get("config_hash", ""))
            ),
            strategy_artifact_hash=str(d.get("strategy_artifact_hash", "")),
            version=str(d.get("version", "v1")),
        )

    @property
    def is_flat(self) -> bool:
        """Check if target quantity is 0."""
        return self.target_quantity == 0

    @property
    def is_long(self) -> bool:
        """Check if target is long (quantity > 0)."""
        return self.target_quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if target is short (quantity < 0)."""
        return self.target_quantity < 0

    @property
    def notional(self) -> float:
        """Absolute notional: |target_market_value|."""
        return abs(self.target_market_value)


@dataclass(frozen=True)
class PortfolioTargetSide:
    """Legacy alias — use PortfolioTarget properties instead.

    Deprecated: Use PortfolioTarget.is_long, .is_short, .is_flat.
    """

    value: str

    @property
    def is_long(self) -> bool:
        return self.value == "LONG"

    @property
    def is_short(self) -> bool:
        return self.value == "SHORT"

    @property
    def is_flat(self) -> bool:
        return self.value == "FLAT"


PortfolioTarget._registry = {}
