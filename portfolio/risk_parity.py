import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from scipy.optimize import minimize


def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    portfolio_var = weights @ cov @ weights
    marginal_risk = cov @ weights
    risk_contrib = weights * marginal_risk / np.sqrt(portfolio_var)
    return risk_contrib


def risk_parity_weights(cov: np.ndarray, target_risk: Optional[np.ndarray] = None) -> np.ndarray:
    n = cov.shape[0]
    if target_risk is None:
        target_risk = np.ones(n) / n

    def objective(w):
        w = np.clip(w, 0, 1)
        w = w / w.sum()
        rc = risk_contribution(w, cov)
        return np.sum((rc - target_risk * rc.sum()) ** 2)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0) for _ in range(n)]
    result = minimize(objective, np.ones(n) / n, bounds=bounds, constraints=constraints, method="SLSQP")
    return result.x / result.x.sum()


def compute_equal_risk_weights(returns: pd.DataFrame, target_risk: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    cov = returns.cov() * 252
    assets = returns.columns.tolist()
    w = risk_parity_weights(cov.values)
    return dict(zip(assets, w))


def compute_risk_parity_portfolio(
    returns: pd.DataFrame,
    target_vol: float = 0.15,
    max_leverage: float = 1.0,
) -> Dict[str, float]:
    cov = returns.cov() * 252
    assets = returns.columns.tolist()
    raw_weights = risk_parity_weights(cov.values)
    portfolio_var = raw_weights @ cov.values @ raw_weights
    portfolio_vol = np.sqrt(portfolio_var)
    leverage = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
    leverage = min(leverage, max_leverage)
    scaled = raw_weights * leverage
    return dict(zip(assets, scaled))
