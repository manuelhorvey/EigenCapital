"""Evidence schemas — event ledger, qualification, and evidence maturity models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventDTO(BaseModel):
    """Single event from the event ledger."""

    event_id: str = Field(description="Event UUID")
    event_type: str = Field(description="Event type")
    timestamp: datetime = Field(description="Event timestamp")
    symbol: str | None = Field(default=None, description="Instrument symbol")
    ticket: int | None = Field(default=None, description="MT5 ticket")
    correlation_id: str | None = Field(default=None, description="Correlation ID linking related events")
    severity: str | None = Field(default=None, description="Event severity")
    message: str = Field(description="Event description")
    details: dict[str, Any] = Field(default_factory=dict, description="Event details")
    build_id: str | None = Field(default=None, description="Build ID")
    strategy_version: str | None = Field(default=None, description="Strategy version")


class EventTimelineDTO(BaseModel):
    """Event timeline with pagination."""

    events: list[EventDTO] = Field(description="List of events")
    total: int = Field(description="Total event count")
    page: int = Field(description="Current page")
    page_size: int = Field(description="Items per page")
    has_more: bool = Field(description="Whether more events exist")
    oldest_timestamp: datetime | None = Field(default=None, description="Oldest event timestamp")
    newest_timestamp: datetime | None = Field(default=None, description="Newest event timestamp")


class EvidenceMaturityDTO(BaseModel):
    """Evidence maturity E0-E6."""

    e0_count: int = Field(description="E0: Signal observations")
    e1_count: int = Field(description="E1: Execution observations")
    e2_count: int = Field(description="E2: Entry quality observations")
    e3_count: int = Field(description="E3: Holding period observations")
    e4_count: int = Field(description="E4: Exit quality observations")
    e5_count: int = Field(description="E5: Risk outcome observations")
    e6_count: int = Field(description="E6: Portfolio-level observations")
    total_trades: int = Field(description="Total completed trades")
    open_trades: int = Field(description="Currently open trades")
    completed_lifecycles: int = Field(description="Completed trade lifecycles")
    observation_days: int = Field(description="Days of observation")
    timestamp: datetime = Field(description="Maturity timestamp")


class QualificationGateDTO(BaseModel):
    """Single qualification gate result."""

    gate_id: str = Field(description="Gate ID: A, B, C")
    name: str = Field(description="Gate name")
    status: str = Field(description="PASS, FAIL, PENDING")
    details: dict[str, Any] = Field(default_factory=dict, description="Gate details")
    timestamp: datetime = Field(description="Evaluation timestamp")


class QualificationStatusDTO(BaseModel):
    """Phase 2 qualification status."""

    campaign_id: str = Field(description="Campaign ID")
    campaign_start: datetime | None = Field(default=None, description="Campaign start time")
    evidence_maturity: EvidenceMaturityDTO = Field(description="Evidence maturity levels")
    gates: list[QualificationGateDTO] = Field(description="Qualification gates")
    overall_status: str = Field(description="Overall qualification status")
    evidence_insufficient: bool = Field(description="Whether evidence is insufficient")
    timestamp: datetime = Field(description="Status timestamp")


class ShadowReducedDTO(BaseModel):
    """Shadow REDUCED counterfactual data."""

    mode: str = Field(description="Always SHADOW_ONLY")
    observations: int = Field(description="Number of observations")
    hypothetical_reductions: int = Field(description="Number of hypothetical reductions")
    average_scale: float | None = Field(default=None, description="Average hypothetical scale factor")
    actual_size: float | None = Field(default=None, description="Actual position size")
    hypothetical_size: float | None = Field(default=None, description="Hypothetical REDUCED size")
    actual_pnl: float | None = Field(default=None, description="Actual P&L")
    hypothetical_pnl: float | None = Field(default=None, description="Hypothetical REDUCED P&L")
    counterfactual_difference: float | None = Field(default=None, description="P&L difference")
    label: str = Field(description="Would Have Happened — NOT APPLIED LIVE")
    timestamp: datetime = Field(description="Data timestamp")


class AlertDTO(BaseModel):
    """Structured alert."""

    alert_id: str = Field(description="Alert ID")
    timestamp: datetime = Field(description="Alert timestamp")
    severity: str = Field(description="CRITICAL, WARNING, INFO")
    category: str = Field(description="Alert category")
    event_type: str = Field(description="Event type")
    message: str = Field(description="Alert message")
    event_id: str | None = Field(default=None, description="Related event ID")
    correlation_id: str | None = Field(default=None, description="Correlation ID")
    state_transition: str | None = Field(default=None, description="State transition")
    consecutive_count: int = Field(default=1, description="Consecutive occurrence count")
    details: dict[str, Any] = Field(default_factory=dict, description="Alert details")
    acknowledged: bool = Field(default=False, description="Whether acknowledged")


class BuildIdentityDTO(BaseModel):
    """Build identity and verification status."""

    git_head: str = Field(description="Git HEAD commit")
    manifest_identity: str = Field(description="R4 manifest identity")
    config_fingerprint: str = Field(description="Configuration fingerprint")
    loop_script_sha256: str = Field(description="Loop script SHA-256")
    build_id: str = Field(description="Build ID")
    verified: bool = Field(description="Whether build is verified")
    drift_detected: bool = Field(default=False, description="Whether drift detected")
    drift_details: dict[str, Any] = Field(default_factory=dict, description="Drift details")
    timestamp: datetime = Field(description="Verification timestamp")
