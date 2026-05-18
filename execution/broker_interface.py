from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Order:
    asset: str
    side: str  # buy or sell
    quantity: float
    order_type: str  # market, limit, stop
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    timestamp: Optional[datetime] = None
    order_id: Optional[str] = None
    status: str = "pending"


@dataclass
class Position:
    asset: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float


@dataclass
class AccountSummary:
    total_cash: float
    buying_power: float
    portfolio_value: float
    positions: List[Position]


class BrokerInterface(ABC):
    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        ...

    @abstractmethod
    def get_account_summary(self) -> AccountSummary:
        ...

    @abstractmethod
    def place_order(self, order: Order) -> str:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        ...

    @abstractmethod
    def get_positions(self) -> List[Position]:
        ...

    @abstractmethod
    def get_current_price(self, asset: str) -> float:
        ...
