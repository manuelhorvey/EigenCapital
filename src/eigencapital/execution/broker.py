"""Paper Broker — simulated execution environment.

The PaperBroker accepts only valid Orders, maintains order state,
generates deterministic fills, and maintains simulated positions.

Critical invariant: Paper-only boundary. No live broker connectivity.
No network calls. No external API access.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any

from eigencapital.core.models.order import Order
from eigencapital.core.models.fill import Fill


class BrokerError(ValueError):
    """Raised on broker-level errors."""

    pass


class OrderLifecycleState(str, Enum):
    """Explicit order lifecycle states."""

    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class PaperBroker:
    """Simulated broker for paper trading.

    The PaperBroker:
    - Accepts only valid Orders
    - Maintains order state
    - Generates deterministic fills
    - Maintains simulated positions
    - Exposes account state
    - Never connects to external services

    Attributes:
        initial_capital: Starting cash balance
        spread_ticks: Simulated spread in tick units
        slippage_ticks: Simulated slippage in tick units
        fill_probability: Probability of fill (0-1)
        deterministic_seed: For reproducible simulation
    """

    initial_capital: float = 100000.0
    spread_ticks: float = 1.0
    slippage_ticks: float = 0.5
    fill_probability: float = 1.0
    deterministic_seed: Optional[int] = None

    def __post_init__(self) -> None:
        self._orders: Dict[str, Order] = {}
        self._order_states: Dict[str, OrderLifecycleState] = {}
        self._fills: Dict[str, List[Fill]] = {}
        self._positions: Dict[str, float] = {}  # instrument_id → signed quantity
        self._cash: float = self.initial_capital
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self._rejected_orders: List[str] = []

    def submit_order(self, order: Order) -> str:
        """Submit an order to the paper broker.

        Args:
            order: Valid Order object

        Returns:
            order_id for tracking

        Raises:
            BrokerError: If order is invalid
        """
        # Validate order
        if order.quantity <= 0:
            raise BrokerError(f"Order quantity must be positive, got {order.quantity}")

        if order.instrument_id in self._order_states:
            existing = self._order_states[order.instrument_id]
            if existing in (
                OrderLifecycleState.SUBMITTED,
                OrderLifecycleState.PARTIALLY_FILLED,
            ):
                raise BrokerError(
                    f"Order already active for {order.instrument_id}: {existing.value}"
                )

        # Store order
        self._orders[order.instrument_id] = order
        self._order_states[order.instrument_id] = OrderLifecycleState.SUBMITTED
        self._fills[order.instrument_id] = []

        return order.instrument_id

    def generate_fill(
        self,
        order_id: str,
        fill_price: float,
        fill_quantity: Optional[float] = None,
    ) -> Fill:
        """Generate a deterministic fill for an order.

        Args:
            order_id: Order to fill
            fill_price: Price to fill at
            fill_quantity: Quantity to fill (default: full order)

        Returns:
            Fill object

        Raises:
            BrokerError: If order not found or not fillable
        """
        if order_id not in self._orders:
            raise BrokerError(f"Order not found: {order_id}")

        state = self._order_states[order_id]
        if state in (
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.REJECTED,
        ):
            raise BrokerError(f"Order not fillable: {state.value}")

        order = self._orders[order_id]
        quantity = fill_quantity or order.quantity

        # Validate fill quantity
        existing_fills = self._fills.get(order_id, [])
        total_filled = sum(f.quantity for f in existing_fills)
        remaining = order.quantity - total_filled

        if quantity > remaining:
            quantity = remaining

        if quantity <= 0:
            raise BrokerError("No remaining quantity to fill")

        # Apply slippage
        if order.side == "BUY":
            effective_price = fill_price + self.slippage_ticks * 0.01
        else:
            effective_price = fill_price - self.slippage_ticks * 0.01

        # Create fill
        fill = Fill(
            fill_id=f"FILL-{uuid.uuid4().hex[:8]}",
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=quantity,
            fill_price=effective_price,
            timestamp_utc=order.timestamp_utc,
            strategy_id=order.strategy_id,
        )

        # Store fill
        if order_id not in self._fills:
            self._fills[order_id] = []
        self._fills[order_id].append(fill)

        # Update lifecycle state
        total_filled += quantity
        if total_filled >= order.quantity:
            self._order_states[order_id] = OrderLifecycleState.FILLED
        else:
            self._order_states[order_id] = OrderLifecycleState.PARTIALLY_FILLED

        # Update position
        self._update_position(order, fill)

        return fill

    def _update_position(self, order: Order, fill: Fill) -> None:
        """Update position based on fill."""
        instrument = order.instrument_id
        current = self._positions.get(instrument, 0.0)

        if order.side == "BUY":
            new_position = current + fill.quantity
        else:
            new_position = current - fill.quantity

        self._positions[instrument] = new_position

        # Update cash (simplified — assumes no margin)
        if order.side == "BUY":
            self._cash -= fill.quantity * fill.fill_price
        else:
            self._cash += fill.quantity * fill.fill_price

    def cancel_order(self, order_id: str) -> bool:
        """Request order cancellation."""
        if order_id not in self._orders:
            return False

        state = self._order_states[order_id]
        if state in (OrderLifecycleState.FILLED, OrderLifecycleState.CANCELLED):
            return False

        self._order_states[order_id] = OrderLifecycleState.CANCEL_REQUESTED
        # Simulate immediate cancellation
        self._order_states[order_id] = OrderLifecycleState.CANCELLED
        return True

    def reject_order(self, order_id: str, reason: str = "") -> bool:
        """Reject an order."""
        if order_id not in self._orders:
            return False

        self._order_states[order_id] = OrderLifecycleState.REJECTED
        self._rejected_orders.append(order_id)
        return True

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def get_order_state(self, order_id: str) -> Optional[OrderLifecycleState]:
        """Get order lifecycle state."""
        return self._order_states.get(order_id)

    def get_open_orders(self) -> List[Order]:
        """Get all open (non-filled, non-cancelled, non-rejected) orders."""
        return [
            self._orders[oid]
            for oid, state in self._order_states.items()
            if state
            in (OrderLifecycleState.SUBMITTED, OrderLifecycleState.PARTIALLY_FILLED)
        ]

    def get_positions(self) -> Dict[str, float]:
        """Get current positions."""
        return dict(self._positions)

    def get_cash(self) -> float:
        """Get current cash balance."""
        return self._cash

    def get_account_snapshot(self) -> Dict[str, Any]:
        """Get complete account state."""
        return {
            "cash": self._cash,
            "positions": dict(self._positions),
            "realized_pnl": self._realized_pnl,
            "num_orders": len(self._orders),
            "num_fills": sum(len(f) for f in self._fills.values()),
            "num_rejected": len(self._rejected_orders),
        }

    def reset(self) -> None:
        """Reset broker to initial state."""
        self._orders.clear()
        self._order_states.clear()
        self._fills.clear()
        self._positions.clear()
        self._cash = self.initial_capital
        self._realized_pnl = 0.0
        self._unrealized_pnl = 0.0
        self._rejected_orders.clear()
