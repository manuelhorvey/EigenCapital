"""Domain model: Order.

Order lifecycle: SUBMITTED → PARTIALLY_FILLED → FILLED / CANCELLED / REJECTED.

Invariants:
- quantity is ALWAYS positive (contracts / shares / units)
- side is BUY or SELL (NOT signed)
- signed_quantity = quantity if side == BUY else -quantity
- filled_quantity <= quantity always (enforced by OrderLifecycle)
- average_fill_price is weighted average of all fills
- order_id is unique identifier
- decision_snapshot_id links back to DecisionSnapshot
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Order:
    """Order submission to the execution engine.

    Key design: Order interface is identical between paper and live brokers.
    Only the broker adapter translates to venue-specific API.

    Invariants:
    - quantity is ALWAYS positive
    - side is BUY or SELL (sign convention is separate)
    - signed_quantity derived: qty if BUY else -qty
    - filled_quantity cumulative across all Fills for this order
    - OrderLifecycle invariant: sum(fills.quantity) <= order.quantity

    Attributes:
        order_id: Unique identifier (UUID or SPEC-format)
        instrument_id: FK → Instrument
        timestamp_utc: When order was submitted
        order_type: MARKET, LIMIT, STOP, STOP_LIMIT
        side: BUY or SELL — NOT signed
        quantity: Always positive total order quantity
        limit_price: For LIMIT/STOP_LIMIT orders
        stop_price: For STOP/STOP_LIMIT orders
        status: SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED
        filled_quantity: Cumulative filled quantity so far
        filled_price: Weighted average fill price
        average_fill_price: Same as filled_price (alias)
        order_metadata: Free-form dict: client_id, algo_name, etc.
        strategy_id: Which strategy generated this order
        experiment_id: Linked experiment (if any)
        decision_snapshot_id: Back to DecisionSnapshot
        version: Version for change tracking
    """

    order_id: str
    instrument_id: str
    timestamp_utc: str  # ISO-8601 UTC when order submitted
    order_type: str  # MARKET, LIMIT, STOP, STOP_LIMIT
    side: str  # BUY or SELL — NOT signed
    quantity: float  # ALWAYS positive
    limit_price: float | None = None
    stop_price: float | None = None
    status: str = "SUBMITTED"  # SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED
    filled_quantity: float = 0.0  # Cumulative, always >= 0 and <= quantity
    filled_price: float = 0.0
    average_fill_price: float = 0.0  # Alias for filled_price
    order_metadata: Dict[str, Any] = field(default_factory=dict)
    strategy_id: str = ""

    # _registry will be set as class variable below
    experiment_id: str = ""
    decision_snapshot_id: str = ""
    version: str = "v1"

    def __post_init__(self) -> None:
        # Validate quantity is positive (>= 0, but 0 is allowed for cancel/replace)
        if self.quantity < 0:
            raise ValueError(
                f"Order quantity must be >= 0, got {self.quantity}. "
                "Quantity is ALWAYS positive or zero (for cancel/zero-size adjustments)."
            )

        # Validate side is BUY or SELL
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"Order side must be 'BUY' or 'SELL', got '{self.side}'")

        # Validate timestamp is ISO-8601 UTC
        if "T" not in self.timestamp_utc:
            raise ValueError(f"timestamp_utc should be ISO-8601 format, got: {self.timestamp_utc}")

        # Validate status is known
        valid_statuses = {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid order status: {self.status}. Must be one of {valid_statuses}")

        # If status is FILLED or PARTIALLY_FILLED, filled_quantity must be <= quantity
        if self.status in ("FILLED", "PARTIALLY_FILLED") and self.filled_quantity > self.quantity:
            raise ValueError(
                f"Invalid order state: filled_quantity ({self.filled_quantity}) "
                f"> quantity ({self.quantity}) for status {self.status}"
            )

        # Validate limit_price if provided (for LIMIT/STOP_LIMIT)
        if self.order_type in ("LIMIT", "STOP_LIMIT") and self.limit_price is not None:
            if self.limit_price is not None and (math.isnan(self.limit_price) or math.isinf(self.limit_price)):
                raise ValueError("limit_price must be finite (no NaN/infinity)")
            if self.limit_price is not None and self.limit_price <= 0:
                raise ValueError("limit_price must be > 0 if provided")

        # Validate stop_price if provided (for STOP/STOP_LIMIT)
        if self.order_type in ("STOP", "STOP_LIMIT") and self.stop_price is not None:
            if self.stop_price is not None and (math.isnan(self.stop_price) or math.isinf(self.stop_price)):
                raise ValueError("stop_price must be finite (no NaN/infinity)")
            if self.stop_price is not None and self.stop_price <= 0:
                raise ValueError("stop_price must be > 0 if provided")

        # Validate filled_price is finite if non-zero
        if self.filled_price != 0.0:
            if math.isnan(self.filled_price) or math.isinf(self.filled_price):
                raise ValueError("filled_price must be finite (no NaN/infinity)")
            if self.filled_price < 0:
                raise ValueError("filled_price must be >= 0")

        # Validate average_fill_price matches filled_price
        if abs(self.average_fill_price - self.filled_price) > 0.0001:
            raise ValueError(f"average_fill_price ({self.average_fill_price}) != filled_price ({self.filled_price})")

        # Validate instrument_id is non-empty
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate order_id is non-empty
        if not self.order_id:
            raise ValueError("order_id must be non-empty")

        # Validate strategy_id is non-empty (required for accountability)
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty (required for accountability)")

    def __hash__(self) -> int:
        return hash((self.order_id, self.side, self.quantity))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Order):
            return NotImplemented
        return self.order_id == other.order_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "order_id": self.order_id,
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "order_type": self.order_type,
            "side": self.side,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "average_fill_price": self.average_fill_price,
            "order_metadata": dict(self.order_metadata),
            "strategy_id": self.strategy_id,
            "experiment_id": self.experiment_id,
            "decision_snapshot_id": self.decision_snapshot_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Order:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Order(
            order_id=d["order_id"],
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            order_type=str(d["order_type"]),
            side=str(d["side"]),
            quantity=float(d["quantity"]),
            limit_price=float(d["limit_price"]) if d.get("limit_price") is not None else None,
            stop_price=float(d["stop_price"]) if d.get("stop_price") is not None else None,
            status=str(d.get("status", "SUBMITTED")),
            filled_quantity=float(d.get("filled_quantity", 0.0)),
            filled_price=float(d.get("filled_price", 0.0)),
            average_fill_price=float(d.get("average_fill_price", 0.0)),
            order_metadata=d.get("order_metadata", {}),
            strategy_id=str(d["strategy_id"]),
            experiment_id=str(d.get("experiment_id", "")),
            decision_snapshot_id=str(d.get("decision_snapshot_id", "")),
            version=str(d.get("version", "v1")),
        )

    @property
    def signed_quantity(self) -> float:
        """Derive signed quantity from side and positive quantity.

        BUY → positive, SELL → negative.
        This is the convention used by Position and Fill models.
        """
        if self.side == "BUY":
            return self.quantity
        else:  # SELL
            return -self.quantity

    @property
    def remaining_quantity(self) -> float:
        """Quantity not yet filled: quantity - filled_quantity."""
        return self.quantity - self.filled_quantity

    @property
    def is_done(self) -> bool:
        """Order is fully filled or cancelled/rejected."""
        return self.status in ("FILLED", "CANCELLED", "REJECTED")

    @property
    def is_active(self) -> bool:
        """Order is still active (submitted, partially filled)."""
        return self.status in ("SUBMITTED", "PARTIALLY_FILLED")

    @property
    def is_buy(self) -> bool:
        """Check if this is a BUY order."""
        return self.side == "BUY"

    @property
    def is_sell(self) -> bool:
        """Check if this is a SELL order."""
        return self.side == "SELL"


@dataclass(frozen=True)
class OrderSide:
    """Legacy alias — use Order.side instead.

    Deprecated: Order.side is BUY/SELL, not signed quantity.
    Keeping for backward compatibility only.
    """

    value: str

    @property
    def is_buy(self) -> bool:
        return self.value == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.value == "SELL"
