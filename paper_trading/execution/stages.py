"""Decision pipeline stage functions — extracted from decision_pipeline.py.

Each stage is a standalone function operating on a shared DecisionContext.
Stages are chained by ``run_decision_pipeline()`` in the parent module.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections import deque
from typing import Any

import pandas as pd

from eigencapital.domain.time import utc_now
from paper_trading.asset_pnl_controller import _sync_broker_sltp
from paper_trading.entry.decision import EntryAction, PositionSide, SignalType, TradeDecision
from paper_trading.execution.decision_pipeline import (
    DecisionContext,
    _get_drift_gap,
    _log_eager_import_failure,
    _record_drift_outcome,
    reset_drift_recorder,
)
from paper_trading.execution.gate_constants import SPREAD_TIER_BPS, get_sell_only_assets
from paper_trading.execution.stacking import StackingGate
from paper_trading.position.protection import PositionProtection

logger = logging.getLogger("eigencapital.stages")

# ── Eagerly hoist late imports (issue #3) ──────────────────────────────
# These are used inside build_entry_artifacts and manage_position.
try:
    from paper_trading.governance.multipliers import compute_effective_multipliers
except ImportError as _exc:
    compute_effective_multipliers = None  # type: ignore[assignment]
    _log_eager_import_failure("compute_effective_multipliers", _exc)

try:
    from paper_trading.entry.tp_compiler import compute_take_profit
except ImportError as _exc:
    compute_take_profit = None  # type: ignore[assignment]
    _log_eager_import_failure("compute_take_profit", _exc)

try:
    from paper_trading.entry.deferred_entry import DeferredEntry
except ImportError as _exc:
    DeferredEntry = None  # type: ignore[assignment,misc]
    _log_eager_import_failure("DeferredEntry", _exc)


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


def _first_non_none(*values: object) -> object:
    """Return the first value that is not ``None``."""
    for v in values:
        if v is not None:
            return v
    return None


def apply_confidence_gate(ctx: DecisionContext) -> None:
    """Block entry if confidence is below the direction-appropriate threshold.

    Direction-conditional thresholds address the BUY/SELL information gap:
    BUY signals have systematically lower win rates (~41%) than SELL (~72%),
    so a lower BUY threshold lets in more calibrated BUY trades without
    lowering the SELL threshold that maintains high WR.

    Fallback chain (tried in order):
      1. Per-asset direction-specific override (e.g. ``GBPJPY.min_confidence_buy``)
      2. Global direction-specific default (``defaults.min_confidence_buy``)
      3. Per-asset global threshold (``GBPJPY.min_confidence``)
      4. Global default (``defaults.min_confidence``)
      5. Hard-coded 0.55 (separation-of-concerns safety net)
    """
    if ctx.new_side is None:
        return
    engine = ctx.engine
    cfg = ctx.config or engine._engine_cfg
    cfg_defaults = getattr(cfg, "defaults", {}) or {}

    if ctx.new_side == PositionSide.LONG:
        min_conf = _first_non_none(
            engine.config.get("min_confidence_buy"),
            cfg_defaults.get("min_confidence_buy"),
            engine.config.get("min_confidence"),
            cfg_defaults.get("min_confidence"),
            0.55,
        )
    else:  # PositionSide.SHORT
        min_conf = _first_non_none(
            engine.config.get("min_confidence_sell"),
            cfg_defaults.get("min_confidence_sell"),
            engine.config.get("min_confidence"),
            cfg_defaults.get("min_confidence"),
            0.55,
        )
    if ctx.decision.confidence < min_conf:
        logger.debug(
            "%s: skipping %s, confidence %.1f%% < min_confidence_%s=%.1f%%",
            engine.name,
            "BUY" if ctx.new_side == PositionSide.LONG else "SELL",
            ctx.decision.confidence,
            "buy" if ctx.new_side == PositionSide.LONG else "sell",
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
        if action.new_sl is not None:
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
            # Sync to anchor batch stop_loss (dual-SL reconciliation)
            if engine.batches:
                anchor = next(
                    (b for b in engine.batches.values() if b.is_anchor),
                    None,
                )
                if anchor is not None:
                    anchor.update_stop_loss(float(action.new_sl))
                    logger.debug(
                        "%s: synced PositionProtection SL %.5f to anchor batch",
                        engine.name,
                        action.new_sl,
                    )
            # Push to broker (MT5)
            _sync_broker_sltp(engine)

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
                "%s: stacking rejected — holding current %s position (%s)",
                engine.name,
                ctx.current_side,
                decision.reason,
            )
        else:
            logger.info(
                "%s: stacking disabled — holding current %s position",
                engine.name,
                ctx.current_side,
            )
        # Stacking disabled or gate rejected: hold the current position.
        # Never fall through to close-reopen — that would destroy trailing
        # SL protection and generate false "FLIP" exit records.
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
        # Record flip outcome for drift tracking
        pre_close_pnl = engine.pos_mgr.position_pnl(d.close_price) if has_pos and d.close_price > 0 else 0.0
        ok = engine._close_all_positions(d.close_price, d.timestamp, "FLIP")
        if ok:
            _record_drift_outcome(engine.name, getattr(engine, "_last_confidence", 0.5), pre_close_pnl >= 0)
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
            if compute_effective_multipliers is None or compute_take_profit is None:
                logger.error(
                    "%s: build_entry_artifacts aborted — required governance/tp_compiler imports missing "
                    "at module load",
                    engine.name,
                )
                ctx.new_side = None
                return

            vol = engine._tb_vol(ctx.df["close"]) if hasattr(engine, "_tb_vol") else 0.01
            state = engine.validity_sm.current_state.value if engine.validity_sm else "YELLOW"

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

            tp_geo = compute_take_profit(
                d.close_price,
                sl_dist,
                state,
                d.archetype,
                structure,
            )

    elif entry_action == EntryAction.DEFER:
        if DeferredEntry is None:
            logger.error(
                "%s: build_entry_artifacts aborted — DeferredEntry import missing at module load",
                engine.name,
            )
            ctx.new_side = None
            return
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
    # Use live price (updated every cycle from MT5 / 5d fallback) so the
    # sparkline shows intraday price action instead of a flat daily-close line.
    live_price = getattr(engine, "current_price", None)
    engine.prob_history.append(
        {
            "date": d.timestamp,
            "prob_long": round(d.prob_long * 100, 2),
            "prob_short": round(d.prob_short * 100, 2),
            "signal": d.signal,
            "confidence": d.confidence,
            "close_price": live_price if live_price is not None else d.close_price,
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


# ── VIX suppression gate ────────────────────────────────────────────────────

VIX_GATE_THRESHOLD = 30.0
VIX_GATE_ASSETS = frozenset({"CL"})


def apply_vix_gate(ctx: DecisionContext) -> None:
    """Suppress signals for CL=F when VIX exceeds threshold.

    CL=F (crude oil) suffers catastrophic losses during tail-risk events
    (2020 COVID crash: -2.72R) because the model's momentum/carry features
    fail under extreme volatility.  VIX > 30 is a reliable proxy for
    tail-risk regimes across multiple historical episodes (2008, 2011, 2020).

    Re-enables immediately when VIX drops back below threshold (no cooldown)
    because the CL=F model performs well in normal conditions (6/7 non-2020
    years positive).

    See the 2026-07-01 profitability diagnostic for full evidence.
    """
    engine = ctx.engine
    if engine.name not in VIX_GATE_ASSETS:
        return

    # Check VIX level via the macro data cache (shared across assets).
    # The macro cache has daily frequency; if the last value is more than
    # 5 calendar days old (long weekend gap), skip the check to avoid
    # suppressing based on stale data.
    try:
        from features.data_fetch import _macro_cache

        macro = _macro_cache.get("macro_batch")
        if macro is None or "^VIX" not in macro:
            logger.debug(
                "%s: VIX gate — macro data unavailable, fail-open (allow entry)",
                engine.name,
            )
            return

        vix_series = macro["^VIX"]
        if vix_series.empty:
            return

        # Freshness check: skip if last VIX data point is >5 days old
        last_vix_date = vix_series.index[-1]
        days_ago = (utc_now().date() - last_vix_date.date()).days
        if days_ago > 5:
            logger.debug(
                "%s: VIX gate — data stale (%d days old), pass-through",
                engine.name,
                days_ago,
            )
            return

        vix_level = vix_series.iloc[-1]
        if vix_level > VIX_GATE_THRESHOLD:
            logger.info(
                "%s: VIX gate suppressing — VIX=%.1f > threshold=%.0f (data age=%dd)",
                engine.name,
                vix_level,
                VIX_GATE_THRESHOLD,
                days_ago,
            )
            ctx.new_side = None
    except Exception:
        logger.exception("%s: VIX gate error — fail-open", engine.name)


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

    ES removed 2026-07-01 — moved to full two-way trading.

    NQ removed 2026-07-01 — moved to full two-way trading.
    """
    engine = ctx.engine
    if engine.name not in get_sell_only_assets():
        return

    # Force-close any existing LONG position (stale from pre-filter era)
    if engine.pos_mgr.has_position() and engine.pos_mgr.current_side() == PositionSide.LONG:
        close_price = ctx.decision.close_price or engine.current_price
        if close_price is not None and close_price > 0:
            ok = engine._close_all_positions(close_price, ctx.decision.timestamp, "SELL_ONLY_FLATTEN")
            if ok:
                logger.info("%s: sell-only filter — force-closed LONG positions", engine.name)
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
SPREAD_GATE_MIN_OBSERVE_CYCLES = 720  # ~12h at 60s — covers opens, mid-session, closes

