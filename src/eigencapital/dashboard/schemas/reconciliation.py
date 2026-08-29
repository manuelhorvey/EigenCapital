"""Reconciliation schemas — broker/internal state comparison models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReconciliationCheckDTO(BaseModel):
    """Single reconciliation check result."""

    check_name: str = Field(description="Check name")
    status: str = Field(description="PASS, WARNING, CRITICAL, BLOCKING")
    severity: str = Field(description="INFO, WARNING, CRITICAL, BLOCKING")
    action: str = Field(description="SAFE_AUTOFIX, REQUIRES_REVIEW, HALT")
    message: str = Field(description="Status message")
    broker_value: Any = Field(default=None, description="Broker-side value")
    internal_value: Any = Field(default=None, description="Internal-side value")
    tolerance: float | None = Field(default=None, description="Allowed tolerance")
    timestamp: datetime = Field(description="Check timestamp")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional details")


class ReconciliationStatusDTO(BaseModel):
    """Reconciliation status summary."""

    overall_status: str = Field(description="CLEAN, WARNING, CRITICAL, HALT")
    last_reconciliation: datetime | None = Field(default=None, description="Last reconciliation time")
    checks_performed: int = Field(description="Number of checks performed")
    checks_passed: int = Field(description="Number of checks passed")
    checks_warning: int = Field(description="Number of warning checks")
    checks_critical: int = Field(description="Number of critical checks")
    checks_blocking: int = Field(description="Number of blocking checks")
    stale_positions: int = Field(default=0, description="Number of stale positions")
    missing_fills: int = Field(default=0, description="Number of missing fills")
    duplicate_orders: int = Field(default=0, description="Number of duplicate orders")
    foreign_positions: int = Field(default=0, description="Number of foreign positions")
    timestamp: datetime = Field(description="Status timestamp")


class PositionReconciliationDTO(BaseModel):
    """Position-level reconciliation."""

    ticket: int = Field(description="MT5 ticket")
    symbol: str = Field(description="Instrument symbol")
    internal_size: float = Field(description="Internal position size")
    broker_size: float = Field(description="Broker position size")
    size_match: bool = Field(description="Whether sizes match")
    internal_sl: float | None = Field(default=None, description="Internal stop-loss")
    broker_sl: float | None = Field(default=None, description="Broker stop-loss")
    sl_match: bool = Field(default=True, description="Whether stop-losses match")
    status: str = Field(description="RECONCILED, MISMATCH, MISSING, FOREIGN")
    details: dict[str, Any] = Field(default_factory=dict, description="Reconciliation details")
