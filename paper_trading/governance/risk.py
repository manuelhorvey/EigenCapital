import logging
import threading
from collections import deque
from datetime import datetime, timezone

from paper_trading.governance.drift import get_shadow_intelligence

logger = logging.getLogger("quantforge.risk")

_lock = threading.Lock()
_cache: dict = {}
_MAX_CACHE_SIZE = 500

# Per-asset SL hit rate tracker
_sl_hit_rates: dict[str, deque] = {}
_sl_hit_rate_lock = threading.Lock()

# SELL-side win rate tracker (tripwire)
_sell_win_rates: dict[str, deque] = {}
_sell_win_rate_lock = threading.Lock()
_tripwire_last_state: dict[str, bool] = {}

SELL_WIN_RATE_WINDOW = 20
TRIPWIRE_THRESHOLD = 0.65  # alert if SELL win rate drops below 65%

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


def reset() -> None:
    """Clear all cached state. Call on engine initialisation to prevent
    stale data from a previous session leaking into a new run."""
    with _lock:
        _cache.clear()
    with _sl_hit_rate_lock:
        _sl_hit_rates.clear()
    with _sell_win_rate_lock:
        _sell_win_rates.clear()
    _tripwire_last_state.clear()


def record_trade_outcome(asset: str, reason: str) -> None:
    """Record a trade exit reason for SL hit rate tracking."""
    with _sl_hit_rate_lock:
        if asset not in _sl_hit_rates:
            _sl_hit_rates[asset] = deque(maxlen=SL_HIT_RATE_WINDOW)
        _sl_hit_rates[asset].append(1 if reason.upper() == "SL" else 0)


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


def record_sell_side_outcome(asset: str, reason: str, side: str) -> None:
    if side != "short":
        return
    if reason.upper() not in ("TP", "SL"):
        return

    with _sell_win_rate_lock:
        if asset not in _sell_win_rates:
            _sell_win_rates[asset] = deque(maxlen=SELL_WIN_RATE_WINDOW)
        _sell_win_rates[asset].append(1 if reason.upper() == "TP" else 0)

        dq = _sell_win_rates[asset]
        n = len(dq)
        win_rate = sum(dq) / n if n >= 5 else None

    if win_rate is not None and win_rate < TRIPWIRE_THRESHOLD:
        prev = _tripwire_last_state.get(asset, False)
        if not prev:
            logger.warning(
                "SELL tripwire TRIPPED for %s: win_rate=%.1f%% (%d trades, threshold=%.0f%%). "
                "Re-investigate: model may have flipped or calibration shifted.",
                asset,
                win_rate * 100,
                n,
                TRIPWIRE_THRESHOLD * 100,
            )
        _tripwire_last_state[asset] = True
    else:
        if _tripwire_last_state.get(asset, False):
            logger.info(
                "SELL tripwire CLEARED for %s: win_rate=%.1f%%",
                asset,
                win_rate * 100 if win_rate is not None else 0,
            )
        _tripwire_last_state[asset] = False


def get_sell_win_rate(asset: str) -> float | None:
    """Return SELL win rate over the last N trades, or None if <5 trades."""
    with _sell_win_rate_lock:
        dq = _sell_win_rates.get(asset)
        if dq is None or len(dq) < 5:
            return None
        return sum(dq) / len(dq)


def get_sell_tripwire_state(asset: str, sell_only: bool = False) -> dict:
    win_rate = get_sell_win_rate(asset)
    tripped = sell_only and win_rate is not None and win_rate < TRIPWIRE_THRESHOLD
    return {"win_rate": win_rate, "tripped": tripped}


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

        # Incorporate SELL tripwire as an additive risk factor
        sell_wr = get_sell_win_rate(asset)
        if sell_wr is not None and sell_wr < TRIPWIRE_THRESHOLD:
            risk_score += 0.25
            details["sell_tripwire_risk"] = "TRIPPED"
            details["sell_win_rate"] = round(sell_wr, 4)

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
                    "sell_win_rate": "SELL_TRIPWIRE",
                }
                risk_flags.append(flag_map[key])

        if sl_rate is not None:
            if sl_rate > SL_HIT_RATE_CRITICAL:
                risk_flags.append("EXCESSIVE_SL_HITS")
            elif sl_rate > SL_HIT_RATE_ALERT:
                risk_flags.append("ELEVATED_SL_HITS")

        if sell_wr is not None and sell_wr < TRIPWIRE_THRESHOLD:
            risk_flags.append("SELL_TRIPWIRE")

        recommended_action = _recommend(risk_level, risk_flags)
        explanations = _generate_explanations(drift_scores, risk_flags, sl_rate, sell_wr)

        signal = {
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
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
            if len(_cache) > _MAX_CACHE_SIZE:
                _cache.clear()
                logger.warning("risk cache exceeded %d entries — clearing", _MAX_CACHE_SIZE)

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
    if "SELL_TRIPWIRE" in risk_flags:
        return "PAUSE"
    if risk_level == "HIGH":
        return "PAUSE"
    elif risk_level == "MEDIUM":
        return "REDUCE_RISK"
    elif risk_flags:
        return "MONITOR"
    return "NORMAL"


def _generate_explanations(drift_scores: dict, risk_flags: list, sl_rate: float | None = None, sell_wr: float | None = None) -> list:
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
        "SELL_TRIPWIRE": "SELL win rate below threshold ({score:.1%}) — possible calibration shift or directional inversion",
    }
    key_map = {
        "MODEL_DRIFT": "model_drift",
        "SIGNAL_INSTABILITY": "signal_drift",
        "PNL_DEGRADATION": "pnl_drift",
        "FEATURE_UNSTABLE": "feature_stability",
        "REGIME_SHIFT": "regime_consistency",
        "SELL_TRIPWIRE": "sell_win_rate",
    }
    explanations = []
    for flag in risk_flags:
        key = key_map.get(flag)
        score = drift_scores.get(key, 0.0) if key else 0.0
        if flag in ("ELEVATED_SL_HITS", "EXCESSIVE_SL_HITS"):
            score = sl_rate or 0.0
        if flag == "SELL_TRIPWIRE":
            score = sell_wr or 0.0
        template = templates.get(flag, "")
        if template:
            explanations.append(template.format(score=score))
    if not explanations:
        explanations.append("No significant drift detected — risk within normal bounds")
    return explanations


def _fallback_signal(asset: str) -> dict:
    return {
        "asset": asset,
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
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
