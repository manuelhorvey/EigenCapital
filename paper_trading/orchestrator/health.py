"""Health monitoring for the actor-based engine.

Provides:
    - HealthMonitor: aggregates health across actors, computes system-wide stats
    - CircuitBreaker: checks portfolio-level conditions (drawdown, vol, halt ratio)
    - RecoveryScheduler: manages recovery probe timing for halted actors
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum

from paper_trading.orchestrator.actor import (
    AssetActor,
    compute_health_snapshot,
)

logger = logging.getLogger("eigencapital.orchestrator.health")


def portfolio_vol_estimate(portfolio_returns: list[float]) -> float | None:
    """Estimate daily portfolio return vol from rolling returns (60-day).

    Returns None if fewer than 30 observations are available.
    """
    if len(portfolio_returns) < 30:
        return None
    arr = portfolio_returns[-60:]
    mean = sum(arr) / len(arr)
    ddof = 1 if len(arr) > 1 else 0
    var = sum((x - mean) ** 2 for x in arr) / (len(arr) - ddof)
    return math.sqrt(var)


def compute_var_cvar(
    portfolio_returns: list[float],
    window: int = 60,
    percentile: float = 0.05,
) -> tuple[float | None, float | None]:
    """Compute VaR and CVaR at the given percentile from rolling returns.

    Args:
        portfolio_returns: list of daily portfolio returns (fraction).
        window: number of most recent returns to use.
        percentile: tail percentile (0.05 = 95% VaR).

    Returns:
        (var, cvar) tuple, each as fraction. Returns (None, None) if
        fewer than ``window`` observations are available.
    """
    if len(portfolio_returns) < window:
        return None, None
    rets = sorted(portfolio_returns[-window:])
    n = len(rets)
    idx = max(0, min(n - 1, int(percentile * n)))
    var = rets[idx]
    loss_idx = rets[: idx + 1]
    cvar = sum(loss_idx) / max(len(loss_idx), 1)
    return var, cvar


# ── HealthMonitor ─────────────────────────────────────────────────────────────


@dataclass
class HealthSummary:
    """System-wide health summary for one observation point."""

    timestamp: float = field(default_factory=time.monotonic)
    n_green: int = 0
    n_degraded: int = 0
    n_halted: int = 0
    n_recovering: int = 0
    halt_ratio: float = 0.0
    portfolio_drawdown_pct: float = 0.0
    portfolio_vol_zscore: float = 0.0
    emergency_halt_active: bool = False
    recommendations: list[str] = field(default_factory=list)


class HealthMonitor:
    """Continuously monitors actor health and portfolio conditions.

    Call ``observe()`` once per engine cycle.
    """

    def __init__(
        self,
        max_halt_ratio: float = 0.5,
        max_portfolio_drawdown_pct: float = 0.25,
        vol_spike_threshold: float = 3.0,
        history_window: int = 252,
    ):
        self._max_halt_ratio = max_halt_ratio
        self._max_drawdown = max_portfolio_drawdown_pct
        self._vol_spike_threshold = vol_spike_threshold
        self._history: list[HealthSummary] = []
        self._history_window = history_window
        self._last_warning: dict[str, float] = {}

    def observe(
        self,
        actors: dict[str, AssetActor],
        portfolio_value: float | None = None,
        portfolio_peak: float | None = None,
        portfolio_vol: float | None = None,
        baseline_vol: float | None = None,
    ) -> HealthSummary:
        snapshot = compute_health_snapshot(actors)
        summary = HealthSummary(
            timestamp=time.monotonic(),
            n_green=snapshot.green,
            n_degraded=snapshot.degraded,
            n_halted=snapshot.halted,
            n_recovering=snapshot.recovering,
            halt_ratio=snapshot.halt_ratio,
        )

        # Portfolio drawdown
        if portfolio_value is not None and portfolio_peak is not None and portfolio_peak > 0:
            dd = (portfolio_value - portfolio_peak) / portfolio_peak
            summary.portfolio_drawdown_pct = round(dd * 100, 2)
            if dd <= -self._max_drawdown:
                rec = (
                    f"portfolio_drawdown_{summary.portfolio_drawdown_pct:.1f}%_exceeds_"
                    f"{self._max_drawdown * 100:.0f}%_limit"
                )
                summary.recommendations.append(rec)

        # Portfolio vol spike
        if portfolio_vol is not None and baseline_vol is not None and baseline_vol > 0:
            vol_ratio = portfolio_vol / baseline_vol
            summary.portfolio_vol_zscore = round(vol_ratio, 2)
            if vol_ratio >= self._vol_spike_threshold:
                summary.recommendations.append(
                    f"vol_spike_{vol_ratio:.1f}x_exceeds_{self._vol_spike_threshold:.0f}x_threshold"
                )

        # Halt ratio exceeded
        if snapshot.halt_ratio >= self._max_halt_ratio:
            summary.recommendations.append(f"halt_ratio_{snapshot.halt_ratio:.2f}_exceeds_{self._max_halt_ratio:.2f}")

        # Equity cluster alarm removed: ES, NQ, ^DJI no longer in portfolio

        # Rate-limit warnings: same recommendation within 60s
        throttled = []
        for rec in summary.recommendations:
            last = self._last_warning.get(rec, 0.0)
            if time.monotonic() - last > 60.0:
                self._last_warning[rec] = time.monotonic()
                throttled.append(rec)
            else:
                logger.debug("HealthMonitor: suppressed duplicate recommendation: %s", rec)
        summary.recommendations = throttled

        self._history.append(summary)
        if len(self._history) > self._history_window:
            self._history = self._history[-self._history_window :]

        return summary

    def get_recent_history(self, n: int = 10) -> list[HealthSummary]:
        return self._history[-n:]

    @property
    def is_system_healthy(self) -> bool:
        if not self._history:
            return True
        return self._history[-1].halt_ratio < self._max_halt_ratio


# ── CircuitBreaker ────────────────────────────────────────────────────────────


@dataclass
class BreakerDecision:
    trip: bool
    reason: str
    severity: str  # "info", "warning", "critical"
    actors_to_halt: list[str] | None = None


class CircuitBreaker:
    """Portfolio-level circuit breaker with multiple trip conditions.

    Trips when ANY of:
        - Portfolio drawdown exceeds max_drawdown_pct
        - Halt ratio exceeds max_halt_ratio
        - Portfolio vol exceeds baseline_vol * vol_spike_threshold
        - Consecutive_portfolio_losses exceeds max_consecutive_losses
    """

    def __init__(
        self,
        max_drawdown_pct: float = 0.25,
        max_halt_ratio: float = 0.50,
        vol_spike_threshold: float = 3.0,
        max_consecutive_losses: int = 7,
        loss_streak_lookback: int = 30,
    ):
        # max_consecutive_losses=7 calibrated by circuit_breaker_sim.py
        # (2026-06-22, 10K sims across 3 horizons, 10-day blocks).
        # Caveat: calibration window was a 14-month bull market; revisit
        # after 6 months of live data or a -10R drawdown, whichever first.
        self._max_drawdown = max_drawdown_pct
        self._max_halt_ratio = max_halt_ratio
        self._vol_spike = vol_spike_threshold
        self._max_losses = max_consecutive_losses
        self._loss_lookback = loss_streak_lookback
        self._daily_pnl_history: list[float] = []

    def check(
        self,
        portfolio_value: float,
        peak_value: float | None = None,
        portfolio_vol: float | None = None,
        baseline_vol: float | None = None,
        actors: dict[str, AssetActor] | None = None,
    ) -> BreakerDecision:
        # Peak value is now passed in from the orchestrator (single source of truth).
        # The CircuitBreaker no longer tracks its own _peak_value to avoid
        # divergence from EngineOrchestrator._peak_portfolio_value.
        _peak = peak_value if peak_value is not None else portfolio_value
        dd = (portfolio_value - _peak) / _peak if _peak > 0 else 0.0

        # 1. Drawdown trip
        if dd <= -self._max_drawdown:
            return BreakerDecision(
                trip=True,
                reason=f"dd={dd:.2%}≤{self._max_drawdown:.0%}",
                severity="critical",
                actors_to_halt=list(actors.keys()) if actors else None,
            )

        # 2. Vol spike trip
        if portfolio_vol is not None and baseline_vol is not None and baseline_vol > 0:
            vol_ratio = portfolio_vol / baseline_vol
            if vol_ratio >= self._vol_spike:
                return BreakerDecision(
                    trip=True,
                    reason=f"vol_spike={vol_ratio:.1f}x≥{self._vol_spike:.0f}x",
                    severity="critical",
                )

        # 3. Halt ratio trip
        if actors is not None:
            health = compute_health_snapshot(actors)
            if health.halt_ratio >= self._max_halt_ratio:
                return BreakerDecision(
                    trip=True,
                    reason=f"halt_ratio={health.halt_ratio:.2f}≥{self._max_halt_ratio:.2f}",
                    severity="critical",
                )

        # 4. Consecutive loss streak
        recent = self._daily_pnl_history[-self._loss_lookback :]
        streak = 0
        for pnl in reversed(recent):
            if pnl < 0:
                streak += 1
            else:
                break
        if streak >= self._max_losses:
            return BreakerDecision(
                trip=True,
                reason=f"{streak}_consecutive_losses≥{self._max_losses}",
                severity="warning",
            )

        return BreakerDecision(trip=False, reason="ok", severity="info")

    def restore_state(self, peak_value: float | None, daily_pnl: list[float] | None) -> None:
        # peak_value is no longer stored locally — it is passed from the orchestrator.
        # Only restore daily PnL history which is unique to the CircuitBreaker.
        if daily_pnl is not None:
            self._daily_pnl_history = list(daily_pnl)

    def snapshot_state(self) -> tuple[float | None, list[float]]:
        # peak_value is no longer stored locally — the orchestrator owns the canonical peak.
        return (None, list(self._daily_pnl_history))

    def record_daily_pnl(self, pnl: float) -> None:
        self._daily_pnl_history.append(pnl)
        if len(self._daily_pnl_history) > 252 * 3:
            self._daily_pnl_history = self._daily_pnl_history[-(252 * 3) :]


class HaltReason(Enum):
    """Reason a circuit breaker or emergency halt was triggered.

    Used to gate auto-unhalt eligibility in EngineOrchestrator.
    """

    DRAWDOWN = "drawdown"
    HALT_RATIO = "halt_ratio"
    VOL_SPIKE = "vol_spike"
    CONSECUTIVE_LOSSES = "consecutive_losses"


# ── RecoveryScheduler ─────────────────────────────────────────────────────────


@dataclass
class RecoveryAttempt:
    asset: str
    attempt_time: float
    success: bool
    error: str = ""


class RecoveryScheduler:
    """Manages recovery probe timing for halted actors.

    Uses exponential backoff::
        backoff = base_delay * 2 ** attempts
        max_backoff = 3600 (1 hour)
    """

    def __init__(self, base_delay_seconds: float = 60.0, max_delay_seconds: float = 3600.0):
        self._base = base_delay_seconds
        self._max = max_delay_seconds
        self._attempts: dict[str, int] = {}
        self._last_probe: dict[str, float] = {}
        self._history: list[RecoveryAttempt] = []

    def is_due(self, asset: str) -> bool:
        now = time.monotonic()
        last = self._last_probe.get(asset, 0.0)
        delay = min(self._base * (2 ** self._attempts.get(asset, 0)), self._max)
        return (now - last) >= delay

    def record_result(self, asset: str, success: bool, error: str = "") -> None:
        self._history.append(
            RecoveryAttempt(
                asset=asset,
                attempt_time=time.monotonic(),
                success=success,
                error=error,
            )
        )
        if success:
            self._attempts[asset] = 0
        else:
            self._attempts[asset] = self._attempts.get(asset, 0) + 1
            self._last_probe[asset] = time.monotonic()

    def reset(self, asset: str) -> None:
        self._attempts.pop(asset, None)
        self._last_probe.pop(asset, None)
