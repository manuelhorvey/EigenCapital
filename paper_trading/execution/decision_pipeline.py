"""Decision pipeline — decomposes AssetEngine._apply_decision into composable stages.

Each stage is a standalone function operating on a shared DecisionContext.
Stages are chained by `run_decision_pipeline()`.

This makes each sub-phase independently testable without instantiating
an AssetEngine.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from paper_trading.entry.decision import PositionSide, TradeDecision

logger = logging.getLogger("eigencapital.decision_pipeline")


# ── Thread-safe outcome tracking ───────────────────────────────────────────
# _outcome_records is mutated from ThreadPoolExecutor workers via
# _record_drift_outcome().  A per-key lock prevents concurrent writes
# from different actors racing on the same deque.
#
# Encapsulated in DriftOutcomeRecorder for explicit lifecycle management
# (ARCH-01).  Module-level convenience references are kept for backward
# compatibility; new code should prefer the class-based API.


class DriftOutcomeRecorder:
    """Thread-safe tracker of confidence vs outcome per asset.

    Maintains a rolling window of (confidence, was_win) pairs per asset,
    used by the calibration drift gate to detect overconfidence patterns.

    Lifecycle:
        Instances are module-level singletons.  Call ``reset()`` in test
        fixtures to clear state between test cases.
    """

    def __init__(self, window: int = 30, gap_threshold: float = 0.20):
        self._window = window
        self._gap_threshold = gap_threshold
        self._records: dict[str, deque] = {}
        self._lock = threading.Lock()

    def record(self, asset: str, confidence: float, was_win: bool) -> None:
        """Record one trade outcome for an asset."""
        with self._lock:
            if asset not in self._records:
                self._records[asset] = deque(maxlen=self._window)
            self._records[asset].append((confidence, was_win))

    def get_gap(self, asset: str) -> float | None:
        """Return confidence - win_rate gap for an asset, or None if insufficient data."""
        with self._lock:
            records = self._records.get(asset)
            if records is None or len(records) < 10:
                return None
            mean_conf = sum(r[0] for r in records) / len(records)
            mean_wr = sum(1 for r in records if r[1]) / len(records)
            return mean_conf - mean_wr

    @property
    def gap_threshold(self) -> float:
        return self._gap_threshold

    def record_count(self, asset: str) -> int:
        """Return number of records for an asset (for diagnostics)."""
        with self._lock:
            return len(self._records.get(asset, []))

    def reset(self) -> None:
        """Clear all records.  Call in test fixtures to prevent state bleeding."""
        with self._lock:
            self._records.clear()


# Module-level singleton for backward compatibility.
# Production code uses this instance; tests can call ``_drift_recorder.reset()``
# between test cases to prevent state bleeding across fixtures.
_drift_recorder = DriftOutcomeRecorder()


DRIFT_WINDOW = 30
DRIFT_GAP_THRESHOLD = 0.20


def _record_drift_outcome(asset: str, confidence: float, was_win: bool) -> None:
    _drift_recorder.record(asset, confidence, was_win)


def _get_drift_gap(asset: str) -> float | None:
    return _drift_recorder.get_gap(asset)


def reset_drift_recorder() -> None:
    """Test hook: clear all drift records."""
    _drift_recorder.reset()


def _log_eager_import_failure(name: str, exc: BaseException) -> None:
    """Module-level helpers imported lazily inside the pipeline.

    ``build_entry_artifacts`` previously imported these inside the stage body.
    If the import failed AFTER ``structure`` detection or after ``ctx.engine._structure``
    had been written but BEFORE the function returned, the engine would be left
    in a half-configured state for the next cycle. Hoisting them to module
    scope turns import errors into hard ImportErrors at process start (or
    captured import-time warnings if the symbols are not yet available).
    """
    logger.warning(
        "decision_pipeline: eager import %s unavailable — %s",
        name,
        exc,
    )


# ── Eagerly hoist late imports (issue #3) ──────────────────────────────
# ``build_entry_artifacts`` previously performed these imports after state
# mutations. Hoist to module level so that import errors surface at process
# start (or a logged warning + sentinel fallback) rather than mid-pipeline.
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


@dataclass
class DecisionContext:
    """Mutable context passed through all pipeline stages.

    Stages read from and write to this object. The pipeline
    aborts early if ``abort`` is set by any stage.

    ``config`` carries the engine configuration (``EngineConfig`` instance)
    so pipeline stages can read sizing/behaviour parameters without
    reaching for the ``get_config()`` global singleton.
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

    # Injected config (avoids global get_config() call in pipeline stages)
    config: Any = None  # EngineConfig instance


# ── Stage type ──────────────────────────────────────────────────────────

StageFn = Callable[[DecisionContext], None]


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
    from paper_trading.config_manager import get_config as _fallback_get_config

    ctx = DecisionContext(
        engine=engine,
        decision=decision,
        df=df,
        current_side=engine.pos_mgr.current_side(),
        feature_hash=feature_hash,
        config=getattr(engine, "_engine_cfg", None) or _fallback_get_config(),
    )

    ctx.gates_trace = {}
    for stage in stages:
        stage_name = stage.__name__
        prev_new_side = ctx.new_side
        prev_abort = ctx.abort
        ctx.gates_trace[stage_name] = not ctx.abort
        stage(ctx)
        if ctx.abort and not prev_abort:
            ctx.engine._gate_blocked_counts[stage_name] = ctx.engine._gate_blocked_counts.get(stage_name, 0) + 1
            break
        if not prev_abort and prev_new_side is not None and ctx.new_side is None and not ctx.abort:
            ctx.engine._gate_blocked_counts[stage_name] = ctx.engine._gate_blocked_counts.get(stage_name, 0) + 1

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

# ── Backward-compatible re-exports for moved stage functions ────────────────
from paper_trading.execution.stages import (  # noqa: E402, F401
    ADX_ENTRY_GATE_DEFAULT_THRESHOLD,
    DEFAULT_STAGES,
    SESSION_TIER_WINDOWS,
    _compute_adx_from_ohlcv,
    _first_non_none,
    apply_adx_entry_gate,
    apply_bar_jump_suppression,
    apply_calibration_drift_gate,
    apply_confidence_gate,
    apply_first_cycle_suppression,
    apply_kelly_sizing,
    apply_meta_label_advisory,
    apply_regime_transition_gate,
    apply_risk_off_suppression,
    apply_sell_only_filter,
    apply_session_gate,
    apply_signal_hysteresis,
    apply_spread_gate,
    apply_vix_gate,
    apply_weekend_gate,
    build_entry_artifacts,
    evaluate_conviction_gate,
    manage_position,
    poll_deferred_entries,
    resolve_signal,
    route_execution_policy,
    store_prediction_metadata,
    update_mae_mfe,
    update_prob_history,
    update_regime_bar_counter,
)
from paper_trading.position.protection import _update_position_protection  # noqa: E402, F401
