"""Adversarial manifold evaluation — stress-tests model stability under synthetic perturbations."""

import numpy as np
import pandas as pd

PERTURBATIONS = {
    "volatility_shock": {"type": "volatility", "kind": "shock"},
    "volatility_compression": {"type": "volatility", "kind": "compression"},
    "volatility_noise": {"type": "volatility", "kind": "noise"},
    "correlation_decouple": {"type": "correlation", "kind": "decouple"},
    "correlation_inversion": {"type": "correlation", "kind": "inversion"},
    "correlation_break": {"type": "correlation", "kind": "break"},
    "trend_flip": {"type": "trend", "kind": "flip"},
    "trend_burst": {"type": "trend", "kind": "burst"},
    "trend_decay": {"type": "trend", "kind": "decay"},
    "noise_inject": {"type": "noise", "kind": "inject"},
    "noise_spike": {"type": "noise", "kind": "spike"},
    "noise_dropout": {"type": "noise", "kind": "dropout"},
}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _safe(value, default=0.0):
    """Return value if not None, else default."""
    return value if value is not None else default


def _clip01(value):
    """Clip value to [0, 1]."""
    return max(0.0, min(1.0, value))


def _entropy(proba):
    """Compute entropy from probability array (n, 3)."""
    # Clip to avoid log(0)
    p = np.clip(proba, 1e-12, 1.0)
    h = -np.sum(p * np.log(p), axis=1)
    return float(np.mean(h))


# ──────────────────────────────────────────────
# Perturbation functions
# ──────────────────────────────────────────────


def _perturb_volatility(x, kind):
    """Apply volatility perturbation to features."""
    n, m = x.shape
    result = x.copy()

    if kind == "shock":
        # Amplify variance
        result = result * (1.5 + np.random.randn(m) * 0.2)
    elif kind == "compression":
        # Reduce variance
        result = result * (0.5 + np.random.rand(m) * 0.3)
    elif kind == "noise":
        # Add noise
        std_vals = result.std(axis=0).values
        noise = np.random.randn(n, m) * 0.3 * std_vals
        result = result + noise
    else:
        # Fallback: mild shock
        result = result * 1.1

    return result


def _perturb_correlation(x, kind):
    """Apply correlation perturbation to features."""
    n, m = x.shape
    result = x.copy()

    if kind == "decouple":
        # Shuffle each column independently
        for col in range(m):
            np.random.shuffle(result.iloc[:, col].values)
    elif kind == "inversion":
        # Invert sign of one column
        if m >= 2:
            result.iloc[:, 0] = -result.iloc[:, 0]
    elif kind == "break":
        # Add orthogonal noise to break correlations
        std_vals = result.std(axis=0).values
        noise = np.random.randn(n, m) * std_vals
        result = result * 0.7 + noise * 0.3
    else:
        result = result * 1.0

    return result


def _perturb_trend(x, kind):
    """Apply trend perturbation to features."""
    result = x.copy()

    if kind == "flip":
        # Flip sign of momentum-like columns
        momentum_cols = [c for c in result.columns if "mom" in c.lower()]
        for col in momentum_cols:
            result[col] = -result[col]
        # Also flip other columns
        result = -result
    elif kind == "burst":
        # Amplify momentum features
        for col in result.columns:
            if "mom" in col.lower() or "vs_" in col.lower():
                result[col] = result[col] * 3.0
    elif kind == "decay":
        # Dampen momentum features
        for col in result.columns:
            if "mom" in col.lower():
                result[col] = result[col] * 0.3
    else:
        result = result * 1.0

    return result


def _perturb_noise(x, kind):
    """Apply noise perturbation to features."""
    n, m = x.shape
    result = x.copy()

    if kind == "inject":
        # Inject uniform noise
        std_vals = result.std(axis=0).values
        noise = np.random.uniform(-1, 1, (n, m)) * std_vals
        result = result + noise
    elif kind == "spike":
        # Add spike to random positions
        spike_mask = np.random.random((n, m)) < 0.05
        vals = result.values.copy()
        vals[spike_mask] = vals[spike_mask] * 5.0
        result = pd.DataFrame(vals, index=result.index, columns=result.columns)
    elif kind == "dropout":
        # Set random positions to 0
        dropout_mask = np.random.random((n, m)) < 0.1
        vals = result.values.copy()
        vals[dropout_mask] = 0.0
        result = pd.DataFrame(vals, index=result.index, columns=result.columns)
    else:
        result = result * 1.0

    return result


