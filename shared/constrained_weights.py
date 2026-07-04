"""Factor-constrained weight computation — extracted from shared/factor_model.py

Breaks the circular import between ``shared/portfolio_weights.py`` and
``shared/factor_model.py`` by providing a dedicated module that both can
import without referencing each other.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.constrained_weights")

from shared.factor_model import (
    DEFAULT_FACTOR_LIMITS,
    FACTOR_GROUPS,
    compute_factor_exposures,
    factor_exposure_penalty,
)


# ── Last-valid-weights cache for optimizer fallback ──
_last_valid_weights: dict[str, dict[str, float]] = {}
_WEIGHTS_CACHE_LOCK = threading.Lock()


def factor_constrained_weights(
    returns: pd.DataFrame,
    limits: dict[str, tuple[float, float]] | None = None,
    risk_parity_weight: float = 0.7,
    penalty_scale: float = 10.0,
) -> dict[str, float]:
    """Compute weights with factor exposure constraints (v1 — penalty method).

    Uses a two-stage approach:
    1. Compute base risk parity weights
    2. Apply factor exposure penalty to constrain optimization

    This is a simple penalized approach rather than constrained optimization,
    making it numerically stable and compatible with the existing risk parity.

    Args:
        returns: DataFrame of asset returns
        limits: Factor exposure limits
        risk_parity_weight: Weight on risk parity objective (vs penalty)
        penalty_scale: Scale for exposure penalty

    Returns:
        {asset: weight} dict with factor constraints (may still violate limits)
    """
    if limits is None:
        limits = DEFAULT_FACTOR_LIMITS

    from shared.portfolio_weights import compute_weights

    base_wv = compute_weights("risk_parity_v1", returns)
    base = base_wv.weights
    assets_list = list(base.keys())
    n = len(assets_list)

    if n == 0:
        return {}
    if n == 1:
        return base

    base_array = np.array([base[a] for a in assets_list])

    from scipy.optimize import minimize

    def objective(w):
        w = np.asarray(w, dtype=float)
        w = w / (w.sum() + 1e-12)

        cov = returns[assets_list].cov().values * 252
        port_var = w @ cov @ w
        mrc = np.ones(n) / n if port_var <= 0 else w * (cov @ w) / np.sqrt(port_var)
        rc_var = np.var(mrc)

        weights_dict = dict(zip(assets_list, w))
        penalty = factor_exposure_penalty(weights_dict, limits, penalty_scale)

        return risk_parity_weight * rc_var + (1 - risk_parity_weight) * penalty

    x0 = base_array.copy()
    bounds = [(0.0, 1.0)] * n
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    result = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 500})

    if result.success:
        final = result.x / result.x.sum()
        out = dict(zip(assets_list, [round(float(w), 6) for w in final]))
        with _WEIGHTS_CACHE_LOCK:
            _last_valid_weights["v1"] = out
        return out
    else:
        with _WEIGHTS_CACHE_LOCK:
            fallback = _last_valid_weights.get("v1", base)
        logger.critical(
            "factor_constrained_weights (v1) optimizer FAILED — returning %s weights",
            "last valid" if fallback is not base else "unconstrained base",
        )
        return fallback


def factor_constrained_weights_v2(
    returns: pd.DataFrame,
    limits: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Compute weights with hard factor exposure constraints.

    Unlike v1 (penalty method), this uses direct linear inequality constraints
    in the optimizer, guaranteeing constraint satisfaction when the optimizer
    converges.  If no constraints are violated by the base risk parity weights,
    they are returned unchanged.

    The objective is pure risk parity (equal risk contribution).  Factor limits
    are enforced as ``A @ w <= b``, where each row of A is a one-hot factor
    group membership vector.

    Args:
        returns: DataFrame of asset returns
        limits: Factor exposure limits (defaults to DEFAULT_FACTOR_LIMITS)

    Returns:
        {asset: weight} dict with factor constraints enforced.
    """
    if limits is None:
        limits = DEFAULT_FACTOR_LIMITS

    from shared.portfolio_weights import compute_weights

    base_wv = compute_weights("risk_parity_v1", returns)
    base = base_wv.weights
    assets_list = list(base.keys())
    n = len(assets_list)

    if n == 0:
        return {}
    if n == 1:
        return base

    base_exposures = compute_factor_exposures(base)
    has_violation = any(
        base_exposures.get(f, 0) < lo or base_exposures.get(f, 0) > hi
        for f, (lo, hi) in limits.items()
        if f in FACTOR_GROUPS
    )
    if not has_violation:
        return base

    x0 = np.array([base[a] for a in assets_list], dtype=float)
    bounds = [(0.0, 1.0)] * n
    cons: list[dict] = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    for factor, (lo, hi) in limits.items():
        if factor not in FACTOR_GROUPS:
            continue
        mask = np.array([1.0 if a in FACTOR_GROUPS[factor] else 0.0 for a in assets_list])
        if mask.sum() == 0:
            continue
        if lo > -np.inf:
            cons.append({"type": "ineq", "fun": lambda w, m=mask, low=lo: (w @ m) - low})
        if hi < np.inf:
            cons.append({"type": "ineq", "fun": lambda w, m=mask, high=hi: high - (w @ m)})

    cov = returns[assets_list].cov().values * 252

    def objective(w):
        w = np.asarray(w, dtype=float)
        w = w / (w.sum() + 1e-12)
        port_var = w @ cov @ w
        mrc = np.full(n, 1.0 / n) if port_var <= 0 else w * (cov @ w) / np.sqrt(port_var)
        return float(np.var(mrc))

    from scipy.optimize import minimize

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 2000, "ftol": 1e-12},
    )

    if result.success:
        final = result.x / max(result.x.sum(), 1e-12)
        out = dict(zip(assets_list, [round(float(w), 6) for w in final]))
        with _WEIGHTS_CACHE_LOCK:
            _last_valid_weights["v2"] = out
        return out
    else:
        with _WEIGHTS_CACHE_LOCK:
            fallback = _last_valid_weights.get("v2", base)
        logger.critical(
            "factor_constrained_weights_v2 optimizer FAILED — returning %s weights",
            "last valid" if fallback is not base else "unconstrained base",
        )
        return fallback
