from abc import ABC, abstractmethod
from typing import Optional, Dict

import numpy as np
import pandas as pd
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


class PositionSizingStrategy(ABC):
    @abstractmethod
    def compute(self, close: pd.Series, config: dict) -> float:
        ...


class VolTargetSizing(PositionSizingStrategy):
    def __init__(self, window: int = 30, target_vol: float = 0.30, regime_aware: bool = False):
        self.window = window
        self.target_vol = target_vol
        self.regime_aware = regime_aware

    def compute(self, close: pd.Series, config: dict, regime: str = "neutral") -> float:
        if not config.get("vol_scalar"):
            return 1.0
        
        target = self.target_vol
        if self.regime_aware:
            # CALM/range expands target; CRISIS/volatile contracts (plan aliases included)
            multipliers = {
                "range": 1.2,
                "calm": 1.2,
                "trend": 1.0,
                "volatile": 0.5,
                "crisis": 0.5,
                "neutral": 1.0,
            }
            target *= multipliers.get(str(regime).lower(), 1.0)
            
        rets = close.pct_change().dropna()
        if len(rets) < self.window:
            return 1.0
        rv = rets.iloc[-self.window:].std() * np.sqrt(252)
        if pd.isna(rv) or np.isinf(rv):
            return 1.0
        vol_baseline = config.get("vol_baseline")
        if vol_baseline is not None and vol_baseline > 0:
            rv = max(rv, float(vol_baseline))
        scalar = target / (rv + 1e-9)
        impact_bps = config.get("impact_bps")
        if impact_bps is not None:
            scalar *= self.edge_decay(float(impact_bps))
        return min(scalar, 1.0)

    def edge_decay(self, impact_bps: float, threshold_bps: float = 5.0) -> float:
        """Scales down position size when estimated impact exceeds a threshold."""
        if impact_bps > threshold_bps:
            return 0.5
        return 1.0
