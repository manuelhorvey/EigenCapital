from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "side": self.side,
            "notional": self.notional,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "sl_distance_pct": self.sl_distance_pct,
            "current_pnl_pct": self.current_pnl_pct,
            "mtm_value": self.mtm_value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PositionInfo:
        return cls(**d)


@dataclass(frozen=True)
class ClusterInfo:
    """Correlated cluster snapshot. Detected from live positions, not rebalance targets."""

    factor_group: str  # "CHF", "US_EQUITY", "COMMODITY", etc.
    assets: tuple[str, ...]
    dominant_side: str | None  # "long" | "short" | None
    total_notional: float
    position_count: int
    average_correlation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_group": self.factor_group,
            "assets": list(self.assets),
            "dominant_side": self.dominant_side,
            "total_notional": self.total_notional,
            "position_count": self.position_count,
            "average_correlation": self.average_correlation,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClusterInfo:
        return cls(
            factor_group=d["factor_group"],
            assets=tuple(d["assets"]),
            dominant_side=d.get("dominant_side"),
            total_notional=d["total_notional"],
            position_count=d["position_count"],
            average_correlation=d["average_correlation"],
        )


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "spread_ok": self.spread_ok,
            "session_ok": self.session_ok,
            "sell_only_ok": self.sell_only_ok,
            "confidence_ok": self.confidence_ok,
            "risk_off_ok": self.risk_off_ok,
            "hysteresis_ok": self.hysteresis_ok,
            "conviction_ok": self.conviction_ok,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssetGateState:
        return cls(**d)


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
    max_positions_per_cluster: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at.isoformat(),
            "mode": self.mode,
            "total_equity": self.total_equity,
            "peak_value": self.peak_value,
            "drawdown_pct": self.drawdown_pct,
            "positions": [p.to_dict() for p in self.positions],
            "total_long_notional": self.total_long_notional,
            "total_short_notional": self.total_short_notional,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "open_position_count": self.open_position_count,
            "daily_pnl": self.daily_pnl,
            "daily_loss_remaining": self.daily_loss_remaining,
            "max_daily_loss": self.max_daily_loss,
            "drawdown_remaining": self.drawdown_remaining,
            "leverage_remaining": self.leverage_remaining,
            "max_leverage": self.max_leverage,
            "concurrent_remaining": self.concurrent_remaining,
            "max_concurrent": self.max_concurrent,
            "factor_exposures": [list(t) for t in self.factor_exposures],
            "factor_limits": [list(t) for t in self.factor_limits],
            "factor_headroom": [list(t) for t in self.factor_headroom],
            "clusters": [c.to_dict() for c in self.clusters],
            "asset_gates": [g.to_dict() for g in self.asset_gates],
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "min_risk_per_trade_pct": self.min_risk_per_trade_pct,
            "position_ranking_enabled": self.position_ranking_enabled,
            "max_positions_per_cluster": self.max_positions_per_cluster,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PortfolioStateSnapshot:
        return cls(
            version=d["version"],
            generated_at=datetime.fromisoformat(d["generated_at"]),
            mode=d["mode"],
            total_equity=d["total_equity"],
            peak_value=d["peak_value"],
            drawdown_pct=d["drawdown_pct"],
            positions=tuple(PositionInfo.from_dict(p) for p in d["positions"]),
            total_long_notional=d["total_long_notional"],
            total_short_notional=d["total_short_notional"],
            gross_exposure=d["gross_exposure"],
            net_exposure=d["net_exposure"],
            open_position_count=d["open_position_count"],
            daily_pnl=d["daily_pnl"],
            daily_loss_remaining=d["daily_loss_remaining"],
            max_daily_loss=d["max_daily_loss"],
            drawdown_remaining=d["drawdown_remaining"],
            leverage_remaining=d["leverage_remaining"],
            max_leverage=d["max_leverage"],
            concurrent_remaining=d["concurrent_remaining"],
            max_concurrent=d["max_concurrent"],
            factor_exposures=tuple(tuple(t) for t in d["factor_exposures"]),
            factor_limits=tuple(tuple(t) for t in d["factor_limits"]),
            factor_headroom=tuple(tuple(t) for t in d["factor_headroom"]),
            clusters=tuple(ClusterInfo.from_dict(c) for c in d["clusters"]),
            asset_gates=tuple(AssetGateState.from_dict(g) for g in d["asset_gates"]),
            max_risk_per_trade_pct=d["max_risk_per_trade_pct"],
            min_risk_per_trade_pct=d["min_risk_per_trade_pct"],
            position_ranking_enabled=d["position_ranking_enabled"],
            max_positions_per_cluster=d.get("max_positions_per_cluster", 3),
        )

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
