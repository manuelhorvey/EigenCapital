"""Alerts routes — structured alert endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from eigencapital.dashboard.schemas.evidence import AlertDTO
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/alerts", tags=["alerts"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("", response_model=list[AlertDTO])
async def get_alerts(
    limit: int = Query(50, ge=1, le=500, description="Maximum alerts to return"),
    severity: str | None = Query(None, description="Filter by severity: CRITICAL, WARNING, INFO"),
    state: DashboardStateService = Depends(get_state_service),
) -> list[AlertDTO]:
    """Get recent alerts."""
    alerts = state.get_recent_alerts(limit=limit)

    result = []
    for a in alerts:
        if severity and a.get("severity", "").upper() != severity.upper():
            continue

        try:
            result.append(AlertDTO(
                alert_id=a.get("alert_id", a.get("id", "unknown")),
                timestamp=datetime.fromisoformat(a.get("timestamp", datetime.now(UTC).isoformat())),
                severity=a.get("severity", "INFO"),
                category=a.get("category", "SYSTEM"),
                event_type=a.get("event_type", a.get("type", "UNKNOWN")),
                message=a.get("message", "Alert"),
                event_id=a.get("event_id"),
                correlation_id=a.get("correlation_id"),
                state_transition=a.get("state_transition"),
                consecutive_count=a.get("consecutive_count", 1),
                details=a.get("details", {}),
                acknowledged=a.get("acknowledged", False),
            ))
        except Exception:
            pass

    return result
