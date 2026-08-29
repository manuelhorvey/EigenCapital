"""Portfolio schemas — account, positions, and portfolio state models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AccountDTO(BaseModel):
    """Account state snapshot."""

    equity: float = Field(description="Current equity")
    balance: float = Field(description="Account balance")
    free_margin: float = Field(default=0, description="Available margin")
    margin_used: float = Field(default=0, description="Used margin")
    margin_utilization: float = Field(default=0, description="Margin utilization ratio (0-1)")
    equity_high_water: float = Field(default=0, description="Equity high-water mark")
    drawdown: float = Field(default=0, description="Current drawdown from high-water mark")
    drawdown_pct: float = Field(default=0, description="Drawdown percentage")
    daily_pnl: float = Field(default=0, description="Today's realized + unrealized P&L")
    daily_loss_remaining: float = Field(default=250, description="Remaining daily loss budget")
    unrealized_pnl: float = Field(default=0, description="Total unrealized P&L")
    currency: str = Field(default="USD", description="Account currency")
    timestamp: datetime = Field(description="Snapshot timestamp")
    freshness: str | None = Field(default=None, description="LIVE, STALE, or UNKNOWN")
    source: str | None = Field(default=None, description="Data source")


class PositionDTO(BaseModel):
    """Single position with risk metadata."""

    ticket: int = Field(description="MT5 ticket number")
    symbol: str = Field(description="Instrument symbol")
    direction: str = Field(description="BUY or SELL")
    size: float = Field(description="Position volume")
    entry_price: float = Field(description="Average entry price")
    current_price: float = Field(description="Current market price")
    unrealized_pnl: float = Field(description="Unrealized P&L")
    unrealized_pnl_pct: float = Field(default=0, description="Unrealized P&L percentage")
    stop_loss: float | None = Field(default=None, description="Stop-loss price")
    distance_to_sl: float | None = Field(default=None, description="Distance to stop-loss")
    mae: float | None = Field(default=None, description="Maximum Adverse Excursion")
    mfe: float | None = Field(default=None, description="Maximum Favorable Excursion")
    holding_time: str | None = Field(default=None, description="Time since entry")
    risk_state: str = Field(default="NORMAL", description="Risk state: NORMAL, WARNING, CRITICAL")
    protected: bool = Field(description="Whether SL is set")
    attribution_state: str | None = Field(default=None, description="Attribution state")
    last_update: datetime = Field(description="Last price update timestamp")
    freshness: str | None = Field(default=None, description="LIVE, STALE, or UNKNOWN")
    source: str | None = Field(default=None, description="Data source")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional position details")


class PortfolioSummaryDTO(BaseModel):
    """Portfolio-level summary."""

    position_count: int = Field(description="Total position count")
    long_count: int = Field(description="Long position count")
    short_count: int = Field(description="Short position count")
    gross_exposure: float = Field(description="Total gross exposure")
    net_exposure: float = Field(description="Net exposure (long - short)")
    exposure_pct: float = Field(description="Exposure as percentage of equity")
    concentration: float = Field(description="Largest position concentration")
    largest_position_symbol: str | None = Field(default=None, description="Largest position by notional")
    protected_count: int = Field(description="Positions with SL set")
    unprotected_count: int = Field(description="Positions without SL")
    timestamp: datetime = Field(description="Summary timestamp")
    freshness: str | None = Field(default=None, description="LIVE, STALE, or UNKNOWN")
