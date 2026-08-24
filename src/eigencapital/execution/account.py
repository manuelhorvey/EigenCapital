"""Account State — paper trading accounting engine.

Maintains:
- starting cash
- cash
- equity
- realized P&L
- unrealized P&L
- gross/net exposure
- timestamp

Accounting is derived from authoritative events (fills).
Do not maintain multiple competing sources of truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class AccountSnapshot:
    """Immutable snapshot of account state.

    Attributes:
        timestamp_utc: When snapshot was taken
        cash: Current cash balance
        equity: Total equity (cash + unrealized P&L)
        realized_pnl: Total realized P&L
        unrealized_pnl: Total unrealized P&L
        gross_exposure: Total gross exposure
        net_exposure: Total net exposure
        num_positions: Number of open positions
        provenance_hash: Deterministic hash
    """

    timestamp_utc: str = ""
    cash: float = 0.0
    equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    num_positions: int = 0
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "cash": self.cash,
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "num_positions": self.num_positions,
        }

    def compute_hash(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AccountState:
    """Mutable account state for paper trading.

    Tracks cash, equity, P&L, and exposure.
    All state changes are derived from fills.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._realized_pnl = 0.0
        self._unrealized_pnl = 0.0
        self._gross_exposure = 0.0
        self._net_exposure = 0.0
        self._num_positions = 0

    def update_from_fill(
        self,
        side: str,
        quantity: float,
        price: float,
        timestamp: str = "",
    ) -> None:
        """Update account from a fill.

        Args:
            side: "buy" or "sell"
            quantity: Fill quantity (always positive)
            price: Fill price
            timestamp: Fill timestamp
        """
        if side == "buy":
            self._cash -= quantity * price
        else:
            self._cash += quantity * price

    def update_positions(
        self,
        gross_exposure: float,
        net_exposure: float,
        num_positions: int,
        unrealized_pnl: float,
    ) -> None:
        """Update account from position state."""
        self._gross_exposure = gross_exposure
        self._net_exposure = net_exposure
        self._num_positions = num_positions
        self._unrealized_pnl = unrealized_pnl

    def update_realized_pnl(self, realized_pnl: float) -> None:
        """Update realized P&L."""
        self._realized_pnl = realized_pnl

    @property
    def equity(self) -> float:
        """Total equity = cash + unrealized P&L."""
        return self._cash + self._unrealized_pnl

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def unrealized_pnl(self) -> float:
        return self._unrealized_pnl

    @property
    def gross_exposure(self) -> float:
        return self._gross_exposure

    @property
    def net_exposure(self) -> float:
        return self._net_exposure

    def snapshot(self, timestamp: str = "") -> AccountSnapshot:
        """Create immutable snapshot of current state."""
        snap = AccountSnapshot(
            timestamp_utc=timestamp,
            cash=self._cash,
            equity=self.equity,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=self._unrealized_pnl,
            gross_exposure=self._gross_exposure,
            net_exposure=self._net_exposure,
            num_positions=self._num_positions,
        )
        return AccountSnapshot(
            **{**snap.__dict__, "provenance_hash": snap.compute_hash()}
        )

    def reset(self) -> None:
        """Reset to initial state."""
        self._cash = self._initial_capital
        self._realized_pnl = 0.0
        self._unrealized_pnl = 0.0
        self._gross_exposure = 0.0
        self._net_exposure = 0.0
        self._num_positions = 0
