import json
import logging
import os
import threading
from collections import Counter

import numpy as np

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from eigencapital.domain.time import utc_now_iso
from paper_trading.shadow.feedback import read_feedback

logger = logging.getLogger("eigencapital.shadow.learning")

_lock = threading.Lock()

LEARNING_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "shadow_learning"
)


def compile_shadow_learning(
    asset: str,
    feedback_logs: list | None = None,
    drift_history: dict | None = None,
    risk_history: dict | None = None,
) -> dict:
    try:
        if feedback_logs is None:
            feedback_logs = read_feedback(asset, months=6)

        if not feedback_logs:
            return _empty_report(asset)

        n = len(feedback_logs)

        profile = _compute_learning_profile(feedback_logs)
        latent_patterns = _mine_latent_patterns(feedback_logs)
        regime_map = _build_regime_behavior_map(feedback_logs)
        insights = _compute_shadow_insights(feedback_logs)

        compiled = {
            "asset": asset,
            "timestamp": utc_now_iso(),
            "event_count": n,
            "learning_profile": profile,
            "latent_patterns": latent_patterns,
            "regime_behavior_map": regime_map,
            "shadow_insights": insights,
        }

        _save_compiled(asset, compiled)
        return compiled
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Shadow learning compilation failed for %s: %s: %s", asset, type(e).__name__, e)
        return _empty_report(asset)


def _compute_learning_profile(events: list) -> dict:
    n = len(events)
    if n == 0:
        return {
            "behavioral_stability": 0.0,
            "drift_resilience": 0.0,
            "signal_consistency": 0.0,
            "risk_sensitivity": 0.0,
            "action_coherence": 0.0,
        }

    instabilities = []
    alignments = []
    drift_sensitivity_values = []
    risk_action_pairs = []

    for e in events:
        d = e.get("derived", {})
        instabilities.append(d.get("instability_index", 0.0))
        alignments.append(d.get("risk_alignment", 1.0))

        inp = e.get("inputs", {})
        drift = inp.get("drift", {})
        avg_drift = sum(drift.values()) / max(len(drift), 1)
        drift_sensitivity_values.append(avg_drift)

        risk = inp.get("risk", {})
        action = inp.get("shadow_action", {})
        risk_action_pairs.append((risk.get("risk_level", "LOW"), action.get("action_type", "NONE")))

    behavioral_stability = max(0.0, 1.0 - np.mean(instabilities))
    drift_resilience = max(0.0, 1.0 - np.mean(drift_sensitivity_values))
    signal_consistency = max(0.0, 1.0 - np.mean(instabilities) * 0.5)
    action_coherence = np.mean(alignments)

    high_risk_count = sum(1 for r, a in risk_action_pairs if r in ("MEDIUM", "HIGH"))
    protective_action_count = sum(1 for r, a in risk_action_pairs if a in ("REDUCE_EXPOSURE", "PAUSE_TRADING"))
    risk_sensitivity = (protective_action_count / high_risk_count) if high_risk_count > 0 else 0.5

    return {
        "behavioral_stability": round(float(behavioral_stability), 4),
        "drift_resilience": round(float(drift_resilience), 4),
        "signal_consistency": round(float(signal_consistency), 4),
        "risk_sensitivity": round(float(risk_sensitivity), 4),
        "action_coherence": round(float(action_coherence), 4),
    }


def _mine_latent_patterns(events: list) -> list:
    patterns = []
    n = len(events)
    if n < 5:
        return patterns

    drift_scores = []
    flip_rates = []
    instability_scores = []
    risk_levels = []
    regime_counts = Counter()

    for e in events:
        inp = e.get("inputs", {})
        drift = inp.get("drift", {})
        risk = inp.get("risk", {})
        d = e.get("derived", {})

        avg_drift = sum(drift.values()) / max(len(drift), 1)
        drift_scores.append(avg_drift)
        instability_scores.append(d.get("instability_index", 0.0))
        risk_levels.append(risk.get("risk_level", "LOW"))

        sig = inp.get("signal", {})
        flip_rates.append(1.0 - sig.get("confidence", 1.0) / 100.0)

        inp.get("drift", {})
        regime_counts["event"] += 1

    drift_arr = np.array(drift_scores)
    flip_arr = np.array(flip_rates)
    instability_arr = np.array(instability_scores)

    if n >= 10:
        corr = np.corrcoef(drift_arr, flip_arr)[0, 1] if np.std(drift_arr) > 0 and np.std(flip_arr) > 0 else 0.0
        if abs(corr) > 0.3:
            patterns.append(f"HIGH_DRIFT_PERIODS_CORRELATE_WITH_{'SIGNAL_FLIPS' if corr > 0 else 'SIGNAL_STABILITY'}")

        instability_arr > np.percentile(instability_arr, 75)
        drift_arr > np.percentile(drift_arr, 75)
        feature_decay_windows = sum(1 for i in range(1, n) if instability_arr[i] > instability_arr[i - 1] * 1.5)
        if feature_decay_windows > n * 0.1:
            patterns.append("FEATURE_DECAY_AFTER_VOLATILITY_SPIKES")

    high_risk_count = sum(1 for r in risk_levels if r == "HIGH")
    if high_risk_count > n * 0.3:
        patterns.append("PROLONGED_HIGH_RISK_REGIME_DETECTED")

    medium_risk_with_normal_action = sum(
        1
        for i, r in enumerate(risk_levels)
        if r == "MEDIUM"
        and i < len(events)
        and events[i].get("inputs", {}).get("shadow_action", {}).get("action_type") == "NONE"
    )
    if medium_risk_with_normal_action > n * 0.1:
        patterns.append("RISK_UNDERREACTION_IN_MEDIUM_RISK_PERIODS")

    high_risk_no_action = sum(
        1
        for i, r in enumerate(risk_levels)
        if r == "HIGH"
        and i < len(events)
        and events[i].get("inputs", {}).get("shadow_action", {}).get("action_type") in ("NONE", "INCREASE_MONITORING")
    )
    if high_risk_no_action > n * 0.05:
        patterns.append("RISK_OVEREACTION_IN_HIGH_VIX_REGIMES")

    return patterns


