"""Health schemas — system health and trading authorization models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DimensionHealthDTO(BaseModel):
    """Health status for a single dimension."""

    dimension: str = Field(description="Health dimension name")
    state: str = Field(description="Current state: HEALTHY, DEGRADED, BLOCKED, CONTAINED, HALTED")
    message: str = Field(description="Human-readable status message")
    timestamp: datetime = Field(description="Observation timestamp")
    last_change: datetime | None = Field(default=None, description="Timestamp of last state change")
    consecutive_failures: int = Field(default=0, description="Consecutive failure count")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional details")


class SystemHealthDTO(BaseModel):
    """Complete system health status."""

    overall_state: str = Field(description="Overall system health state")
    trading_authorization: str = Field(description="TRADING_AUTHORIZED, TRADING_BLOCKED, or TRADING_HALTED")
    dimensions: list[DimensionHealthDTO] = Field(description="Health status for each dimension")
    blocking_dimensions: list[str] = Field(description="Dimensions currently blocking trading")
    timestamp: datetime = Field(description="Health check timestamp")
    uptime_seconds: float | None = Field(default=None, description="System uptime in seconds")
    freshness: str | None = Field(default=None, description="LIVE, STALE, or UNKNOWN")


class TradingAuthorizationDTO(BaseModel):
    """Trading authorization status."""

    status: str = Field(description="TRADING_AUTHORIZED, TRADING_BLOCKED, TRADING_HALTED")
    authorization_id: str | None = Field(default=None, description="Authorization ID")
    campaign_id: str | None = Field(default=None, description="Campaign ID")
    execution_mode: str = Field(description="paper, shadow, or live")
    max_capital: float | None = Field(default=None, description="Maximum authorized capital")
    max_drawdown: float | None = Field(default=None, description="Maximum authorized drawdown")
    authorization_timestamp: datetime | None = Field(default=None, description="When authorized")
    expiry_timestamp: datetime | None = Field(default=None, description="Authorization expiry")
    fingerprint_status: str = Field(description="VERIFIED or DRIFT_DETECTED")
    timestamp: datetime = Field(description="Status timestamp")


class WatchdogDTO(BaseModel):
    """Watchdog state."""

    state: str = Field(description="Watchdog state")
    previous_state: str | None = Field(default=None, description="Previous watchdog state")
    authorize_trading: bool = Field(description="Whether watchdog authorizes trading")
    authorize_flatten_on_reconnect: bool = Field(default=False, description="Whether to flatten on reconnect")
    reason: str = Field(description="Reason for current state")
    last_transition: datetime | None = Field(default=None, description="Timestamp of last state transition")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Watchdog evidence")
