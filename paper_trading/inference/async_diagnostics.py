"""Async diagnostics queue — moves shadow/risk/drift off the hot inference path."""

import logging
import queue
import threading
from dataclasses import dataclass, field

logger = logging.getLogger("eigencapital.async_diagnostics")


@dataclass
class DiagnosticsSnapshot:
    asset_name: str
    proba_long: float
    proba_short: float
    proba_neutral: float
    threshold: float
    signal: str
    confidence: float
    shadow_stype: str
    shadow_conf_pct: float
    feature_row: dict[str, float]
    close_prices: list[float]
    timestamp: str
    model: object = None
    features: list = field(default_factory=list)


class DiagnosticsQueue:
    def __init__(self, maxsize: int = 100):
        self._queue: queue.Queue[DiagnosticsSnapshot] = queue.Queue(maxsize=maxsize)
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._consumer = threading.Thread(target=self._run, daemon=True)
        self._consumer.start()

    def enqueue(self, snapshot: DiagnosticsSnapshot) -> None:
        import contextlib

        if self._queue.full():
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()
        self._queue.put_nowait(snapshot)

    def _run(self) -> None:
        import numpy as np
        import pandas as pd

        from paper_trading.governance.drift import get_shadow_intelligence as _get_drift
        from paper_trading.governance.risk import evaluate as _risk_evaluate
        from paper_trading.ops import diagnostics as diag
        from paper_trading.ops.tracer import trace_diagnostic_report
        from paper_trading.shadow.actions import compute_shadow_actions as _compute_shadow
        from paper_trading.shadow.feedback import record_shadow_feedback as _record_feedback
        from paper_trading.shadow.learning import compile_shadow_learning as _compile_learning
        from paper_trading.shadow.memory import store_event as _shadow_store

        while True:
            snap = self._queue.get()
            try:
                proba_list = [snap.proba_short, snap.proba_neutral, snap.proba_long]
                sig_div = diag.analyze_signal_divergence(
                    proba_list,
                    snap.threshold,
                    snap.signal,
                    snap.confidence,
                    snap.shadow_stype,
                    snap.shadow_conf_pct,
                )
                mod_div = diag.analyze_model_distribution(snap.asset_name, proba_list)
                x_row = pd.DataFrame([snap.feature_row])
                proba_arr = snap.model.predict_proba(x_row)
                feat_drivers = diag.analyze_feature_impact(
                    snap.model,
                    x_row,
                    snap.features,
                    proba_arr,
                )
                close_series = pd.Series(snap.close_prices)
                regime = diag.analyze_regime_context(close_series)
                report = diag.build_shadow_report(
                    asset=snap.asset_name,
                    timestamp=snap.timestamp,
                    signal_match=sig_div["match"],
                    signal_divergence=sig_div,
                    model_divergence=mod_div,
                    feature_drivers=feat_drivers,
                    regime_context=regime,
                )
                trace_diagnostic_report(report)
                _shadow_store(snap.asset_name, report)

                risk_signal = _risk_evaluate(snap.asset_name)
                drift_intel = _get_drift(snap.asset_name)
                shadow_action = _compute_shadow(
                    asset=snap.asset_name,
                    state=None,
                    drift_report=drift_intel,
                    risk_signal=risk_signal,
                )
                _record_feedback(
                    asset=snap.asset_name,
                    signal_data={"signal": snap.signal, "confidence": snap.confidence},
                    drift=drift_intel,
                    risk=risk_signal,
                    action=shadow_action,
                )
                shadow_learning = _compile_learning(
                    asset=snap.asset_name,
                    feedback_logs=None,
                    drift_history=drift_intel,
                    risk_history=risk_signal,
                )

                with self._lock:
                    self._results[snap.asset_name] = {
                        "risk_signal": risk_signal,
                        "shadow_drift_intel": drift_intel,
                        "shadow_action": shadow_action,
                        "shadow_learning": shadow_learning,
                    }
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
                logger.debug("%s: shadow learning feedback skipped", snap.asset_name)

    def apply_pending(self, asset_name: str, asset) -> bool:
        """Apply any pending async results to the asset. Returns True if applied."""
        with self._lock:
            results = self._results.pop(asset_name, None)
        if results is not None:
            asset._risk_signal = results["risk_signal"]
            asset._shadow_drift_intel = results["shadow_drift_intel"]
            asset._shadow_action = results["shadow_action"]
            asset._shadow_learning = results["shadow_learning"]
            return True
        return False


_diagnostics_queue: DiagnosticsQueue | None = None


def get_diagnostics_queue() -> DiagnosticsQueue:
    global _diagnostics_queue
    if _diagnostics_queue is None:
        _diagnostics_queue = DiagnosticsQueue()
    return _diagnostics_queue
