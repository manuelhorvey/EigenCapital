"""Risk routes — risk observation and enforcement endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from eigencapital.dashboard.schemas.risk import (
    RiskEnvelopeDTO,
    RiskObservationDTO,
    RiskStateDTO,
)
from eigencapital.dashboard.services.dashboard_state import DashboardStateService

router = APIRouter(prefix="/risk", tags=["risk"])


def get_state_service() -> DashboardStateService:
    return DashboardStateService()


@router.get("", response_model=RiskStateDTO)
async def get_risk_state(
    state: DashboardStateService = Depends(get_state_service),
) -> RiskStateDTO:
    """Get current risk state with all observation dimensions."""
    risk = state.get_risk_state()

    observations = []
    for obs in risk.get("observations", []):
        try:
            ts = obs.pop("timestamp", None)
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            elif ts is None:
                ts = datetime.now(UTC)
            observations.append(RiskObservationDTO(timestamp=ts, **obs))
        except Exception:
            pass  # Skip malformed observations

    return RiskStateDTO(
        overall_level=risk["overall_level"],
        observations=observations,
        any_critical=risk["any_critical"],
        any_warning=risk["any_warning"],
        critical_dimensions=risk["critical_dimensions"],
        warning_dimensions=risk["warning_dimensions"],
        timestamp=datetime.fromisoformat(risk["timestamp"]),
        freshness=risk.get("freshness"),
    )


@router.get("/envelope", response_model=RiskEnvelopeDTO)
async def get_risk_envelope() -> RiskEnvelopeDTO:
    """Get risk limits configuration.

    Returns actual risk envelope from the live risk enforcement module.
    If unavailable, returns NOT_AVAILABLE state rather than hardcoded values.
    """
    try:
        from eigencapital.live.risk_enforcement import RiskEnvelope

        env = RiskEnvelope.from_config()
        return RiskEnvelopeDTO(
            max_concurrent_positions=env.max_concurrent_positions,
            max_position_notional=env.max_position_notional,
            max_order_notional=env.max_order_notional,
            max_per_position_loss_pct=env.max_per_position_loss_pct,
            max_account_drawdown_pct=env.max_account_drawdown_pct,
            max_daily_loss=env.max_daily_loss,
            min_equity=env.min_equity,
            require_sl_on_positions=env.require_sl_on_positions,
            t0_equity=env.t0_equity,
        )
    except ImportError:
        # Risk enforcement module not available — report clearly
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Risk envelope not available",
                "detail": "Risk enforcement module not loaded",
                "subsystem": "risk_envelope",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to read risk envelope",
                "detail": str(e),
                "subsystem": "risk_envelope",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
