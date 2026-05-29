import threading
from collections import deque
from datetime import datetime

from paper_trading.governance.drift import get_shadow_intelligence

_lock = threading.Lock()
_cache: dict = {}

# Per-asset SL hit rate tracker
_sl_hit_rates: dict[str, deque] = {}
_sl_hit_rate_lock = threading.Lock()

WEIGHTS = {
    "model_drift": 0.25,
    "signal_drift": 0.20,
    "pnl_drift": 0.25,
    "feature_stability": 0.15,
    "regime_consistency": 0.15,
}

FLAG_THRESHOLD = 0.3

# SL hit rate monitoring defaults
SL_HIT_RATE_WINDOW = 20  # last N trades to evaluate
SL_HIT_RATE_ALERT = 0.40  # alert if SL hit rate exceeds 40%
SL_HIT_RATE_CRITICAL = 0.55  # halt trading if SL hit rate exceeds 55%


def record_trade_outcome(asset: str, reason: str) -> None:
    """Record a trade exit reason for SL hit rate tracking."""
    with _sl_hit_rate_lock:
        if asset not in _sl_hit_rates:
            _sl_hit_rates[asset] = deque(maxlen=SL_HIT_RATE_WINDOW)
        _sl_hit_rates[asset].append(1 if reason == "sl" else 0)


def get_sl_hit_rate(asset: str) -> float | None:
    """Return the SL hit rate over the last N trades."""
    with _sl_hit_rate_lock:
        dq = _sl_hit_rates.get(asset)
        if dq is None or len(dq) < 5:
            return None
        return sum(dq) / len(dq)


def get_sl_hit_rate_all() -> dict[str, float]:
    """Return SL hit rate for all tracked assets."""
    with _sl_hit_rate_lock:
        return {a: sum(dq) / len(dq) for a, dq in _sl_hit_rates.items() if len(dq) >= 5}


def evaluate(asset: str) -> dict:
    try:
        intelligence = get_shadow_intelligence(asset)
        drift_scores = intelligence.get("drift_scores", {})
        details = intelligence.get("details", {})

        risk_score = sum(drift_scores.get(k, 0.0) * v for k, v in WEIGHTS.items())

        # Incorporate SL hit rate as an additive risk factor
        sl_rate = get_sl_hit_rate(asset)
        if sl_rate is not None:
            if sl_rate > SL_HIT_RATE_CRITICAL:
                risk_score += 0.30
                details["sl_hit_rate_risk"] = "CRITICAL"
            elif sl_rate > SL_HIT_RATE_ALERT:
                risk_score += 0.15
                details["sl_hit_rate_risk"] = "ELEVATED"
            details["sl_hit_rate"] = round(sl_rate, 4)
            details["sl_hit_rate_window"] = SL_HIT_RATE_WINDOW

        if risk_score < 0.3:
            risk_level = "LOW"
        elif risk_score < 0.6:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        exposure_multiplier = max(0.0, 1.0 - risk_score)

        risk_flags = []
        for key, threshold in [
            ("model_drift", FLAG_THRESHOLD),
            ("signal_drift", FLAG_THRESHOLD),
            ("pnl_drift", FLAG_THRESHOLD),
            ("feature_stability", FLAG_THRESHOLD),
            ("regime_consistency", FLAG_THRESHOLD),
        ]:
            if drift_scores.get(key, 0.0) > threshold:
                flag_map = {
                    "model_drift": "MODEL_DRIFT",
                    "signal_drift": "SIGNAL_INSTABILITY",
                    "pnl_drift": "PNL_DEGRADATION",
                    "feature_stability": "FEATURE_UNSTABLE",
                    "regime_consistency": "REGIME_SHIFT",
                }
                risk_flags.append(flag_map[key])

        if sl_rate is not None:
            if sl_rate > SL_HIT_RATE_CRITICAL:
                risk_flags.append("EXCESSIVE_SL_HITS")
            elif sl_rate > SL_HIT_RATE_ALERT:
                risk_flags.append("ELEVATED_SL_HITS")

        recommended_action = _recommend(risk_level, risk_flags)
        explanations = _generate_explanations(drift_scores, risk_flags, sl_rate)

        signal = {
            "asset": asset,
            "timestamp": datetime.utcnow().isoformat(),
            "risk_level": risk_level,
            "risk_score": round(risk_score, 4),
            "confidence": round(1.0 - risk_score, 4),
            "exposure_multiplier": round(exposure_multiplier, 4),
            "risk_flags": risk_flags,
            "recommended_action": recommended_action,
            "explanations": explanations,
            "component_scores": {k: round(drift_scores.get(k, 0.0), 4) for k in WEIGHTS},
            "drift_details": details,
        }

        with _lock:
            _cache[asset] = signal

        return signal
    except Exception:
        return _fallback_signal(asset)


def get_latest(asset: str | None = None):
    with _lock:
        if asset:
            return _cache.get(asset)
        return dict(_cache)


def _recommend(risk_level: str, risk_flags: list) -> str:
    if "EXCESSIVE_SL_HITS" in risk_flags:
        return "PAUSE"
    if risk_level == "HIGH":
        return "PAUSE"
    elif risk_level == "MEDIUM":
        return "REDUCE_RISK"
    elif risk_flags:
        return "MONITOR"
    return "NORMAL"


def _generate_explanations(drift_scores: dict, risk_flags: list, sl_rate: float | None = None) -> list:
    templates = {
        "MODEL_DRIFT": "Model probability distribution deviates significantly from baseline (KL {score:.2f})",
        "SIGNAL_INSTABILITY": "Signal flip rate increased beyond historical percentile (mismatch rate {score:.2f})",
        "PNL_DEGRADATION": "PnL divergence exceeds expected baseline variance (MAE {score:.2f})",
        "FEATURE_UNSTABLE": "Feature stability declining, Jaccard similarity dropping (stability {score:.2f})",
        "REGIME_SHIFT": (
            "Regime classification mismatch increasing vs historical distribution (consistency {score:.2f})"
        ),
        "ELEVATED_SL_HITS": "SL hit rate elevated ({score:.1%}) — consider wider stops or lower sizing",
        "EXCESSIVE_SL_HITS": "SL hit rate critical ({score:.1%}) — halting, stops too tight or model broken",
    }
    key_map = {
        "MODEL_DRIFT": "model_drift",
        "SIGNAL_INSTABILITY": "signal_drift",
        "PNL_DEGRADATION": "pnl_drift",
        "FEATURE_UNSTABLE": "feature_stability",
        "REGIME_SHIFT": "regime_consistency",
    }
    explanations = []
    for flag in risk_flags:
        key = key_map.get(flag)
        score = drift_scores.get(key, 0.0) if key else 0.0
        if flag in ("ELEVATED_SL_HITS", "EXCESSIVE_SL_HITS"):
            score = sl_rate or 0.0
        template = templates.get(flag, "")
        if template:
            explanations.append(template.format(score=score))
    if not explanations:
        explanations.append("No significant drift detected — risk within normal bounds")
    return explanations


def _fallback_signal(asset: str) -> dict:
    return {
        "asset": asset,
        "timestamp": datetime.utcnow().isoformat(),
        "risk_level": "LOW",
        "risk_score": 0.0,
        "confidence": 1.0,
        "exposure_multiplier": 1.0,
        "risk_flags": [],
        "recommended_action": "NORMAL",
        "explanations": ["Risk governance unavailable — defaulting to LOW risk"],
        "component_scores": {},
        "drift_details": {},
    }
