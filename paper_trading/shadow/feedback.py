import json
import logging
import os
import threading

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from eigencapital.domain.time import utc_now_iso, utc_now_naive

logger = logging.getLogger("eigencapital.shadow.feedback")

_lock = threading.Lock()

FEEDBACK_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "shadow_feedback"
)


def record_shadow_feedback(
    asset: str,
    signal_data: dict,
    drift: dict,
    risk: dict,
    action: dict,
) -> None:
    if not asset or not isinstance(asset, str):
        logger.warning("record_shadow_feedback: invalid asset=%r", asset)
        return
    if signal_data is None:
        logger.warning("record_shadow_feedback: signal_data is None for %s", asset)
        return
    if drift is None:
        logger.warning("record_shadow_feedback: drift is None for %s", asset)
        return
    if risk is None:
        logger.warning("record_shadow_feedback: risk is None for %s", asset)
        return
    if action is None:
        logger.warning("record_shadow_feedback: action is None for %s", asset)
        return

    scores = _compute_derived_metrics(signal_data, drift, risk, action)
    event = _build_event(asset, signal_data, drift, risk, action, scores)
    _store_event(asset, event)


def _compute_derived_metrics(
    signal_data: dict,
    drift: dict,
    risk: dict,
    action: dict,
) -> dict:
    drift_scores = drift.get("drift_scores", {}) if drift else {}
    avg_drift = sum(drift_scores.values()) / max(len(drift_scores), 1)

    confidence = signal_data.get("confidence", 0.0) if signal_data else 0.0
    risk.get("risk_score", 0.0) if risk else 0.0
    action_type = action.get("action_type", "NONE") if action else "NONE"

    severity_map = {"NONE": 0.0, "INCREASE_MONITORING": 0.33, "REDUCE_EXPOSURE": 0.66, "PAUSE_TRADING": 1.0}
    action_severity = severity_map.get(action_type, 0.0)

    agreement_score = max(0.0, 1.0 - (avg_drift * 0.5 + (1.0 - confidence) * 0.3 + action_severity * 0.2))

    instability_index = (
        drift_scores.get("model_drift", 0.0) * 0.25
        + drift_scores.get("signal_drift", 0.0) * 0.25
        + drift_scores.get("pnl_drift", 0.0) * 0.25
        + drift_scores.get("feature_stability", 0.0) * 0.15
        + drift_scores.get("regime_consistency", 0.0) * 0.10
    )

    expected_action = _expected_action_for_risk(risk)
    risk_alignment = _compute_alignment(action_type, expected_action)

    return {
        "agreement_score": round(agreement_score, 4),
        "instability_index": round(instability_index, 4),
        "risk_alignment": round(risk_alignment, 4),
    }


def _expected_action_for_risk(risk: dict) -> str:
    if not risk:
        return "NONE"
    level = risk.get("risk_level", "LOW")
    return {"LOW": "NONE", "MEDIUM": "REDUCE_EXPOSURE", "HIGH": "PAUSE_TRADING"}.get(level, "NONE")


def _compute_alignment(actual: str, expected: str) -> float:
    if actual == expected:
        return 1.0
    severity = {"NONE": 0, "INCREASE_MONITORING": 1, "REDUCE_EXPOSURE": 2, "PAUSE_TRADING": 3}
    diff = abs(severity.get(actual, 0) - severity.get(expected, 0))
    return max(0.0, 1.0 - diff * 0.5)


def _build_event(
    asset: str,
    signal_data: dict,
    drift: dict,
    risk: dict,
    action: dict,
    derived: dict,
) -> dict:
    drift_scores = drift.get("drift_scores", {}) if drift else {}
    risk_signal = risk or {}
    action_data = action or {}

    return {
        "timestamp": utc_now_iso(),
        "asset": asset,
        "inputs": {
            "signal": {
                "type": signal_data.get("signal", "FLAT") if signal_data else "FLAT",
                "confidence": signal_data.get("confidence", 0.0) if signal_data else 0.0,
            },
            "drift": {
                "model": drift_scores.get("model_drift", 0.0),
                "signal": drift_scores.get("signal_drift", 0.0),
                "pnl": drift_scores.get("pnl_drift", 0.0),
                "feature": drift_scores.get("feature_stability", 0.0),
                "regime": drift_scores.get("regime_consistency", 0.0),
            },
            "risk": {
                "risk_level": risk_signal.get("risk_level", "LOW"),
                "risk_score": risk_signal.get("risk_score", 0.0),
            },
            "shadow_action": {
                "action_type": action_data.get("action_type", "NONE"),
                "exposure_adjustment": action_data.get("exposure_adjustment", 1.0),
            },
        },
        "derived": derived,
    }


def _store_event(asset: str, event: dict) -> None:
    try:
        now = utc_now_naive()
        month_key = now.strftime("%Y-%m")
        path = os.path.join(FEEDBACK_DIR, asset, f"{month_key}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock, open(path, "a") as f:
            f.write(json.dumps(event, cls=EigenCapitalJSONEncoder) + "\n")
    except OSError as e:
        logger.error("Failed to store shadow feedback for %s: %s", asset, e)
    except TypeError as e:
        logger.error("Non-serializable shadow feedback for %s: %s", asset, e)


def read_feedback(asset: str, months: int = 3) -> list:
    try:
        from datetime import timedelta

        now = utc_now_naive()
        events = []
        for i in range(months):
            dt = now - timedelta(days=30 * i)
            month_key = dt.strftime("%Y-%m")
            path = os.path.join(FEEDBACK_DIR, asset, f"{month_key}.jsonl")
            if not os.path.exists(path):
                continue
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        return events
    except Exception as e:
        logger.warning("Failed to read shadow feedback for %s: %s: %s", asset, type(e).__name__, e)
        return []
