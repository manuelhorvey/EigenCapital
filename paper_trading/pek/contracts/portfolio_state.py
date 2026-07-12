from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime


logger = logging.getLogger("eigencapital.pek.portfolio_state")


@dataclass(frozen=True)
class PositionInfo:
    """Snapshot of one open position. Frozen — never mutated after construction."""

    asset: str
    side: str  # "long" | "short"
    notional: float
    entry_price: float
    current_price: float
    sl_distance_pct: float
    current_pnl_pct: float
    mtm_value: float


@dataclass(frozen=True)
class ClusterInfo:
    """Correlated cluster snapshot. Detected from live positions, not rebalance targets."""

    factor_group: str  # "CHF", "US_EQUITY", "COMMODITY", etc.
    assets: tuple[str, ...]
    dominant_side: str | None  # "long" | "short" | None
    total_notional: float
    position_count: int
    average_correlation: float


@dataclass(frozen=True)
class AssetGateState:
    """Per-asset gate results, pre-computed once per snapshot cycle.
    Avoids re-fetching spread/price/session per asset during admission."""

    asset: str
    spread_ok: bool
    session_ok: bool
    sell_only_ok: bool
    confidence_ok: bool
    risk_off_ok: bool
    hysteresis_ok: bool
    conviction_ok: bool

    @property
    def all_ok(self) -> bool:
        return (
            self.spread_ok
            and self.session_ok
            and self.sell_only_ok
            and self.confidence_ok
            and self.risk_off_ok
            and self.hysteresis_ok
            and self.conviction_ok
        )


@dataclass(frozen=True)
class PortfolioStateSnapshot:
    """Single authoritative portfolio exposure state.
    Built once per cycle in the pre-phase, never mutated downstream.
    All admission decisions use THIS snapshot as the single source of truth."""

    # ── Identity ──
    version: int
    generated_at: datetime
    mode: str  # "production" | "challenge_ftmo_10k" | "live"

    # ── Core equity ──
    total_equity: float
    peak_value: float
    drawdown_pct: float

    # ── Open positions (from actual live positions) ──
    positions: tuple[PositionInfo, ...]
    total_long_notional: float
    total_short_notional: float
    gross_exposure: float  # long + short
    net_exposure: float  # long - short
    open_position_count: int

    # ── Remaining risk budgets ──
    daily_pnl: float
    daily_loss_remaining: float
    max_daily_loss: float
    drawdown_remaining: float
    leverage_remaining: float  # PERSISTENT across cycles, replenished on close
    max_leverage: float
    concurrent_remaining: int
    max_concurrent: int

    # ── Factor exposures (from LIVE positions, not rebalance targets) ──
    factor_exposures: tuple[tuple[str, float], ...]  # (factor, net_exposure)
    factor_limits: tuple[tuple[str, float, float], ...]  # (factor, min, max)
    factor_headroom: tuple[tuple[str, float], ...]  # (factor, remaining_capacity)

    # ── Cluster exposures ──
    clusters: tuple[ClusterInfo, ...]

    # ── Per-asset gate pre-compute ──
    asset_gates: tuple[AssetGateState, ...]

    # ── Mode-derived parameters for downstream consumption ──
    max_risk_per_trade_pct: float
    min_risk_per_trade_pct: float
    position_ranking_enabled: bool

    def __post_init__(self):
        if self.total_equity < 0:
            raise ValueError(f"total_equity must be >= 0, got {self.total_equity}")
        if self.open_position_count < 0:
            raise ValueError(f"open_position_count must be >= 0, got {self.open_position_count}")
        # Clamp drawdown_pct to [-1.0, 0.0] to handle floating-point edge cases
        # where peak_value slightly exceeds total_equity due to price update timing,
        # FX conversion rounding, or stale snapshot restores. A small positive value
        # (e.g. +0.0001) should not crash the system on restart.
        _original = self.drawdown_pct
        _clamped = min(0.0, max(-1.0, _original))
        if _clamped != _original:
            logger.warning(
                "drawdown_pct clamped from %.6f to %.6f — likely a floating-point edge case "
                "from price update timing, FX rounding, or stale snapshot",
                _original,
                _clamped,
            )
        object.__setattr__(self, "drawdown_pct", _clamped)
