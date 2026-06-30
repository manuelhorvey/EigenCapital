from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
        assert self.total_equity >= 0
        assert self.open_position_count >= 0
        assert -1.0 <= self.drawdown_pct <= 0.0, f"drawdown_pct={self.drawdown_pct} must be <= 0"
