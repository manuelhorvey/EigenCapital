import logging
from datetime import datetime, timezone

logger = logging.getLogger("quorrin.shadow.actions")


def compute_shadow_actions(
    asset: str,
    state: dict | None,
    drift_report: dict | None,
    risk_signal: dict | None,
) -> dict:
    try:
        if not drift_report or not risk_signal:
            return _fallback("SHADOW_FAILURE")

        drift = drift_report.get("drift_scores", {})
        risk_level = risk_signal.get("risk_level", "LOW")
        risk_score = risk_signal.get("risk_score", 0.0)
        risk_signal.get("risk_flags", [])

        model = drift.get("model_drift", 0.0)
        signal = drift.get("signal_drift", 0.0)
        pnl = drift.get("pnl_drift", 0.0)
        feature = drift.get("feature_stability", 0.0)
        regime = drift.get("regime_consistency", 0.0)

        reason_codes = []
        if model > 0.3:
            reason_codes.append("HIGH_MODEL_DRIFT")
        if signal > 0.3:
            reason_codes.append("SIGNAL_INSTABILITY")
        if pnl > 0.3:
            reason_codes.append("PNL_DIVERGENCE")
        if feature > 0.3:
            reason_codes.append("FEATURE_DEGRADATION")
        if regime > 0.3:
            reason_codes.append("REGIME_SHIFT")

        _action_type, _exposure_adjustment = _compute_action(risk_level, risk_score)
        guardrails = _compute_guardrails(risk_level, risk_score)

        return {
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "action_type": _action_type,
            "exposure_adjustment": round(_exposure_adjustment, 4),
            "confidence": round(1.0 - risk_score, 4),
            "reason_codes": reason_codes,
            "drift_summary": {
                "model": round(model, 4),
                "signal": round(signal, 4),
                "pnl": round(pnl, 4),
                "feature": round(feature, 4),
                "regime": round(regime, 4),
            },
            "recommended_guardrails": guardrails,
        }
    except Exception as e:
        logger.warning("Shadow actions failed for %s: %s: %s", asset, type(e).__name__, e)
        return _fallback("SHADOW_FAILURE")


def _compute_action(risk_level: str, risk_score: float) -> tuple:
    if risk_level == "HIGH":
        return "PAUSE_TRADING", max(0.0, 1.0 - risk_score)
    elif risk_level == "MEDIUM":
        return "REDUCE_EXPOSURE", max(0.0, 1.0 - risk_score)
    elif risk_score > 0.1:
        return "INCREASE_MONITORING", 1.0
    return "NONE", 1.0


def _compute_guardrails(risk_level: str, risk_score: float) -> dict:
    if risk_level == "HIGH":
        return {
            "max_position_size": round(max(0.0, 1.0 - risk_score), 4),
            "min_hold_time": 2,
            "entry_block": True,
        }
    elif risk_level == "MEDIUM":
        return {
            "max_position_size": round(max(0.0, 1.0 - risk_score), 4),
            "min_hold_time": 1,
            "entry_block": False,
        }
    return {
        "max_position_size": 1.0,
        "min_hold_time": 0,
        "entry_block": False,
    }


def _fallback(reason: str) -> dict:
    return {
        "asset": "",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "action_type": "NONE",
        "exposure_adjustment": 1.0,
        "confidence": 0.0,
        "reason_codes": [reason],
        "drift_summary": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.0},
        "recommended_guardrails": {
            "max_position_size": 1.0,
            "min_hold_time": 0,
            "entry_block": False,
        },
    }
