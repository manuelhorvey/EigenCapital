from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from eigencapital.domain.entities.position import OrderType, StackCommand

logger = logging.getLogger("eigencapital.stacking")


@dataclass
class StackDecision:
    should_stack: bool = False
    reason: str = ""


# ── Pure helper functions (no config dependency) ───────────────────────


def _last_stack_entry_price(pos) -> float | None:
    if not pos or not pos.layers:
        return None
    return pos.layers[-1].entry_price


def _stack_sl_price(pos, current_price: float, stack_sl_tighten: float) -> float:
    base_sl_distance_pct = abs(pos.entry_price - pos.stop_loss) / max(pos.entry_price, 1e-9)
    stack_sl_distance_pct = base_sl_distance_pct * stack_sl_tighten
    if pos.is_long:
        return current_price * (1 - stack_sl_distance_pct)
    else:
        return current_price * (1 + stack_sl_distance_pct)


def _position_risk_at_sl(pos, current_price: float) -> float:
    return pos.notional_risk(current_price)


def _get_adx_from_df(df: pd.DataFrame) -> float | None:
    try:
        val = float(df["adx"].iloc[-1])
        if not pd.isna(val):
            return val
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return None


def _get_adx(df_or_ctx) -> float | None:
    """Accept DecisionContext (old API) or raw DataFrame (new API)."""
    df = df_or_ctx.df if hasattr(df_or_ctx, "df") else df_or_ctx
    return _get_adx_from_df(df)


def _position_unrealized_r(ctx, current_price: float) -> float:
    pos = ctx.engine.pos_mgr.position
    if pos is None:
        return 0.0
    entry = pos.avg_price
    vol_est = pos.vol
    if vol_est <= 0 or entry <= 0:
        return 0.0
    if pos.is_long:
        return (current_price - entry) / (entry * vol_est)
    else:
        return (entry - current_price) / (entry * vol_est)


def _contract_size_from_ticker(ticker: str) -> float:
    """Derive the contract size (base units per lot) from a ticker string.

    Used to convert USD notional → lots/contracts so that the stacking
    size floor is in the same unit as base_entry_size.  Matches broker
    conventions in mt5_broker.py.

    Ticker patterns:
      - ``xxx=X`` (forex):            100,000  (standard lot)
      - ``GC=F``  (gold futures):     100      (troy oz per contract)
      - ``NQ=F``  (Nasdaq futures):   20       ($20 × index)
      - ``ES=F``  (S&P 500 futures):  50       ($50 × index)
      - ``^DJI``  (Dow Jones index):   1       (no multiplier)
      - ``BTC-USD`` (crypto):          1       (1 unit = 1 BTC)
      - anything else:                 1
    """
    if ticker == "BTC-USD":
        return 1.0
    if ticker.startswith("^"):
        return 1.0
    if ticker.endswith("=F"):
        name: str = ticker.split("=")[0]
        futures_sizes = {"GC": 100.0, "NQ": 20.0, "ES": 50.0, "CL": 1000.0, "YM": 5.0}
        return futures_sizes.get(name, 1.0)
    if "=X" in ticker:
        return 100_000.0
    return 1.0


# ── StackingGate ───────────────────────────────────────────────────────


