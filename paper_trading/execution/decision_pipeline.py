"""Decision pipeline — decomposes AssetEngine._apply_decision into composable stages.

Each stage is a standalone function operating on a shared DecisionContext.
Stages are chained by `run_decision_pipeline()`.

This makes each sub-phase independently testable without instantiating
an AssetEngine.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from paper_trading.entry.decision import EntryAction, PositionSide, SignalType, TradeDecision
from quantforge.domain.entities.position import OrderType, StackCommand

logger = logging.getLogger("quantforge.decision_pipeline")


@dataclass
class DecisionContext:
    """Mutable context passed through all pipeline stages.

    Stages read from and write to this object. The pipeline
    aborts early if ``abort`` is set by any stage.
    """

    engine: Any  # AssetEngine (avoid circular import)
    decision: TradeDecision
    df: pd.DataFrame

    # Computed during pipeline execution
    new_side: PositionSide | None = None
    flip_allowed: bool = True
    abort: bool = False
    current_side: PositionSide | None = None

    # Per-stage pass/fail trace for UI display
    gates_trace: dict[str, bool] | None = None

    # Causal replay identifiers (set before pipeline runs)
    feature_hash: str = ""


# ── Stage type ──────────────────────────────────────────────────────────

StageFn = Callable[[DecisionContext], None]


# ── Individual stages ───────────────────────────────────────────────────


def store_prediction_metadata(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    engine._last_label = d.label
    engine._last_confidence = d.confidence
    engine._last_prob_long = d.prob_long
    engine._last_prob_short = d.prob_short
    engine._last_prob_neutral = d.prob_neutral
    engine._entry_archetype = d.archetype
    engine._entry_pressure = None


def update_mae_mfe(ctx: DecisionContext) -> None:
    engine = ctx.engine
    if engine.pos_mgr.has_position() and engine._current_trade_id:
        try:
            high_val = float(ctx.df["high"].iloc[-1])
            low_val = float(ctx.df["low"].iloc[-1])
            if hasattr(engine, "_bars_at_entry"):
                engine._attribution.update_trade_extremes(
                    engine._current_trade_id, high_val, low_val, engine._bars_at_entry
                )
        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.debug("MAE/MFE tracking skipped for %s: %s", engine.name, e)


def resolve_signal(ctx: DecisionContext) -> None:
    d = ctx.decision
    if d.signal == SignalType.BUY:
        ctx.new_side = PositionSide.LONG
    elif d.signal == SignalType.SELL:
        ctx.new_side = PositionSide.SHORT
    else:
        ctx.new_side = None


def apply_confidence_gate(ctx: DecisionContext) -> None:
    if ctx.new_side is None:
        return
    engine = ctx.engine
    from paper_trading.config_manager import get_config

    global_cfg = get_config()
    min_conf = engine.config.get("min_confidence", getattr(global_cfg.defaults, "min_confidence", 0.0))
    if ctx.decision.confidence < min_conf:
        logger.debug(
            "%s: skipping trade, confidence %.1f%% < min %.1f%%",
            engine.name,
            ctx.decision.confidence,
            min_conf,
        )
        ctx.new_side = None


def apply_signal_stability_filter(ctx: DecisionContext) -> None:
    if ctx.new_side is None:
        return
    engine = ctx.engine
    prob_long = ctx.decision.prob_long
    prob_short = ctx.decision.prob_short
    max_prob = max(prob_long, prob_short)
    margin = max_prob - 0.5
    if margin < 0.15:
        logger.debug(
            "%s: signal too close to boundary (margin=%.4f, max_prob=%.4f) — holding flat",
            engine.name,
            margin,
            max_prob,
        )
        ctx.new_side = None


HYSTERESIS_WINDOW = 3
HYSTERESIS_MIN_AGREE = 2


def apply_signal_hysteresis(ctx: DecisionContext) -> None:
    if ctx.new_side is None:
        return
    engine = ctx.engine
    engine._signal_chain.append(ctx.new_side)
    if len(engine._signal_chain) > HYSTERESIS_WINDOW:
        engine._signal_chain.pop(0)
    if not engine.pos_mgr.has_position() or ctx.new_side == ctx.current_side:
        return
    if len(engine._signal_chain) < HYSTERESIS_WINDOW:
        return
    agree = sum(1 for s in engine._signal_chain if s == ctx.new_side)
    if agree < HYSTERESIS_MIN_AGREE:
        logger.info(
            "%s: hysteresis blocked flip to %s (%d/%d last signals agree)",
            engine.name,
            ctx.new_side,
            agree,
            HYSTERESIS_WINDOW,
        )
        ctx.new_side = None


def apply_meta_label_advisory(ctx: DecisionContext) -> None:
    if ctx.new_side is None:
        return
    engine = ctx.engine
    if (
        engine._meta_label_model is not None
        and engine.config.get("meta_labeling", {}).get("enabled", False)
        and hasattr(engine, "_last_meta_proba")
        and engine._last_meta_proba is not None
        and engine._last_meta_proba < engine._meta_label_model.threshold
    ):
        logger.info(
            "%s: meta-label below threshold (p(TP>SL)=%.2f < %.2f) — sizing will suppress",
            engine.name,
            engine._last_meta_proba,
            engine._meta_label_model.threshold,
        )


def update_regime_bar_counter(ctx: DecisionContext) -> None:
    engine = ctx.engine
    current_regime = getattr(engine, "_current_regime", "neutral")
    if current_regime != engine._last_regime_label:
        engine._regime_bar_counter = 1
        engine._last_regime_label = current_regime
    else:
        engine._regime_bar_counter += 1


def evaluate_conviction_gate(ctx: DecisionContext) -> None:
    engine = ctx.engine
    if ctx.new_side is None or ctx.new_side == ctx.current_side or not engine.pos_mgr.has_position():
        return
    flip_allowed, flip_reason = engine._evaluate_flip_gate()
    if not flip_allowed:
        logger.info("%s: flip blocked by conviction gate — %s", engine.name, flip_reason)
    ctx.flip_allowed = flip_allowed


def manage_position(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    has_pos = engine.pos_mgr.has_position()

    # ── Position protection (every cycle, any position) ────────────
    # Breakeven SL and trailing stop — not stacking-specific.
    _update_position_protection(ctx)

    if has_pos and ctx.new_side == ctx.current_side:
        stacking_enabled = engine.config.get("stacking", {}).get("enabled", False)
        if stacking_enabled and _should_stack(ctx):
            _execute_stack(ctx)
            ctx.new_side = None
            return
        logger.info(
            "%s: already in %s position — suppressing re-entry",
            engine.name,
            ctx.new_side,
        )
        ctx.new_side = None
        return

    # Check entry gate before doing anything.
    # If cool-down or other gate blocks, don't close the existing position
    # (avoids the "close-then-wait" churn pattern).
    if ctx.new_side is not None:
        ok, reason = engine._can_enter(
            ctx.new_side,
            d.close_price,
            {"regime": getattr(engine, "_current_regime", "neutral")},
        )
        if not ok:
            logger.info(
                "%s: flip aborted — entry gate blocking %s (%s)",
                engine.name,
                ctx.new_side,
                reason,
            )
            ctx.new_side = None

    # Close existing if flip allowed AND entry gate passed
    if has_pos and ctx.flip_allowed and ctx.new_side is not None:
        profit_lock_pct = engine.config.get("profit_lock_threshold_pct", 15.0)
        current_price = getattr(engine, "current_price", None)
        if current_price is not None and current_price > 0:
            unrealized_pnl = engine.pos_mgr.position_pnl(current_price)
            if unrealized_pnl > profit_lock_pct:
                logger.info(
                    "%s: profit lock — position up %.1f%%, holding instead of flipping to %s",
                    engine.name,
                    unrealized_pnl,
                    ctx.new_side,
                )
                ctx.new_side = None
                return
        stack_layer_count = engine.pos_mgr.stack_layer_count()
        if stack_layer_count > 0:
            logger.info(
                "%s: flipping %s->%s — clearing %d stacking layer(s)",
                engine.name,
                ctx.current_side,
                ctx.new_side,
                stack_layer_count,
            )
        ok = engine._close_position(d.close_price, d.timestamp, "FLIP")
        if not ok:
            ctx.new_side = None
            return

    if ctx.new_side is None or not ctx.flip_allowed:
        return


# ── Stacking helpers ─────────────────────────────────────────────────────────


def _position_unrealized_r(ctx: DecisionContext, current_price: float) -> float:
    """Position unrealised PnL in R-units (relative to position vol estimate)."""
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


def _last_stack_entry_price(pos) -> float | None:
    """Return the entry price of the last stack layer, or None."""
    if not pos or not pos.layers:
        return None
    return pos.layers[-1].entry_price


def _stack_sl_price(pos, current_price: float, stack_sl_tighten: float) -> float:
    """Stack layer's SL price given position params and tightening factor."""
    base_sl_distance_pct = abs(pos.entry_price - pos.stop_loss) / max(pos.entry_price, 1e-9)
    stack_sl_distance_pct = base_sl_distance_pct * stack_sl_tighten
    if pos.is_long:
        return current_price * (1 - stack_sl_distance_pct)
    else:
        return current_price * (1 + stack_sl_distance_pct)


