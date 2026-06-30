from collections import Counter

import numpy as np

from paper_trading.shadow.memory import load_baseline, read_events


def _extract_probas(events: list) -> tuple:
    short, neutral, long_ = [], [], []
    for e in events:
        md = e.get("model_divergence", {})
        cur = md.get("current", {})
        if cur.get("proba_short") is not None:
            short.append(cur["proba_short"])
            neutral.append(cur["proba_neutral"])
            long_.append(cur["proba_long"])
    return short, neutral, long_


def _extract_signal_mismatches(events: list) -> tuple:
    total = 0
    mismatches = 0
    flips = 0
    for e in events:
        sd = e.get("signal_divergence", {})
        if not sd:
            continue
        total += 1
        if not sd.get("match", True):
            mismatches += 1
            if sd.get("flip_reason") == "direction_flip":
                flips += 1
    return total, mismatches, flips


def _extract_pnl_diffs(events: list) -> list:
    diffs = []
    for e in events:
        pnl = e.get("pnl_decomposition", {})
        if pnl.get("original_pnl") is not None and pnl.get("computed_pnl") is not None:
            diffs.append(abs(pnl["original_pnl"] - pnl["computed_pnl"]))
    return diffs


def _extract_regime_counts(events: list) -> dict:
    counts = Counter()
    for e in events:
        rc = e.get("regime_context", {})
        r = rc.get("volatility_regime")
        if r:
            counts[r] += 1
    return dict(counts)


def _extract_feature_drivers(events: list) -> list:
    all_features = []
    for e in events:
        fd = e.get("feature_drivers", [])
        all_features.append([f["feature"] for f in fd[:3]])
    return all_features


def _kl_divergence(p: list, q: list) -> float:
    p = np.array(p, dtype=np.float64)
    q = np.array(q, dtype=np.float64)
    if p.sum() == 0 or q.sum() == 0:
        return 0.0
    p = p / p.sum()
    q = q / q.sum()
    # Avoid NaN from log(0/0) when both are zero; KL only sums over
    # bins where p > 0 (convention: 0 * log(0/q) = 0).
    mask = p > 0
    q_safe = np.maximum(q, 1e-10)
    return float(np.sum(p[mask] * np.log(p[mask] / q_safe[mask])))


def _histogram(values: list, bins: int = 10, low: float = 0.0, high: float = 1.0) -> list:
    if not values:
        return [0.0] * bins
    hist, _ = np.histogram(values, bins=bins, range=(low, high))
    return hist.astype(np.float64).tolist()


