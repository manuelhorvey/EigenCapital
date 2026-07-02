from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Portfolio:
    total_capital: float
    cash_buffer: float = 0.0
    peak_value: float = 0.0
    start_date: datetime | None = None
    last_update: datetime | None = None
    asset_allocations: dict[str, float] = field(default_factory=dict)
    risk_parity_weights: dict[str, float] = field(default_factory=dict)

    @property
    def allocated_capital(self) -> float:
        return sum(self.asset_allocations.values())

    @property
    def allocation_ratio(self) -> float:
        if self.total_capital == 0:
            return 0.0
        return self.allocated_capital / self.total_capital

    def update_peak(self, current_value: float) -> None:
        if current_value > self.peak_value:
            self.peak_value = current_value

    def drawdown(self, current_value: float) -> float:
        if self.peak_value <= 0:
            return 0.0
        return (current_value - self.peak_value) / self.peak_value

    def total_return(self, current_value: float) -> float:
        if self.total_capital <= 0:
            return 0.0
        return (current_value - self.total_capital) / self.total_capital


@dataclass
class PortfolioSummary:
    total_value: float = 0.0
    mtm_value: float = 0.0
    total_return_pct: float = 0.0
    realized_return_pct: float = 0.0
    unrealized_pnl: float = 0.0
    days_running: int = 0
    open_positions: int = 0
    closed_trades: int = 0
    execution_state: str = "ACTIVE"
    average_validity_exposure: float = 0.0
    portfolio_drawdown_pct: float = 0.0
    capital: float = 0.0
    allocations: dict = field(default_factory=dict)
