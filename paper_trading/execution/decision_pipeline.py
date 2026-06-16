"""Decision pipeline — decomposes AssetEngine._apply_decision into composable stages.

Each stage is a standalone function operating on a shared DecisionContext.
Stages are chained by `run_decision_pipeline()`.

This makes each sub-phase independently testable without instantiating
an AssetEngine.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from paper_trading.entry.decision import EntryAction, PositionSide, SignalType, TradeDecision

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
    min_conf = engine.config.get("min_confidence", 0.0)
    if ctx.decision.confidence < min_conf:
        logger.debug(
            "%s: skipping trade, confidence %.1f%% < min %.1f%%",
            engine.name,
            ctx.decision.confidence,
            min_conf,
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
    if ctx.new_side == ctx.current_side:
        return

    # Close existing if flip allowed
    if engine.pos_mgr.has_position() and ctx.flip_allowed:
        engine._close_position(d.close_price, d.timestamp, "signal_flip")

    if ctx.new_side is None or not ctx.flip_allowed:
        return

    ok, reason = engine._can_enter(
        ctx.new_side,
        d.close_price,
        {"regime": getattr(engine, "_current_regime", "neutral")},
    )
    if not ok:
        logger.info(
            "%s: entry gate blocking %s entry — %s",
            engine.name,
            ctx.new_side,
            reason,
        )
        ctx.new_side = None


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


# ── Pipeline definition ─────────────────────────────────────────────────

DEFAULT_STAGES: list[StageFn] = [
    store_prediction_metadata,
    update_mae_mfe,
    resolve_signal,
    apply_confidence_gate,
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
) -> None:
    """Execute the decision pipeline for a single asset cycle."""
    if stages is None:
        stages = DEFAULT_STAGES

    ctx = DecisionContext(
        engine=engine,
        decision=decision,
        df=df,
        current_side=engine.pos_mgr.current_side(),
    )

    for stage in stages:
        stage(ctx)
        if ctx.abort:
            break