def _get_adx(ctx: DecisionContext) -> float | None:
    """Extract ADX from the features DataFrame if available."""
    try:
        val = float(ctx.df["adx"].iloc[-1])
        if not pd.isna(val):
            return val
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return None


def _is_trending(ctx: DecisionContext) -> bool:
    """IV-6: trending regime check via ADX > threshold."""
    engine = ctx.engine
    cfg = engine.config.get("stacking", {})
    threshold = cfg.get("adx_threshold", 25)
    adx = _get_adx(ctx)
    if adx is not None:
        return adx > threshold
    # Fallback: no ADX available — fail-open (allow stacking)
    return True


def _log_stack_rejection(ctx: DecisionContext, gate: str, value: float, required: float) -> None:
    """Log a structured stack rejection for dry-run validation."""
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


def _position_risk_at_sl(pos, current_price: float) -> float:
    """Current notional risk at SL (dollar equivalent)."""
    return pos.notional_risk(current_price)


def _projected_risk_for_stack(ctx: DecisionContext, stack_size: float) -> float:
    """IV-3: projected total position risk after adding the stack layer.

    Computes the notional risk of the combined position (existing + stack)
    at the new effective SL (tightest across all layers including the
    stack's tighter SL). This CAN be <= current risk if the tightened SL
    compensates for the increased size.
    """
    engine = ctx.engine
    pos = engine.pos_mgr.position
    current_price = getattr(engine, "current_price", None)
    if pos is None or current_price is None or current_price <= 0:
        return 0.0

    cfg = engine.config.get("stacking", {})
    stack_sl_tighten = cfg.get("stack_sl_tighten", 0.5)

    # Stack's tighter SL
    stack_sl = _stack_sl_price(pos, current_price, stack_sl_tighten)

    # New effective SL across ALL layers (existing risk envelope + new stack)
    existing_effective = pos.effective_sl
    if pos.is_long:
        new_effective = max(existing_effective, stack_sl) if stack_sl > 0 else existing_effective
    else:
        new_effective = (
            min(existing_effective, stack_sl)
            if existing_effective > 0 and stack_sl > 0
            else stack_sl
            if stack_sl > 0
            else existing_effective
        )

    # Total notional after stacking
    total_after = pos.total_size + stack_size

    # Projected notional risk at the new effective SL
    if pos.is_long:
        return total_after * max(current_price - new_effective, 0)
    else:
        return total_after * max(new_effective - current_price, 0)


