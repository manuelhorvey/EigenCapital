from typing import Dict, List

import numpy as np
import pandas as pd

from shared.sizing import compute_equal_risk_weights, risk_parity_weights


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
