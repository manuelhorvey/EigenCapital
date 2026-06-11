import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_lock = threading.Lock()
_distribution_history: dict = {}


def analyze_signal_divergence(
    proba: list,
    threshold: float,
    original_signal: str,
    original_confidence: float,
    wrapper_signal: str,
    wrapper_confidence: float,
) -> dict:
    match = (wrapper_signal == original_signal) and abs(wrapper_confidence - original_confidence) < 0.001

    prob_long = proba[2]
    prob_short = proba[0]
    dist_long = prob_long - threshold
    dist_short = prob_short - threshold
    margin = max(dist_long, dist_short) if prob_long > threshold or prob_short > threshold else 0.0

    if wrapper_signal != original_signal:
        flip_reason = "direction_flip"
    elif abs(wrapper_confidence - original_confidence) >= 0.001:
        flip_reason = "confidence_divergence"
    else:
        flip_reason = "none" if match else "unknown"

    return {
        "match": match,
        "flip_reason": flip_reason,
        "threshold_distance_long": round(float(dist_long), 6),
        "threshold_distance_short": round(float(dist_short), 6),
        "margin": round(float(margin), 6),
        "confidence_gap": round(float(abs(wrapper_confidence - original_confidence)), 6),
    }


def analyze_model_distribution(
    asset: str,
    proba: list,
    window: int = 100,
) -> dict:
    entry = {
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "proba_short": float(proba[0]),
        "proba_neutral": float(proba[1]),
        "proba_long": float(proba[2]),
        "predicted": (
            "SHORT"
            if proba[0] > max(proba[1], proba[2])
            else "LONG"
            if proba[2] > max(proba[0], proba[1])
            else "NEUTRAL"
        ),
        "confidence": float(max(proba)),
    }

    with _lock:
        if asset not in _distribution_history:
            _distribution_history[asset] = []
        _distribution_history[asset].append(entry)
        if len(_distribution_history[asset]) > window:
            _distribution_history[asset] = _distribution_history[asset][-window:]
        hist = _distribution_history[asset]

    recent = hist[-min(len(hist), window) :]
    if len(recent) < 2:
        return {
            "current": entry,
            "short_freq": 0.0,
            "neutral_freq": 0.0,
            "long_freq": 0.0,
            "drift_detected": False,
        }

    n = len(recent)
    short_count = sum(1 for h in recent if h["predicted"] == "SHORT")
    neutral_count = sum(1 for h in recent if h["predicted"] == "NEUTRAL")
    long_count = sum(1 for h in recent if h["predicted"] == "LONG")

    return {
        "current": entry,
        "short_freq": round(short_count / n, 4),
        "neutral_freq": round(neutral_count / n, 4),
        "long_freq": round(long_count / n, 4),
        "drift_detected": long_count > n * 0.8 or short_count > n * 0.8,
    }


def analyze_feature_impact(
    model,
    x_row: pd.DataFrame,
    feature_names: list,
    baseline_proba: np.ndarray,
) -> list:
    try:
        baseline_class = int(np.argmax(baseline_proba[0]))
        baseline_conf = float(baseline_proba[0, baseline_class])
        impacts = []

        for feat in feature_names[:20]:
            if feat not in x_row.columns:
                continue
            perturbed = x_row.copy()
            perturbed[feat] = 0.0
            perturbed_proba = model.predict_proba(perturbed)
            perturbed_conf = float(perturbed_proba[0, baseline_class])
            impact = baseline_conf - perturbed_conf
            impacts.append(
                {
                    "feature": feat,
                    "impact": round(impact, 6),
                    "direction": "increases" if impact > 0 else "decreases",
                }
            )

        impacts.sort(key=lambda x: abs(x["impact"]), reverse=True)
        return impacts[:5]
    except Exception:
        return []


def analyze_regime_context(close: pd.Series) -> dict:
    try:
        returns = np.log(close / close.shift(1)).dropna()
        if len(returns) < 20:
            return {"volatility_regime": "unknown", "current_vol": 0.0, "vol_percentile": 0.0}

        recent_vol = returns.tail(20).std() * np.sqrt(252)
        rolling = [returns.iloc[i : i + 20].std() * np.sqrt(252) for i in range(len(returns) - 19)]
        if not rolling:
            return {
                "volatility_regime": "unknown",
                "current_vol": round(float(recent_vol), 6),
                "vol_percentile": 0.5,
            }

        pct = sum(1 for v in rolling if v < recent_vol) / len(rolling)

        if pct > 0.75:
            regime = "high"
        elif pct < 0.25:
            regime = "low"
        else:
            regime = "medium"

        return {
            "volatility_regime": regime,
            "current_vol": round(float(recent_vol), 6),
            "vol_percentile": round(float(pct), 4),
        }
    except Exception:
        return {"volatility_regime": "unknown", "current_vol": 0.0, "vol_percentile": 0.0}


def analyze_pnl_decomposition(
    current_value: float,
    direction: int,
    ret: float,
    position_size_fraction: float,
    pos_size: float,
    original_pnl: float,
) -> dict:
    computed_pnl = current_value * direction * ret * position_size_fraction * pos_size
    match = abs(computed_pnl - original_pnl) < 1e-10

    return {
        "computed_pnl": round(float(computed_pnl), 10),
        "original_pnl": round(float(original_pnl), 10),
        "match": match,
        "absolute_error": round(float(abs(computed_pnl - original_pnl)), 15),
        "attribution": {
            "direction": round(float(direction), 0),
            "return": round(float(ret), 10),
            "size_product": round(float(position_size_fraction * pos_size), 6),
        },
        "inputs": {
            "current_value": float(current_value),
            "direction": int(direction),
            "ret": round(float(ret), 10),
            "position_size_fraction": float(position_size_fraction),
            "pos_size": float(pos_size),
        },
    }


def build_shadow_report(
    asset: str,
    timestamp: str,
    signal_match: bool,
    pnl_match: bool | None = None,
    model_divergence: dict | None = None,
    signal_divergence: dict | None = None,
    feature_drivers: list | None = None,
    regime_context: dict | None = None,
    pnl_decomposition: dict | None = None,
    sltp_drift: dict | None = None,
) -> dict:
    report = {
        "asset": asset,
        "timestamp": timestamp,
        "signal_match": signal_match,
        "pnl_match": pnl_match,
        "model_divergence": model_divergence or {},
        "signal_divergence": signal_divergence or {},
        "feature_drivers": feature_drivers or [],
        "regime_context": regime_context or {},
        "pnl_decomposition": pnl_decomposition or {},
        "sltp_drift": sltp_drift or {},
    }

    hypotheses = []
    if signal_divergence and not signal_divergence.get("match", True):
        hypotheses.append(f"signal_mismatch:{signal_divergence.get('flip_reason', 'unknown')}")
    if pnl_decomposition and not pnl_decomposition.get("match", True):
        hypotheses.append("pnl_mismatch:computation_divergence")
    if model_divergence and model_divergence.get("drift_detected"):
        hypotheses.append("model_drift:class_imbalance")

    report["root_cause_hypothesis"] = "; ".join(hypotheses) if hypotheses else "no_divergence"
    return report
