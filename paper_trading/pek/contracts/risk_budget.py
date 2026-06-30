from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskBudget:
    """Adaptive risk budget — output of RiskEngineV2, consumed by PEK.
    PEK applies: final_risk = min(config.max_risk, budget.max_risk_per_trade_pct).
    """

    max_risk_per_trade_pct: float  # effective % risk per trade after all scaling
    max_portfolio_heat: float  # max total notional / equity ratio (clamped)
    max_concurrent_positions: int  # may be reduced below config max by risk engine
    volatility_scalar: float  # for info/debugging: what vol adjustment was applied
    drawdown_scalar: float  # for info/debugging: what dd adjustment was applied
    performance_scalar: float  # for info/debugging: composite from PerformanceState
    velocity_scalar: float  # for info/debugging: velocity adjustment
