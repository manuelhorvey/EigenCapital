"""Health State Model — machine-readable system health for trading authorization.

Health dimensions:
- SYSTEM_HEALTH: Process alive, resources OK
- BROKER_HEALTH: MT5 connection, data quality
- DATA_HEALTH: Price freshness, data completeness
- POSITION_HEALTH: Position count, attribution
- RISK_HEALTH: All risk gates
- EXECUTION_HEALTH: Fill rate, rejection rate
- RECONCILIATION_HEALTH: State consistency
- STRATEGY_HEALTH: Signal computation
- EVIDENCE_HEALTH: Ledger completeness

Each dimension has states:
- HEALTHY: Operating normally
- DEGRADED: Non-critical issues detected
- BLOCKED: Critical issues, trading blocked
- CONTAINED: Critical issues, existing positions may be at risk
- HALTED: System halted, manual intervention required

Trading authorization:
- Strategy says: BUY EURUSD
- Risk says: APPROVED
- Reconciliation says: HEALTHY
- Broker says: CONNECTED
- Watchdog says: NORMAL
- TRADING_AUTHORIZED → EXECUTE

Any critical layer says NO:
- TRADING_BLOCKED → no new exposure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class HealthState(str, Enum):
    """Health state for any dimension."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    CONTAINED = "CONTAINED"
    HALTED = "HALTED"


class HealthDimension(str, Enum):
    """Health dimensions."""

    SYSTEM = "SYSTEM_HEALTH"
    BROKER = "BROKER_HEALTH"
    DATA = "DATA_HEALTH"
    POSITION = "POSITION_HEALTH"
    RISK = "RISK_HEALTH"
    EXECUTION = "EXECUTION_HEALTH"
    RECONCILIATION = "RECONCILIATION_HEALTH"
    STRATEGY = "STRATEGY_HEALTH"
    EVIDENCE = "EVIDENCE_HEALTH"


class TradingAuthorization(str, Enum):
    """Trading authorization status."""

    AUTHORIZED = "TRADING_AUTHORIZED"
    BLOCKED = "TRADING_BLOCKED"
    HALTED = "TRADING_HALTED"


@dataclass(frozen=True)
class DimensionHealth:
    """Health status for a single dimension."""

    dimension: str
    state: str
    message: str
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)
    last_change: Optional[str] = None
    consecutive_failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "state": self.state,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
            "last_change": self.last_change,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass(frozen=True)
class SystemHealth:
    """Complete system health status."""

    overall_state: str
    authorization: str
    dimensions: Dict[str, DimensionHealth]
    timestamp: str
    blocking_dimensions: List[str]
    degraded_dimensions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_state": self.overall_state,
            "authorization": self.authorization,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "timestamp": self.timestamp,
            "blocking_dimensions": self.blocking_dimensions,
            "degraded_dimensions": self.degraded_dimensions,
        }


