from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RegimeVelocity:
    """Rate-of-change across all four performance dimensions.
    Computed from short-window (5 cycle) vs medium-window (20 cycle) deltas.
    Positive values indicate deterioration (for penalty dimensions) or
    improvement (for recovery dimensions)."""

    pnl_velocity: float  # slope of portfolio_value over last 5 cycles. Negative = losing
    pnl_acceleration: float  # change in pnl_velocity over last 5 cycles
    vol_velocity: float  # change in atr_ratio over last 5 cycles. Positive = vol expanding
    degradation_velocity: float  # change in calibration_ece over last 5 cycles. Positive = drifting faster
    execution_velocity: float  # change in slippage over last 5 cycles. Positive = friction increasing


@dataclass(frozen=True)
class PerformanceState:
    """System behavioral state — telemetry layer, not control input.
    Built after Phase 4 each cycle, consumed by RiskEngine next cycle.
    IMMUTABLE — single frozen snapshot per cycle."""

    version: int
    generated_at: datetime

    # ── Individual position scalars ──
    outcome_scalar: float  # [0.3, 1.2] — win/loss streak adaptation
    degradation_scalar: float  # [0.3, 1.0] — model health
    market_scalar: float  # [0.4, 1.0] — vol/liquidity regime
    execution_scalar: float  # [0.5, 1.0] — fill quality

    # ── Velocity layer ──
    velocity: RegimeVelocity
    velocity_scalar: float  # [0.5, 1.5] — amplifies or dampens position-based response

    # ── Composite (position × velocity) ──
    composite_scalar: float  # computed: product of all 5 scalars, clamped [0.02, 1.2]

    # ── Underlying metrics for debugging / dashboard ──
    win_rate_20: float
    consecutive_losses: int
    r_cumulative_20: float
    calibration_ece: float
    atr_ratio: float
    regime_label: str  # "TREND" | "RANGE" | "VOLATILE"
    slippage_p90: float
