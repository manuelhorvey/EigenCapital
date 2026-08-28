"""Risk Observation Engine — continuous observation of risk dimensions.

Observes:
- Equity and drawdown
- Daily loss
- Position exposure (gross, net, long, short)
- Margin utilization
- Concentration risk
- SL protection status
- Stale data detection
- Correlation risk
- Loss velocity

This engine OBSERVES, ALERTS, and CONTAINS only.
It does NOT change R4 sizing behavior.

All observations are recorded to the event ledger for Phase 2 qualification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List


class RiskObservationLevel(str, Enum):
    """Risk observation levels."""

    NORMAL = "NORMAL"  # All within bounds
    ELEVATED = "ELEVATED"  # Approaching limits
    WARNING = "WARNING"  # At or near limits
    CRITICAL = "CRITICAL"  # Breaching limits
    HALT = "HALT"  # Emergency halt required


@dataclass(frozen=True)
class RiskObservation:
    """Single risk observation."""

    dimension: str
    level: str
    value: float
    limit: float | None
    message: str
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "level": self.level,
            "value": self.value,
            "limit": self.limit,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class RiskState:
    """Complete risk state snapshot."""

    overall_level: str
    observations: Dict[str, RiskObservation]
    timestamp: str
    any_critical: bool
    any_warning: bool
    critical_dimensions: List[str]
    warning_dimensions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_level": self.overall_level,
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
            "timestamp": self.timestamp,
            "any_critical": self.any_critical,
            "any_warning": self.any_warning,
            "critical_dimensions": self.critical_dimensions,
            "warning_dimensions": self.warning_dimensions,
        }


class RiskObserver:
    """Continuous risk observation engine.

    OBSERVES, ALERTS, and CONTAINS only.
    Does NOT change R4 sizing behavior.
    """

    def __init__(
        self,
        max_daily_loss: float = 250.0,
        max_drawdown_pct: float = 0.10,
        max_concentration_pct: float = 0.30,
        max_margin_utilization: float = 0.80,
        stale_threshold_seconds: float = 300.0,
        min_equity: float = 4000.0,  # F-003: should match config.live_risk.min_equity
    ) -> None:
        """Initialize risk observer.

        Args:
            max_daily_loss: Maximum daily loss ($)
            max_drawdown_pct: Maximum drawdown (percentage)
            max_concentration_pct: Maximum concentration in single instrument
            max_margin_utilization: Maximum margin utilization
            stale_threshold_seconds: Threshold for stale data detection
            min_equity: Minimum equity floor ($) — should come from config.live_risk.min_equity
        """
        self._max_daily_loss = max_daily_loss
        self._max_drawdown_pct = max_drawdown_pct
        self._max_concentration_pct = max_concentration_pct
        self._max_margin_utilization = max_margin_utilization
        self._stale_threshold = stale_threshold_seconds
        self._min_equity = min_equity

        # State tracking
        self._peak_equity = 0.0
        self._daily_pnl_start = 0.0
        self._last_observation_time = time.time()

        # Observation history
        self._history: List[Dict[str, Any]] = []
        self._max_history = 1000

    def observe(
        self,
        equity: float,
        balance: float,
        free_margin: float,
        positions: List[Dict[str, Any]],
        daily_pnl: float,
        last_update_time: float | None = None,
    ) -> RiskState:
        """Perform comprehensive risk observation.

        Args:
            equity: Current account equity
            balance: Current account balance
            free_margin: Current free margin
            positions: List of current positions
            daily_pnl: Current day's P&L
            last_update_time: Timestamp of last data update

        Returns:
            Complete risk state snapshot
        """
        now = datetime.now(UTC).isoformat()
        observations: Dict[str, RiskObservation] = {}

        # Update peak equity
        if equity > self._peak_equity:
            self._peak_equity = equity

        # 1. Drawdown observation
        drawdown_obs = self._observe_drawdown(equity)
        observations["drawdown"] = drawdown_obs

        # 2. Daily loss observation
        daily_loss_obs = self._observe_daily_loss(daily_pnl)
        observations["daily_loss"] = daily_loss_obs

        # 3. Position count observation
        position_count_obs = self._observe_position_count(positions)
        observations["position_count"] = position_count_obs

        # 4. Gross exposure observation
        gross_exposure_obs = self._observe_gross_exposure(positions, equity)
        observations["gross_exposure"] = gross_exposure_obs

        # 5. Concentration observation
        concentration_obs = self._observe_concentration(positions, equity)
        observations["concentration"] = concentration_obs

        # 6. Margin utilization observation
        margin_obs = self._observe_margin_utilization(equity, free_margin)
        observations["margin_utilization"] = margin_obs

        # 7. SL protection observation
        sl_obs = self._observe_sl_protection(positions)
        observations["sl_protection"] = sl_obs

        # 8. Stale data observation
        stale_obs = self._observe_stale_data(last_update_time)
        observations["stale_data"] = stale_obs

        # 9. Equity floor observation
        equity_floor_obs = self._observe_equity_floor(equity)
        observations["equity_floor"] = equity_floor_obs

        # 10. Loss velocity observation
        loss_velocity_obs = self._observe_loss_velocity(equity, daily_pnl)
        observations["loss_velocity"] = loss_velocity_obs

        # Compute overall state
        critical_dims = [k for k, v in observations.items() if v.level == RiskObservationLevel.CRITICAL.value]
        warning_dims = [
            k
            for k, v in observations.items()
            if v.level in (RiskObservationLevel.WARNING.value, RiskObservationLevel.ELEVATED.value)
        ]

        any_critical = len(critical_dims) > 0
        any_warning = len(warning_dims) > 0

        if any_critical:
            overall_level = RiskObservationLevel.CRITICAL.value
        elif any_warning:
            overall_level = RiskObservationLevel.WARNING.value
        else:
            overall_level = RiskObservationLevel.NORMAL.value

        state = RiskState(
            overall_level=overall_level,
            observations=observations,
            timestamp=now,
            any_critical=any_critical,
            any_warning=any_warning,
            critical_dimensions=critical_dims,
            warning_dimensions=warning_dims,
        )

        # Record to history
        self._history.append(state.to_dict())
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        return state

    def _observe_drawdown(self, equity: float) -> RiskObservation:
        """Observe drawdown from peak."""
        if self._peak_equity <= 0:
            return RiskObservation(
                dimension="drawdown",
                level=RiskObservationLevel.NORMAL.value,
                value=0.0,
                limit=self._max_drawdown_pct,
                message="No peak equity recorded",
                timestamp=datetime.now(UTC).isoformat(),
            )

        drawdown = self._peak_equity - equity
        drawdown_pct = drawdown / self._peak_equity

        if drawdown_pct >= self._max_drawdown_pct:
            level = RiskObservationLevel.CRITICAL.value
            message = f"Drawdown {drawdown_pct:.1%} exceeds limit {self._max_drawdown_pct:.0%}"
        elif drawdown_pct >= self._max_drawdown_pct * 0.8:
            level = RiskObservationLevel.WARNING.value
            message = f"Drawdown {drawdown_pct:.1%} approaching limit"
        elif drawdown_pct >= self._max_drawdown_pct * 0.5:
            level = RiskObservationLevel.ELEVATED.value
            message = f"Drawdown {drawdown_pct:.1%} elevated"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Drawdown {drawdown_pct:.1%} within limits"

        return RiskObservation(
            dimension="drawdown",
            level=level,
            value=drawdown_pct,
            limit=self._max_drawdown_pct,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={
                "peak_equity": self._peak_equity,
                "current_equity": equity,
                "drawdown": drawdown,
            },
        )

    def _observe_daily_loss(self, daily_pnl: float) -> RiskObservation:
        """Observe daily loss."""
        daily_loss = max(0, -daily_pnl)  # Only track losses

        if daily_loss >= self._max_daily_loss:
            level = RiskObservationLevel.CRITICAL.value
            message = f"Daily loss ${daily_loss:.2f} exceeds limit ${self._max_daily_loss:.2f}"
        elif daily_loss >= self._max_daily_loss * 0.8:
            level = RiskObservationLevel.WARNING.value
            message = f"Daily loss ${daily_loss:.2f} approaching limit"
        elif daily_loss >= self._max_daily_loss * 0.5:
            level = RiskObservationLevel.ELEVATED.value
            message = f"Daily loss ${daily_loss:.2f} elevated"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Daily loss ${daily_loss:.2f} within limits"

        return RiskObservation(
            dimension="daily_loss",
            level=level,
            value=daily_loss,
            limit=self._max_daily_loss,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={"daily_pnl": daily_pnl},
        )

    def _observe_position_count(self, positions: List[Dict[str, Any]]) -> RiskObservation:
        """Observe position count."""
        count = len(positions)
        limit = 19  # From config

        if count > limit:
            level = RiskObservationLevel.CRITICAL.value
            message = f"Position count {count} exceeds limit {limit}"
        elif count >= limit * 0.9:
            level = RiskObservationLevel.WARNING.value
            message = f"Position count {count} approaching limit"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Position count {count} within limits"

        return RiskObservation(
            dimension="position_count",
            level=level,
            value=count,
            limit=limit,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _observe_gross_exposure(
        self,
        positions: List[Dict[str, Any]],
        equity: float,
    ) -> RiskObservation:
        """Observe gross exposure."""
        gross_exposure = sum(abs(p.get("notional", 0)) for p in positions)
        exposure_pct = gross_exposure / equity if equity > 0 else 0

        if exposure_pct >= 2.0:  # 200% leverage
            level = RiskObservationLevel.CRITICAL.value
            message = f"Gross exposure {exposure_pct:.1%} exceeds 200%"
        elif exposure_pct >= 1.5:
            level = RiskObservationLevel.WARNING.value
            message = f"Gross exposure {exposure_pct:.1%} elevated"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Gross exposure {exposure_pct:.1%} within limits"

        return RiskObservation(
            dimension="gross_exposure",
            level=level,
            value=exposure_pct,
            limit=2.0,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={"gross_exposure": gross_exposure},
        )

    def _observe_concentration(
        self,
        positions: List[Dict[str, Any]],
        equity: float,
    ) -> RiskObservation:
        """Observe concentration risk."""
        if not positions or equity <= 0:
            return RiskObservation(
                dimension="concentration",
                level=RiskObservationLevel.NORMAL.value,
                value=0.0,
                limit=self._max_concentration_pct,
                message="No positions",
                timestamp=datetime.now(UTC).isoformat(),
            )

        # Find max concentration
        max_concentration = 0.0
        max_symbol = ""
        for pos in positions:
            notional = abs(pos.get("notional", 0))
            concentration = notional / equity
            if concentration > max_concentration:
                max_concentration = concentration
                max_symbol = pos.get("symbol", "?")

        if max_concentration >= self._max_concentration_pct:
            level = RiskObservationLevel.WARNING.value
            message = f"Max concentration {max_concentration:.1%} in {max_symbol} exceeds limit"
        elif max_concentration >= self._max_concentration_pct * 0.8:
            level = RiskObservationLevel.ELEVATED.value
            message = f"Max concentration {max_concentration:.1%} in {max_symbol} elevated"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Max concentration {max_concentration:.1%} in {max_symbol} within limits"

        return RiskObservation(
            dimension="concentration",
            level=level,
            value=max_concentration,
            limit=self._max_concentration_pct,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={"max_symbol": max_symbol},
        )

    def _observe_margin_utilization(
        self,
        equity: float,
        free_margin: float,
    ) -> RiskObservation:
        """Observe margin utilization."""
        if equity <= 0:
            return RiskObservation(
                dimension="margin_utilization",
                level=RiskObservationLevel.CRITICAL.value,
                value=1.0,
                limit=self._max_margin_utilization,
                message="Equity <= 0",
                timestamp=datetime.now(UTC).isoformat(),
            )

        used_margin = equity - free_margin
        utilization = used_margin / equity if equity > 0 else 0

        if utilization >= self._max_margin_utilization:
            level = RiskObservationLevel.CRITICAL.value
            message = f"Margin utilization {utilization:.1%} exceeds limit"
        elif utilization >= self._max_margin_utilization * 0.8:
            level = RiskObservationLevel.WARNING.value
            message = f"Margin utilization {utilization:.1%} approaching limit"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Margin utilization {utilization:.1%} within limits"

        return RiskObservation(
            dimension="margin_utilization",
            level=level,
            value=utilization,
            limit=self._max_margin_utilization,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={"used_margin": used_margin},
        )

    def _observe_sl_protection(self, positions: List[Dict[str, Any]]) -> RiskObservation:
        """Observe SL protection status."""
        unprotected = [p for p in positions if p.get("sl", 0) == 0]

        if unprotected:
            symbols = [p.get("symbol", "?") for p in unprotected]
            level = RiskObservationLevel.WARNING.value
            message = f"{len(unprotected)} positions without SL: {', '.join(symbols)}"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = "All positions have SL protection"

        return RiskObservation(
            dimension="sl_protection",
            level=level,
            value=len(unprotected),
            limit=0,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={
                "unprotected_count": len(unprotected),
                "symbols": [p.get("symbol") for p in unprotected],
            },
        )

    def _observe_stale_data(self, last_update_time: float | None) -> RiskObservation:
        """Observe stale data."""
        if last_update_time is None:
            return RiskObservation(
                dimension="stale_data",
                level=RiskObservationLevel.NORMAL.value,
                value=0.0,
                limit=self._stale_threshold,
                message="No last update time available",
                timestamp=datetime.now(UTC).isoformat(),
            )

        staleness = time.time() - last_update_time

        if staleness >= self._stale_threshold:
            level = RiskObservationLevel.WARNING.value
            message = f"Data stale for {staleness:.0f}s (threshold: {self._stale_threshold:.0f}s)"
        elif staleness >= self._stale_threshold * 0.8:
            level = RiskObservationLevel.ELEVATED.value
            message = f"Data age {staleness:.0f}s approaching threshold"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Data fresh ({staleness:.0f}s old)"

        return RiskObservation(
            dimension="stale_data",
            level=level,
            value=staleness,
            limit=self._stale_threshold,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _observe_equity_floor(self, equity: float) -> RiskObservation:
        """Observe equity floor."""
        min_equity = self._min_equity

        if equity < min_equity:
            level = RiskObservationLevel.CRITICAL.value
            message = f"Equity ${equity:,.2f} below minimum ${min_equity:,.2f}"
        elif equity < min_equity * 1.1:
            level = RiskObservationLevel.WARNING.value
            message = f"Equity ${equity:,.2f} approaching minimum"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Equity ${equity:,.2f} above minimum"

        return RiskObservation(
            dimension="equity_floor",
            level=level,
            value=equity,
            limit=min_equity,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _observe_loss_velocity(
        self,
        equity: float,
        daily_pnl: float,
    ) -> RiskObservation:
        """Observe loss velocity (rate of loss)."""
        # Simplified: compare daily P&L to equity
        if equity <= 0:
            velocity = 0.0
        else:
            velocity = abs(daily_pnl) / equity if daily_pnl < 0 else 0

        if velocity >= 0.05:  # 5% daily loss rate
            level = RiskObservationLevel.CRITICAL.value
            message = f"Loss velocity {velocity:.1%} is critical"
        elif velocity >= 0.02:
            level = RiskObservationLevel.WARNING.value
            message = f"Loss velocity {velocity:.1%} is elevated"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Loss velocity {velocity:.1%} is normal"

        return RiskObservation(
            dimension="loss_velocity",
            level=level,
            value=velocity,
            limit=0.05,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def get_history(self) -> List[Dict[str, Any]]:
        """Get observation history."""
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        """Get observation statistics."""
        if not self._history:
            return {"total_observations": 0}

        levels = {}
        for obs in self._history:
            level = obs.get("overall_level", "UNKNOWN")
            levels[level] = levels.get(level, 0) + 1

        return {
            "total_observations": len(self._history),
            "levels": levels,
            "peak_equity": self._peak_equity,
        }

    def get_streaming_metrics(self) -> Dict[str, Any]:
        """Get real-time streaming metrics for dashboard consumption.

        Returns a snapshot of key portfolio metrics suitable for
        real-time display or external monitoring systems.
        """
        if not self._history:
            return {"status": "no_data"}

        latest = self._history[-1]
        observations = latest.get("observations", {})

        # Compute rolling metrics from recent history
        recent = self._history[-min(60, len(self._history)) :]  # Last 60 observations
        drawdowns = [obs.get("observations", {}).get("drawdown", {}).get("value", 0) for obs in recent]
        daily_losses = [obs.get("observations", {}).get("daily_loss", {}).get("value", 0) for obs in recent]

        return {
            "timestamp": latest.get("timestamp"),
            "overall_level": latest.get("overall_level"),
            "equity": observations.get("equity_floor", {}).get("value", 0),
            "drawdown": observations.get("drawdown", {}).get("value", 0),
            "drawdown_limit": observations.get("drawdown", {}).get("limit", 0),
            "daily_loss": observations.get("daily_loss", {}).get("value", 0),
            "daily_loss_limit": observations.get("daily_loss", {}).get("limit", 0),
            "position_count": observations.get("position_count", {}).get("value", 0),
            "position_limit": observations.get("position_count", {}).get("limit", 0),
            "gross_exposure": observations.get("gross_exposure", {}).get("value", 0),
            "margin_utilization": observations.get("margin_utilization", {}).get("value", 0),
            "concentration": observations.get("concentration", {}).get("value", 0),
            "sl_unprotected": observations.get("sl_protection", {}).get("value", 0),
            "loss_velocity": observations.get("loss_velocity", {}).get("value", 0),
            "peak_drawdown_rolling": max(drawdowns) if drawdowns else 0,
            "max_daily_loss_rolling": max(daily_losses) if daily_losses else 0,
            "critical_dimensions": latest.get("critical_dimensions", []),
            "warning_dimensions": latest.get("warning_dimensions", []),
            "any_critical": latest.get("any_critical", False),
            "any_warning": latest.get("any_warning", False),
        }

    def observe_correlation(
        self,
        positions: List[Dict[str, Any]],
        returns: Dict[str, float] | None = None,
    ) -> RiskObservation:
        """Observe correlation risk across positions.

        Checks if too many positions are in the same asset class
        or if returns are highly correlated.
        """
        if not positions:
            return RiskObservation(
                dimension="correlation",
                level=RiskObservationLevel.NORMAL.value,
                value=0.0,
                limit=0.5,
                message="No positions",
                timestamp=datetime.now(UTC).isoformat(),
            )

        # Group by asset class (simplified)
        asset_classes: Dict[str, int] = {}
        for pos in positions:
            symbol = pos.get("symbol", "")
            # Simple classification
            if any(x in symbol.upper() for x in ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]):
                ac = "FX"
            elif any(x in symbol.upper() for x in ["XAU", "XAG"]):
                ac = "METALS"
            elif any(x in symbol.upper() for x in ["US30", "SPX", "NAS"]):
                ac = "INDICES"
            elif any(x in symbol.upper() for x in ["BTC", "ETH"]):
                ac = "CRYPTO"
            elif any(x in symbol.upper() for x in ["OIL", "NGAS"]):
                ac = "ENERGY"
            else:
                ac = "OTHER"
            asset_classes[ac] = asset_classes.get(ac, 0) + 1

        total = len(positions)
        max_class = max(asset_classes.values()) if asset_classes else 0
        max_class_name = max(asset_classes, key=asset_classes.get) if asset_classes else "?"
        concentration = max_class / total if total > 0 else 0

        if concentration >= 0.7:  # 70% in one class
            level = RiskObservationLevel.WARNING.value
            message = f"High correlation: {concentration:.0%} in {max_class_name} ({max_class}/{total})"
        elif concentration >= 0.5:
            level = RiskObservationLevel.ELEVATED.value
            message = f"Moderate correlation: {concentration:.0%} in {max_class_name}"
        else:
            level = RiskObservationLevel.NORMAL.value
            message = f"Diversified: max {concentration:.0%} in {max_class_name}"

        return RiskObservation(
            dimension="correlation",
            level=level,
            value=concentration,
            limit=0.7,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
            details={"asset_classes": asset_classes},
        )
