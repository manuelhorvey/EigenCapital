"""PerformanceStateBuilder — builds the frozen PerformanceState snapshot.

Consumes data from OutcomeTracker, DegradationMonitor (wrapping existing drift.py
and ECETracker), MarketStateReader, and ExecutionQualityTracker.
Computes both position-based scalars and velocity (rate of change) scalars."""

from __future__ import annotations

import logging
from collections import deque

from eigencapital.domain.time import utc_now
from paper_trading.pek.contracts.performance_state import PerformanceState, RegimeVelocity
from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

logger = logging.getLogger("eigencapital.pek.perf")


class DegradationMonitor:
    """Wraps existing drift, ECE, and PSI trackers into a scalar output."""

    def __init__(self):
        self._ece_history: deque[float] = deque(maxlen=20)
        self._feature_stability_history: deque[float] = deque(maxlen=20)

    def update(self, ece: float, feature_stability: float) -> None:
        self._ece_history.append(ece)
        self._feature_stability_history.append(feature_stability)

    def scalar(self) -> float:
        if not self._ece_history or not self._feature_stability_history:
            return 1.0
        avg_ece = sum(self._ece_history) / len(self._ece_history)
        avg_stability = sum(self._feature_stability_history) / len(self._feature_stability_history)
        if avg_ece > 0.15 and avg_stability < 0.60:
            return 0.4
        if avg_ece > 0.10 or avg_stability < 0.70:
            return 0.6
        return 1.0

    def ece_velocity(self) -> float:
        """Rate of change in ECE over last 5 observations. Positive = getting worse."""
        if len(self._ece_history) < 5:
            return 0.0
        recent = list(self._ece_history)[-5:]
        return (recent[-1] - recent[0]) / max(len(recent) - 1, 1)


class MarketStateReader:
    """Reads current market regime, ATR ratio, and liquidity state."""

    def __init__(self):
        self._atr_history: deque[float] = deque(maxlen=21)
        self._current_regime: str = "RANGE"
        self._current_spread_regime: str = "NORMAL"
        self._current_liquidity_regime: str = "NORMAL"

    def update(self, atr_ratio: float, regime: str, spread_regime: str, liquidity_regime: str) -> None:
        self._atr_history.append(atr_ratio)
        self._current_regime = regime
        self._current_spread_regime = spread_regime
        self._current_liquidity_regime = liquidity_regime

    def atr_ratio(self) -> float:
        return self._atr_history[-1] if self._atr_history else 1.0

    def atr_ratio_velocity(self) -> float:
        if len(self._atr_history) < 5:
            return 0.0
        recent = list(self._atr_history)[-5:]
        return (recent[-1] - recent[0]) / max(len(recent) - 1, 1)

    def scalar(self) -> float:
        """Market scalar — higher = less risk reduction.

        Convention notes (see audit finding #L4):
        - RANGE returns 1.0 (no reduction) because the model's momentum bias
          produces fewer confident bets in choppy markets — position-taking
          is naturally suppressed by other gates (confidence, spread).
        - TREND returns 0.8 (moderate reduction) as a hedge against the
          system's known failure mode: confident wrong-direction bets during
          sustained trends (BUY inversion discovery, 2026-06-20).  The SELL_ONLY
          gate covers 3 permanently flagged assets; this scalar covers all
          assets as a second layer of protection.
        """
        atr = self.atr_ratio()
        if self._current_liquidity_regime == "STRESSED":
            return 0.4
        if self._current_spread_regime == "WIDE":
            return 0.6
        if atr > 1.5 and self._current_regime == "VOLATILE":
            return 0.5
        if self._current_regime == "RANGE":
            return 1.0
        return 0.8  # TREND or unknown — see docstring above


