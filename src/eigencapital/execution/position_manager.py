"""Position Manager — tracks positions from fills.

Position quantity remains signed:
    quantity > 0 → LONG
    quantity < 0 → SHORT
    quantity = 0 → FLAT

Never introduces a separate authoritative "position_side".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from eigencapital.core.models.fill import Fill


@dataclass
class PositionRecord:
    """Position record for a single instrument.

    Attributes:
        instrument_id: Instrument identifier
        quantity: Signed quantity (positive = long, negative = short)
        average_entry_price: Weighted average entry price
        realized_pnl: Realized P&L from closed portions
        unrealized_pnl: Unrealized P&L from open position
        fills: List of fills that created this position
    """

    instrument_id: str
    quantity: float = 0.0
    average_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fills: List[Fill] = field(default_factory=list)

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < 1e-10

    @property
    def notional(self) -> float:
        return abs(self.quantity) * self.average_entry_price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "average_entry_price": self.average_entry_price,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "num_fills": len(self.fills),
        }


class PositionManager:
    """Manages positions from fills.

    Updates positions deterministically from fill events.
    Tracks average entry price and realized/unrealized P&L.
    """

    def __init__(self) -> None:
        self._positions: Dict[str, PositionRecord] = {}

    def update_from_fill(self, fill: Fill, current_price: float | None = None) -> PositionRecord:
        """Update position from a fill.

        Args:
            fill: Fill event
            current_price: Current market price for unrealized P&L

        Returns:
            Updated PositionRecord
        """
        instrument = fill.instrument_id

        if instrument not in self._positions:
            self._positions[instrument] = PositionRecord(instrument_id=instrument)

        pos = self._positions[instrument]
        old_quantity = pos.quantity

        # Update quantity
        if fill.side == "BUY":
            new_quantity = old_quantity + fill.quantity
        else:
            new_quantity = old_quantity - fill.quantity

        # Calculate realized P&L on closed/reduced portions
        if old_quantity != 0 and new_quantity != 0:
            # Check if we're reducing or crossing through zero
            if abs(new_quantity) < abs(old_quantity):
                # Reducing position
                closed_qty = fill.quantity
                if old_quantity > 0:
                    realized = closed_qty * (fill.fill_price - pos.average_entry_price)
                else:
                    realized = closed_qty * (pos.average_entry_price - fill.fill_price)
                pos.realized_pnl += realized
            elif (old_quantity > 0 and new_quantity < 0) or (old_quantity < 0 and new_quantity > 0):
                # Crossing through zero
                closed_qty = abs(old_quantity)
                if old_quantity > 0:
                    realized = closed_qty * (fill.fill_price - pos.average_entry_price)
                else:
                    realized = closed_qty * (pos.average_entry_price - fill.fill_price)
                pos.realized_pnl += realized
        elif old_quantity == 0:
            # Opening new position
            pos.average_entry_price = fill.fill_price
        elif new_quantity == 0:
            # Closing position
            closed_qty = abs(old_quantity)
            if old_quantity > 0:
                realized = closed_qty * (fill.fill_price - pos.average_entry_price)
            else:
                realized = closed_qty * (pos.average_entry_price - fill.fill_price)
            pos.realized_pnl += realized

        # Update average entry price for increasing positions
        if abs(new_quantity) > abs(old_quantity) and old_quantity != 0:
            total_cost = pos.average_entry_price * abs(old_quantity) + fill.fill_price * fill.quantity
            pos.average_entry_price = total_cost / abs(new_quantity)
        elif old_quantity == 0:
            pos.average_entry_price = fill.fill_price

        pos.quantity = new_quantity
        pos.fills.append(fill)

        # Update unrealized P&L
        if current_price is not None and not pos.is_flat:
            if pos.is_long:
                pos.unrealized_pnl = pos.quantity * (current_price - pos.average_entry_price)
            else:
                pos.unrealized_pnl = pos.quantity * (pos.average_entry_price - current_price)
        else:
            pos.unrealized_pnl = 0.0

        return pos

    def get_position(self, instrument_id: str) -> PositionRecord | None:
        """Get position for an instrument."""
        return self._positions.get(instrument_id)

    def get_all_positions(self) -> Dict[str, PositionRecord]:
        """Get all positions."""
        return dict(self._positions)

    def get_total_realized_pnl(self) -> float:
        """Get total realized P&L across all positions."""
        return sum(p.realized_pnl for p in self._positions.values())

    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L across all positions."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    def get_gross_exposure(self) -> float:
        """Get total gross exposure."""
        return sum(abs(p.notional) for p in self._positions.values())

    def get_net_exposure(self) -> float:
        """Get total net exposure."""
        return sum(p.notional for p in self._positions.values())

    def reset(self) -> None:
        """Reset all positions."""
        self._positions.clear()
