"""Portfolio routes — account, positions, and portfolio endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eigencapital.dashboard.schemas.portfolio import (
    AccountDTO,
    PortfolioSummaryDTO,
    PositionDTO,
)
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("/account", response_model=AccountDTO)
async def get_account(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> AccountDTO:
    """Get account state snapshot."""
    account = state.get_account_state()
    return AccountDTO(**account)


@router.get("/positions", response_model=list[PositionDTO])
async def get_positions(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> list[PositionDTO]:
    """Get all current positions."""
    positions = state.get_positions()
    return [PositionDTO(**p) for p in positions]


@router.get("/summary", response_model=PortfolioSummaryDTO)
async def get_portfolio_summary(
    state: Annotated[DashboardStateService, Depends(get_state_service)],
) -> PortfolioSummaryDTO:
    """Get portfolio-level summary."""
    positions = state.get_positions()

    long_positions = [p for p in positions if p["direction"] == "BUY"]
    short_positions = [p for p in positions if p["direction"] == "SELL"]

    gross_exposure = sum(abs(p.get("size", 0) * p.get("current_price", 0)) for p in positions)
    net_exposure = sum(
        (p.get("size", 0) * p.get("current_price", 0)) * (1 if p["direction"] == "BUY" else -1) for p in positions
    )

    # Concentration
    max_notional = 0
    max_symbol = None
    for p in positions:
        notional = abs(p.get("size", 0) * p.get("current_price", 0))
        if notional > max_notional:
            max_notional = notional
            max_symbol = p["symbol"]

    account = state.get_account_state()
    equity = account.get("equity", 0) or 1

    return PortfolioSummaryDTO(
        position_count=len(positions),
        long_count=len(long_positions),
        short_count=len(short_positions),
        gross_exposure=gross_exposure,
        net_exposure=net_exposure,
        exposure_pct=net_exposure / equity,
        concentration=max_notional / equity if equity > 0 else 0,
        largest_position_symbol=max_symbol,
        protected_count=sum(1 for p in positions if p.get("protected", False)),
        unprotected_count=sum(1 for p in positions if not p.get("protected", False)),
        timestamp=datetime.now(UTC),
        freshness=account.get("freshness"),
    )
