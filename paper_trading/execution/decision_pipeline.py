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
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from paper_trading.entry.decision import EntryAction, PositionSide, SignalType, TradeDecision
from paper_trading.execution.gate_constants import SPREAD_TIER_BPS, get_sell_only_assets
from paper_trading.execution.stacking import StackingGate
from paper_trading.position.protection import PositionProtection

logger = logging.getLogger("quorrin.decision_pipeline")


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


# ── Kelly sizing stage ──────────────────────────────────────────────────


def apply_kelly_sizing(ctx: DecisionContext) -> None:
    """Scale position size by Kelly criterion using calibrated probabilities.

    Reads edge from calibrated probability and TP/SL config, stores the
    Kelly multiplier on the engine for the sizing chain to consume.

    Stage position: after signal/gates decide direction, before entry sizing.

    Safety: skips Kelly if probability calibration was not applied upstream.
    Using raw XGBoost softmax in Kelly produces unreliable edge estimates
    because XGBoost probabilities are not well-calibrated (see the BUY
    inversion discovery — raw p_long=0.57 had 0% win rate).
    """
    if ctx.new_side is None:
        return

    engine = ctx.engine
    d = ctx.decision

    kelly_cfg = engine.config.get("kelly", {})
    if not kelly_cfg.get("enabled", False):
        return

    # ── Guard: calibration must have been applied ────────────────────
    # If not, Kelly would consume raw XGBoost softmax which is miscalibrated
    # (see BUY inversion discovery).  Fall through — Kelly is disabled
    # by default, so this is defence-in-depth for when it is enabled.
    if not getattr(engine, "_calibration_applied", False):
        logger.warning(
            "%s: Kelly skipped — calibration was not applied upstream, "
            "raw XGBoost softmax is unreliable for edge computation",
            engine.name,
        )
        return

    fraction = float(kelly_cfg.get("fraction", 0.25))
    max_cap = float(kelly_cfg.get("max_cap", 1.0))
    min_edge = float(kelly_cfg.get("min_edge", 0.0))

    prob_long = getattr(d, "prob_long", 0.5)
    tp_mult = float(engine.config.get("tp_mult", 2.0))
    sl_mult = float(engine.config.get("sl_mult", 2.0))

    from shared.kelly import compute_kelly_multiplier, edge_description

    multiplier = compute_kelly_multiplier(
        prob_long=prob_long,
        tp_mult=tp_mult,
        sl_mult=sl_mult,
        fraction=fraction,
        max_cap=max_cap,
        min_edge=min_edge,
    )

    engine._kelly_multiplier = multiplier

    if multiplier <= 0:
        ctx.new_side = None
        desc = edge_description(prob_long, tp_mult, sl_mult)
        logger.info("%s: Kelly blocks — %s", engine.name, desc)
        return

    desc = edge_description(prob_long, tp_mult, sl_mult)
    logger.debug("%s: Kelly multiplier=%.4f — %s", engine.name, multiplier, desc)