def _build_regime_behavior_map(events: list) -> dict:
    if not events:
        return {
            "low_vol": {"stability": 0.5, "risk_action_rate": 0.0},
            "high_vol": {"stability": 0.5, "risk_action_rate": 0.0},
        }

    low_vol_stabilities = []
    high_vol_stabilities = []
    low_vol_risk = 0
    low_vol_total = 0
    high_vol_risk = 0
    high_vol_total = 0

    for e in events:
        inp = e.get("inputs", {})
        drift = inp.get("drift", {})
        d = e.get("derived", {})
        action = inp.get("shadow_action", {}).get("action_type", "NONE")
        is_risk_action = action in ("REDUCE_EXPOSURE", "PAUSE_TRADING")

        regime = drift.get("regime", 0.0)
        is_high_vol = regime > 0.3

        if is_high_vol:
            high_vol_stabilities.append(1.0 - d.get("instability_index", 0.0))
            high_vol_total += 1
            if is_risk_action:
                high_vol_risk += 1
        else:
            low_vol_stabilities.append(1.0 - d.get("instability_index", 0.0))
            low_vol_total += 1
            if is_risk_action:
                low_vol_risk += 1

    return {
        "low_vol": {
            "stability": round(float(np.mean(low_vol_stabilities)), 4) if low_vol_stabilities else 0.5,
            "risk_action_rate": round(low_vol_risk / low_vol_total, 4) if low_vol_total > 0 else 0.0,
        },
        "high_vol": {
            "stability": round(float(np.mean(high_vol_stabilities)), 4) if high_vol_stabilities else 0.5,
            "risk_action_rate": round(high_vol_risk / high_vol_total, 4) if high_vol_total > 0 else 0.0,
        },
    }


def _compute_shadow_insights(events: list) -> dict:
    n = len(events)
    if n == 0:
        return {"top_instability_drivers": [], "dominant_failure_mode": "unknown", "execution_fragility_score": 0.0}

    drift_dims = {"model": [], "signal": [], "pnl": [], "feature": [], "regime": []}
    flag_counter = Counter()

    for e in events:
        inp = e.get("inputs", {})
        drift = inp.get("drift", {})
        for k in drift_dims:
            v = drift.get(k, 0.0)
            drift_dims[k].append(v)

        risk = inp.get("risk", {})
        for flag in risk.get("risk_flags", []):
            flag_counter[flag] += 1

    avg_drifts = {k: float(np.mean(v)) for k, v in drift_dims.items() if v}
    sorted_dims = sorted(avg_drifts.items(), key=lambda x: x[1], reverse=True)
    top_drivers = [d[0] for d in sorted_dims[:3] if d[1] > 0.1]

    dominant = flag_counter.most_common(1)
    dominant_mode = dominant[0][0].lower() if dominant else "none_detected"

    instabilities = [e.get("derived", {}).get("instability_index", 0.0) for e in events]
    fragility = min(1.0, float(np.mean(instabilities)) * 2.0)

    return {
        "top_instability_drivers": top_drivers,
        "dominant_failure_mode": dominant_mode,
        "execution_fragility_score": round(fragility, 4),
    }


def _save_compiled(asset: str, report: dict) -> None:
    try:
        path = os.path.join(LEARNING_DIR, asset, "compiled.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            existing = {}
            if os.path.exists(path):
                with open(path) as f:
                    existing = json.load(f)
            for key in ["learning_profile", "latent_patterns", "shadow_insights"]:
                existing[key] = report.get(key, existing.get(key, {} if key != "latent_patterns" else []))
            history = existing.get("history", [])
            history.append(
                {
                    "timestamp": report["timestamp"],
                    "event_count": report["event_count"],
                    "learning_profile": report["learning_profile"],
                }
            )
            if len(history) > 180:
                history = history[-180:]
            existing["history"] = history
            existing["last_updated"] = report["timestamp"]
            existing["asset"] = asset
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(existing, f, indent=2, cls=EigenCapitalJSONEncoder)
            os.replace(tmp, path)
    except OSError as e:
        logger.error("Failed to save compiled learning for %s: %s", asset, e)
    except TypeError as e:
        logger.error("Non-serializable compiled learning for %s: %s", asset, e)


def load_compiled(asset: str) -> dict | None:
    try:
        path = os.path.join(LEARNING_DIR, asset, "compiled.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to load compiled learning for %s: %s: %s", asset, type(e).__name__, e)
        return None


def _empty_report(asset: str) -> dict:
    return {
        "asset": asset,
        "timestamp": utc_now_iso(),
        "event_count": 0,
        "learning_profile": {
            "behavioral_stability": 0.0,
            "drift_resilience": 0.0,
            "signal_consistency": 0.0,
            "risk_sensitivity": 0.0,
            "action_coherence": 0.0,
        },
        "latent_patterns": [],
        "regime_behavior_map": {
            "low_vol": {"stability": 0.5, "risk_action_rate": 0.0},
            "high_vol": {"stability": 0.5, "risk_action_rate": 0.0},
        },
        "shadow_insights": {
            "top_instability_drivers": [],
            "dominant_failure_mode": "unknown",
            "execution_fragility_score": 0.0,
        },
    }
