"""Portfolio Health Monitoring.

Canonical entry points:
- PortfolioHealthMonitor: fail-closed health assessment against RiskPolicy
- HealthReport / HealthState / Alert: assessment outputs
"""

from eigencapital.monitoring.health import (
    ALERT_ASSET_CLASS_EXPOSURE,
    ALERT_CONCENTRATION,
    ALERT_DAILY_LOSS,
    ALERT_GROSS_LEVERAGE,
    ALERT_KILL_SWITCH,
    ALERT_MAX_DRAWDOWN,
    ALERT_MIN_EQUITY,
    ALERT_POSITION_COUNT,
    ALERT_SNAPSHOT_STALE,
    ALERT_SNAPSHOT_UNPARSEABLE,
    ALERT_WARN_DAILY_LOSS,
    ALERT_WARN_DRAWDOWN,
    ALERT_WARN_GROSS_LEVERAGE,
    ALERT_WEEKLY_LOSS,
    Alert,
    HealthReport,
    HealthState,
    PortfolioHealthMonitor,
    Severity,
)

__all__ = [
    "ALERT_ASSET_CLASS_EXPOSURE",
    "ALERT_CONCENTRATION",
    "ALERT_DAILY_LOSS",
    "ALERT_GROSS_LEVERAGE",
    "ALERT_KILL_SWITCH",
    "ALERT_MAX_DRAWDOWN",
    "ALERT_MIN_EQUITY",
    "ALERT_POSITION_COUNT",
    "ALERT_SNAPSHOT_STALE",
    "ALERT_SNAPSHOT_UNPARSEABLE",
    "ALERT_WARN_DAILY_LOSS",
    "ALERT_WARN_DRAWDOWN",
    "ALERT_WARN_GROSS_LEVERAGE",
    "ALERT_WEEKLY_LOSS",
    "Alert",
    "HealthReport",
    "HealthState",
    "PortfolioHealthMonitor",
    "Severity",
]
