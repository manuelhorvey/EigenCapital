"""Evidence routes — event timeline, qualification, and evidence endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eigencapital.dashboard.schemas.evidence import (
    EventDTO,
    EventTimelineDTO,
    QualificationStatusDTO,
    ShadowReducedDTO,
)
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/evidence", tags=["evidence"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("/events", response_model=EventTimelineDTO)
async def get_event_timeline(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
) -> EventTimelineDTO:
    """Get event timeline with pagination."""
    events = state.get_recent_events(limit=1000)

    total = len(events)
    start = (page - 1) * page_size
    end = start + page_size
    page_events = events[start:end]

    parsed = []
    for e in page_events:
        try:
            # Map raw decisions.jsonl fields to EventDTO
            # Raw fields: event, status, timestamp, equity_before, equity_after,
            #   positions_before, positions_after, submitted, filled, closed, failed,
            #   orders, limit, error, diag, duration_seconds
            event_type = e.get("event_type") or e.get("type") or e.get("event") or "UNKNOWN"

            # Build a human-readable message from available fields
            message = e.get("message") or e.get("action") or ""
            if not message:
                if event_type == "executed":
                    submitted = e.get("submitted", 0)
                    filled = e.get("filled", 0)
                    failed = e.get("failed", 0)
                    message = f"Submitted {submitted}, filled {filled}, failed {failed}"
                elif event_type == "dry_run":
                    orders = e.get("orders", 0)
                    message = f"Dry run: {orders} order(s) generated"
                elif event_type == "aligned":
                    positions = e.get("positions", 0)
                    message = f"Aligned: {positions} position(s) active"
                elif event_type == "regime_skip":
                    diag = e.get("diag", {})
                    reason = "regime off"
                    if diag:
                        reason += (
                            f" (vol_now={diag.get('vol_now', '?'):.4f}, vol_median={diag.get('vol_median', '?'):.4f})"
                        )
                    message = f"Skipped: {reason}"
                elif event_type == "closed":
                    message = e.get("message", "Position closed")
                elif event_type == "startup_fingerprint_verified":
                    message = "Build fingerprint verified at startup"
                elif event_type == "t0_validated":
                    message = "T0 baseline validated"
                elif event_type == "startup_position_assertion":
                    count = e.get("count", e.get("positions", "?"))
                    message = f"Startup position assertion: {count} position(s)"
                elif event_type == "trading_authorized":
                    message = "Trading authorization granted"
                elif event_type == "concurrency_limit":
                    limit = e.get("limit", "?")
                    count = e.get("count", e.get("positions", "?"))
                    message = f"Concurrency limit: {count}/{limit}"
                elif event_type == "t0_mismatch":
                    message = "T0 equity mismatch detected"
                elif event_type == "emergency_flatten":
                    message = "Emergency flatten executed"
                elif event_type == "order_intents_persisted":
                    count = e.get("count", e.get("orders", "?"))
                    message = f"Order intents persisted: {count} order(s)"
                elif event_type == "error":
                    msg = e.get("error", e.get("message", "Unknown error"))
                    message = f"Error: {msg}"
                elif event_type == "reconciliation":
                    message = "Reconciliation check completed"
                elif event_type == "disconnect":
                    message = "Broker connection lost"
                else:
                    message = event_type.replace("_", " ").title()

            # Derive severity from event type
            severity = e.get("severity")
            if not severity:
                upper = event_type.upper()
                if (
                    "error" in upper
                    or "critical" in upper
                    or "halt" in upper
                    or "emergency" in upper
                    or "flatten" in upper
                    or "disconnect" in upper
                ):
                    severity = "CRITICAL"
                elif (
                    "warning" in upper
                    or "skip" in upper
                    or "fail" in upper
                    or "mismatch" in upper
                    or "concurrency" in upper
                ):
                    severity = "WARNING"
                else:
                    severity = "INFO"

            parsed.append(
                EventDTO(
                    event_id=e.get("event_id", e.get("id", str(e.get("timestamp", "unknown")))),
                    event_type=event_type.upper().replace("_", " "),
                    timestamp=datetime.fromisoformat(e.get("timestamp", datetime.now(UTC).isoformat())),
                    symbol=e.get("symbol"),
                    ticket=e.get("ticket"),
                    correlation_id=e.get("correlation_id"),
                    severity=severity,
                    message=message,
                    details=e.get("details", e.get("diag", {})),
                    build_id=e.get("build_id"),
                    strategy_version=e.get("strategy_version"),
                )
            )
        except Exception:
            pass

    return EventTimelineDTO(
        events=parsed,
        total=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
        newest_timestamp=parsed[0].timestamp if parsed else None,
        oldest_timestamp=parsed[-1].timestamp if parsed else None,
    )


@router.get("/qualification", response_model=QualificationStatusDTO)
async def get_qualification(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> QualificationStatusDTO:
    """Get Phase 2 qualification status."""
    qual = state.get_qualification_status()
    return QualificationStatusDTO(
        campaign_id=qual.get("campaign_id", "UNKNOWN"),
        overall_status=qual.get("overall_status", "UNKNOWN"),
        evidence_insufficient=qual.get("evidence_insufficient", True),
        evidence_maturity={
            "e0_count": qual.get("e0_count", 0),
            "e1_count": qual.get("e1_count", 0),
            "e2_count": qual.get("e2_count", 0),
            "e3_count": qual.get("e3_count", 0),
            "e4_count": qual.get("e4_count", 0),
            "e5_count": qual.get("e5_count", 0),
            "e6_count": qual.get("e6_count", 0),
            "total_trades": qual.get("total_trades", 0),
            "open_trades": qual.get("open_trades", 0),
            "completed_lifecycles": qual.get("completed_lifecycles", 0),
            "observation_days": qual.get("observation_days", 0),
            "timestamp": datetime.now(UTC),
        },
        gates=qual.get("gates", []),
        timestamp=datetime.now(UTC),
        freshness=qual.get("freshness"),
    )


@router.get("/shadow-reduced", response_model=ShadowReducedDTO)
async def get_shadow_reduced(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> ShadowReducedDTO:
    """Get shadow REDUCED counterfactual data."""
    reduced = state.get_shadow_reduced()
    return ShadowReducedDTO(
        mode="SHADOW_ONLY",
        observations=reduced.get("observations", 0),
        hypothetical_reductions=reduced.get("hypothetical_reductions", 0),
        average_scale=reduced.get("average_scale"),
        actual_size=reduced.get("actual_size"),
        hypothetical_size=reduced.get("hypothetical_size"),
        actual_pnl=reduced.get("actual_pnl"),
        hypothetical_pnl=reduced.get("hypothetical_pnl"),
        counterfactual_difference=reduced.get("counterfactual_difference"),
        freshness=reduced.get("freshness"),
        label="Would Have Happened — NOT APPLIED LIVE",
        timestamp=datetime.now(UTC),
    )