class StackingGate:
    def __init__(self, config: dict[str, Any]):
        self._cfg = config

    def should_stack(self, ctx) -> StackDecision:
        engine = ctx.engine
        cfg = self._cfg
        pos = engine.pos_mgr.position
        current_price = getattr(engine, "current_price", None)

        if current_price is None or current_price <= 0:
            self._log_rejection(ctx, "NO_PRICE", 0.0, 0.0)
            return StackDecision(False, "no_price")
        if pos is None:
            return StackDecision(False, "no_position")

        # IV-4: Position must be sufficiently profitable
        min_r = cfg.get("min_stack_r", 0.5)
        unrealized_r = _position_unrealized_r(ctx, current_price)
        if unrealized_r < min_r:
            self._log_rejection(ctx, "MIN_R", unrealized_r, min_r)
            return StackDecision(False, f"unrealized_r={unrealized_r:.2f} < min_r={min_r}")

        # Confidence gate
        min_conf = cfg.get("min_confidence", 0.60)
        if ctx.decision.confidence < min_conf:
            self._log_rejection(ctx, "CONFIDENCE", ctx.decision.confidence, min_conf)
            return StackDecision(False, f"confidence={ctx.decision.confidence:.2f} < {min_conf}")

        # IV-1: Max layers
        max_layers = cfg.get("max_layers", 3)
        if engine.pos_mgr.max_layers_reached(max_layers):
            self._log_rejection(ctx, "MAX_LAYERS", float(engine.pos_mgr.stack_layer_count()), float(max_layers))
            return StackDecision(False, f"max_layers={engine.pos_mgr.stack_layer_count()} >= {max_layers}")

        # IV-8: One stack per bar
        bar_counter = getattr(engine, "_bar_counter", 0)
        if pos.last_stack_bar_id > 0 and pos.last_stack_bar_id == bar_counter:
            self._log_rejection(ctx, "DUPLICATE_BAR", float(bar_counter), float(pos.last_stack_bar_id + 1))
            return StackDecision(False, "duplicate_bar")

        # IV-5: Stack spacing
        spacing_r = cfg.get("stack_spacing_r", 0.5)
        last_entry = _last_stack_entry_price(pos)
        if last_entry is not None:
            vol_est = pos.vol
            if vol_est > 0:
                price_gap_r = abs(current_price - last_entry) / (pos.avg_price * vol_est)
                if price_gap_r < spacing_r:
                    self._log_rejection(ctx, "STACK_SPACING", price_gap_r, spacing_r)
                    return StackDecision(False, f"stack_spacing={price_gap_r:.2f} < {spacing_r}")

        # IV-6: Trending regime
        if not self._is_trending(ctx.df):
            adx_val = _get_adx(ctx.df) or 0.0
            self._log_rejection(ctx, "ADX", adx_val, float(cfg.get("adx_threshold", 25)))
            return StackDecision(False, f"adx={adx_val:.1f} < threshold")

        # Compute stack size (needed for IV-2 and IV-3)
        stack_size = self._compute_stack_size(ctx)

        # IV-2: Stack size <= base entry size
        base_size = pos.base_entry_size
        if base_size > 0 and stack_size > base_size:
            self._log_rejection(ctx, "STACK_SIZE", stack_size, base_size)
            return StackDecision(False, f"stack_size={stack_size:.4f} > base={base_size:.4f}")

        # IV-3: Projected risk <= current risk
        # Use the original stop_loss (not effective_sl) for current risk so that
        # PositionProtection tightening (which runs before this check in
        # manage_position) doesn't artificially reduce current_risk and
        # prevent valid stacks. The stack layer gets its own tighter SL via
        # _projected_risk_for_stack.
        if pos.is_long:
            current_risk = pos.total_size * max(current_price - pos.stop_loss, 0)
        else:
            current_risk = pos.total_size * max(pos.stop_loss - current_price, 0)
        projected_risk = self._projected_risk_for_stack(ctx, stack_size)
        if projected_risk > current_risk:
            self._log_rejection(ctx, "RISK_INVARIANT", projected_risk, current_risk)
            return StackDecision(False, f"projected_risk={projected_risk:.4f} > current_risk={current_risk:.4f}")

        # Gate 9: Pending entry conflict
        side = ctx.new_side.value if hasattr(ctx.new_side, "value") else ctx.new_side
        pending = getattr(engine, "_pending_entries", {})
        if side in pending:
            self._log_rejection(ctx, "PENDING_ENTRY", float(len(pending)), 0.0)
            return StackDecision(False, "pending_entry_conflict")

        # Gate 10: Stopout cooldown
        last_stop_out_cycle = getattr(engine, "_last_stop_out_cycle", None)
        if last_stop_out_cycle is not None:
            cross_cooldown = engine.config.get("stopout_cross_side_cooldown_cycles", 1)
            elapsed = engine._cycle_counter - last_stop_out_cycle
            if elapsed < cross_cooldown:
                self._log_rejection(ctx, "STOPOUT_COOLDOWN", float(elapsed), float(cross_cooldown))
                return StackDecision(False, f"stopout_cooldown={elapsed} < {cross_cooldown}")

        return StackDecision(True, "all_gates_passed")

    def execute_stack(self, ctx) -> None:
        engine = ctx.engine
        d = ctx.decision
        stack_cmd = StackCommand(
            size=self._compute_stack_size(ctx),
            reason="stack_signal",
            expected_layer_idx=engine.pos_mgr.stack_layer_count(),
            expected_price=d.close_price,
        )
        dry_run = self._cfg.get("dry_run", True)
        logger.info(
            "%s: STACK approved dry_run=%s size=%.4f layer=%d pnl_r=%.2f reason=%s",
            engine.name,
            dry_run,
            stack_cmd.size,
            stack_cmd.expected_layer_idx,
            _position_unrealized_r(ctx, d.close_price),
            stack_cmd.reason,
        )
        pos = engine.pos_mgr.position
        if pos is not None:
            bar_counter = getattr(engine, "_bar_counter", 0)
            pos.last_stack_bar_id = bar_counter
        if not dry_run:
            engine._open_position(
                ctx.new_side,
                d.close_price,
                d.timestamp,
                ctx.df,
                order_type=OrderType.STACK,
                stack_cmd=stack_cmd,
            )

    # ── Private helpers ─────────────────────────────────────────────

    def _log_rejection(self, ctx, gate: str, value: float, required: float) -> None:
        engine = ctx.engine
        current_price = getattr(engine, "current_price", None)
        logger.info(
            "%s: STACK REJECTED gate=%s value=%.4f required=%.4f price=%s pnl_r=%.2f layers=%d",
            engine.name,
            gate,
            value,
            required,
            f"{current_price:.5f}" if current_price else "None",
            _position_unrealized_r(ctx, current_price) if current_price else 0.0,
            len(engine.pos_mgr.position.layers) if engine.pos_mgr.position else 0,
        )

    def _is_trending(self, df: pd.DataFrame) -> bool:
        threshold = self._cfg.get("adx_threshold", 25)
        adx = _get_adx(df)
        if adx is not None:
            return adx > threshold
        return True

    def _projected_risk_for_stack(self, ctx, stack_size: float) -> float:
        engine = ctx.engine
        pos = engine.pos_mgr.position
        current_price = getattr(engine, "current_price", None)
        if pos is None or current_price is None or current_price <= 0:
            return 0.0

        stack_sl_tighten = self._cfg.get("stack_sl_tighten", 0.5)
        stack_sl = _stack_sl_price(pos, current_price, stack_sl_tighten)

        existing_effective = pos.effective_sl
        if pos.is_long:
            new_effective = max(existing_effective, stack_sl) if stack_sl > 0 else existing_effective
        else:
            if existing_effective > 0 and stack_sl > 0:
                new_effective = min(existing_effective, stack_sl)
            elif stack_sl > 0:
                new_effective = stack_sl
            else:
                new_effective = existing_effective

        total_after = pos.total_size + stack_size
        if pos.is_long:
            return total_after * max(current_price - new_effective, 0)
        else:
            return total_after * max(new_effective - current_price, 0)

    def _compute_stack_size(self, ctx) -> float:
        engine = ctx.engine
        cfg = self._cfg
        pos_mgr = engine.pos_mgr
        pos = pos_mgr.position

        base_entry_size = pos.base_entry_size if pos else pos_mgr.position_size
        layer_mults = cfg.get("layer_multipliers", [0.8, 0.5, 0.3])
        layer_idx = pos_mgr.stack_layer_count()
        mult = layer_mults[layer_idx] if layer_idx < len(layer_mults) else layer_mults[-1]

        target_vol = cfg.get("stack_target_vol", 0.15)
        realized_vol = getattr(engine, "_realized_volatility", target_vol)
        vol_adj = target_vol / max(realized_vol, 1e-9)
        vol_clamp = cfg.get("stack_vol_clamp", [0.3, 1.2])
        vol_adj = max(vol_clamp[0], min(vol_adj, vol_clamp[1]))

        base = base_entry_size * mult * vol_adj
        size_cap = cfg.get("size_cap", 1.0)
        base = min(base, base_entry_size * size_cap)

        # IV-min-stack floor: enforce a minimum stack size in the SAME UNITS as
        # base_entry_size (lots/contracts).  The prior implementation multiplied
        # USD notional (`min_viable_position_pct × capital_base`) directly against
        # lot-scale `base`, producing a 3500× mismatch in production.
        #
        # Correct conversion:   min_notional_USD / (price × contract_size) → lots
        # where contract_size is 100,000 for FX, 100 for GC=F, 1 for indices, etc.
        # See _contract_size_from_ticker().
        min_stack_factor = cfg.get("min_stack_size_factor", 0.5)
        if min_stack_factor > 0:
            price = getattr(engine, "current_price", None)
            ticker = getattr(engine, "ticker", "")
            if price and price > 0:
                min_notional = cfg.get("min_viable_position_pct", 0.01) * engine.capital_base
                contract_mult = cfg.get("lot_multiplier", 0.0)
                if contract_mult <= 0:
                    contract_mult = _contract_size_from_ticker(ticker)
                min_lots = min_notional / (price * contract_mult) if (price * contract_mult) > 0 else 0.0
                min_stack = max(min_stack_factor * min_lots, cfg.get("stack_micro_threshold", 0.0))
            else:
                min_stack = 0.0
        else:
            min_stack = 0.0
        return max(base, min_stack)