# SPREAD_TIER_BPS imported from paper_trading.execution.gate_constants


def apply_spread_gate(ctx: DecisionContext) -> None:
    """Skip entry if spread exceeds per-asset-class threshold.

    Fail-closed: if spread data is missing or stale, the entry is blocked
    (conservative — entering blind is worse than missing a trade).

    Observe mode: for the first SPREAD_GATE_MIN_OBSERVE_CYCLES cycles (~12h
    at 60s cadence) the gate logs what it *would* do but does not block, to
    validate thresholds against real market conditions before going live.
    """
    cfg = ctx.config or getattr(ctx.engine, "_engine_cfg", None)
    spread_gate_cfg = (cfg.defaults or {}).get("spread_gate", {}) if cfg else {}
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

SESSION_GATE_MIN_OBSERVE_CYCLES = 720  # ~12h at 60s — covers opens, mid-session, closes

SESSION_TIER_WINDOWS: dict[str, tuple[int, int]] = {
    "fx_major": (7, 17),  # London+NY overlap 07:00–17:00 UTC
    "fx_cross": (7, 17),  # London+NY overlap 07:00–17:00 UTC
    "indices": (13, 20),  # US cash session 13:30–20:00 UTC
    "metals": (8, 18),  # London fix + NY 08:00–18:00 UTC
    "crypto": (0, 24),  # 24/7 — BTCUSD, other always-on assets
}


