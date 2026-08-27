"""Execution Boundary Contracts — strict interfaces for production execution.

Defines:
- BrokerAdapter: abstract broker interface
- ShadowBrokerAdapter: records what WOULD have been submitted
- LiveBrokerAdapter: interface only (not implemented in 1N)
- ExecutionMode: PAPER / SHADOW / LIVE
- LiveAuthorization: explicit authorization boundary
- ExecutionBoundary: all broker execution passes through one boundary
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple


class ExecutionMode(str, Enum):
    """Execution mode."""

    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class OrderResult(str, Enum):
    """Result of order submission."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"
    UNAUTHORIZED = "unauthorized"
    BROKER_UNAVAILABLE = "broker_unavailable"
    KILL_SWITCH_ACTIVE = "kill_switch_active"


@dataclass(frozen=True)
class BrokerOrder:
    """Order submitted to broker adapter."""

    order_id: str
    instrument_id: str
    side: str  # "BUY" or "SELL"
    quantity: float
    order_type: str  # "MARKET", "LIMIT"
    limit_price: float | None = None
    timestamp_utc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass(frozen=True)
class BrokerFill:
    """Fill from broker adapter."""

    fill_id: str
    order_id: str
    instrument_id: str
    side: str
    quantity: float
    price: float
    timestamp_utc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "timestamp_utc": self.timestamp_utc,
        }


class BrokerAdapter(ABC):
    """Abstract broker adapter interface.

    All broker execution must pass through this interface.
    No strategy, portfolio, or risk component may directly access a broker.
    """

    @abstractmethod
    def submit_order(self, order: BrokerOrder) -> Tuple[OrderResult, str]:
        """Submit an order.

        Returns:
            (OrderResult, message)
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Dict[str, Any] | None:
        """Get order status."""
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, float]:
        """Get current positions."""
        pass

    @abstractmethod
    def get_account_state(self) -> Dict[str, Any]:
        """Get account state."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check broker health."""
        pass


@dataclass
class ShadowBrokerAdapter(BrokerAdapter):
    """Shadow broker adapter — records what WOULD have been submitted.

    Never submits real orders. Records hypothetical orders for analysis.
    """

    _orders: Dict[str, BrokerOrder] = field(default_factory=dict)
    _fills: List[BrokerFill] = field(default_factory=list)
    _order_counter: int = 0

    def submit_order(self, order: BrokerOrder) -> Tuple[OrderResult, str]:
        """Record what would have been submitted."""
        self._order_counter += 1
        self._orders[order.order_id] = order
        return (OrderResult.ACCEPTED, f"Shadow order {order.order_id} recorded")

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            del self._orders[order_id]
            return True
        return False

    def get_order(self, order_id: str) -> Dict[str, Any] | None:
        order = self._orders.get(order_id)
        return order.to_dict() if order else None

    def get_positions(self) -> Dict[str, float]:
        return {}

    def get_account_state(self) -> Dict[str, Any]:
        return {"mode": "shadow", "orders_recorded": self._order_counter}

    def health_check(self) -> bool:
        return True

    def get_recorded_orders(self) -> List[BrokerOrder]:
        return list(self._orders.values())

    def get_recorded_fills(self) -> List[BrokerFill]:
        return list(self._fills)


@dataclass(frozen=True)
class LiveAuthorization:
    """Explicit authorization for live execution.

    Must be explicit and independently verifiable.
    Default: LIVE = DISABLED
    """

    live_enabled: bool = False
    authorization_token: str = ""
    config_fingerprint: str = ""
    risk_fingerprint: str = ""
    strategy_fingerprint: str = ""
    broker_fingerprint: str = ""
    expiry_timestamp: str = ""
    approver: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "live_enabled": self.live_enabled,
            "authorization_token": self.authorization_token,
            "config_fingerprint": self.config_fingerprint,
            "risk_fingerprint": self.risk_fingerprint,
            "strategy_fingerprint": self.strategy_fingerprint,
            "broker_fingerprint": self.broker_fingerprint,
            "expiry_timestamp": self.expiry_timestamp,
            "approver": self.approver,
        }

    def is_valid(self) -> bool:
        """Check if authorization is valid for live execution."""
        if not self.live_enabled:
            return False
        if not self.authorization_token:
            return False
        if not self.config_fingerprint:
            return False
        return True

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class ExecutionBoundary:
    """All broker execution must pass through one boundary.

    Enforces:
    - Execution mode check
    - Authorization check
    - Kill switch check
    - Risk boundary check
    - Market data freshness check
    """

    mode: ExecutionMode = ExecutionMode.PAPER
    authorization: LiveAuthorization = field(default_factory=LiveAuthorization)
    kill_switch_active: bool = False
    risk_boundary_healthy: bool = True
    market_data_fresh: bool = True
    broker_healthy: bool = True

    def authorize_order(
        self,
        order: BrokerOrder,
        broker: BrokerAdapter,
    ) -> Tuple[OrderResult, str]:
        """Authorize and submit an order through the boundary.

        Returns:
            (OrderResult, message)
        """
        # Check kill switch
        if self.kill_switch_active:
            return (OrderResult.KILL_SWITCH_ACTIVE, "Kill switch is active")

        # Check risk boundary
        if not self.risk_boundary_healthy:
            return (OrderResult.REJECTED, "Risk boundary unhealthy")

        # Check market data
        if not self.market_data_fresh:
            return (OrderResult.REJECTED, "Market data stale")

        # Check broker health
        if not self.broker_healthy:
            return (OrderResult.BROKER_UNAVAILABLE, "Broker unavailable")

        # Check execution mode
        if self.mode == ExecutionMode.LIVE:
            if not self.authorization.is_valid():
                return (
                    OrderResult.UNAUTHORIZED,
                    "Live authorization invalid or missing",
                )
            # In 1N, live is always blocked
            return (OrderResult.UNAUTHORIZED, "Live execution disabled in Phase 1N")

        # Submit to broker
        return broker.submit_order(order)
