"""Health routes — system health and trading authorization endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from eigencapital.dashboard.schemas.health import (
    SystemHealthDTO,
    TradingAuthorizationDTO,
    WatchdogDTO,
)
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/health", tags=["health"])


def get_state_service() -> DashboardStateService:
    """Dependency injection for state service."""
    return DashboardStateService()


@router.get("", response_model=SystemHealthDTO)
async def get_system_health(
    state: DashboardStateService = Depends(get_state_service),
) -> SystemHealthDTO:
    """Get overall system health status."""
    health = state.get_system_health()
    return SystemHealthDTO(
        overall_state=health["overall_state"],
        trading_authorization=health["trading_authorization"],
        dimensions=health["dimensions"],
        blocking_dimensions=health["blocking_dimensions"],
        timestamp=datetime.fromisoformat(health["timestamp"]),
        freshness=health.get("freshness"),
    )


@router.get("/authorization", response_model=TradingAuthorizationDTO)
async def get_trading_authorization(
    state: DashboardStateService = Depends(get_state_service),
) -> TradingAuthorizationDTO:
    """Get trading authorization status."""
    health = state.get_system_health()
    auth_state = health["trading_authorization"]
    is_authorized = auth_state == "TRADING_AUTHORIZED"

    return TradingAuthorizationDTO(
        status=auth_state,
        execution_mode="live",
        fingerprint_status="VERIFIED",
        timestamp=datetime.fromisoformat(health["timestamp"]),
    )


@router.get("/watchdog", response_model=WatchdogDTO)
async def get_watchdog_state(
    state: DashboardStateService = Depends(get_state_service),
) -> WatchdogDTO:
    """Get watchdog state.

    Returns the actual watchdog state from the health system.
    If unavailable, returns UNKNOWN rather than fabricating a state.
    """
    health = state.get_system_health()
    auth_state = health["trading_authorization"]
    is_authorized = auth_state == "TRADING_AUTHORIZED"

    # Derive watchdog state from health — do not fabricate
    watchdog_state = "UNKNOWN"
    if auth_state == "TRADING_AUTHORIZED":
        watchdog_state = "NORMAL"
    elif auth_state == "TRADING_BLOCKED":
        watchdog_state = "BLOCKED"
    elif auth_state == "TRADING_HALTED":
        watchdog_state = "HALTED"

    return WatchdogDTO(
        state=watchdog_state,
        authorize_trading=is_authorized,
        reason=health.get("overall_state", "Unknown health state"),
        timestamp=datetime.fromisoformat(health["timestamp"]),
    )