# ──────────────────────────────────────────────
# Core evaluation
# ──────────────────────────────────────────────


def _compute_regime_score(model, x_orig, x_pert, close, baseline_proba):
    """Compute a score [0,1] comparing perturbed output to baseline.

    Higher score = more stable (less affected by perturbation).
    """
    try:
        pert_proba = model.predict_proba(x_pert)
    except Exception:
        return 0.0

    n = len(x_orig)
    # Compare probability distributions
    kl_divs = []
    for i in range(n):
        # Simple diff-based divergence (avoid log(0) issues)
        diff = np.sum(np.abs(pert_proba[i] - baseline_proba[i]))
        kl_divs.append(diff)

    # Baselines: original vs original should give near-zero diffs
    baseline_diffs = []
    for i in range(n):
        diff = np.sum(np.abs(baseline_proba[i] - baseline_proba[i]))
        baseline_diffs.append(diff)
    baseline_mean = np.mean(baseline_diffs)

    pert_mean = np.mean(kl_divs)
    # Score: 1 - (pert_mean - baseline_mean) clipped to [0, 1]
    if pert_mean <= baseline_mean:
        return 1.0
    score = 1.0 - min(pert_mean - baseline_mean, 1.0)
    return _clip01(score)


def evaluate_adversarial_manifold(asset, model, x, close, threshold=0.45, predict_fn=None):
    """Run adversarial manifold evaluation on a model.

    Applies 12 synthetic perturbations (volatility, correlation, trend, noise)
    and scores the model's prediction stability under each. Produces a
    Composite Model Stability Score (CMSS) and stability classification.

    Args:
        asset: Asset name (passed through to result dict).
        model: Fitted model with ``predict_proba``.
        x: Feature DataFrame of shape (n_samples, n_features).
        close: Close price Series (length n_samples), used for regime scoring.
        threshold: Confidence threshold for signal classification (unused internally;
            passed through for compatibility).
        predict_fn: Optional custom prediction function ``fn(model, x)``.

    Returns:
        dict with keys:
            - asset: Asset name.
            - cmss: Composite Model Stability Score [0, 1].
            - max_regime_drop: Worst-case score drop under perturbation.
            - attractor_drift: Variance of perturbation scores.
            - stability_class: "ROBUST" (cmss >= 0.7), "MODERATE" (>= 0.5), or "BRITTLE".
            - regime_scores: Per-perturbation dict of stability scores.
            - normal_score: Baseline (unperturbed) stability score.
    """
    # Baseline predictions
    baseline_proba = (
        predict_fn(model, x) if predict_fn is not None else model.predict_proba(x)
    )

    regime_scores = {}
    normal_score = _compute_regime_score(model, x, x, close, baseline_proba)

    for name, perturb_info in PERTURBATIONS.items():
        perturb_type = perturb_info["type"]
        kind = perturb_info["kind"]

        if perturb_type == "volatility":
            x_pert = _perturb_volatility(x, kind)
        elif perturb_type == "correlation":
            x_pert = _perturb_correlation(x, kind)
        elif perturb_type == "trend":
            x_pert = _perturb_trend(x, kind)
        elif perturb_type == "noise":
            x_pert = _perturb_noise(x, kind)
        else:
            continue

        score = _compute_regime_score(model, x, x_pert, close, baseline_proba)
        regime_scores[name] = score

    # Composite Model Stability Score (CMSS)
    all_scores = [normal_score] + list(regime_scores.values())
    cmss = float(np.mean(all_scores))

    # Max regime drop
    min_regime_score = min(regime_scores.values()) if regime_scores else normal_score
    max_regime_drop = normal_score - min_regime_score

    # Attractor drift: variance of regime scores
    attractor_drift = float(np.var(list(regime_scores.values()))) if regime_scores else 0.0

    # Stability class
    if cmss >= 0.7:
        stability_class = "ROBUST"
    elif cmss >= 0.5:
        stability_class = "MODERATE"
    else:
        stability_class = "BRITTLE"

    result = {
        "asset": asset,
        "cmss": round(cmss, 4),
        "max_regime_drop": round(max_regime_drop, 4),
        "attractor_drift": round(attractor_drift, 4),
        "stability_class": stability_class,
        "regime_scores": regime_scores,
        "normal_score": normal_score,
    }

    return result