def _jaccard_similarity(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compute_model_drift(
    asset: str,
    baseline: dict | None = None,
    window_days: int = 30,
) -> dict:
    events = read_events(asset, days=window_days)
    if not events:
        return {"score": 0.0, "kl_divergence": 0.0, "event_count": 0, "status": "insufficient_data"}

    short, neutral, long_ = _extract_probas(events)
    if not short:
        return {"score": 0.0, "kl_divergence": 0.0, "event_count": 0, "status": "insufficient_data"}

    if baseline is None:
        baseline = {}

    current_hist = np.array(
        [
            _histogram(short),
            _histogram(neutral),
            _histogram(long_),
        ]
    )

    baseline_proba = baseline.get("model_proba_distribution", {})
    baseline_hist = np.array(
        [
            _histogram(baseline_proba.get("short", [])),
            _histogram(baseline_proba.get("neutral", [])),
            _histogram(baseline_proba.get("long", [])),
        ]
    )

    if baseline_hist.sum() == 0:
        return {"score": 0.0, "kl_divergence": 0.0, "event_count": len(short), "status": "no_baseline"}

    kl_scores = [_kl_divergence(current_hist[i].tolist(), baseline_hist[i].tolist()) for i in range(3)]
    avg_kl = sum(kl_scores) / 3.0

    score = min(avg_kl / 0.5, 1.0)

    return {
        "score": round(score, 4),
        "kl_divergence_short": round(kl_scores[0], 4),
        "kl_divergence_neutral": round(kl_scores[1], 4),
        "kl_divergence_long": round(kl_scores[2], 4),
        "average_kl": round(avg_kl, 4),
        "event_count": len(short),
        "status": "ok",
    }


def compute_signal_drift(
    asset: str,
    baseline: dict | None = None,
    window_days: int = 30,
) -> dict:
    events = read_events(asset, days=window_days)
    total, mismatches, flips = _extract_signal_mismatches(events)

    if total == 0:
        return {"score": 0.0, "mismatch_rate": 0.0, "event_count": 0, "status": "insufficient_data"}

    mismatch_rate = mismatches / total
    flip_rate = flips / total

    if baseline is None:
        baseline = {}

    baseline_sig = baseline.get("signal_distribution", {})
    if not baseline_sig:
        return {
            "score": 0.0,
            "mismatch_rate": round(mismatch_rate, 4),
            "flip_rate": round(flip_rate, 4),
            "baseline_mismatch_rate": 0.0,
            "total_signals": total,
            "mismatches": mismatches,
            "status": "no_baseline",
        }

    baseline_mismatch = baseline_sig.get("mismatch_rate", 0.0)
    score = min(mismatch_rate / baseline_mismatch, 1.0) if baseline_mismatch > 0 else 0.0

    return {
        "score": round(score, 4),
        "mismatch_rate": round(mismatch_rate, 4),
        "flip_rate": round(flip_rate, 4),
        "baseline_mismatch_rate": round(baseline_mismatch, 4),
        "total_signals": total,
        "mismatches": mismatches,
        "status": "ok",
    }


def compute_pnl_drift(
    asset: str,
    baseline: dict | None = None,
    window_days: int = 30,
) -> dict:
    events = read_events(asset, days=window_days)
    diffs = _extract_pnl_diffs(events)

    if len(diffs) < 3:
        return {"score": 0.0, "mae": 0.0, "event_count": len(diffs), "status": "insufficient_data"}

    mae = float(np.mean(diffs))
    rmse = float(np.sqrt(np.mean(np.array(diffs) ** 2)))

    baseline_pnl = baseline.get("pnl_mismatch_stats", {}) if baseline else {}
    if not baseline_pnl:
        return {
            "score": 0.0,
            "mae": round(mae, 10),
            "rmse": round(rmse, 10),
            "baseline_mae": 0.0,
            "event_count": len(diffs),
            "status": "no_baseline",
        }

    baseline_mae = baseline_pnl.get("mean_abs_error", 0.0)
    score = min(mae / baseline_mae, 1.0) if baseline_mae > 0 else 0.0

    return {
        "score": round(score, 4),
        "mae": round(mae, 10),
        "rmse": round(rmse, 10),
        "baseline_mae": round(baseline_mae, 10),
        "event_count": len(diffs),
        "status": "ok",
    }


def compute_feature_stability(
    asset: str,
    window_days: int = 30,
) -> dict:
    events = read_events(asset, days=window_days)
    drivers = _extract_feature_drivers(events)

    if len(drivers) < 5:
        return {"score": 0.0, "event_count": len(drivers), "status": "insufficient_data"}

    similarities = []
    for i in range(1, len(drivers)):
        sim = _jaccard_similarity(set(drivers[i - 1]), set(drivers[i]))
        similarities.append(sim)

    mean_sim = float(np.mean(similarities)) if similarities else 1.0
    score = round(1.0 - mean_sim, 4)

    top_features = Counter()
    for driver_set in drivers:
        for f in driver_set:
            top_features[f] += 1
    most_stable = top_features.most_common(5)

    return {
        "score": score,
        "mean_jaccard_similarity": round(mean_sim, 4),
        "top_features": [{"feature": f, "appearances": c} for f, c in most_stable],
        "event_count": len(drivers),
        "status": "ok",
    }


def compute_regime_consistency(
    asset: str,
    baseline: dict | None = None,
    window_days: int = 30,
) -> dict:
    events = read_events(asset, days=window_days)
    current_counts = _extract_regime_counts(events)

    total_current = sum(current_counts.values())
    if total_current == 0:
        return {"score": 0.0, "event_count": 0, "status": "insufficient_data"}

    baseline_counts = baseline.get("regime_distribution", {}) if baseline else {}
    total_baseline = sum(baseline_counts.values()) or 1

    all_regimes = set(list(current_counts.keys()) + list(baseline_counts.keys()))
    diff_sum = 0.0
    for r in all_regimes:
        cur_prop = current_counts.get(r, 0) / total_current
        base_prop = baseline_counts.get(r, 0) / total_baseline
        diff_sum += abs(cur_prop - base_prop)

    consistency_score = round(diff_sum / 2.0, 4)

    mode_current = max(current_counts, key=current_counts.get) if current_counts else "unknown"
    mode_baseline = max(baseline_counts, key=baseline_counts.get) if baseline_counts else "unknown"
    mode_match = mode_current == mode_baseline

    return {
        "score": consistency_score,
        "regime_mode_current": mode_current,
        "regime_mode_baseline": mode_baseline,
        "mode_match": mode_match,
        "current_distribution": current_counts,
        "event_count": total_current,
        "status": "ok",
    }


def get_shadow_intelligence(
    asset: str,
    baseline: dict | None = None,
) -> dict:
    if baseline is None:
        baseline = load_baseline(asset) or {}

    model = compute_model_drift(asset, baseline, window_days=30)
    signal = compute_signal_drift(asset, baseline, window_days=30)
    pnl = compute_pnl_drift(asset, baseline, window_days=30)
    feature = compute_feature_stability(asset, window_days=30)
    regime = compute_regime_consistency(asset, baseline, window_days=30)

    scores = {
        "model_drift": model.get("score", 0.0),
        "signal_drift": signal.get("score", 0.0),
        "pnl_drift": pnl.get("score", 0.0),
        "feature_stability": feature.get("score", 0.0),
        "regime_consistency": regime.get("score", 0.0),
    }

    mean_score = np.mean(list(scores.values())) if scores else 0.0

    if mean_score < 0.2:
        trend = "stable"
        risk_flag = "low"
    elif mean_score < 0.5:
        trend = "degrading"
        risk_flag = "medium"
    else:
        trend = "degrading"
        risk_flag = "high"

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_sources = [s[0] for s in sorted_scores[:3] if s[1] > 0.1]

    baseline_dist = round(
        abs(baseline.get("event_count", 0) - len(read_events(asset, days=30))) / (baseline.get("event_count", 1) + 1), 4
    )

    return {
        "asset": asset,
        "drift_scores": scores,
        "trend": trend,
        "risk_flag": risk_flag,
        "top_drift_sources": top_sources,
        "baseline_distance": baseline_dist,
        "details": {
            "model": model,
            "signal": signal,
            "pnl": pnl,
            "feature": feature,
            "regime": regime,
        },
    }
