"""PortfolioStateBuilder — single source of truth for portfolio exposure.

Built once per cycle in the pre-phase, before any signal generation.
Computes all fields of PortfolioStateSnapshot from live engine state.
Replaces the distributed budget_ref + per-cycle leverage budget pattern."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from paper_trading.pek.contracts.portfolio_state import (
    AssetGateState,
    ClusterInfo,
    PortfolioStateSnapshot,
    PositionInfo,
)
from shared.factor_model import DEFAULT_FACTOR_LIMITS, FACTOR_GROUPS

logger = logging.getLogger("quantforge.pek.state")

# ── Correlated cluster definitions (mirrors factor groups that exhibit high intra-group correlation) ──
# These are the factor groups where members tend to move together.
# We use the factor group definitions from the factor model directly.
CLUSTER_GROUPS: dict[str, frozenset[str]] = {
    "CHF": frozenset({"EURCHF", "USDCHF", "NZDCHF", "CADCHF", "GBPCHF"}),
    "US_EQUITY": frozenset({"ES", "NQ", "^DJI"}),
    "COMMODITY": frozenset({"GC"}),
    "AUD": frozenset({"AUDUSD", "EURAUD"}),
    "NZD": frozenset({"NZDUSD", "NZDCHF", "EURNZD"}),
}


class PortfolioStateBuilder:
    """Constructs a frozen PortfolioStateSnapshot from the live engine.
    Intended to be called once per cycle in the orchestrator pre-phase."""

    def __init__(self, mode_config: dict[str, Any]):
        self._mode = mode_config

    def build(
        self,
        engine: Any,
        cycle_count: int,
        daily_pnl: float,
        peak_value: float,
    ) -> PortfolioStateSnapshot:
        """Build the snapshot. All data gathered, validated, then frozen."""
        now = datetime.now(timezone.utc)
        mode_name = self._mode.get("name", "production")

        # ── Gather positions from all actors ──
        positions: list[PositionInfo] = []
        total_equity = 0.0
        total_long_notional = 0.0
        total_short_notional = 0.0

        actors = getattr(engine, "_actors", {})
        for name, actor in actors.items():
            eng = getattr(actor, "_engine", None)
            if eng is None:
                continue

            mtm = getattr(eng, "mtm_value", 0.0) or 0.0
            total_equity += mtm

            pos_mgr = getattr(eng, "pos_mgr", None)
            if pos_mgr is None or not pos_mgr.has_position():
                continue

            pos = getattr(pos_mgr, "position", None)
            if pos is None:
                continue

            side = getattr(pos, "side", None)
            if side is None:
                continue

            entry_price = getattr(pos, "entry_price", 0.0) or 0.0
            current_price = getattr(eng, "current_price", entry_price) or entry_price
            pnl_pct = (
                getattr(pos_mgr, "position_pnl", None)(current_price)
                if entry_price > 0 and hasattr(pos_mgr, "position_pnl")
                else 0.0
            )

            notional = getattr(eng, "_last_entry_notional", 0.0) or 0.0
            if side == "long":
                total_long_notional += notional
            elif side == "short":
                total_short_notional += notional

            sl_distance_pct = 0.0
            sl_price = getattr(pos, "stop_loss", None)
            if sl_price and entry_price > 0:
                sl_distance_pct = abs(entry_price - sl_price) / entry_price

            positions.append(
                PositionInfo(
                    asset=name,
                    side=side,
                    notional=notional,
                    entry_price=entry_price,
                    current_price=current_price,
                    sl_distance_pct=sl_distance_pct,
                    current_pnl_pct=pnl_pct,
                    mtm_value=mtm,
                )
            )

        # ── Core equity numbers ──
        peak = max(peak_value, total_equity)
        dd_pct = (total_equity - peak) / max(peak, 1.0)
        gross_exposure = total_long_notional + total_short_notional
        net_exposure = total_long_notional - total_short_notional
        open_count = len(positions)

        # ── Budgets from mode config ──
        max_daily_loss_pct = self._mode.get("max_daily_loss_pct")
        max_daily_loss = total_equity * max_daily_loss_pct if max_daily_loss_pct is not None else float("inf")
        dd_limit_pct = self._mode.get("max_drawdown_pct", -0.15)
        dd_remaining = max(0.0, abs(dd_limit_pct) - abs(dd_pct)) * total_equity
        daily_loss_remaining = max(0.0, max_daily_loss - abs(min(0.0, daily_pnl)))
        max_leverage = self._mode.get("max_leverage", 2.0)
        leverage_remaining = max(0.0, max_leverage * total_equity - gross_exposure)
        max_concurrent = self._mode.get("max_concurrent_positions", 21)
        concurrent_remaining = max(0, max_concurrent - open_count)

        # ── Factor exposures from LIVE positions ──
        position_weights: dict[str, float] = {}
        for p in positions:
            position_weights[p.asset] = p.notional / max(total_equity, 1.0)

        factor_exposures_list: list[tuple[str, float]] = []
        factor_limits_list: list[tuple[str, float, float]] = []
        factor_headroom_list: list[tuple[str, float]] = []

        for factor, factor_assets in FACTOR_GROUPS.items():
            exposure = sum(position_weights.get(a, 0.0) for a in factor_assets)
            factor_exposures_list.append((factor, round(exposure, 6)))
            lo, hi = DEFAULT_FACTOR_LIMITS.get(factor, (-1.0, 1.0))
            factor_limits_list.append((factor, lo, hi))
            headroom = max(0.0, hi - exposure) if exposure >= 0 else max(0.0, exposure - lo)
            factor_headroom_list.append((factor, round(headroom, 6)))

        # ── Cluster exposures ──
        clusters_list: list[ClusterInfo] = []
        for cluster_name, cluster_assets in CLUSTER_GROUPS.items():
            cluster_positions = [p for p in positions if p.asset in cluster_assets]
            if len(cluster_positions) < 2:
                continue
            longs = sum(1 for p in cluster_positions if p.side == "long")
            shorts = sum(1 for p in cluster_positions if p.side == "short")
            dominant = "long" if longs > shorts else ("short" if shorts > longs else None)
            total_cluster_notional = sum(p.notional for p in cluster_positions)
            clusters_list.append(
                ClusterInfo(
                    factor_group=cluster_name,
                    assets=tuple(p.asset for p in cluster_positions),
                    dominant_side=dominant,
                    total_notional=total_cluster_notional,
                    position_count=len(cluster_positions),
                    average_correlation=0.0,  # computed by CorrelationMonitor; placeholder
                )
            )

        # ── Per-asset gate pre-compute ──
        gates_list: list[AssetGateState] = []
        for name, actor in actors.items():
            eng = getattr(actor, "_engine", None)
            if eng is None:
                continue
            gates_list.append(self._compute_asset_gates(name, eng))

        # ── Risk parameters from mode config ──
        max_risk_pt = self._mode.get("max_risk_per_trade_pct", 1.0)
        min_risk_pt = self._mode.get("min_risk_per_trade_pct", 0.10)
        ranking_enabled = self._mode.get("position_ranking", {}).get("enabled", False)

        return PortfolioStateSnapshot(
            version=cycle_count,
            generated_at=now,
            mode=mode_name,
            total_equity=total_equity,
            peak_value=peak,
            drawdown_pct=dd_pct,
            positions=tuple(positions),
            total_long_notional=total_long_notional,
            total_short_notional=total_short_notional,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            open_position_count=open_count,
            daily_pnl=daily_pnl,
            daily_loss_remaining=daily_loss_remaining,
            max_daily_loss=max_daily_loss,
            drawdown_remaining=dd_remaining,
            leverage_remaining=leverage_remaining,
            max_leverage=max_leverage,
            concurrent_remaining=concurrent_remaining,
            max_concurrent=max_concurrent,
            factor_exposures=tuple(factor_exposures_list),
            factor_limits=tuple(factor_limits_list),
            factor_headroom=tuple(factor_headroom_list),
            clusters=tuple(clusters_list),
            asset_gates=tuple(gates_list),
            max_risk_per_trade_pct=max_risk_pt,
            min_risk_per_trade_pct=min_risk_pt,
            position_ranking_enabled=ranking_enabled,
        )

    def _compute_asset_gates(self, name: str, engine: Any) -> AssetGateState:
        """Snapshot per-asset gate state. Each bool represents whether
        the asset CAN trade (True = ok, False = blocked)."""
        sell_only = False
        try:
            from paper_trading.execution.gate_constants import get_sell_only_assets

            sell_only = name in get_sell_only_assets()
        except ImportError:
            pass

        return AssetGateState(
            asset=name,
            spread_ok=True,  # populated by spread gate live check
            session_ok=True,  # populated by session gate
            sell_only_ok=not sell_only,
            confidence_ok=(lambda v: v >= 55.0 if isinstance(v, (int, float)) else True)(
                getattr(engine, "_last_confidence", 100.0)
            ),
            risk_off_ok=True,  # populated by risk-off detector
            hysteresis_ok=True,  # populated by signal hysteresis
            conviction_ok=True,  # populated by conviction gate
        )