def _should_stack(ctx: DecisionContext) -> bool:
    """8-gate stacking approval with all invariants enforced.

    Returns True only if ALL 8 invariants pass.
    Logs the first failing gate for dry-run validation.
    """
    engine = ctx.engine
    cfg = engine.config.get("stacking", {})
    pos = engine.pos_mgr.position
    current_price = getattr(engine, "current_price", None)

    if current_price is None or current_price <= 0:
        _log_stack_rejection(ctx, "NO_PRICE", 0.0, 0.0)
        return False
    if pos is None:
        return False

    # ── IV-4: Position must be sufficiently profitable ─────────────
    min_r = cfg.get("min_stack_r", 0.5)
    unrealized_r = _position_unrealized_r(ctx, current_price)
    if unrealized_r < min_r:
        _log_stack_rejection(ctx, "MIN_R", unrealized_r, min_r)
        return False

    # ── Confidence gate ────────────────────────────────────────────
    min_conf = cfg.get("min_confidence", 0.60)
    if ctx.decision.confidence < min_conf:
        _log_stack_rejection(ctx, "CONFIDENCE", ctx.decision.confidence, min_conf)
        return False

    # ── IV-1: Max layers ----------------------------
    max_layers = cfg.get("max_layers", 3)
    if engine.pos_mgr.max_layers_reached(max_layers):
        _log_stack_rejection(ctx, "MAX_LAYERS", float(engine.pos_mgr.stack_layer_count()), float(max_layers))
        return False

    # ── IV-8: One stack per bar ─────────────────────
    bar_counter = getattr(engine, "_bar_counter", 0)
    if pos.last_stack_bar_id > 0 and pos.last_stack_bar_id == bar_counter:
        _log_stack_rejection(ctx, "DUPLICATE_BAR", float(bar_counter), float(pos.last_stack_bar_id + 1))
        return False

    # ── IV-5: Stack spacing ─────────────────────────
    spacing_r = cfg.get("stack_spacing_r", 0.5)
    last_entry = _last_stack_entry_price(pos)
    if last_entry is not None:
        vol_est = pos.vol
        if vol_est > 0:
            price_gap_r = abs(current_price - last_entry) / (pos.avg_price * vol_est)
            if price_gap_r < spacing_r:
                _log_stack_rejection(ctx, "STACK_SPACING", price_gap_r, spacing_r)
                return False

    # ── IV-6: Trending regime ───────────────────────
    if not _is_trending(ctx):
        adx_val = _get_adx(ctx) or 0.0
        _log_stack_rejection(ctx, "ADX", adx_val, float(cfg.get("adx_threshold", 25)))
        return False

    # ── Compute stack size (needed for IV-2 and IV-3) ──
    stack_size = _compute_stack_size(ctx)

    # ── IV-2: Stack size <= base entry size ─────────
    base_size = pos.base_entry_size
    if base_size > 0 and stack_size > base_size:
        _log_stack_rejection(ctx, "STACK_SIZE", stack_size, base_size)
        return False

    # ── IV-3: Projected risk <= current risk ─────────
    current_risk = _position_risk_at_sl(pos, current_price)
    projected_risk = _projected_risk_for_stack(ctx, stack_size)
    if projected_risk > current_risk:
        _log_stack_rejection(ctx, "RISK_INVARIANT", projected_risk, current_risk)
        return False

    return True


