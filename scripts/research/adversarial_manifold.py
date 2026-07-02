import json
import logging
import os
from collections.abc import Callable
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.adversarial_manifold")

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sandbox")


def _safe(val, default=0.0):
    return val if val is not None else default


def _clip01(v):
    return max(0.0, min(1.0, v))


def _entropy(proba: np.ndarray) -> float:
    probs = proba / (proba.sum(axis=1, keepdims=True) + 1e-12)
    return float(np.mean(-np.sum(probs * np.log(probs + 1e-12), axis=1)))


def _perturb_volatility(X: pd.DataFrame, method: str = "shock") -> pd.DataFrame:
    X_p = X.copy()
    n = len(X_p)
    if method == "shock":
        scale = 1.0 + 3.0 * np.random.rand()
        start = np.random.randint(0, max(n // 2, 1))
        end = min(start + np.random.randint(max(n // 5, 2), max(n // 3, 3)), n)
        X_p.iloc[start:end] *= scale
    elif method == "compression":
        scale = 0.3 + 0.2 * np.random.rand()
        start = np.random.randint(0, max(n // 2, 1))
        end = min(start + np.random.randint(max(n // 4, 2), max(n // 2, 3)), n)
        X_p.iloc[start:end] *= scale
    else:
        vol = np.abs(np.random.randn(n)) * 0.5 + 0.5
        for i in range(n):
            X_p.iloc[i] *= 1.0 + (vol[i] - 0.5)
    return X_p


def _perturb_correlation(X: pd.DataFrame, method: str = "decouple") -> pd.DataFrame:
    X_p = X.copy()
    n, m = X_p.shape
    if method == "decouple" and m >= 2:
        cols = np.random.choice(m, size=max(2, m // 3), replace=False)
        for c in cols:
            noise = np.random.randn(n) * X_p.iloc[:, c].std() * 1.5
            X_p.iloc[:, c] += noise
    elif method == "inversion":
        cols = np.random.choice(m, size=max(2, m // 3), replace=False)
        for i in range(0, len(cols) - 1, 2):
            c1, c2 = int(cols[i]), int(cols[i + 1])
            mean1, mean2 = X_p.iloc[:, c1].mean(), X_p.iloc[:, c2].mean()
            X_p.iloc[:, c1] = 2 * mean1 - X_p.iloc[:, c1]
            X_p.iloc[:, c2] = 2 * mean2 - X_p.iloc[:, c2]
    else:
        noise = np.random.randn(n, m) * X_p.std().values * 0.8
        X_p += noise
    return X_p


def _perturb_trend(X: pd.DataFrame, method: str = "flip") -> pd.DataFrame:
    X_p = X.copy()
    mom_cols = [c for c in X_p.columns if "_mom_" in c or "_vs_spy" in c]
    if not mom_cols:
        mom_cols = X_p.columns.tolist()
    if method == "flip":
        for c in mom_cols:
            X_p[c] = -X_p[c]
    elif method == "burst":
        n = len(X_p)
        start = np.random.randint(0, max(n // 2, 1))
        dur = np.random.randint(max(n // 10, 2), max(n // 5, 3))
        end = min(start + dur, n)
        for c in mom_cols:
            burst = np.random.randn() * X_p[c].std() * 2.0
            X_p.iloc[start:end] += burst
    else:
        decay = 0.995 ** np.arange(len(X_p))
        for c in mom_cols:
            X_p[c] *= decay
    return X_p


def _perturb_noise(X: pd.DataFrame, method: str = "inject") -> pd.DataFrame:
    X_p = X.copy()
    n, m = X_p.shape
    if method == "inject":
        noise_std = X_p.std().values * np.random.uniform(0.3, 0.8)
        noise = np.random.randn(n, m) * noise_std
        X_p += noise
    elif method == "spike":
        n_spikes = max(1, n // 20)
        for _ in range(n_spikes):
            idx = np.random.randint(n)
            col = np.random.randint(m)
            X_p.iloc[idx, col] *= np.random.choice([5.0, -5.0]) * np.random.uniform(0.5, 2.0)
    else:
        mask = np.random.rand(n, m) < 0.05
        X_p[mask] = np.nan
        X_p = X_p.ffill().bfill()
    return X_p


PERTURBATIONS = {
    "normal": None,
    "vol_shock": lambda X: _perturb_volatility(X, "shock"),
    "vol_compression": lambda X: _perturb_volatility(X, "compression"),
    "correlation_break": lambda X: _perturb_correlation(X, "decouple"),
    "correlation_inversion": lambda X: _perturb_correlation(X, "inversion"),
    "trend_flip": lambda X: _perturb_trend(X, "flip"),
    "trend_burst": lambda X: _perturb_trend(X, "burst"),
    "noise_inject": lambda X: _perturb_noise(X, "inject"),
    "noise_spike": lambda X: _perturb_noise(X, "spike"),
}


def _compute_regime_score(
    model,
    X_orig: pd.DataFrame,
    X_pert: pd.DataFrame,
    close: pd.Series,
    baseline_proba: np.ndarray,
    threshold: float = 0.45,
    predict_fn: Callable | None = None,
) -> float:
    if predict_fn is None:

        def predict_fn(m, x):
            return m.predict_proba(x)

    try:
        pert_proba = predict_fn(model, X_pert)
        n = len(pert_proba)
        base_sig = (baseline_proba[:, 2] > threshold).astype(int) * 2 + (baseline_proba[:, 0] > threshold).astype(
            int
        ) * 0
        base_sig = np.clip(base_sig, 0, 2)
        pert_sig = (pert_proba[:, 2] > threshold).astype(int) * 2 + (pert_proba[:, 0] > threshold).astype(int) * 0
        pert_sig = np.clip(pert_sig, 0, 2)
        signal_agreement = float((base_sig == pert_sig).mean())
        base_ent = _entropy(baseline_proba)
        pert_ent = _entropy(pert_proba)
        ent_drift = abs(pert_ent - base_ent) / (base_ent + 1e-12)
        base_conf = np.max(baseline_proba, axis=1).mean()
        pert_conf = np.max(pert_proba, axis=1).mean()
        conf_drift = abs(pert_conf - base_conf) / (base_conf + 1e-12)
        base_dist = np.bincount(np.argmax(baseline_proba, axis=1), minlength=3) / n
        pert_dist = np.bincount(np.argmax(pert_proba, axis=1), minlength=3) / n
        dist_shift = float(np.sum(np.abs(pert_dist - base_dist)) / 2)
        agreement_score = _clip01((signal_agreement - 0.5) / 0.5)
        ent_score = _clip01(1.0 - ent_drift * 5)
        conf_score = _clip01(1.0 - conf_drift * 10)
        dist_score = _clip01(1.0 - dist_shift * 2)
        return _clip01(0.4 * agreement_score + 0.2 * ent_score + 0.2 * conf_score + 0.2 * dist_score)
    except Exception as e:  # noqa: BLE001
        logger.error("regime_score failed: %s", e)
        return 0.0


def evaluate_adversarial_manifold(
    asset: str,
    model,
    X: pd.DataFrame,
    close: pd.Series,
    threshold: float = 0.45,
    predict_fn: Callable | None = None,
) -> dict:
    if predict_fn is None:

        def predict_fn(m, x):
            return m.predict_proba(x)

    np.random.seed(42)
    baseline_proba = predict_fn(model, X)
    regime_scores = {}
    for name, pert_fn in PERTURBATIONS.items():
        X_pert = X if pert_fn is None else pert_fn(X)
        score = float(_compute_regime_score(model, X, X_pert, close, baseline_proba, threshold, predict_fn))
        regime_scores[name] = round(score, 4)
    score_vals = list(regime_scores.values())
    normal_score = regime_scores.get("normal", 0.5)
    cmss = round(1.0 - float(np.var(score_vals)), 4)
    max_drop = round(normal_score - min(score_vals), 4)
    perturbed_scores = [v for k, v in regime_scores.items() if k != "normal"]
    attractor_drift = round(1.0 - float(np.mean(perturbed_scores)), 4) if perturbed_scores else 0.0
    if cmss >= 0.80:
        stab_class = "ROBUST"
    elif cmss >= 0.60:
        stab_class = "MODERATE"
    else:
        stab_class = "BRITTLE"
    result = {
        "asset": asset,
        "timestamp": datetime.now().isoformat(),
        "cmss": float(cmss),
        "max_regime_drop": float(max_drop),
        "attractor_drift": float(attractor_drift),
        "stability_class": stab_class,
        "regime_scores": {k: float(v) for k, v in regime_scores.items()},
        "normal_score": float(normal_score),
    }
    out_dir = os.path.join(BASE, asset)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "manifold_adversarial.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)
    return result
