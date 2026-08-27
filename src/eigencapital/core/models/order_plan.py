"""Domain model: OrderPlan.

Intermediary abstraction between ApprovedTarget and Order.

Portfolio/risk determines AUTHORIZED exposure (OrderPlan).
Execution determines HOW to achieve it (Order).

This separation becomes extremely important when multiple strategies
simultaneously want the same asset, or when execution constraints
(slippage, urgency, venue) modify the how without changing the what.

Flow: ApprovedTarget → OrderPlan → Order → Fill → Position

Attributes:
- plan_id: Unique identifier
- instrument_id: The instrument
- target_quantity: Signed: authorized exposure
- current_quantity: Current position (signed)
- quantity_delta: target - current, signed (what order must achieve)
- execution_policy_version: Which execution policy governs
- urgency: IMMEDIATE, SESSION, END_OF_DAY
- allowed_order_types: Which order types are permitted
- max_slippage: Maximum acceptable slippage (price units)
- Expiry: when this plan expires if unfilled
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict


class Urgency(str):
    """Order execution urgency."""

    IMMEDIATE = "IMMEDIATE"
    SESSION = "SESSION"
    END_OF_DAY = "END_OF_DAY"


@dataclass(frozen=True)
class OrderPlan:
    """Intermediary abstraction: portfolio/risk determines authorized exposure.

    Portfolio/risk says: "You may have +1 NQ."
    Execution says: "I'll submit a LIMIT order at 14:30:05 with max 1 tick slippage."

    This separation is valuable when:
    - Multiple strategies want the same asset
    - Execution constraints (urgency, slippage, venue) modify how without changing what
    - The plan can expire if not filled, forcing re-assessment

    Flow:
        ApprovedTarget
              ↓
        OrderPlan           ← Portfolio/risk: authorized exposure
              ↓
        Order               ← Execution: how to achieve it
              ↓
        Fill
    """

    plan_id: str
    instrument_id: str
    target_quantity: float  # SIGNED: authorized exposure (positive=LONG, negative=SHORT)
    current_quantity: float  # SIGNED: current position (what we already have)
    quantity_delta: float  # SIGNED: target - current, what the order must achieve
    execution_policy_version: str
    urgency: Urgency  # IMMEDIATE, SESSION, END_OF_DAY
    allowed_order_types: list | None = None  # e.g. ["MARKET", "LIMIT"]
    max_slippage: float = 0.0  # Maximum acceptable slippage (price units)
    expiry: str | None = None  # ISO-8601 UTC when plan expires if unfilled
    version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate plan_id is non-empty
        if not self.plan_id:
            raise ValueError("plan_id must be non-empty")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate target_quantity is finite
        if math.isnan(self.target_quantity) or math.isinf(self.target_quantity):
            raise ValueError("target_quantity must be finite (no NaN/infinity)")

        # Validate current_quantity is finite
        if math.isnan(self.current_quantity) or math.isinf(self.current_quantity):
            raise ValueError("current_quantity must be finite (no NaN/infinity)")

        # Validate quantity_delta = target_quantity - current_quantity
        expected_delta = self.target_quantity - self.current_quantity
        if abs(self.quantity_delta - expected_delta) > 0.0001:
            # Allow tiny floating point tolerance
            raise ValueError(
                f"Invariant violated: quantity_delta ({self.quantity_delta}) "
                f"!= target_quantity ({self.target_quantity}) - current_quantity "
                f"({self.current_quantity}) = {expected_delta}"
            )

        # Validate urgency is a known value
        valid_urgencies = {Urgency.IMMEDIATE, Urgency.SESSION, Urgency.END_OF_DAY}
        if self.urgency not in valid_urgencies:
            raise ValueError(f"Invalid urgency: {self.urgency}. Must be one of {valid_urgencies}")

        # Validate execution_policy_version is non-empty
        if not self.execution_policy_version:
            raise ValueError("execution_policy_version must be non-empty")

        # Validate max_slippage is non-negative if provided
        if self.max_slippage < 0:
            raise ValueError("max_slippage must be >= 0")

        # Validate expiry format if set
        if self.expiry is not None:
            if "T" not in self.expiry:
                raise ValueError(f"expiry should be ISO-8601 format, got: {self.expiry}")

        # Registry check for duplicate plan_ids
        if self.plan_id in self._registry:
            raise ValueError(f"Duplicate plan_id: {self.plan_id}. Plan IDs must be unique.")
        self._registry[self.plan_id] = True

    def __hash__(self) -> int:
        return hash((self.plan_id, self.instrument_id, self.target_quantity))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OrderPlan):
            return NotImplemented
        return self.plan_id == other.plan_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "plan_id": self.plan_id,
            "instrument_id": self.instrument_id,
            "target_quantity": self.target_quantity,
            "current_quantity": self.current_quantity,
            "quantity_delta": self.quantity_delta,
            "execution_policy_version": self.execution_policy_version,
            "urgency": self.urgency,
            "allowed_order_types": self.allowed_order_types,
            "max_slippage": self.max_slippage,
            "expiry": self.expiry,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> OrderPlan:
        """Deserialize from dict (deterministic, keys sorted)."""
        return OrderPlan(
            plan_id=d["plan_id"],
            instrument_id=d["instrument_id"],
            target_quantity=float(d["target_quantity"]),
            current_quantity=float(d["current_quantity"]),
            quantity_delta=float(d["quantity_delta"]),
            execution_policy_version=str(d["execution_policy_version"]),
            urgency=Urgency(d["urgency"]) if isinstance(d.get("urgency"), str) else d["urgency"],
            allowed_order_types=d.get("allowed_order_types"),
            max_slippage=float(d.get("max_slippage", 0.0)),
            expiry=d.get("expiry"),
            version=str(d.get("version", "v1")),
        )

    @property
    def is_fulfillable(self) -> bool:
        """Check if quantity_delta can be achieved (non-zero delta)."""
        return self.quantity_delta != 0

    @property
    def delta_sign(self) -> str:
        """Sign of the delta: positive=need to buy, negative=need to sell."""
        if self.quantity_delta > 0:
            return "BUY"
        elif self.quantity_delta < 0:
            return "SELL"
        else:
            return "FLAT"

    @property
    def urgency_enum(self) -> str:
        """Return urgency as string."""
        return self.urgency


@dataclass(frozen=True)
class OrderPlanSide:
    """Legacy alias — use OrderPlan.delta_sign instead.

    Deprecated: Use OrderPlan.delta_sign.
    """

    value: str

    @property
    def is_buy(self) -> bool:
        return self.value == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.value == "SELL"


OrderPlan._registry = {}
