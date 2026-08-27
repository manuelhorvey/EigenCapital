"""Domain model: Position.

Three-way position tracking: desired → approved → actual.

Invariants:
- quantity is SIGNED: positive=LONG, negative=SHORT, 0=FLAT
- quantity == 0 ⇒ average_entry_price is None or 0
- average_entry_price is Optional[float] — weighted average fill price
- market_value, unrealized_pnl, realized_pnl_today are currency denominated
- overnight carries across sessions
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class Position:
    """Three-way position: desired → approved → actual.

    The quantity sign encodes direction:
    - quantity > 0 → LONG
    - quantity < 0 → SHORT
    - quantity = 0 → FLAT

    Critical: average_entry_price is None when quantity == 0.

    Attributes:
        instrument_id: FK → Instrument
        quantity: SIGNED quantity (contracts / shares / units)
        average_entry_price: Weighted average fill price; None if flat
        market_value: Mark-to-market value (currency)
        unrealized_pnl: Floating P&L (currency)
        realized_pnl_today: P&L from fills today (currency)
        overnight: Carried across sessions?
        version: Version for change tracking
    """

    instrument_id: str
    quantity: float  # SIGNED: positive=LONG, negative=SHORT, 0=FLAT
    average_entry_price: float | None = None
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    overnight: bool = False
    version: str = "v1"

    def __post_init__(self) -> None:
        # Validate quantity is numeric
        if not isinstance(self.quantity, (int, float)):
            raise ValueError(f"quantity must be numeric, got {type(self.quantity)}")

        # Validate prices are finite if present
        if self.average_entry_price is not None:
            if not isinstance(self.average_entry_price, (int, float)):
                raise ValueError(f"average_entry_price must be numeric, got {type(self.average_entry_price)}")
            if math.isnan(self.average_entry_price) or math.isinf(self.average_entry_price):
                raise ValueError("average_entry_price must be finite (no NaN/infinity)")

        # Validate market_value is finite if non-zero
        if self.market_value != 0.0:
            if not isinstance(self.market_value, (int, float)):
                raise ValueError("market_value must be numeric")
            if math.isnan(self.market_value) or math.isinf(self.market_value):
                raise ValueError("market_value must be finite (no NaN/infinity)")

        # Validate unrealized_pnl is finite
        if not math.isnan(self.unrealized_pnl) and not math.isinf(self.unrealized_pnl):
            if not isinstance(self.unrealized_pnl, (int, float)):
                raise ValueError("unrealized_pnl must be numeric")

        # Validate realized_pnl_today is finite
        if not math.isnan(self.realized_pnl_today) and not math.isinf(self.realized_pnl_today):
            if not isinstance(self.realized_pnl_today, (int, float)):
                raise ValueError("realized_pnl_today must be numeric")

        # INVARIANT: quantity == 0 ⇒ average_entry_price is None or 0
        if self.quantity == 0 and self.average_entry_price not in (None, 0):
            raise ValueError(
                f"Invariant violated: quantity == 0 but average_entry_price "
                f"is {self.average_entry_price}. "
                f"When flat, average_entry_price must be None or 0."
            )

        # Validate quantity is not NaN/inf
        if math.isnan(self.quantity) or math.isinf(self.quantity):
            raise ValueError("quantity must be finite (no NaN/infinity)")

        # Registry check for duplicate position (same instrument+quantity)
        key = (self.instrument_id, self.quantity)
        if key in self.__class__._registry:
            raise ValueError(
                f"Duplicate Position: instrument={self.instrument_id}, "
                f"quantity={self.quantity}. "
                f"Positions must be unique per instrument+quantity."
            )
        self.__class__._registry[key] = key

    def __hash__(self) -> int:
        return hash((self.instrument_id, self.quantity))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return self.instrument_id == other.instrument_id and self.quantity == other.quantity

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "average_entry_price": self.average_entry_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl_today": self.realized_pnl_today,
            "overnight": self.overnight,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Position:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Position(
            instrument_id=d["instrument_id"],
            quantity=float(d["quantity"]),
            average_entry_price=(float(d["average_entry_price"]) if d.get("average_entry_price") is not None else None),
            market_value=float(d["market_value"]),
            unrealized_pnl=float(d["unrealized_pnl"]),
            realized_pnl_today=float(d["realized_pnl_today"]),
            overnight=bool(d.get("overnight", False)),
            version=str(d.get("version", "v1")),
        )

    @property
    def side(self) -> str:
        """Derive side from quantity sign.

        Note: No separate position_side field — sign encodes direction.
        """
        if self.quantity > 0:
            return "LONG"
        elif self.quantity < 0:
            return "SHORT"
        else:
            return "FLAT"

    @property
    def is_flat(self) -> bool:
        """Check if position is flat (quantity = 0)."""
        return self.quantity == 0

    @property
    def is_long(self) -> bool:
        """Check if position is long (quantity > 0)."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short (quantity < 0)."""
        return self.quantity < 0

    @property
    def entry_price(self) -> float | None:
        """Convenience: average_entry_price alias."""
        return self.average_entry_price

    @property
    def notional(self) -> float:
        """Gross notional exposure: |quantity| * |entry_price proxy|.

        For simplicity, we use market_value as the proxy when available.
        """
        if self.market_value != 0.0:
            return abs(self.quantity) * abs(self.market_value / max(abs(self.quantity), 1))
        return 0.0


Position._registry = {}