def _compute_stack_size(ctx: DecisionContext) -> float:
    engine = ctx.engine
    cfg = engine.config.get("stacking", {})
    pos_mgr = engine.pos_mgr
    pos = pos_mgr.position

    # Base anchor: frozen at first entry, never drifts
    base_entry_size = pos.base_entry_size if pos else pos_mgr.position_size

    # Layer multiplier (diminishing)
    layer_mults = cfg.get("layer_multipliers", [0.8, 0.5, 0.3])
    layer_idx = pos_mgr.stack_layer_count()
    mult = layer_mults[layer_idx] if layer_idx < len(layer_mults) else layer_mults[-1]

    # Volatility normalization
    target_vol = cfg.get("stack_target_vol", 0.15)
    realized_vol = getattr(engine, "_realized_volatility", target_vol)
    vol_adj = target_vol / max(realized_vol, 1e-9)
    vol_clamp = cfg.get("stack_vol_clamp", [0.3, 1.2])
    vol_adj = max(vol_clamp[0], min(vol_adj, vol_clamp[1]))

    base = base_entry_size * mult * vol_adj

    # Size cap (IV-2): stack <= base_entry_size
    size_cap = cfg.get("size_cap", 1.0)
    base = min(base, base_entry_size * size_cap)

    # Min floor
    min_entry = cfg.get("min_viable_position_pct", 0.01) * engine.capital_base
    min_stack_factor = cfg.get("min_stack_size_factor", 0.5)
    min_stack = max(min_stack_factor * min_entry, cfg.get("stack_micro_threshold", 0.0))
    return max(base, min_stack)


