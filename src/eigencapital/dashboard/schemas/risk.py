"""Risk schemas — risk observation and enforcement models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RiskObservationDTO(BaseModel):
    """Single risk observation dimension."""

    dimension: str = Field(description="Risk dimension name")
    level: str = Field(description="NORMAL, ELEVATED, WARNING, CRITICAL, HALT")
    value: float = Field(description="Current value")
    limit: float | None = Field(default=None, description="Threshold limit")
    utilization: float | None = Field(default=None, description="Utilization ratio (0-1)")
    message: str = Field(description="Human-readable status message")
    timestamp: datetime = Field(description="Observation timestamp")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional details")
    trend: str | None = Field(default=None, description="Trend: IMPROVING, STABLE, DEGRADING")


class RiskStateDTO(BaseModel):
    """Complete risk state snapshot."""

    overall_level: str = Field(description="Overall risk level")
    observations: list[RiskObservationDTO] = Field(description="All risk observations")
    any_critical: bool = Field(description="Whether any dimension is critical")
    any_warning: bool = Field(description="Whether any dimension is warning")
    critical_dimensions: list[str] = Field(description="Critical dimension names")
    warning_dimensions: list[str] = Field(description="Warning dimension names")
    timestamp: datetime = Field(description="Risk state timestamp")
    freshness: str | None = Field(default=None, description="LIVE, STALE, or UNKNOWN")


class RiskGateDTO(BaseModel):
    """Single risk gate check result."""

    gate_name: str = Field(description="Gate name")
    result: str = Field(description="PASS, BLOCK, CRITICAL")
    reason: str | None = Field(default=None, description="Block reason")
    message: str = Field(description="Status message")
    timestamp: datetime = Field(description="Check timestamp")


class RiskEnvelopeDTO(BaseModel):
    """Risk limits configuration."""

    max_concurrent_positions: int = Field(description="Maximum concurrent positions")
    max_position_notional: float = Field(description="Maximum position notional")
    max_order_notional: float = Field(description="Maximum order notional")
    max_per_position_loss_pct: float = Field(description="Maximum per-position loss percentage")
    max_account_drawdown_pct: float = Field(description="Maximum account drawdown percentage")
    max_daily_loss: float = Field(description="Maximum daily loss")
    min_equity: float = Field(description="Minimum equity floor")
    require_sl_on_positions: bool = Field(description="Whether SL is required")
    t0_equity: float = Field(description="T=0 equity for drawdown calculation")


class TradeAttributionDTO(BaseModel):
    """Trade risk attribution record."""

    ticket: int = Field(description="MT5 ticket")
    symbol: str = Field(description="Instrument symbol")
    direction: str = Field(description="BUY or SELL")
    entry_time: datetime = Field(description="Entry timestamp")
    entry_price: float = Field(description="Entry price")
    entry_size: float = Field(description="Entry size")
    equity_at_entry: float = Field(description="Equity at entry")
    drawdown_at_entry: float = Field(description="Drawdown at entry")
    risk_level_at_entry: str = Field(description="Risk level at entry")
    exit_time: datetime | None = Field(default=None, description="Exit timestamp")
    exit_price: float | None = Field(default=None, description="Exit price")
    realized_pnl: float | None = Field(default=None, description="Realized P&L")
    mae: float | None = Field(default=None, description="Maximum Adverse Excursion")
    mfe: float | None = Field(default=None, description="Maximum Favorable Excursion")
    holding_days: float | None = Field(default=None, description="Holding period in days")
    counterfactual_size: float | None = Field(default=None, description="REDUCED hypothetical size")
    counterfactual_pnl: float | None = Field(default=None, description="REDUCED hypothetical P&L")