# ── Backward-compatible module-level function wrappers ────────────────────────
# These extract the stacking config from the engine to create a properly
# configured StackingGate instance, preserving the old standalone function API.


def _should_stack(ctx) -> StackDecision:
    engine = ctx.engine
    cfg = getattr(engine, "config", {}).get("stacking", {})
    return StackingGate(cfg).should_stack(ctx)


def _execute_stack(ctx) -> None:
    engine = ctx.engine
    cfg = getattr(engine, "config", {}).get("stacking", {})
    StackingGate(cfg).execute_stack(ctx)


def _compute_stack_size(ctx) -> float:
    engine = ctx.engine
    cfg = getattr(engine, "config", {}).get("stacking", {})
    return StackingGate(cfg)._compute_stack_size(ctx)


def _is_trending(df_or_ctx) -> bool:
    df = df_or_ctx.df if hasattr(df_or_ctx, "df") else df_or_ctx
    return StackingGate({})._is_trending(df)


def _projected_risk_for_stack(ctx, stack_size: float) -> float:
    engine = ctx.engine
    cfg = getattr(engine, "config", {}).get("stacking", {})
    return StackingGate(cfg)._projected_risk_for_stack(ctx, stack_size)


def _log_stack_rejection(ctx, gate: str, value: float, required: float) -> None:
    engine = ctx.engine
    cfg = getattr(engine, "config", {}).get("stacking", {})
    StackingGate(cfg)._log_rejection(ctx, gate, value, required)
