"""PortfolioStateBuilder — single source of truth for portfolio exposure.

Built once per cycle in the pre-phase, before any signal generation.
Computes all fields of PortfolioStateSnapshot from live engine state.
Replaces the distributed budget_ref + per-cycle leverage budget pattern."""

from __future__ import annotations

import logging
from typing import Any

from eigencapital.domain.time import utc_now
from paper_trading.config_manager import get_config
from paper_trading.pek.contracts.portfolio_state import (
    AssetGateState,
    ClusterInfo,
    PortfolioStateSnapshot,
    PositionInfo,
)
from shared.factor_model import FACTOR_GROUPS

logger = logging.getLogger("eigencapital.pek.state")

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
        # Read factor exposure limits from config (P3). Falls back to
        # shared/factor_model.DEFAULT_FACTOR_LIMITS if not configured.
        self._factor_limits = _resolve_factor_limits()

    def build(
        self,
        engine: Any,
        cycle_count: int,
        daily_pnl: float,
        peak_value: float,
    ) -> PortfolioStateSnapshot:
        """Build the snapshot. All data gathered, validated, then frozen."""
        now = utc_now()
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

            # Compute notional from live position size × current price,
            # NOT from _last_entry_notional which is cached at trade entry
            # and becomes stale after SL/TP hits, partial closes, or scale-outs.
            # _last_entry_notional reflects the initial trade size, not the
            # current position's market value.
            qty = getattr(pos, "quantity", 0) or 0
            live_notional = abs(qty) * current_price if qty and current_price > 0 else 0.0
            if side == "long":
                total_long_notional += live_notional
            elif side == "short":
                total_short_notional += live_notional

            sl_distance_pct = 0.0
            sl_price = getattr(pos, "stop_loss", None)
            if sl_price and entry_price > 0:
                sl_distance_pct = abs(entry_price - sl_price) / entry_price

            positions.append(
                PositionInfo(
                    asset=name,
                    side=side,
                    notional=live_notional,
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

        # ── Factor exposures from LIVE positions (signed: short = negative weight) ──
        position_weights: dict[str, float] = {}
        for p in positions:
            weight = p.notional / max(total_equity, 1.0)
            if p.side == "short":
                weight = -weight
            position_weights[p.asset] = weight

        factor_exposures_list: list[tuple[str, float]] = []
        factor_limits_list: list[tuple[str, float, float]] = []
        factor_headroom_list: list[tuple[str, float]] = []

        for factor, factor_assets in FACTOR_GROUPS.items():
            exposure = sum(position_weights.get(a, 0.0) for a in factor_assets)
            factor_exposures_list.append((factor, round(exposure, 6)))
            lo, hi = self._factor_limits.get(factor, (-1.0, 1.0))
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

        # ── Risk parameters from mode config (tiered by equity) ──
        from shared.sizing_chain import get_risk_for_equity
        max_risk_pt = get_risk_for_equity(
            total_equity,
            self._mode.get("risk_tiers"),
            self._mode.get("max_risk_per_trade_pct", 1.0),
        )
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
        the asset CAN trade (True = ok, False = blocked).

        Gate computation order (matching DEFAULT_STAGES in decision_pipeline):
          1. spread_ok     — live spread vs per-tier threshold
          2. session_ok    — current UTC hour vs per-tier session window
          3. sell_only_ok  — from SELL_ONLY_ASSETS
          4. confidence_ok — from _last_confidence
          5. risk_off_ok   — from _risk_off flag (VIX>0 & SPX<0)
          6. hysteresis_ok — from _last_gates_trace
          7. conviction_ok — from _last_gates_trace

        All exceptions are caught and logged individually so a single gate
        computation failure doesn't crash the entire snapshot.  Failed gates
        default to ``False`` (fail-closed: block entry) to be conservative.
        """
        from paper_trading.execution.decision_pipeline import SESSION_TIER_WINDOWS
        from paper_trading.execution.gate_constants import SPREAD_TIER_BPS, get_sell_only_assets

        # ── spread_ok ──
        spread_ok = False
        try:
            spread_bps = getattr(engine, "_last_spread_bps", None)
            if isinstance(spread_bps, (int, float)):
                tier = getattr(engine, "_spread_tier", "fx_cross")
                threshold = SPREAD_TIER_BPS.get(tier, 20.0)
                spread_ok = spread_bps < threshold
            else:
                logger.warning("%s: no spread data available — spread gate blocking entries", name)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.warning("%s: spread gate computation failed: %s", name, exc, exc_info=True)

        # ── session_ok ──
        session_ok = True
        try:
            tier = getattr(engine, "_spread_tier", "fx_cross")
            window = SESSION_TIER_WINDOWS.get(tier)
            if window is not None:
                start, end = window
                current_hour = utc_now().hour
                session_ok = start <= current_hour < end
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.warning("%s: session gate computation failed: %s", name, exc, exc_info=True)

        # ── sell_only_ok ──
        sell_only_ok = True
        try:
            sell_only_ok = name not in get_sell_only_assets()
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.warning("%s: sell_only gate computation failed: %s", name, exc, exc_info=True)

        # ── confidence_ok ──
        confidence_ok = True
        try:
            from paper_trading.config_manager import get_config as get_paper_config

            cfg = get_paper_config()
            asset_cfg = cfg.assets.get(name, {}) if hasattr(cfg, "assets") else {}
            min_conf = asset_cfg.get("min_confidence", 55.0)
            last_conf = getattr(engine, "_last_confidence", 100.0)
            confidence_ok = last_conf >= min_conf if isinstance(last_conf, (int, float)) else True
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.warning("%s: confidence gate computation failed: %s — defaulting to pass", name, exc, exc_info=True)

        # ── risk_off_ok ──
        risk_off_ok = True
        try:
            risk_off_ok = not getattr(engine, "_risk_off", False)
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("%s: risk_off gate computation failed: %s", name, exc, exc_info=True)

        # ── hysteresis_ok (from last gate trace) ──
        hysteresis_ok = True
        try:
            gates_trace = getattr(engine, "_last_gates_trace", None) or {}
            hysteresis_ok = gates_trace.get("apply_signal_hysteresis", True)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            logger.warning("%s: hysteresis gate computation failed: %s", name, exc, exc_info=True)

        # ── conviction_ok (from last gate trace) ──
        conviction_ok = True
        try:
            gates_trace = getattr(engine, "_last_gates_trace", None) or {}
            conviction_ok = gates_trace.get("evaluate_conviction_gate", True)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            logger.warning("%s: conviction gate computation failed: %s", name, exc, exc_info=True)

        return AssetGateState(
            asset=name,
            spread_ok=spread_ok,
            session_ok=session_ok,
            sell_only_ok=sell_only_ok,
            confidence_ok=confidence_ok,
            risk_off_ok=risk_off_ok,
            hysteresis_ok=hysteresis_ok,
            conviction_ok=conviction_ok,
        )


def _resolve_factor_limits() -> dict[str, tuple[float, float]]:
    """Resolve factor exposure limits from config, falling back to hardcoded defaults.

    Reads ``portfolio.factor_exposure_limits`` from the global config (P3 domain
    file ``configs/domains/portfolio/factor_model.yaml``). If not configured,
    returns ``DEFAULT_FACTOR_LIMITS`` from ``shared/factor_model``.

    Returns:
        {factor: (min, max)} dict with the same structure as DEFAULT_FACTOR_LIMITS.
    """
    from shared.factor_model import DEFAULT_FACTOR_LIMITS

    try:
        cfg = get_config()
        limits_raw = getattr(cfg, "portfolio", {}).get("factor_exposure_limits")
    except (ValueError, TypeError, AttributeError, RuntimeError):
        limits_raw = None

    if limits_raw is None:
        return dict(DEFAULT_FACTOR_LIMITS)

    if not isinstance(limits_raw, dict):
        logger.warning("factor_exposure_limits: expected mapping, got %s — using defaults", type(limits_raw).__name__)
        return dict(DEFAULT_FACTOR_LIMITS)

    # Validate and coerce each limit into (min, max) tuple
    validated: dict[str, tuple[float, float]] = {}
    for factor, raw_limit in limits_raw.items():
        if not isinstance(raw_limit, (list, tuple)) or len(raw_limit) != 2:
            logger.warning(
                "factor_exposure_limits.%s: expected [min, max], got %s — skipping",
                factor,
                raw_limit,
            )
            continue
        try:
            lo, hi = float(raw_limit[0]), float(raw_limit[1])
            validated[factor] = (lo, hi)
        except (ValueError, TypeError):
            logger.warning(
                "factor_exposure_limits.%s: non-numeric bounds %s — skipping",
                factor,
                raw_limit,
            )
            continue

    # Fall back to DEFAULT_FACTOR_LIMITS for factors not in config
    for factor, default_limit in DEFAULT_FACTOR_LIMITS.items():
        if factor not in validated:
            validated[factor] = default_limit

    return validated
