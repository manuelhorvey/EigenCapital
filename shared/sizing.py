import typing
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    portfolio_var = weights @ cov @ weights
    marginal_risk = cov @ weights
    risk_contrib = weights * marginal_risk / np.sqrt(portfolio_var)
    return typing.cast(np.ndarray, risk_contrib)


# DEPRECATED: risk_parity_weights and compute_equal_risk_weights moved to
# shared/portfolio_weights.py. All new code should use:
#   from shared.portfolio_weights import compute_weights
# These will be removed in a future cleanup pass.


class PositionSizingStrategy(ABC):
    @abstractmethod
    def compute(self, close: pd.Series, config: dict) -> float: ...


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

        rets = close.diff() / close.shift(1)
        rets = rets.iloc[1:]
        if len(rets) < self.window:
            return 1.0
        rv = rets.iloc[-self.window :].std() * np.sqrt(252)
        if pd.isna(rv) or np.isinf(rv):
            return 1.0
        vol_baseline = config.get("vol_baseline")
        if vol_baseline is not None and vol_baseline > 0:
            rv = max(rv, float(vol_baseline))
        scalar = target / (rv + 1e-9)
        impact_bps = config.get("impact_bps")
        if impact_bps is not None:
            scalar *= self.edge_decay(float(impact_bps))
        return typing.cast(float, min(scalar, 1.0))

    def edge_decay(self, impact_bps: float, threshold_bps: float = 5.0) -> float:
        """Scales down position size when estimated impact exceeds a threshold."""
        if impact_bps > threshold_bps:
            return 0.5
        return 1.0