class ExecutionQualityTracker:
    """Tracks slippage, fill quality, and MT5 connection health."""

    def __init__(self):
        self._slippage_history: deque[float] = deque(maxlen=200)
        self._partial_fills: int = 0
        self._total_trades: int = 0
        self._outcome_tracker = OutcomeTracker(window=20)

    def record_trade(
        self,
        asset: str,
        exit_reason: str,
        r_multiple: float,
        mae_pct: float,
        mfe_pct: float,
    ) -> None:
        """Record a completed trade outcome for the given asset."""
        self._outcome_tracker.record_trade(exit_reason, r_multiple, mae_pct, mfe_pct)

    def record_slippage(self, slippage_pct: float) -> None:
        self._slippage_history.append(abs(slippage_pct))

    def record_fill(self, was_partial: bool) -> None:
        self._total_trades += 1
        if was_partial:
            self._partial_fills += 1

    def slippage_p90(self) -> float:
        if len(self._slippage_history) < 10:
            return 0.0
        sorted_slips = sorted(self._slippage_history)
        idx = int(len(sorted_slips) * 0.9)
        return sorted_slips[min(idx, len(sorted_slips) - 1)]

    def slippage_velocity(self) -> float:
        if len(self._slippage_history) < 10:
            return 0.0
        recent = list(self._slippage_history)[-5:]
        older = list(self._slippage_history)[-10:-5]
        if len(older) == 0:
            return 0.0
        return (sum(recent) / len(recent)) / (sum(older) / len(older)) - 1.0

    def partial_fill_rate(self) -> float:
        if self._total_trades == 0:
            return 0.0
        return self._partial_fills / self._total_trades

    def scalar(self) -> float:
        p90 = self.slippage_p90()
        pfr = self.partial_fill_rate()
        if pfr > 0.20:
            return 0.5
        if p90 > 3.0:  # 3% slippage p90 threshold
            return 0.6
        return 1.0


class VelocityProcessor:
    """Computes the velocity scalar — anticipatory correction factor.
    Split into trend_factor, shock_factor, and health_factor to avoid
    accidental coupling between independent signals."""

    def __init__(self):
        self._pnl_history: deque[float] = deque(maxlen=20)

    def update_portfolio_value(self, value: float) -> None:
        self._pnl_history.append(value)

    def compute(
        self,
        pnl_velocity: float,
        vol_velocity: float,
        degradation_velocity: float,
        execution_velocity: float,
    ) -> RegimeVelocity:
        pnl_acc = self._compute_acceleration(self._pnl_history)
        # Trend factor: positive PnL velocity = recovery, negative = deterioration
        if pnl_velocity < -0.02 and vol_velocity > 0.1:
            trend_factor = 0.5  # crash: losing AND vol expanding
        elif pnl_velocity < -0.01:
            trend_factor = 0.7  # moderate deterioration
        elif pnl_velocity > 0.02 and vol_velocity < -0.05:
            trend_factor = 1.3  # recovery: winning AND vol contracting
        elif pnl_velocity > 0.01:
            trend_factor = 1.15  # mild recovery
        else:
            trend_factor = 1.0

        # Shock factor: volatility + execution degradation
        if vol_velocity > 0.15 or execution_velocity > 0.1:
            shock_factor = 0.5
        elif vol_velocity > 0.08 or execution_velocity > 0.05:
            shock_factor = 0.7
        else:
            shock_factor = 1.0

        # Health factor: model degradation velocity
        if degradation_velocity > 0.05:
            health_factor = 0.6
        elif degradation_velocity > 0.02:
            health_factor = 0.8
        else:
            health_factor = 1.0

        raw = (trend_factor * shock_factor * health_factor) ** (1.0 / 3.0)
        velocity_scalar = max(0.5, min(1.5, raw))

        return RegimeVelocity(
            pnl_velocity=pnl_velocity,
            pnl_acceleration=pnl_acc,
            vol_velocity=vol_velocity,
            degradation_velocity=degradation_velocity,
            execution_velocity=execution_velocity,
        ), velocity_scalar

    @staticmethod
    def _compute_acceleration(history: deque) -> float:
        if len(history) < 10:
            return 0.0
        recent = list(history)
        half = len(recent) // 2
        first_half = recent[:half]
        second_half = recent[half:]
        v1 = (first_half[-1] - first_half[0]) / max(len(first_half) - 1, 1)
        v2 = (second_half[-1] - second_half[0]) / max(len(second_half) - 1, 1)
        return v2 - v1


