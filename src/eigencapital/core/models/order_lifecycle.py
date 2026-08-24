"""Domain model: OrderLifecycle.

Aggregate order lifecycle invariant management.

Critical design decision: The invariant `sum(fills.quantity) <= order.quantity`
belongs in OrderLifecycle, NOT in the individual Fill model.

Individual Fill model only validates its own fields (quantity > 0, side matches order,
instrument_id matches order). The lifecycle validator checks the aggregate constraint.

This separation is important because:
- Two fills of 60 each on a 100-share order are individually valid
- But aggregate: 60 + 60 = 120 > 100 violates the order-level constraint
- The Fill model cannot access the order's remaining quantity (aggregate state)
- The OrderLifecycle model has access to all fills for the order

Responsibilities:
- Track all fills associated with an order
- Validate aggregate: sum(fills.quantity) <= order.quantity
- Provide remaining_quantity: order.quantity - sum(fills.quantity)
- Detect overfill attempts
- Manage order status transitions based on fill state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class OrderLifecycle:
    """Aggregate order lifecycle invariant manager.

    The key invariant: sum(fills.quantity) <= order.quantity

    This belongs in the lifecycle manager, not in the individual Fill model,
    because Fill cannot access the order's remaining quantity (aggregate state).

    Example:
        Order = 100
        Fill A = 60  ← individually valid (60 > 0, side matches, etc.)
        Fill B = 40  ← individually valid
        Aggregate: 60 + 40 = 100 <= 100 ✓

        Fill A = 60
        Fill B = 60  ← individually valid, but aggregate: 60 + 60 = 120 > 100 ✗
        The Fill model cannot catch this; only OrderLifecycle can.
    """

    order_id: str
    order_instrument_id: str
    order_side: str  # BUY or SELL
    order_quantity: float  # ALWAYS positive, total order quantity
    status: str = (
        "SUBMITTED"  # SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED
    )

    # Internal tracking: all fills associated with this order
    _fills: Dict[str, float] = field(default_factory=dict)  # fill_id -> filled_quantity

    # Class-level tracking across all lifecycles

    def __post_init__(self) -> None:
        # Validate order_quantity is positive
        if self.order_quantity <= 0:
            raise ValueError(f"Order quantity must be > 0, got {self.order_quantity}")

        # Validate order_side is BUY or SELL
        if self.order_side not in ("BUY", "SELL"):
            raise ValueError(
                f"Order side must be 'BUY' or 'SELL', got '{self.order_side}'"
            )

        # Validate status is known
        valid_statuses = {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }
        if self.status not in valid_statuses:
            raise ValueError(
                f"Invalid lifecycle status: {self.status}. "
                f"Must be one of {valid_statuses}"
            )

        # Validate order_id is non-empty
        if not self.order_id:
            raise ValueError("order_id must be non-empty")

        # INVARIANT: Initialize with zero fills (order starts unfilled)
        # The _fills dict starts empty; fills are added via add_fill()

        # Registry check for duplicate order_id lifecycles
        if self.order_id in self._registry:
            raise ValueError(
                f"Duplicate order_id in lifecycle: {self.order_id}. "
                "Each order can have only one lifecycle."
            )
        self._registry[self.order_id] = True

    def add_fill(self, fill: object) -> None:
        """Add a fill to the lifecycle and validate aggregate invariant.

        Args:
            fill: A Fill dataclass instance. The fill's order_id must match
                  this lifecycle's order_id.

        Raises:
            ValueError: If the aggregate invariant would be violated
                        (sum fills.quantity > order.quantity)
                      If fill_id already exists in this lifecycle
        """
        # Validate fill has required attributes
        if not hasattr(fill, "fill_id"):
            raise ValueError("fill must have a fill_id attribute")
        if not hasattr(fill, "quantity"):
            raise ValueError("fill must have a quantity attribute")

        fill_id = fill.fill_id
        fill_quantity = fill.quantity

        # INVARIANT: fill_id must not already exist in this lifecycle
        if fill_id in self._fills:
            raise ValueError(
                f"Fill ID '{fill_id}' already exists in order lifecycle "
                f"for order {self.order_id}. Duplicate fills are not allowed."
            )

        # INVARIANT: Aggregate check — after adding this fill, total must not exceed order quantity
        potential_total = sum(self._fills.values()) + fill_quantity
        if potential_total > self.order_quantity:
            raise ValueError(
                f"Order lifecycle invariant violated: adding fill {fill_id} "
                f"quantity {fill_quantity} would make total {potential_total} "
                f"exceed order quantity {self.order_quantity}. "
                f"Current total: {sum(self._fills.values())}, "
                f"remaining: {self.order_quantity - sum(self._fills.values())}"
            )

        # Add the fill to tracking
        self._fills[fill_id] = fill_quantity

        # Update status based on fill state
        total_filled = sum(self._fills.values())
        if total_filled >= self.order_quantity and self.status != "FILLED":
            object.__setattr__(self, "status", "FILLED")
        elif total_filled > 0 and self.status == "SUBMITTED":
            object.__setattr__(self, "status", "PARTIALLY_FILLED")

    def remove_fill(self, fill_id: str) -> None:
        """Remove a fill from the lifecycle (e.g., on cancel/replace).

        Args:
            fill_id: The fill_id to remove

        Raises:
            ValueError: If fill_id not found in this lifecycle
        """
        if fill_id not in self._fills:
            raise ValueError(
                f"Fill ID '{fill_id}' not found in order lifecycle for order {self.order_id}"
            )

        self._fills.pop(fill_id)

        # Update status after removal
        total_filled = sum(self._fills.values())
        if total_filled == 0:
            object.__setattr__(self, "status", "SUBMITTED")
        elif total_filled > 0 and self.status == "FILLED":
            # If we had filled the order entirely and now removing a fill,
            # move to partially filled (or SUBMITTED if we want to be conservative)
            object.__setattr__(self, "status", "PARTIALLY_FILLED")

    @property
    def filled_quantity(self) -> float:
        """Cumulative quantity filled across all fills."""
        return sum(self._fills.values())

    @property
    def remaining_quantity(self) -> float:
        """Remaining quantity to be filled: order_quantity - filled_quantity."""
        return self.order_quantity - sum(self._fills.values())

    @property
    def is_fully_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.filled_quantity >= self.order_quantity and self.status == "FILLED"

    @property
    def is_partially_filled(self) -> bool:
        """Check if order is partially filled."""
        return (
            0 < self.filled_quantity < self.order_quantity
            and self.status == "PARTIALLY_FILLED"
        )

    @property
    def is_active(self) -> bool:
        """Check if order is still active (submitted or partially filled)."""
        return self.status in ("SUBMITTED", "PARTIALLY_FILLED", "FILLED")

    @property
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state (filled, cancelled, rejected)."""
        return self.status in ("FILLED", "CANCELLED", "REJECTED")

    @property
    def is_buy(self) -> bool:
        """Check if this is a BUY order."""
        return self.order_side == "BUY"

    @property
    def is_sell(self) -> bool:
        """Check if this is a SELL order."""
        return self.order_side == "SELL"

    def total_commission(self) -> float:
        """Total commission across all fills (if fill objects have commission)."""
        # This would need access to individual fill commissions;
        # for now, return 0 as placeholder
        return 0.0

    def total_fees(self) -> float:
        """Total fees across all fills."""
        return 0.0

    def __repr__(self) -> str:
        return (
            f"OrderLifecycle(order_id='{self.order_id}', "
            f"instrument='{self.order_instrument_id}', "
            f"side={self.order_side}, "
            f"quantity={self.order_quantity}, "
            f"filled={self.filled_quantity}, "
            f"remaining={self.remaining_quantity}, "
            f"status={self.status})"
        )

    def __repr_short__(self) -> str:
        """Short representation."""
        return f"OL({self.order_id[:8]}...){self.status}"


OrderLifecycle._registry = {}