def apply_session_gate(ctx: DecisionContext) -> None:
    """Block new entries outside configurable UTC session windows.

    The model produces daily-bar signals but the engine runs every ~60s.
    Entering at 02:00 UTC or Sunday open exposes positions to wide spreads
    and low-liquidity conditions absent in training data.

    Observe mode: for the first ``SESSION_GATE_MIN_OBSERVE_CYCLES`` cycles
    (~12h) the gate logs what it would do but does not block, to validate
    windows against real market conditions before going live.
    """
    # Only applies to new entries (existing positions unaffected)
    if ctx.new_side is None:
        return

    engine = ctx.engine
    current_hour = utc_now().hour
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


# ── Regime transition gate ────────────────────────────────────────────────

REGIME_TRANSITION_SUPPRESS_DAYS = 30


def apply_regime_transition_gate(ctx: DecisionContext) -> None:
    """Suppress entries for 30 days after a bull↔bear regime transition.

    Detects when close crosses the 50-period MA. During regime transitions,
    the model's learned directional bias is unreliable — the Jan-Feb 2026
    drawdown was caused by the model betting confidently in the pre-transition
    direction for 2 months after the transition had already occurred.
    """
    if ctx.new_side is None:
        return
    engine = ctx.engine
    try:
        close = ctx.df["close"].dropna()
        if len(close) < 60:
            return
        ma50 = close.rolling(50).mean()
        current_close = close.iloc[-1]
        current_ma = ma50.iloc[-1]
        if pd.isna(current_ma):
            return
        new_trend = "bull" if current_close > current_ma else "bear"
        last_trend = getattr(engine, "_regime_last_trend", None)
        transition_date = getattr(engine, "_regime_transition_date", None)
        if last_trend is not None and new_trend != last_trend:
            now = utc_now()
            engine._regime_transition_date = now
            engine._regime_last_trend = new_trend
            logger.info(
                "%s: regime transition %s→%s — suppressing entries for %d days",
                engine.name,
                last_trend,
                new_trend,
                REGIME_TRANSITION_SUPPRESS_DAYS,
            )
        else:
            engine._regime_last_trend = new_trend
        if transition_date is not None:
            days_since = (utc_now() - transition_date).total_seconds() / 86400
            if days_since < REGIME_TRANSITION_SUPPRESS_DAYS:
                logger.info(
                    "%s: regime transition gate — blocking entry (%.0f/%.0f days since transition)",
                    engine.name,
                    days_since,
                    float(REGIME_TRANSITION_SUPPRESS_DAYS),
                )
                ctx.new_side = None
    except Exception:  # noqa: BLE001
        logger.debug("%s: regime transition check failed", engine.name, exc_info=True)


