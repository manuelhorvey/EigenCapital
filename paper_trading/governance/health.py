import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from paper_trading.governance.drift import get_shadow_intelligence
from paper_trading.state_store import StateStore

logger = logging.getLogger("eigencapital.health_monitor")

_lock = threading.Lock()
_cache: dict = {}

WEIGHTS = {
    "validity": 0.25,
    "drift": 0.20,
    "pnl_stability": 0.20,
    "shadow_agreement": 0.15,
    "stress_robustness": 0.20,
}

COMPONENT_SOURCES = {
    "validity": "state_machine",
    "drift": "drift_scoring",
    "pnl_stability": "drift_scoring",
    "shadow_agreement": "shadow_memory",
    "stress_robustness": "adversarial_manifold",
}

BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)

_STATE_STORE: StateStore | None = None
_ENGINE: object | None = None


def register_engine(engine: object) -> None:
    """Register the live engine instance so compute_all reads directly
    from engine assets instead of the state store file."""
    global _ENGINE
    _ENGINE = engine


def register_state_store(store: StateStore | None) -> None:
    """Register a StateStore instance for use when the live engine is not available.

    Must be called before ``_get_state_store()``. Pass ``None`` to clear.
    Unlike the old lazy-singleton pattern, this no longer creates an
    independent StateStore on first use — the caller must provide one.
    """
    global _STATE_STORE
    _STATE_STORE = store


def _get_state_store() -> StateStore | None:
    """Return the registered StateStore, or None if not set.

    Callers must handle None (e.g., by injecting from the server context).
    """
    return _STATE_STORE


def _load_state_assets() -> dict:
    # Live engine path — no file round-trip, always current.
    if _ENGINE is not None:
        try:
            state = _ENGINE.get_state()
            assets = state.get("assets", {})
            if assets:
                return assets
        except (AttributeError, TypeError, ValueError, KeyError):
            logger.warning("Failed to load engine state from live engine", exc_info=True)
    # Fallback: state store snapshot
    store = _get_state_store()
    if store is not None:
        try:
            snapshot = store.load_snapshot()
            if snapshot is not None and snapshot.assets:
                return snapshot.assets
        except (AttributeError, OSError, TypeError, ValueError):
            logger.warning("Failed to load snapshot from state store", exc_info=True)
    return {}


def _load_cmss(asset: str) -> float | None:
    path = os.path.join(BASE_DIR, "sandbox", asset, "manifold_adversarial.json")
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            return data.get("cmss")
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Failed to load CMSS for %s", asset, exc_info=True)
    return None


def _get_validity_score(validity_state: str) -> float:
    mapping = {
        "GREEN": 1.0,
        "YELLOW": 0.75,
        "RED": 0.0,
    }
    return mapping.get(validity_state, 0.75)


def _compute_drift_health(drift_scores: dict) -> float:
    dims = [
        drift_scores.get("model_drift", 0.0),
        drift_scores.get("signal_drift", 0.0),
        drift_scores.get("feature_stability", 0.0),
        drift_scores.get("regime_consistency", 0.0),
    ]
    avg_drift = np.mean(dims) if dims else 0.0
    return 1.0 - avg_drift


def _compute_pnl_health(drift_scores: dict) -> float:
    pnl_drift = drift_scores.get("pnl_drift", 0.0)
    return 1.0 - pnl_drift


def _compute_shadow_agreement(drift_scores: dict, intelligence: dict) -> float:
    details = intelligence.get("details", {})
    signal_data = details.get("signal", {})
    mismatch_rate = signal_data.get("mismatch_rate", 0.0)

    model_data = details.get("model", {})
    kl_score = model_data.get("average_kl", 0.0)

    effective_drift = max(mismatch_rate, min(kl_score * 2, 1.0))
    return 1.0 - effective_drift


def compute(asset: str, assets: dict | None = None) -> dict:
    try:
        if assets is None:
            assets = _load_state_assets()
        asset_data = assets.get(asset, {})
        validity_state = asset_data.get("validity_state", "YELLOW")

        intelligence = get_shadow_intelligence(asset)
        drift_scores = intelligence.get("drift_scores", {})

        validity_score = _get_validity_score(validity_state)
        drift_health = _compute_drift_health(drift_scores)
        pnl_health = _compute_pnl_health(drift_scores)
        shadow_agreement = _compute_shadow_agreement(drift_scores, intelligence)

        cmss = _load_cmss(asset)
        stress_robustness = cmss if cmss is not None else max(drift_health, 0.5)

        components = {
            "validity": round(validity_score, 4),
            "drift": round(drift_health, 4),
            "pnl_stability": round(pnl_health, 4),
            "shadow_agreement": round(shadow_agreement, 4),
            "stress_robustness": round(stress_robustness, 4),
        }

        health_score = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)

        if health_score >= 0.80:
            health_label = "HEALTHY"
            health_color = "green"
        elif health_score >= 0.55:
            health_label = "DEGRADED"
            health_color = "amber"
        else:
            health_label = "CRITICAL"
            health_color = "red"

        limiting = sorted(
            [(k, v) for k, v in components.items()],
            key=lambda x: x[1],
        )[:2]

        result = {
            "asset": asset,
            "health_score": round(health_score, 4),
            "health_label": health_label,
            "health_color": health_color,
            "components": components,
            "weights": WEIGHTS,
            "limiting_factors": [{"component": k, "score": v} for k, v in limiting if v < 0.75],
            "drift_scores": {k: round(v, 4) for k, v in drift_scores.items()},
            "validity_state": validity_state,
            "stress_robustness_source": "adversarial_manifold" if cmss is not None else "estimated",
        }

        with _lock:
            _cache[asset] = result

        return result
    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        logger.exception("Health computation failed for %s", asset)
        return _fallback(asset)


def get_latest(asset: str | None = None):
    with _lock:
        if asset:
            return _cache.get(asset)
        return dict(_cache)


def compute_all() -> dict:
    all_assets = _load_state_assets()
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=min(len(all_assets) or 1, 8)) as pool:
        future_map = {pool.submit(compute, name, all_assets): name for name in all_assets}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
            except (KeyError, ValueError, TypeError, AttributeError):
                logger.exception("Health computation thread failed for %s", name)
                results[name] = _fallback(name)

    if results:
        mean_health = np.mean([r["health_score"] for r in results.values()])
        min_asset = min(results, key=lambda a: results[a]["health_score"])
        max_asset = max(results, key=lambda a: results[a]["health_score"])
    else:
        mean_health = 0.0
        min_asset = None
        max_asset = None

    return {
        "assets": results,
        "system_health": {
            "mean_health_score": round(float(mean_health), 4),
            "n_assets": len(results),
            "healthiest_asset": max_asset,
            "weakest_asset": min_asset,
            "n_healthy": sum(1 for r in results.values() if r["health_label"] == "HEALTHY"),
            "n_degraded": sum(1 for r in results.values() if r["health_label"] == "DEGRADED"),
            "n_critical": sum(1 for r in results.values() if r["health_label"] == "CRITICAL"),
        },
    }


def _fallback(asset: str) -> dict:
    return {
        "asset": asset,
        "health_score": 0.5,
        "health_label": "UNKNOWN",
        "health_color": "grey",
        "components": {k: 0.5 for k in WEIGHTS},
        "weights": WEIGHTS,
        "limiting_factors": [],
        "drift_scores": {},
        "validity_state": "YELLOW",
        "stress_robustness_source": "fallback",
        "error": "Health score unavailable — defaulting to neutral",
    }
