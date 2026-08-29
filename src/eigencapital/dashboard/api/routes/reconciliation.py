"""Reconciliation routes — broker/internal state comparison endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eigencapital.dashboard.schemas.reconciliation import (
    ReconciliationStatusDTO,
)
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("", response_model=ReconciliationStatusDTO)
async def get_reconciliation_status(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> ReconciliationStatusDTO:
    """Get reconciliation status — broker ↔ internal state."""
    recon = state.get_reconciliation_status()

    return ReconciliationStatusDTO(
        overall_status=recon["overall_status"],
        last_reconciliation=datetime.fromisoformat(recon["last_reconciliation"])
        if recon.get("last_reconciliation")
        else None,
        checks_performed=recon["checks_performed"],
        checks_passed=recon["checks_passed"],
        checks_warning=recon["checks_warning"],
        checks_critical=recon["checks_critical"],
        checks_blocking=recon["checks_blocking"],
        stale_positions=recon["stale_positions"],
        missing_fills=recon["missing_fills"],
        duplicate_orders=recon["duplicate_orders"],
        foreign_positions=recon["foreign_positions"],
        timestamp=datetime.fromisoformat(recon["timestamp"]),
        freshness=recon.get("freshness"),
    )
