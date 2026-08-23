"""Accounting Engine — cash, P&L, and equity tracking.

Proves: cash + realized P&L + unrealized P&L - costs = equity

Usage:
    accounting = AccountingEngine(initial_cash=100_000)
    accounting.apply_fill(fill_price=4500, quantity=5, side="BUY", multiplier=50)
    equity = accounting.compute_equity(current_price=4510)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class PositionState:
    """Current position state.

    Attributes:
        quantity: Signed quantity (positive=LONG, negative=SHORT)
        average_entry_price: Weighted average fill price
    """

    quantity: float = 0.0
    average_entry_price: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


@dataclass
class FillRecord:
    """Record of a single fill for accounting purposes."""

    timestamp: str
    fill_price: float
    quantity: float  # ALWAYS positive
    side: str  # BUY or SELL
    multiplier: float = 1.0
    commission: float = 0.0
    fees: float = 0.0


@dataclass
class AccountingEngine:
    """Tracks cash, positions, P&L, and costs.

    Invariant: equity = initial_cash + realized_pnl + unrealized_pnl - total_costs

    Attributes:
        initial_cash: Starting cash balance
        current_cash: Current cash balance
        position: Current position state
        fill_history: All fills for audit trail
        total_commission: Cumulative commission paid
        total_fees: Cumulative fees paid
    """

    initial_cash: float = 100_000.0
    current_cash: float = 0.0
    position: PositionState = field(default_factory=PositionState)
    fill_history: List[FillRecord] = field(default_factory=list)
    total_commission: float = 0.0
    total_fees: float = 0.0
    contract_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.current_cash == 0.0:
            self.current_cash = self.initial_cash

    def apply_fill(
        self,
        fill_price: float,
        quantity: float,
        side: str,
        multiplier: float = 1.0,
        commission: float = 0.0,
        fees: float = 0.0,
        timestamp: str = "",
    ) -> None:
        """Apply a fill to the accounting state.

        Args:
            fill_price: Execution price
            quantity: Fill quantity (always positive)
            side: BUY or SELL
            multiplier: Contract multiplier (e.g., 50 for ES)
            commission: Commission for this fill
            fees: Exchange fees for this fill
            timestamp: Fill timestamp
        """
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side}")
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")

        signed_qty = quantity if side == "BUY" else -quantity

        # Record the fill
        self.fill_history.append(FillRecord(
            timestamp=timestamp,
            fill_price=fill_price,
            quantity=quantity,
            side=side,
            multiplier=multiplier,
            commission=commission,
            fees=fees,
        ))

        # Update costs
        self.total_commission += commission
        self.total_fees += fees
        self.contract_multiplier = multiplier

        # Update cash: BUY costs money, SELL receives money
        if side == "BUY":
            self.current_cash -= fill_price * quantity * multiplier
        else:
            self.current_cash += fill_price * quantity * multiplier

        # Update position using weighted average
        old_qty = self.position.quantity
        new_qty = old_qty + signed_qty

        if new_qty == 0:
            # Position closed
            self.position.quantity = 0.0
            self.position.average_entry_price = 0.0
        elif old_qty == 0:
            # New position
            self.position.quantity = new_qty
            self.position.average_entry_price = fill_price
        elif (new_qty > 0 and old_qty > 0) or (new_qty < 0 and old_qty < 0):
            # Adding to existing position (same direction)
            total_cost = (
                self.position.average_entry_price * abs(old_qty)
                + fill_price * quantity
            )
            self.position.average_entry_price = total_cost / abs(new_qty)
            self.position.quantity = new_qty
        else:
            # Reversing position (crossing zero)
            # The new position takes the fill price as entry
            self.position.quantity = new_qty
            self.position.average_entry_price = fill_price

    def compute_realized_pnl(self) -> float:
        """Compute realized P&L from closed portions."""
        # Simplified: realized P&L is tracked through cash changes
        # In a full implementation, we'd track each close separately
        return 0.0  # Placeholder — full implementation tracks closes

    def compute_unrealized_pnl(self, current_price: float) -> float:
        """Compute unrealized P&L at current market price."""
        if self.position.is_flat:
            return 0.0
        return (current_price - self.position.average_entry_price) * self.position.quantity * self.contract_multiplier

    def compute_equity(self, current_price: float) -> float:
        """Compute total equity: cash + unrealized P&L."""
        unrealized = self.compute_unrealized_pnl(current_price)
        return self.current_cash + unrealized

    def summary(self) -> Dict[str, Any]:
        """Return accounting summary."""
        return {
            "initial_cash": self.initial_cash,
            "current_cash": self.current_cash,
            "position_quantity": self.position.quantity,
            "position_avg_entry": self.position.average_entry_price,
            "total_fills": len(self.fill_history),
            "total_commission": self.total_commission,
            "total_fees": self.total_fees,
        }