class HealthMonitor:
    """Machine-readable system health for trading authorization.

    Tracks health across all dimensions and computes trading authorization.
    """

    def __init__(
        self,
        max_consecutive_failures: int = 3,
        degradation_threshold: int = 1,
    ) -> None:
        """Initialize health monitor.

        Args:
            max_consecutive_failures: Failures before escalating to BLOCKED
            degradation_threshold: Failures before escalating to DEGRADED
        """
        self._max_consecutive_failures = max_consecutive_failures
        self._degradation_threshold = degradation_threshold

        # Current state for each dimension
        self._dimensions: Dict[str, DimensionHealth] = {}

        # History of state changes
        self._history: List[Dict[str, Any]] = []
        self._max_history = 1000

        # Initialize all dimensions to HEALTHY
        for dim in HealthDimension:
            self._dimensions[dim.value] = DimensionHealth(
                dimension=dim.value,
                state=HealthState.HEALTHY.value,
                message="Initialized",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def update_dimension(
        self,
        dimension: HealthDimension,
        state: HealthState,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> DimensionHealth:
        """Update health state for a dimension.

        Args:
            dimension: Which dimension to update
            state: New health state
            message: Human-readable message
            details: Additional context

        Returns:
            Updated DimensionHealth
        """
        now = datetime.now(timezone.utc).isoformat()
        current = self._dimensions.get(dimension.value)

        # Track consecutive failures
        consecutive_failures = 0
        if current and current.state != HealthState.HEALTHY.value:
            consecutive_failures = current.consecutive_failures + 1

        # Create updated health
        updated = DimensionHealth(
            dimension=dimension.value,
            state=state.value,
            message=message,
            timestamp=now,
            details=details or {},
            last_change=current.state if current else None,
            consecutive_failures=consecutive_failures,
        )

        self._dimensions[dimension.value] = updated

        # Record state change
        if current and current.state != state.value:
            self._history.append(
                {
                    "dimension": dimension.value,
                    "old_state": current.state,
                    "new_state": state.value,
                    "message": message,
                    "timestamp": now,
                }
            )
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

        return updated

    def get_system_health(self) -> SystemHealth:
        """Compute complete system health and trading authorization."""
        now = datetime.now(timezone.utc).isoformat()

        # Classify dimensions
        blocking = []
        degraded = []

        for dim_name, dim_health in self._dimensions.items():
            if dim_health.state in (
                HealthState.BLOCKED.value,
                HealthState.CONTAINED.value,
                HealthState.HALTED.value,
            ):
                blocking.append(dim_name)
            elif dim_health.state == HealthState.DEGRADED.value:
                degraded.append(dim_name)

        # Determine overall state
        if blocking:
            # Check if any dimension is HALTED
            halted = any(
                d.state == HealthState.HALTED.value for d in self._dimensions.values()
            )
            overall_state = (
                HealthState.HALTED.value if halted else HealthState.BLOCKED.value
            )
        elif degraded:
            overall_state = HealthState.DEGRADED.value
        else:
            overall_state = HealthState.HEALTHY.value

        # Determine trading authorization
        if blocking:
            authorization = (
                TradingAuthorization.HALTED.value
                if overall_state == HealthState.HALTED.value
                else TradingAuthorization.BLOCKED.value
            )
        else:
            authorization = TradingAuthorization.AUTHORIZED.value

        return SystemHealth(
            overall_state=overall_state,
            authorization=authorization,
            dimensions=self._dimensions,
            timestamp=now,
            blocking_dimensions=blocking,
            degraded_dimensions=degraded,
        )

    def is_trading_authorized(self) -> bool:
        """Check if trading is currently authorized."""
        health = self.get_system_health()
        return health.authorization == TradingAuthorization.AUTHORIZED.value

    def get_dimension(self, dimension: HealthDimension) -> DimensionHealth:
        """Get health state for a specific dimension."""
        return self._dimensions.get(
            dimension.value,
            DimensionHealth(
                dimension=dimension.value,
                state=HealthState.HEALTHY.value,
                message="Not initialized",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        )

    def get_history(self) -> List[Dict[str, Any]]:
        """Get health state change history."""
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        """Get health statistics."""
        states = {}
        for dim_health in self._dimensions.values():
            states[dim_health.state] = states.get(dim_health.state, 0) + 1

        return {
            "dimensions": len(self._dimensions),
            "states": states,
            "history_size": len(self._history),
            "blocking_count": sum(
                1
                for d in self._dimensions.values()
                if d.state
                in (
                    HealthState.BLOCKED.value,
                    HealthState.CONTAINED.value,
                    HealthState.HALTED.value,
                )
            ),
        }

    def reset_dimension(self, dimension: HealthDimension) -> DimensionHealth:
        """Reset a dimension to HEALTHY state."""
        return self.update_dimension(
            dimension=dimension,
            state=HealthState.HEALTHY,
            message="Reset to healthy",
        )

    def reset_all(self) -> None:
        """Reset all dimensions to HEALTHY state."""
        for dim in HealthDimension:
            self.reset_dimension(dim)


# Convenience functions for common health updates


def update_broker_health(
    monitor: HealthMonitor,
    connected: bool,
    data_fresh: bool,
    message: str,
) -> DimensionHealth:
    """Update broker health state."""
    if not connected:
        state = HealthState.BLOCKED
    elif not data_fresh:
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY

    return monitor.update_dimension(
        dimension=HealthDimension.BROKER,
        state=state,
        message=message,
        details={"connected": connected, "data_fresh": data_fresh},
    )


def update_risk_health(
    monitor: HealthMonitor,
    all_gates_pass: bool,
    any_critical: bool,
    message: str,
) -> DimensionHealth:
    """Update risk health state."""
    if any_critical:
        state = HealthState.BLOCKED
    elif not all_gates_pass:
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY

    return monitor.update_dimension(
        dimension=HealthDimension.RISK,
        state=state,
        message=message,
        details={"all_gates_pass": all_gates_pass, "any_critical": any_critical},
    )


def update_reconciliation_health(
    monitor: HealthMonitor,
    status: str,
    mismatches: List[str],
    message: str,
) -> DimensionHealth:
    """Update reconciliation health state."""
    if status == "BLOCKING":
        state = HealthState.BLOCKED
    elif status == "MISMATCH":
        state = HealthState.CONTAINED
    elif status == "WARNING":
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY

    return monitor.update_dimension(
        dimension=HealthDimension.RECONCILIATION,
        state=state,
        message=message,
        details={"status": status, "mismatches": mismatches},
    )


def update_execution_health(
    monitor: HealthMonitor,
    fill_rate: float,
    rejection_rate: float,
    message: str,
) -> DimensionHealth:
    """Update execution health state."""
    if rejection_rate > 0.1:  # >10% rejection rate
        state = HealthState.BLOCKED
    elif rejection_rate > 0.05 or fill_rate < 0.8:  # >5% rejection or <80% fill
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY

    return monitor.update_dimension(
        dimension=HealthDimension.EXECUTION,
        state=state,
        message=message,
        details={"fill_rate": fill_rate, "rejection_rate": rejection_rate},
    )
