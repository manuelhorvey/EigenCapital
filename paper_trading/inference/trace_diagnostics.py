"""Tracing, shadow model inference, and diagnostics.

Extracted from ``AssetInferencePipeline._trace_and_diagnostics`` and
``_run_shadow_feedback`` as part of MAINT-01 (split oversized modules).

Handles:
    - WAL event emission for features_snapshot (causal boundary P0.1)
    - ``trace_decision()`` for the decision trace log
    - Shadow model comparison (signal + sizing)
    - Shadow model inference (candidate model comparison)
    - Async diagnostics snapshot enqueue
    - Legacy synchronous shadow_feedback path
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytz

from paper_trading.config_manager import get_config
from paper_trading.inference.async_diagnostics import (
    DiagnosticsSnapshot,
    get_diagnostics_queue,
)
from paper_trading.inference.shadow_registry import (
    SHADOW_CONFIGS as _SHADOW_CONFIGS,
)
from paper_trading.inference.shadow_registry import (
    get_shadow_runner as _get_shadow_runner,
)
from paper_trading.inference.shadow_registry import (
    get_shadow_storage as _get_shadow_storage,
)
from paper_trading.inference.shadow_registry import (
    load_shadow_configs as _load_shadow_configs,
)
from paper_trading.ops import wrappers as _w
from paper_trading.ops.tracer import (
    shadow_compare_signal,
    shadow_compare_sizing,
    trace_decision,
)

logger = logging.getLogger("eigencapital.trace_diagnostics")

ET = pytz.timezone("US/Eastern")

# ── Eagerly hoist shadow/diagnostics imports (issue #3 pattern) ──────
# These were previously imported inside the function body.  Hoist to module
# level so import errors surface at process start rather than mid-cycle.
try:
    from paper_trading.governance.drift import get_shadow_intelligence as _get_drift
except ImportError as _exc:
    _get_drift = None  # type: ignore[assignment]
    logger.warning("shadow_intelligence import unavailable — %s", _exc)

try:
    from paper_trading.governance.risk_registry import evaluate as _risk_evaluate
except ImportError as _exc:
    _risk_evaluate = None  # type: ignore[assignment]
    logger.warning("risk.evaluate import unavailable — %s", _exc)

try:
    from paper_trading.ops import diagnostics as _diag
except ImportError as _exc:
    _diag = None  # type: ignore[assignment]
    logger.warning("ops.diagnostics import unavailable — %s", _exc)

try:
    from paper_trading.ops.tracer import trace_diagnostic_report as _trace_diag
except ImportError as _exc:
    _trace_diag = None  # type: ignore[assignment]
    logger.warning("tracer.trace_diagnostic_report import unavailable — %s", _exc)

try:
    from paper_trading.shadow.actions import compute_shadow_actions as _compute_shadow
except ImportError as _exc:
    _compute_shadow = None  # type: ignore[assignment]
    logger.warning("shadow.actions import unavailable — %s", _exc)

try:
    from paper_trading.shadow.feedback import record_shadow_feedback as _record_feedback
except ImportError as _exc:
    _record_feedback = None  # type: ignore[assignment]
    logger.warning("shadow.feedback import unavailable — %s", _exc)

try:
    from paper_trading.shadow.learning import compile_shadow_learning as _compile_learning
except ImportError as _exc:
    _compile_learning = None  # type: ignore[assignment]
    logger.warning("shadow.learning import unavailable — %s", _exc)

try:
    from paper_trading.shadow.memory import store_event as _shadow_store
except ImportError as _exc:
    _shadow_store = None  # type: ignore[assignment]
    logger.warning("shadow.memory import unavailable — %s", _exc)


def trace_and_diagnostics(
    asset: Any,
    decision: Any,
    proba: np.ndarray,
    x: pd.DataFrame,
    df: pd.DataFrame,
    threshold: float,
    feature_vector: dict[str, float] | None = None,
    feature_hash: str = "",
) -> None:
    """Run tracing, shadow comparison, and diagnostics for one inference cycle.

    Calls:
        1. WAL ``features_snapshot`` event
        2. ``trace_decision()`` — decision trace log
        3. Shadow signal + sizing comparison
        4. Shadow model inference (candidate comparison)
        5. Async diagnostics OR sync shadow feedback

    This is extracted from ``AssetInferencePipeline._trace_and_diagnostics``.
    """
    # ── WAL: features_snapshot (causal boundary P0.1) ─────────────────
    wal = getattr(asset, "_wal_writer", None)
    if wal is not None and feature_vector is not None:
        try:
            wal.write(
                "features_snapshot",
                {
                    "asset": asset.name,
                    "features": feature_vector,
                    "feature_hash": feature_hash,
                    "feature_schema": getattr(asset, "_last_feature_schema", sorted(feature_vector.keys())),
                    "model_hash": getattr(asset, "_model_hash", "unknown"),
                },
            )
        except (OSError, RuntimeError, KeyError):
            logger.warning("WAL write failed for features_snapshot on %s", asset.name, exc_info=True)

    # ── Trace.jsonl decision entry ───────────────────────────────────
    _regime_label = (
        asset._last_regime_row.regime_label if getattr(asset, "_last_regime_row", None) is not None else None
    )
    trace_decision(
        asset=asset.name,
        features=(
            feature_vector if feature_vector is not None else {k: round(float(v), 6) for k, v in x.iloc[-1].items()}
        ),
        proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
        threshold=threshold,
        signal=decision.signal,
        confidence=decision.confidence,
        pos_size=float(decision.position_size),
        close_price=decision.close_price,
        current_side=asset.pos_mgr.current_side(),
        halt_flags=asset.check_halt_conditions(),
        current_price=asset.current_price,
        regime_long_prob=asset._last_regime_long_prob,
        regime_short_prob=(
            round(float(asset._last_regime_raw_probas[0]), 6) if asset._last_regime_raw_probas is not None else None
        ),
        regime_label=_regime_label,
        regime_features=asset._last_regime_features,
        feature_hash=feature_hash,
        model_hash=getattr(asset, "_model_hash", "unknown"),
    )

    # ── Shadow signal + sizing comparison ───────────────────────────
    _shadow_signal_df = _w.compute_signals(proba[-1:], x.index[-1:], threshold)
    _shadow_latest = _shadow_signal_df.iloc[-1]
    _shadow_stype, _shadow_conf, _shadow_conf_pct = _w.signal_type_and_confidence(
        int(_shadow_latest["signal"]),
        float(_shadow_latest["prob_long"]),
        float(_shadow_latest["prob_short"]),
    )
    shadow_compare_signal(
        asset=asset.name,
        proba_produced=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
        wrapper_signal=_shadow_stype,
        wrapper_confidence=_shadow_conf_pct,
        original_signal=decision.signal,
        original_confidence=decision.confidence,
    )

    _shadow_size = _w.compute_vol_scalar(df["close"]) if asset.config.get("vol_scalar") else 1.0
    shadow_compare_sizing(
        asset=asset.name,
        wrapper_size=_shadow_size,
        original_size=float(decision.position_size),
    )

    # ── Shadow model inference (candidate model comparison) ─────────
    try:
        if not _SHADOW_CONFIGS:
            _load_shadow_configs()  # mutates _SHADOW_CONFIGS in-place (ARCH-01)
        if _SHADOW_CONFIGS and feature_vector is not None:
            _storage = _get_shadow_storage()
            for _sid, _scfg in list(_SHADOW_CONFIGS.items()):
                _runner = _get_shadow_runner(_sid, _scfg, asset_name=asset.name)
                _shadow_res = _runner.run(feature_vector, feature_hash=feature_hash)
                if _shadow_res is not None:
                    _storage.record(
                        shadow_id=_sid,
                        asset=asset.name,
                        prod_signal=decision.signal,
                        prod_confidence=decision.confidence,
                        prod_p_long=float(proba[-1, 2]),
                        shadow_signal=_shadow_res.signal,
                        shadow_confidence=_shadow_res.confidence,
                        shadow_p_long=_shadow_res.proba_long,
                        feature_hash=feature_hash,
                        model_hash=_shadow_res.model_hash,
                        inference_time_ms=_shadow_res.inference_time_ms,
                    )
                    if _storage.should_flush(_sid):
                        _storage.flush(_sid)
    except (RuntimeError, ValueError, OSError) as _shadow_err:
        logger.debug("%s: shadow model inference skipped: %s", asset.name, _shadow_err)

    # ── Async diagnostics vs sync shadow feedback ──────────────────
    _cfg = get_config()
    if _cfg.optimizations.get("async_diagnostics", True):
        _snap = DiagnosticsSnapshot(
            asset_name=asset.name,
            proba_long=float(proba[-1, 2]),
            proba_short=float(proba[-1, 0]),
            proba_neutral=float(proba[-1, 1]),
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            shadow_stype=_shadow_stype,
            shadow_conf_pct=_shadow_conf_pct,
            feature_row={k: float(v) for k, v in x.iloc[-1].items()},
            close_prices=df["close"].ffill().iloc[-20:].tolist(),
            timestamp=str(datetime.now(tz=ET).date()),
            model=asset.model,
            features=asset.features,
        )
        get_diagnostics_queue().enqueue(_snap)
    else:
        run_shadow_feedback(
            asset,
            decision,
            proba,
            x,
            df,
            threshold,
            _shadow_stype,
            _shadow_conf_pct,
        )


def run_shadow_feedback(
    asset: Any,
    decision: Any,
    proba: np.ndarray,
    x: pd.DataFrame,
    df: pd.DataFrame,
    threshold: float,
    shadow_stype: str,
    shadow_conf_pct: float,
) -> None:
    """Legacy synchronous shadow feedback path.

    Runs signal divergence analysis, model distribution analysis,
    feature impact, regime context, and stores the shadow report.
    Called when ``async_diagnostics`` is disabled.
    """
    # Guard: all shadow imports must be available
    if any(
        dep is None
        for dep in (
            _get_drift,
            _risk_evaluate,
            _diag,
            _trace_diag,
            _compute_shadow,
            _record_feedback,
            _compile_learning,
            _shadow_store,
        )
    ):
        logger.debug(
            "%s: shadow feedback skipped — one or more modules unavailable at process start",
            asset.name,
        )
        return

    try:
        _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
        _sig_div = _diag.analyze_signal_divergence(
            _proba_list,
            threshold,
            decision.signal,
            decision.confidence,
            shadow_stype,
            shadow_conf_pct,
        )
        _mod_div = _diag.analyze_model_distribution(asset.name, _proba_list)
        _feat_drivers = _diag.analyze_feature_impact(
            asset.model,
            x.iloc[[-1]],
            asset.features,
            proba[-1:],
        )
        _regime = _diag.analyze_regime_context(df["close"])
        _report = _diag.build_shadow_report(
            asset=asset.name,
            timestamp=str(datetime.now(tz=ET).date()),
            signal_match=_sig_div["match"],
            signal_divergence=_sig_div,
            model_divergence=_mod_div,
            feature_drivers=_feat_drivers,
            regime_context=_regime,
        )
        _trace_diag(_report)
        if _shadow_store is not None:
            _shadow_store(asset.name, _report)
        asset._risk_signal = _risk_evaluate(asset.name)
        asset._shadow_drift_intel = _get_drift(asset.name)
        asset._shadow_action = _compute_shadow(
            asset=asset.name,
            state=None,
            drift_report=asset._shadow_drift_intel,
            risk_signal=asset._risk_signal,
        )
        if _record_feedback is not None:
            _record_feedback(
                asset=asset.name,
                signal_data={"signal": decision.signal, "confidence": decision.confidence},
                drift=asset._shadow_drift_intel,
                risk=asset._risk_signal,
                action=asset._shadow_action,
            )
        asset._shadow_learning = _compile_learning(
            asset=asset.name,
            feedback_logs=None,
            drift_history=asset._shadow_drift_intel,
            risk_history=asset._risk_signal,
        )
    except (ValueError, TypeError, KeyError):
        logger.debug("%s: shadow learning feedback skipped", asset.name)
