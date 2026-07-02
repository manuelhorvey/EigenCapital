from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    port_variance = weights @ cov @ weights
    marginal_risk = cov @ weights
    risk_contrib = weights * marginal_risk / port_variance
    return risk_contrib


def risk_parity_weights(cov: np.ndarray, target_risk: np.ndarray | None = None) -> np.ndarray:
    n = cov.shape[0]

    def _risk_parity_objective(w: np.ndarray, *args) -> float:
        cov_m = args[0]
        rc = risk_contribution(w, cov_m)
        target = target_risk if target_risk is not None else np.ones(n) / n
        return np.sum((rc - target) ** 2)

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0)] * n
    x0 = np.array([1.0 / n] * n)
    result = minimize(_risk_parity_objective, x0, args=(cov,), method="SLSQP", bounds=bounds, constraints=constraints)
    return result.x if result.success else x0


def compute_equal_risk_weights(returns: pd.DataFrame, target_risk: dict[str, float] | None = None) -> dict[str, float]:
    cov = returns.cov().values
    w = risk_parity_weights(cov)
    return {col: float(w[i]) for i, col in enumerate(returns.columns)}


def calculate_position_size(
    close: pd.Series,
    config: dict,
    target_vol: float = 0.3,
    window: int = 30,
    regime: str = "neutral",
    regime_aware: bool = False,
) -> float:
    rets = close.pct_change().dropna()
    if len(rets) < window:
        window = max(len(rets), 2)
    hist_vol = rets.tail(window).std() * np.sqrt(252)
    if hist_vol <= 0:
        return config.get("position_size", 0.95)

    scalar = target_vol / hist_vol
    max_size = config.get("position_size", 0.95)
    size = min(scalar, max_size)

    if regime_aware:
        regime_mult = {"bull": 1.1, "bear": 0.8, "neutral": 1.0, "crisis": 0.5}
        size *= regime_mult.get(regime, 1.0)

    impact_bps = _edge_decay(size / max_size * 100)
    size *= impact_bps
    return min(max(size, 0.0), max_size)


def _edge_decay(impact_bps: float, threshold_bps: float = 5.0) -> float:
    if impact_bps <= threshold_bps:
        return 1.0
    return max(1.0 - (impact_bps - threshold_bps) * 0.02, 0.5)