def manage_position(ctx: DecisionContext) -> None:
    engine = ctx.engine
    d = ctx.decision
    has_pos = engine.pos_mgr.has_position()

    # ── Position protection (every cycle, any position) ────────────
    current_price = getattr(engine, "current_price", None)
    if current_price is not None and current_price > 0 and engine.pos_mgr.position is not None:
        protection_cfg = engine.config.get("stacking", {})
        action = PositionProtection.update(engine.pos_mgr.position, current_price, protection_cfg)
        if action.action == "breakeven":
            logger.info(
                "%s: breakeven SL activated at %.5f",
                engine.name,
                action.new_sl,
            )
        elif action.action == "trail":
            logger.info(
                "%s: trailing SL tightened to %.5f",
                engine.name,
                action.new_sl,
            )

    if has_pos and ctx.new_side == ctx.current_side:
        stacking_cfg = engine.config.get("stacking", {})
        if stacking_cfg.get("enabled", False):
            gate = StackingGate(stacking_cfg)
            decision = gate.should_stack(ctx)
            if decision.should_stack:
                gate.execute_stack(ctx)
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
    """Suppress signals for AUDUSD when market is in risk-off mode.

    During risk-off (VIX rising, SPX falling), the base model's mean-reversion
    strategy systematically fails on this asset (100% wrong for medium-confidence
    BUY predictions).  This stage holds it flat until macro conditions normalize.
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

# SELL_ONLY_ASSETS resolved via get_sell_only_assets() from paper_trading.execution.gate_constants


def apply_sell_only_filter(ctx: DecisionContext) -> None:
    """Force FLAT on BUY signals for assets with inverted BUY calibration.

    For a subset of assets, p_long > 0.5 corresponds to ~17% win rate (inverted
    signal), while p_long < 0.425 corresponds to ~77% win rate (well-calibrated
    SELL).  This stage lets SELL signals pass through unchanged but overrides
    BUY signals to FLAT, converting these assets to sell-only.

    Also force-closes any existing LONG position on SELL_ONLY assets to
    prevent stale positions from a pre-filter era remaining open.

    AUDUSD, EURNZD, NZDUSD were removed from the filter 2026-06-23 after
    corrected walk-forward showed BUY WR >50%.
    See the 2026-06-20 diagnostic chain for full evidence.

    USDJPY added 2026-06-26, removed 2026-06-26 — Step3 BuyWR=39.4% vs
    BE WR=20.9% (+18.6pp). BUY now profitable. SELL_ONLY no longer needed.

    GBPJPY added 2026-06-26, removed same-day — Step 3 trend-exhaustion features
    (MACD hist, Stoch %K/%D, BB %B, ADX slope, RSI divergence) improved BuyWR to
    38.6% (+7.8pp). With tp/sl=2.22/0.50 (BE WR=18.4%), BUY signals are now
    profitable despite being below 50% WR.

    USDCHF removed 2026-06-26 — Step3 BuyWR=29.9% vs BE WR=22.1% (+7.8pp).
    BUY now profitable. SELL_ONLY no longer needed.

    EURCHF removed 2026-06-26 — Step3 BuyWR=26.2% vs BE WR=25.0% (+1.2pp).
    Marginal but above breakeven. Re-evaluate if drift degrades signal.

    ^DJI removed 2026-06-26 — Step3 BuyWR=24.3% vs BE WR=11.1% (+13.2pp).
    BUY now profitable. SELL_ONLY no longer needed.
    """
    engine = ctx.engine
    if engine.name not in get_sell_only_assets():
        return

    # Force-close any existing LONG position (stale from pre-filter era)
    if engine.pos_mgr.has_position() and engine.pos_mgr.current_side() == PositionSide.LONG:
        close_price = ctx.decision.close_price or engine.current_price
        if close_price is not None and close_price > 0:
            ok = engine._close_position(close_price, ctx.decision.timestamp, "SELL_ONLY_FLATTEN")
            if ok:
                logger.info("%s: sell-only filter — force-closed LONG position", engine.name)
            ctx.new_side = None
            return

    if ctx.new_side is None:
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

# SPREAD_TIER_BPS imported from paper_trading.execution.gate_constants


def apply_spread_gate(ctx: DecisionContext) -> None:
    """Skip entry if spread exceeds per-asset-class threshold.

    Fail-closed: if spread data is missing or stale, the entry is blocked
    (conservative — entering blind is worse than missing a trade).

    Observe mode: for the first SPREAD_GATE_MIN_OBSERVE_CYCLES cycles (~6h
    at 30s cadence) the gate logs what it *would* do but does not block, to
    validate thresholds against real market conditions before going live.
    """
    from paper_trading.config_manager import get_config

    _cfg = get_config()
    spread_gate_cfg = (_cfg.defaults or {}).get("spread_gate", {})
    if not spread_gate_cfg.get("enabled", True):
        return

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


# ── Session gate stage ───────────────────────────────────────────────────

SESSION_GATE_MIN_OBSERVE_CYCLES = 720  # ~6h at 30s — covers opens, mid-session, closes

SESSION_TIER_WINDOWS: dict[str, tuple[int, int]] = {
    "fx_major": (7, 17),  # London+NY overlap 07:00–17:00 UTC
    "fx_cross": (7, 17),  # London+NY overlap 07:00–17:00 UTC
    "indices": (13, 20),  # US cash session 13:30–20:00 UTC
    "metals": (8, 18),  # London fix + NY 08:00–18:00 UTC
}


def apply_session_gate(ctx: DecisionContext) -> None:
    """Block new entries outside configurable UTC session windows.

    The model produces daily-bar signals but the engine runs every ~30s.
    Entering at 02:00 UTC or Sunday open exposes positions to wide spreads
    and low-liquidity conditions absent in training data.

    Observe mode: for the first ``SESSION_GATE_MIN_OBSERVE_CYCLES`` cycles
    (~6h) the gate logs what it would do but does not block, to validate
    windows against real market conditions before going live.
    """
    # Only applies to new entries (existing positions unaffected)
    if ctx.new_side is None:
        return

    engine = ctx.engine
    current_hour = datetime.now(timezone.utc).hour
    tier = getattr(engine, "_spread_tier", "fx_cross")
    window = SESSION_TIER_WINDOWS.get(tier)
    cycle = getattr(engine, "_cycle_counter", 0)

    if window is None:
        # Unknown tier — fail-open (allow entry)
        return

    start, end = window
    in_session = start <= current_hour < end

    if in_session:
        return

    # ── Observe mode — log without blocking ────────────────────────
    if cycle < SESSION_GATE_MIN_OBSERVE_CYCLES:
        logger.info(
            "%s: SESSION_GATE [OBSERVE] hour=%d outside tier=%s window=%02d-%02d "
            "— would block entry in live mode (gate active after %d cycles)",
            engine.name,
            current_hour,
            tier,
            start,
            end,
            SESSION_GATE_MIN_OBSERVE_CYCLES,
        )
        return

    # ── Live blocking ─────────────────────────────────────────────
    logger.info(
        "%s: SESSION_GATE blocking entry — hour=%d outside tier=%s window=%02d-%02d",
        engine.name,
        current_hour,
        tier,
        start,
        end,
    )
    ctx.new_side = None


# ── ADX entry gate stage ─────────────────────────────────────────────────

ADX_ENTRY_GATE_DEFAULT_THRESHOLD = 18


def apply_adx_entry_gate(ctx: DecisionContext) -> None:
    """Block new entries when ADX is below threshold (choppy market).

    The model's momentum/carry features work best in trending markets.
    Entering when ADX < 20 (confirmed chop) amplifies false positives,
    particularly for SELL-only assets that can only express one direction.

    Disabled by default (``enabled: false``). When enabled and
    ``observe_only: true`` the gate logs but does not block, to validate
    thresholds before enforcement.
    """
    # Only applies to new entries
    if ctx.new_side is None:
        return

    engine = ctx.engine

    # Gate must be explicitly enabled
    adx_cfg = engine.config.get("adx_entry_gate", {})
    if not adx_cfg.get("enabled", False):
        return

    threshold = adx_cfg.get("adx_threshold", ADX_ENTRY_GATE_DEFAULT_THRESHOLD)
    observe_only = adx_cfg.get("observe_only", True)

    # Extract ADX from the features DataFrame
    adx_val = _get_adx(ctx)
    if adx_val is None:
        return

    if adx_val >= threshold:
        return

    if observe_only:
        logger.info(
            "%s: ADX_ENTRY_GATE [OBSERVE] adx=%.1f < threshold=%.1f — would block entry in enforce mode",
            engine.name,
            adx_val,
            threshold,
        )
        return

    logger.info(
        "%s: ADX_ENTRY_GATE blocking entry — adx=%.1f < threshold=%.1f",
        engine.name,
        adx_val,
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
    apply_session_gate,
    apply_adx_entry_gate,
    apply_confidence_gate,
    apply_signal_hysteresis,
    apply_meta_label_advisory,
    update_regime_bar_counter,
    evaluate_conviction_gate,
    apply_kelly_sizing,
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
        try:
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
        except Exception:
            logger.exception("WAL write failed for decision_output on %s", engine.name)

    engine._last_gates_trace = ctx.gates_trace

    if ctx.abort:
        return None
    if ctx.new_side == PositionSide.LONG:
        return "BUY"
    if ctx.new_side == PositionSide.SHORT:
        return "SELL"
    return None


# ── Backward-compatible re-exports for moved functions ────────────────────────
from paper_trading.execution.stacking import (  # noqa: E402, F401
    _compute_stack_size,
    _execute_stack,
    _get_adx,
    _is_trending,
    _last_stack_entry_price,
    _log_stack_rejection,
    _position_risk_at_sl,
    _position_unrealized_r,
    _projected_risk_for_stack,
    _should_stack,
    _stack_sl_price,
)
from paper_trading.position.protection import _update_position_protection  # noqa: E402, F401
