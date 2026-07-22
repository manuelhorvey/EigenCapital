"""PortfolioContext — frozen snapshot of portfolio state at decision time.

Captures positions, exposure, PEK budget state, equity, and margin
information as they existed when the decision was made.  Independent
of the inference pipeline — represents the portfolio's side of the
decision boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PositionSnapshot:
    asset: str
    side: str
    notional: float
    entry_price: float
    current_price: float
    unrealized_pnl_pct: float
    mtm_value: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "side": self.side,
            "notional": self.notional,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "mtm_value": self.mtm_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionSnapshot:
        return cls(**data)


@dataclass(frozen=True)
class PortfolioContext:
    total_equity: float
    peak_value: float
    drawdown_pct: float
    gross_exposure: float
    net_exposure: float
    open_position_count: int
    positions: tuple[PositionSnapshot, ...] = ()
    pek_budget_utilization: float = 1.0
    pek_max_risk_per_trade_pct: float | None = None
    pek_max_portfolio_heat: float | None = None
    pek_max_concurrent: int | None = None
    daily_pnl: float = 0.0
    daily_loss_remaining: float | None = None
    max_daily_loss: float | None = None
    leverage_remaining: float | None = None
    max_leverage: float | None = None
    concurrent_remaining: int | None = None
    portfolio_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_equity": self.total_equity,
            "peak_value": self.peak_value,
            "drawdown_pct": self.drawdown_pct,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "open_position_count": self.open_position_count,
            "positions": [p.to_dict() for p in self.positions],
            "pek_budget_utilization": self.pek_budget_utilization,
            "pek_max_risk_per_trade_pct": self.pek_max_risk_per_trade_pct,
            "pek_max_portfolio_heat": self.pek_max_portfolio_heat,
            "pek_max_concurrent": self.pek_max_concurrent,
            "daily_pnl": self.daily_pnl,
            "daily_loss_remaining": self.daily_loss_remaining,
            "max_daily_loss": self.max_daily_loss,
            "leverage_remaining": self.leverage_remaining,
            "max_leverage": self.max_leverage,
            "concurrent_remaining": self.concurrent_remaining,
            "portfolio_mode": self.portfolio_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioContext:
        positions = tuple(PositionSnapshot.from_dict(p) for p in data.get("positions", []))
        return cls(**{**data, "positions": positions})