class PerformanceStateBuilder:
    """Factory for PerformanceState. Gathers data from sub-trackers,
    computes scalars, produces frozen snapshot.

    Call build() after Phase 4 each cycle, after trade outcomes are settled."""

    def __init__(self):
        self.outcome = OutcomeTracker(window=20)
        self.degradation = DegradationMonitor()
        self.market = MarketStateReader()
        self.execution = ExecutionQualityTracker()
        self.velocity = VelocityProcessor()
        self._version = 0
        self._ece_connected: bool = False
        self._ece_warned: bool = False
        self._portfolio_value_history: deque[float] = deque(maxlen=20)

    def build(self, portfolio_value: float) -> PerformanceState:
        self._version += 1
        self._portfolio_value_history.append(portfolio_value)
        self.velocity.update_portfolio_value(portfolio_value)

        # Compute position-based scalars
        outcome_scalar = self.outcome.outcome_scalar()
        degradation_scalar = self.degradation.scalar()
        market_scalar = self.market.scalar()
        execution_scalar = self.execution.scalar()

        # Compute velocities
        pnl_vel = self._compute_pnl_velocity()
        vol_vel = self.market.atr_ratio_velocity()
        deg_vel = self.degradation.ece_velocity()
        exec_vel = self.execution.slippage_velocity()

        velocity_obj, velocity_scalar = self.velocity.compute(
            pnl_velocity=pnl_vel,
            vol_velocity=vol_vel,
            degradation_velocity=deg_vel,
            execution_velocity=exec_vel,
        )

        # Composite: position × velocity
        position = outcome_scalar * degradation_scalar * market_scalar * execution_scalar
        composite = position * velocity_scalar
        composite = max(0.02, min(1.2, composite))

        return PerformanceState(
            version=self._version,
            generated_at=utc_now(),
            outcome_scalar=outcome_scalar,
            degradation_scalar=degradation_scalar,
            market_scalar=market_scalar,
            execution_scalar=execution_scalar,
            velocity=velocity_obj,
            velocity_scalar=velocity_scalar,
            composite_scalar=composite,
            win_rate_20=self.outcome.win_rate,
            consecutive_losses=self.outcome.consecutive_losses,
            r_cumulative_20=self.outcome.r_cumulative,
            calibration_ece=self._ece_value(),
            atr_ratio=self.market.atr_ratio(),
            regime_label=self.market._current_regime,
            slippage_p90=self.execution.slippage_p90(),
        )

    def _ece_value(self) -> float:
        """Return calibration ECE, logging a warning once if ECETracker was
        never connected by an external caller.

        The original design intended for ``calibration_ece`` to be populated
        from an ``ECETracker`` instance (see ``eigencapital.calibration.ECE``).
        That wiring was never completed.  This method returns 0.0 and warns
        once per instance lifetime so the gap is visible in logs without
        crashing or silently producing a misleading value.
        """
        if not self._ece_connected and not self._ece_warned:
            logger.warning(
                "PerformanceStateBuilder.calibration_ece=0.0 — "
                "ECETracker was never connected. "
                "See eigencapital.calibration.ECE for the intended wiring path."
            )
            self._ece_warned = True
        return 0.0

    def _compute_pnl_velocity(self) -> float:
        if len(self._portfolio_value_history) < 5:
            return 0.0
        recent = list(self._portfolio_value_history)[-5:]
        return (recent[-1] - recent[0]) / max(recent[0], 1.0)