def _execute_stack(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    stack_cmd = StackCommand(
        size=_compute_stack_size(ctx),
        reason="stack_signal",
        expected_layer_idx=engine.pos_mgr.stack_layer_count(),
        expected_price=d.close_price,
    )

    # Dry-run mode: log without executing
    dry_run = engine.config.get("stacking", {}).get("dry_run", True)
    logger.info(
        "%s: STACK approved dry_run=%s size=%.4f layer=%d pnl_r=%.2f reason=%s",
        engine.name,
        dry_run,
        stack_cmd.size,
        stack_cmd.expected_layer_idx,
        _position_unrealized_r(ctx, d.close_price),
        stack_cmd.reason,
    )

    # Remember bar for IV-8
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


def _update_position_protection(ctx: DecisionContext) -> None:
    """Event-driven position protection: breakeven SL and trailing stop.

    Called every cycle for any open position (not stacking-specific).
    Only modifies the risk floor when price moves meaningfully.
    """
    engine = ctx.engine
    pos = engine.pos_mgr.position
    current_price = getattr(engine, "current_price", None)
    if pos is None or current_price is None or current_price <= 0:
        return

    cfg = engine.config.get("stacking", {})

    # ── Track peak (HWM for longs, LWM for shorts) ─────────────────
    if pos.is_long:
        pos.peak_price = max(pos.peak_price, current_price)
    else:
        pos.peak_price = min(pos.peak_price, current_price) if pos.peak_price > 0 else current_price

    unrealized_r = _position_unrealized_r(ctx, current_price)

    # ── Breakeven SL ───────────────────────────────────────────────
    be_threshold = cfg.get("breakeven_threshold_r", 0.5)
    if not pos.breakeven_set and unrealized_r >= be_threshold:
        if pos.is_long:
            pos.risk_floor = max(pos.risk_floor, pos.avg_price)
        else:
            pos.risk_floor = min(pos.risk_floor, pos.avg_price)
        pos.breakeven_set = True
        logger.info(
            "%s: breakeven SL activated at %.5f (unrealized_r=%.2f >= %.2f)",
            engine.name,
            pos.risk_floor,
            unrealized_r,
            be_threshold,
        )

    # ── Event-driven trailing stop ─────────────────────────────────
    trail_activate = cfg.get("trail_activate_r", 1.0)
    trail_distance = cfg.get("trail_distance_r", 0.5)
    trail_step = cfg.get("trail_step_r", 0.25)
    vol_est = pos.vol

    if unrealized_r >= trail_activate and vol_est > 0:
        # Check if price has moved enough to warrant a trail
        distance_from_peak = (pos.peak_price - current_price) if pos.is_long else (current_price - pos.peak_price)
        peak_to_current_r = distance_from_peak / max(pos.avg_price * vol_est, 1e-9)

        if peak_to_current_r <= 0:
            # At or above peak — tighten SL
            if pos.is_long:
                new_floor = current_price * (1 - trail_distance * vol_est)
                if new_floor > pos.risk_floor:
                    pos.risk_floor = new_floor
                    logger.info(
                        "%s: trailing SL tightened to %.5f (peak_r=%.2f trail_step=%.2f)",
                        engine.name,
                        new_floor,
                        unrealized_r,
                        trail_step,
                    )
            else:
                new_floor = current_price * (1 + trail_distance * vol_est)
                if pos.risk_floor == 0 or new_floor < pos.risk_floor:
                    pos.risk_floor = new_floor
                    logger.info(
                        "%s: trailing SL tightened to %.5f (peak_r=%.2f trail_step=%.2f)",
                        engine.name,
                        new_floor,
                        unrealized_r,
                        trail_step,
                    )


def build_entry_artifacts(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    if ctx.new_side is None:
        return

    structure = engine._structure_detector.detect(ctx.df)
    entry_action = engine._entry_optimizer.evaluate(
        d.signal, d.archetype, structure, engine.config.get("entry_optimization", {})
    )

    tp_geo = None
    deferred_entry = None

    if entry_action == EntryAction.ENTER:
        dynamic_sltp_enabled = engine.config.get("dynamic_sltp", {}).get("enabled", False)
        if not dynamic_sltp_enabled:
            vol = engine._tb_vol(ctx.df["close"]) if hasattr(engine, "_tb_vol") else 0.01
            state = engine.validity_sm.current_state.value if engine.validity_sm else "YELLOW"

            from paper_trading.governance.multipliers import compute_effective_multipliers

            curr_sl_mult, curr_tp_mult, _ = compute_effective_multipliers(
                base_sl=engine.sl_mult,
                base_tp=engine.tp_mult,
                validity_state=state,
                regime_geometry=engine.regime_geometry,
                narrative_sl_mult=engine.governance._narrative_sl_mult,
                liquidity_sl_mult=engine.governance._liquidity_sl_mult,
                narrative_size_scalar=engine.governance._narrative_size_scalar,
                liquidity_size_scalar=engine.governance._liquidity_size_scalar,
            )
            sl_dist = d.close_price * vol * curr_sl_mult

            from paper_trading.entry.tp_compiler import compute_take_profit

            tp_geo = compute_take_profit(
                d.close_price,
                sl_dist,
                state,
                d.archetype,
                structure,
            )

    elif entry_action == EntryAction.DEFER:
        from paper_trading.entry.deferred_entry import DeferredEntry

        deferred_entry = DeferredEntry.from_decision(d, max_bars=engine.config.get("entry_defer_max_bars", 5))

    # Store artifacts on context for next stage
    ctx.engine._structure = structure
    ctx.engine._entry_action = entry_action
    ctx.engine._tp_geo = tp_geo
    ctx.engine._deferred_entry = deferred_entry


def route_execution_policy(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    if ctx.new_side is None:
        return

    structure = engine._structure
    entry_action = engine._entry_action
    tp_geo = engine._tp_geo
    deferred_entry = engine._deferred_entry

    policy_dec = engine._execution_policy.handle(
        entry_action, d, d.archetype, structure, tp_geo=tp_geo, deferred=deferred_entry
    )
    engine._last_policy_hash = str(
        hash(
            (
                policy_dec.action,
                policy_dec.archetype,
                policy_dec.reason,
                str(policy_dec.entry_plan),
                str(policy_dec.exit_plan),
            )
        )
    )[:12]

    if policy_dec.action == EntryAction.ENTER:
        logger.info("%s: POLICY APPROVED ENTER (%s)", engine.name, policy_dec.reason)
        engine._open_position(ctx.new_side, d.close_price, d.timestamp, ctx.df, tp_geo=policy_dec.exit_plan)
        if engine.position is not None:
            engine.position["confidence"] = d.confidence
            engine.position["policy_reason"] = policy_dec.reason

    elif policy_dec.action == EntryAction.DEFER:
        if policy_dec.entry_plan:
            engine._pending_entries[ctx.new_side.value] = policy_dec.entry_plan
            logger.info("%s: POLICY APPROVED DEFER (%s)", engine.name, policy_dec.reason)

    else:
        logger.info("%s: POLICY APPROVED SKIP (%s)", engine.name, policy_dec.reason)

    # Cleanup temporary artifacts
    for attr in ("_structure", "_entry_action", "_tp_geo", "_deferred_entry"):
        with contextlib.suppress(AttributeError):
            delattr(engine, attr)


def poll_deferred_entries(ctx: DecisionContext) -> None:
    ctx.engine._poll_pending_entries(ctx.df)


def update_prob_history(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    engine.prob_history.append(
        {
            "date": d.timestamp,
            "prob_long": round(d.prob_long * 100, 2),
            "prob_short": round(d.prob_short * 100, 2),
            "signal": d.signal,
            "confidence": d.confidence,
            "close_price": d.close_price,
        }
    )
    MAX_PROB_HISTORY = 1000  # noqa: N806
    if len(engine.prob_history) > MAX_PROB_HISTORY:
        engine.prob_history = engine.prob_history[-MAX_PROB_HISTORY:]
    engine._log_confidence_buckets()


# ── Bar-jump suppression stage ──────────────────────────────────────────

BAR_JUMP_SUPPRESS_MINUTES = 60


def apply_bar_jump_suppression(ctx: DecisionContext) -> None:
    """Suppress acting on signals within N minutes of a data-source bar jump.

    A bar jump occurs when the number of aligned business days changes
    significantly between cycles (e.g., yfinance→MT5 source switch).
    Post-jump, feature vectors are contaminated and predictions are unreliable
    (all confidence bands converge to ~47% accuracy for ~60 min).
    """
    engine = ctx.engine
    suppress_until = getattr(engine, "_suppress_until", 0.0)
    if time.time() < suppress_until:
        remaining = int(suppress_until - time.time())
        logger.info(
            "%s: bar-jump suppression active — %ds remaining, holding flat",
            engine.name,
            remaining,
        )
        ctx.new_side = None


# ── Risk-off suppression stage ──────────────────────────────────────────

RISK_OFF_ASSETS = frozenset({"AUDUSD"})


def apply_risk_off_suppression(ctx: DecisionContext) -> None:
    """Suppress signals for AUDUSD/AUDCHF when market is in risk-off mode.

    During risk-off (VIX rising, SPX falling), the base model's mean-reversion
    strategy systematically fails on these assets (100% wrong for medium-confidence
    BUY predictions).  This stage holds them flat until macro conditions normalize.
    """
    engine = ctx.engine
    if engine.name not in RISK_OFF_ASSETS:
        return
    if getattr(engine, "_risk_off", False):
        logger.info(
            "%s: risk-off regime detected — suppressing signal, holding flat",
            engine.name,
        )
        ctx.new_side = None


# ── Sell-only filter stage ────────────────────────────────────────────────

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "AUDUSD",
        "ES",
        "NQ",
        "NZDCHF",
        "EURAUD",
        "^DJI",
        "USDCHF",
        "EURCHF",
        "NZDUSD",
        "EURNZD",
    }
)


def apply_sell_only_filter(ctx: DecisionContext) -> None:
    """Force FLAT on BUY signals for assets with inverted BUY calibration.

    For these 11 assets, p_long > 0.5 corresponds to ~17% win rate (inverted
    signal), while p_long < 0.425 corresponds to ~77% win rate (well-calibrated
    SELL).  This stage lets SELL signals pass through unchanged but overrides
    BUY signals to FLAT, converting these assets to sell-only.

    See the 2026-06-20 diagnostic chain for full evidence.
    """
    if ctx.new_side is None:
        return
    engine = ctx.engine
    if engine.name not in SELL_ONLY_ASSETS:
        return
    if ctx.new_side == PositionSide.LONG:
        logger.info(
            "%s: sell-only filter — suppressing BUY signal (p_long=%.4f), holding flat",
            engine.name,
            ctx.decision.prob_long,
        )
        ctx.new_side = None


# ── Spread gate stage ────────────────────────────────────────────────────

SPREAD_GATE_STALENESS_SECS = 300  # 5 minutes — refreshed every cycle
SPREAD_GATE_MIN_OBSERVE_CYCLES = 720  # ~6h at 30s — covers opens, mid-session, closes

# Per-asset-class spread thresholds in bps.  These are starting defaults
# that should be validated via observe-mode logging before being trusted.
SPREAD_TIER_BPS: dict[str, float] = {
    "fx_major": 10.0,  # EURUSD, AUDUSD, USDCHF, USDCAD, NZDUSD
    "fx_cross": 20.0,  # all other FX pairs
    "indices": 15.0,  # ES, NQ, ^DJI
    "metals": 20.0,  # GC
}


def apply_spread_gate(ctx: DecisionContext) -> None:
    """Skip entry if spread exceeds per-asset-class threshold.

    Fail-closed: if spread data is missing or stale, the entry is blocked
    (conservative — entering blind is worse than missing a trade).

    Observe mode: for the first SPREAD_GATE_MIN_OBSERVE_CYCLES cycles (~6h
    at 30s cadence) the gate logs what it *would* do but does not block, to
    validate thresholds against real market conditions before going live.
    """
    engine = ctx.engine
    # ── Gather spread data ─────────────────────────────────────────
    spread_bps = getattr(engine, "_last_spread_bps", None)
    spread_time = getattr(engine, "_last_spread_time", 0.0)
    age = time.time() - spread_time
    tier = getattr(engine, "_spread_tier", "fx_cross")
    threshold = SPREAD_TIER_BPS.get(tier, 20.0)
    cycle = getattr(engine, "_cycle_counter", 0)

    # ── Observe mode — log without blocking ────────────────────────
    # Runs first so that missing data during warmup doesn't block entries.
    if cycle < SPREAD_GATE_MIN_OBSERVE_CYCLES:
        if spread_bps is None or age > SPREAD_GATE_STALENESS_SECS:
            reason = "no_spread_data" if spread_bps is None else f"stale_spread_{age:.0f}s"
            logger.info(
                "%s: SPREAD_GATE [OBSERVE] %s — would block in live mode (tier=%s threshold=%.1fbps)",
                engine.name,
                reason,
                tier,
                threshold,
            )
        elif spread_bps > threshold:
            logger.info(
                "%s: SPREAD_GATE [OBSERVE] would block — spread=%.1fbps tier=%s threshold=%.1fbps "
                "(gate active after %d cycles)",
                engine.name,
                spread_bps,
                tier,
                threshold,
                SPREAD_GATE_MIN_OBSERVE_CYCLES,
            )
        return

    # ── Staleness / missing-data check (fail-closed, post-observe) ─
    if spread_bps is None or age > SPREAD_GATE_STALENESS_SECS:
        reason = "no_spread_data" if spread_bps is None else f"stale_spread_{age:.0f}s"
        logger.warning(
            "%s: SPREAD_GATE blocking entry — %s (tier=%s threshold=%.1fbps)",
            engine.name,
            reason,
            tier,
            threshold,
        )
        ctx.new_side = None
        return

    # ── Live blocking ─────────────────────────────────────────────
    if spread_bps > threshold:
        logger.info(
            "%s: SPREAD_GATE blocking — spread=%.1fbps exceeds tier=%s threshold=%.1fbps",
            engine.name,
            spread_bps,
            tier,
            threshold,
        )
        ctx.new_side = None


# ── Pipeline definition ─────────────────────────────────────────────────


def apply_first_cycle_suppression(ctx: DecisionContext) -> None:
    """Suppress all trading on cycle 1 after a cold start.

    The first inference cycle post-restart uses full-row inference (truncation
    validation hasn't run yet), producing a transient prediction that differs
    from steady-state single-row inference. Skipping it prevents basing
    decisions on a known- divergent one-time value.
    """
    engine = ctx.engine
    if getattr(engine, "_cycle_counter", 0) <= 1:
        ctx.abort = True
        logger.info("%s: first-cycle suppression — skipping decision", engine.name)


DEFAULT_STAGES: list[StageFn] = [
    apply_first_cycle_suppression,
    apply_bar_jump_suppression,
    store_prediction_metadata,
    update_mae_mfe,
    resolve_signal,
    apply_risk_off_suppression,
    apply_sell_only_filter,
    apply_spread_gate,
    apply_confidence_gate,
    apply_signal_stability_filter,
    apply_signal_hysteresis,
    apply_meta_label_advisory,
    update_regime_bar_counter,
    evaluate_conviction_gate,
    manage_position,
    build_entry_artifacts,
    route_execution_policy,
    poll_deferred_entries,
    update_prob_history,
]


def run_decision_pipeline(
    engine: Any,
    decision: TradeDecision,
    df: pd.DataFrame,
    stages: list[StageFn] | None = None,
) -> str | None:
    """Execute the decision pipeline for a single asset cycle.

    Returns the final signal direction after all governance stages:
      - "BUY"  (ctx.new_side == PositionSide.LONG)
      - "SELL" (ctx.new_side == PositionSide.SHORT)
      - None   (FLAT — ctx.new_side is None or aborted)
    """
    if stages is None:
        stages = DEFAULT_STAGES

    feature_hash = getattr(decision, "feature_hash", "")
    ctx = DecisionContext(
        engine=engine,
        decision=decision,
        df=df,
        current_side=engine.pos_mgr.current_side(),
        feature_hash=feature_hash,
    )

    ctx.gates_trace = {}
    for stage in stages:
        stage_name = stage.__name__
        ctx.gates_trace[stage_name] = not ctx.abort
        stage(ctx)
        if ctx.abort:
            break

    # ── Decision output WAL event (causal boundary P0.3, post-gate) ──
    wal = getattr(engine, "_wal_writer", None)
    if wal is not None:
        final_signal = ctx.new_side.value if ctx.new_side is not None else "NONE"
        wal.write(
            "decision_output",
            {
                "asset": engine.name,
                "final_signal": final_signal,
                "gates_aborted": ctx.abort,
                "gates_trace": ctx.gates_trace,
                "feature_hash": ctx.feature_hash,
                "model_hash": getattr(engine, "_model_hash", "unknown"),
            },
        )

    engine._last_gates_trace = ctx.gates_trace

    if ctx.abort:
        return None
    if ctx.new_side == PositionSide.LONG:
        return "BUY"
    if ctx.new_side == PositionSide.SHORT:
        return "SELL"
    return None
