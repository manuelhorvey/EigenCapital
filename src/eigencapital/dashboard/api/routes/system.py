"""System routes — build identity and system status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eigencapital.dashboard.schemas.evidence import BuildIdentityDTO
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/system", tags=["system"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("/health")
async def get_system_health(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> dict:
    """Get overall system health summary."""
    health = state.get_system_health()
    return {
        "status": "ok" if health["overall_state"] in ("HEALTHY", "NORMAL") else "degraded",
        "overall_state": health["overall_state"],
        "trading_authorization": health["trading_authorization"],
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/build", response_model=BuildIdentityDTO)
async def get_build_identity(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> BuildIdentityDTO:
    """Get build identity and verification status."""
    build = state.get_build_identity()
    return BuildIdentityDTO(**build)


@router.get("/info")
async def get_system_info() -> dict:
    """Get dashboard system information."""
    return {
        "dashboard_version": "0.1.0",
        "read_only": True,
        "can_submit_orders": False,
        "can_modify_r4": False,
        "can_modify_risk_limits": False,
        "can_activate_reduced": False,
        "timestamp": datetime.now(UTC).isoformat(),
    }
