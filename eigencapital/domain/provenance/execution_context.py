"""ExecutionContext — frozen snapshot of engine runtime state at decision time.

Consolidates runtime state that was previously scattered across HaltState,
EquityTracker, CircuitBreaker, HealthMonitor, and RecoveryScheduler into a
single immutable object.  This is the public contract — those internal
classes remain implementation details.

The capture point is the decision boundary (after Phase 3 portfolio health,
before any positions are modified or persistence runs), so this represents
the operational state of the engine at the moment of decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionContext:
    cycle_id: int
    cycle_duration_ms: float = 0.0
    total_equity: float = 0.0
    drawdown_pct: float = 0.0
    exposure_multiplier: float = 1.0
    n_assets: int = 0
    n_healthy: int = 0
    n_halted: int = 0
    halt_ratio: float = 0.0
    emergency_halt: bool = False
    halt_reason: str = ""
    peak_portfolio_value: float | None = None
    circuit_breaker_tripped: bool = False
    circuit_breaker_reason: str = ""
    circuit_breaker_severity: str = ""
    consecutive_losses: int = 0
    var_95: float | None = None
    cvar_95: float | None = None
    daily_pnl: float = 0.0
    pek_budget_utilization: float = 1.0
    correlation_alert: bool = False
    position_concentration_skew: float = 0.0
    position_concentration_dominant_side: str = ""
    orphan_reconciliation_count: int = 0
    is_weekend_cycle: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "cycle_duration_ms": self.cycle_duration_ms,
            "total_equity": self.total_equity,
            "drawdown_pct": self.drawdown_pct,
            "exposure_multiplier": self.exposure_multiplier,
            "n_assets": self.n_assets,
            "n_healthy": self.n_healthy,
            "n_halted": self.n_halted,
            "halt_ratio": self.halt_ratio,
            "emergency_halt": self.emergency_halt,
            "halt_reason": self.halt_reason,
            "peak_portfolio_value": self.peak_portfolio_value,
            "circuit_breaker_tripped": self.circuit_breaker_tripped,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "circuit_breaker_severity": self.circuit_breaker_severity,
            "consecutive_losses": self.consecutive_losses,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "daily_pnl": self.daily_pnl,
            "pek_budget_utilization": self.pek_budget_utilization,
            "correlation_alert": self.correlation_alert,
            "position_concentration_skew": self.position_concentration_skew,
            "position_concentration_dominant_side": self.position_concentration_dominant_side,
            "orphan_reconciliation_count": self.orphan_reconciliation_count,
            "is_weekend_cycle": self.is_weekend_cycle,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContext:
        return cls(**data)