# ── Calibration drift gate ────────────────────────────────────────────────


def apply_calibration_drift_gate(ctx: DecisionContext) -> None:
    """Suppress entries when the model is overconfident.

    Compares the rolling mean confidence to the rolling win rate over the
    last 30 trades. A gap >20pp (e.g., 92% confidence with 60% actual WR)
    indicates the model has decayed — it's confidently wrong, the same
    pattern that caused the Jan-Feb 2026 drawdown.
    """
    if ctx.new_side is None:
        return
    engine = ctx.engine
    gap = _get_drift_gap(engine.name)
    if gap is not None and gap > DRIFT_GAP_THRESHOLD:
        logger.info(
            "%s: calibration drift gate — blocking entry (gap=%.0fpp, threshold=%.0fpp, n=%d)",
            engine.name,
            gap * 100,
            DRIFT_GAP_THRESHOLD * 100,
            _drift_recorder.record_count(engine.name),
        )
        ctx.new_side = None


# ── ADX entry gate stage ─────────────────────────────────────────────────

ADX_ENTRY_GATE_DEFAULT_THRESHOLD = 18


def _compute_adx_from_ohlcv(df: pd.DataFrame) -> float | None:
    """Compute ADX from OHLCV columns in a DataFrame.

    Falls back gracefully if required columns are missing or the
    computation fails (e.g., insufficient data).
    """
    import ta

    try:
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        series = ta.trend.adx(pd.Series(high), pd.Series(low), pd.Series(close), window=14)
        val = float(series.iloc[-1])
        if not pd.isna(val):
            return val
    except (KeyError, IndexError, TypeError, ValueError, ImportError):
        pass
    return None


def apply_adx_entry_gate(ctx: DecisionContext) -> None:
    """Block new entries when ADX is below threshold (choppy market).

    The model's momentum/carry features work best in trending markets.
    Entering when ADX < 20 (confirmed chop) amplifies false positives,
    particularly for SELL-only assets that can only express one direction.

    Disabled by default (``enabled: false``). When enabled and
    ``observe_only: true`` the gate logs but does not block, to validate
    thresholds before enforcement.

    ADX is computed from the raw OHLCV DataFrame (``ctx.df``) rather than
    from ``_get_adx`` which depends on a pre-computed column that is not
    present in the OHLCV-only DataFrame passed to the decision pipeline.
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

    # Compute ADX from raw OHLCV data (ctx.df has high/low/close columns)
    adx_val = _compute_adx_from_ohlcv(ctx.df)
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


def apply_weekend_gate(ctx: DecisionContext) -> None:
    """Block new entries during weekends (Sat/Sun) for non-BTCUSD assets.

    Weekend Sharpe = 0.08 (essentially noise) across all assets except BTCUSD
    which trades 24/7. Blocking weekend entries eliminates this noise without
    affecting crypto positions.
    """
    if ctx.new_side is None:
        return

    engine = ctx.engine
    now = utc_now()
    if now.weekday() < 5:
        return

    asset_name = getattr(engine, "name", "")
    if "BTC" in asset_name.upper():
        return

    logger.info(
        "%s: WEEKEND GATE — blocking %s entry on %s (weekend Sharpe=0.08)",
        asset_name,
        ctx.new_side,
        now.strftime("%a %Y-%m-%d %H:%M UTC"),
    )
    ctx.new_side = None
    ctx.reason = "weekend_gate"
    ctx.abort = True


DEFAULT_STAGES: list[StageFn] = [
    apply_first_cycle_suppression,
    apply_weekend_gate,
    apply_bar_jump_suppression,
    store_prediction_metadata,
    update_mae_mfe,
    resolve_signal,
    apply_risk_off_suppression,
    apply_vix_gate,
    apply_sell_only_filter,
    apply_confidence_gate,
    apply_spread_gate,
    apply_session_gate,
    apply_regime_transition_gate,
    apply_adx_entry_gate,
    apply_calibration_drift_gate,
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


