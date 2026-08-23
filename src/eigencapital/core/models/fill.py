"""Domain model: Fill.

Individual fill execution.

Invariants:
- quantity is ALWAYS positive (executed quantity this fill)
- side must equal Order.side (enforced by OrderLifecycle invariant)
- fill_type: FULL, PARTIAL, CANCELLED
- liquidity_indicator: TAKER, MAKER
- fill_price respects order's limit/stop constraints
- Fill.side == Order.side AND Fill.instrument_id == Order.instrument_id
- Aggregate invariant: sum(fills.quantity) <= Order.quantity (in OrderLifecycle, not per-fill)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, ClassVar
import math


@dataclass(frozen=True)
class Fill:
    """Individual fill execution records.

    Key invariants (enforced at OrderLifecycle level, not per-fill):
    1. Fill.quantity > 0 — always positive executed quantity
    2. Fill.side == Order.side — must match the order's side
    3. Fill.instrument_id == Order.instrument_id — must match the order's instrument
    4. Aggregate: sum(fills.quantity) <= Order.quantity — managed by OrderLifecycle

    Individual Fill model only validates its own fields; the lifecycle
    validator checks the aggregate constraint.

    Attributes:
        fill_id: Unique identifier
        order_id: FK → Order
        instrument_id: FK → Instrument (must match Order.instrument_id)
        timestamp_utc: When fill occurred
        quantity: ALWAYS positive — executed quantity this fill
        side: BUY or SELL — must equal Order.side
        fill_price: Execution price
        commission: Broker commission (>= 0)
        fees: Exchange/regulatory fees (>= 0)
        fill_type: FULL, PARTIAL, CANCELLED
        liquidity_indicator: TAKER, MAKER
        counterparty: Venue/broker identifier
        execution_venue: Where the fill occurred
        strategy_id: Which strategy generated the order
        experiment_id: Linked experiment (if any)
        version: Version for change tracking
    """

    fill_id: str
    order_id: str  # FK → Order
    instrument_id: str
    timestamp_utc: str  # ISO-8601 UTC when fill occurred
    quantity: float  # ALWAYS positive
    side: str  # BUY or SELL — must equal Order.side
    fill_price: float
    commission: float = 0.0
    fees: float = 0.0
    fill_type: str = "FULL"  # FULL, PARTIAL, CANCELLED
    liquidity_indicator: str = "TAKER"  # TAKER, MAKER
    counterparty: str = ""
    execution_venue: str = ""
    strategy_id: str = ""
    experiment_id: str = ""
    version: str = "v1"

    # Class-level registry

    def __post_init__(self) -> None:
        # INVARIANT: quantity is ALWAYS positive
        if self.quantity <= 0:
            raise ValueError(
                f"Fill quantity must be > 0, got {self.quantity}. "
                "Fill quantity is always positive (executed quantity)."
            )

        # INVARIANT: Fill.side must equal Order.side (checked at OrderLifecycle level;
        # we at least validate side is BUY or SELL here)
        if self.side not in ("BUY", "SELL"):
            raise ValueError(
                f"Fill side must be 'BUY' or 'SELL', got '{self.side}'"
            )

        # INVARIANT: Fill.instrument_id must match Order.instrument_id
        # We validate instrument_id is non-empty; the cross-order check is lifecycle-level
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")

        # Validate timestamp is ISO-8601 UTC
        if "T" not in self.timestamp_utc:
            raise ValueError(
                f"timestamp_utc should be ISO-8601 format, got: {self.timestamp_utc}"
            )

        # Validate fill_price is finite and positive
        if math.isnan(self.fill_price) or math.isinf(self.fill_price):
            raise ValueError("fill_price must be finite (no NaN/infinity)")
        if self.fill_price <= 0:
            raise ValueError("fill_price must be > 0")

        # Validate commission is non-negative if provided
        if self.commission < 0:
            raise ValueError("commission must be >= 0")

        # Validate fees is non-negative if provided
        if self.fees < 0:
            raise ValueError("fees must be >= 0")

        # Validate fill_type is known
        valid_fill_types = {"FULL", "PARTIAL", "CANCELLED"}
        if self.fill_type not in valid_fill_types:
            raise ValueError(
                f"Invalid fill_type: {self.fill_type}. Must be one of {valid_fill_types}"
            )

        # Validate liquidity_indicator
        valid_liquidity = {"TAKER", "MAKER"}
        if self.liquidity_indicator not in valid_liquidity:
            raise ValueError(
                f"Invalid liquidity_indicator: {self.liquidity_indicator}. "
                f"Must be one of {valid_liquidity}"
            )

        # Validate strategy_id is non-empty (required for accountability)
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty (required for accountability)")

        # Registry check for duplicate fill_id
        if self.fill_id in self._registry:
            raise ValueError(f"Duplicate fill_id: {self.fill_id}. Fill IDs must be unique.")
        self._registry[self.fill_id] = (self.fill_id, self.order_id, self.instrument_id, self.side, self.quantity)

    def __hash__(self) -> int:
        return hash((self.fill_id, self.order_id, self.side))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Fill):
            return NotImplemented
        return self.fill_id == other.fill_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "instrument_id": self.instrument_id,
            "timestamp_utc": self.timestamp_utc,
            "quantity": self.quantity,
            "side": self.side,
            "fill_price": self.fill_price,
            "commission": self.commission,
            "fees": self.fees,
            "fill_type": self.fill_type,
            "liquidity_indicator": self.liquidity_indicator,
            "counterparty": self.counterparty,
            "execution_venue": self.execution_venue,
            "strategy_id": self.strategy_id,
            "experiment_id": self.experiment_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Fill:
        """Deserialize from dict (deterministic, keys sorted)."""
        return Fill(
            fill_id=d["fill_id"],
            order_id=d["order_id"],
            instrument_id=d["instrument_id"],
            timestamp_utc=str(d["timestamp_utc"]),
            quantity=float(d["quantity"]),
            side=str(d["side"]),
            fill_price=float(d["fill_price"]),
            commission=float(d.get("commission", 0.0)),
            fees=float(d.get("fees", 0.0)),
            fill_type=str(d.get("fill_type", "FULL")),
            liquidity_indicator=str(d.get("liquidity_indicator", "TAKER")),
            counterparty=str(d.get("counterparty", "")),
            execution_venue=str(d.get("execution_venue", "")),
            strategy_id=str(d["strategy_id"]),
            experiment_id=str(d.get("experiment_id", "")),
            version=str(d.get("version", "v1")),
        )

    @property
    def is_full(self) -> bool:
        """Check if this is a full fill."""
        return self.fill_type == "FULL"

    @property
    def is_partial(self) -> bool:
        """Check if this is a partial fill."""
        return self.fill_type == "PARTIAL"

    @property
    def is_cancelled(self) -> bool:
        """Check if this fill was cancelled."""
        return self.fill_type == "CANCELLED"

    @property
    def taker(self) -> bool:
        """Check if this was a taker fill."""
        return self.liquidity_indicator == "TAKER"

    @property
    def maker(self) -> bool:
        """Check if this was a maker fill."""
        return self.liquidity_indicator == "MAKER"


@dataclass(frozen=True)
class FillSide:
    """Legacy alias — use Fill.side instead.

    Deprecated: Fill.side is BUY/SELL, matching Order.side.
    Keeping for backward compatibility only.
    """

    value: str

    @property
    def is_buy(self) -> bool:
        return self.value == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.value == "SELL"


Fill._registry = {}
