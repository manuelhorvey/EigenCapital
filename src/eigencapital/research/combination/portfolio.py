"""Portfolio constructors for multi-strategy alpha combination.

Implements:
- 1/N equal-weight (mandatory baseline)
- Risk-scaled (volatility-targeted)
- Each constructor is a separate research experiment

Critical invariant: Portfolio weights must use only information
available at the allocation timestamp (no look-ahead).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from eigencapital.research.combination.returns import ReturnStream


@dataclass(frozen=True)
class PortfolioWeights:
    """Point-in-time portfolio weights.

    Attributes:
        weights: Dict mapping stream_id → weight
        method: Weighting method used
        timestamp: When weights were computed
        turnover: Weight change from previous period
        provenance_hash: Deterministic hash
    """
    weights: Dict[str, float]
    method: str
    timestamp: str = ""
    turnover: float = 0.0
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weights": dict(sorted(self.weights.items())),
            "method": self.method,
            "timestamp": self.timestamp,
            "turnover": self.turnover,
            "provenance_hash": self.provenance_hash,
        }

    @property
    def weight_sum(self) -> float:
        return sum(self.weights.values())

    @property
    def num_constituents(self) -> int:
        return len(self.weights)

    @property
    def concentration(self) -> float:
        """HHI concentration measure (0 = equal weight, 1 = single asset)."""
        n = len(self.weights)
        if n == 0:
            return 0.0
        return sum(w ** 2 for w in self.weights.values())


@dataclass(frozen=True)
class PortfolioResult:
    """Result of a portfolio combination experiment.

    Attributes:
        experiment_id: Unique identifier
        method: Weighting method
        constituents: List of stream IDs
        weights_history: List of PortfolioWeights (one per rebalance)
        returns: Combined portfolio returns
        timestamps: Return timestamps
        metrics: Performance metrics
        provenance_hash: Deterministic hash
    """
    experiment_id: str
    method: str
    constituents: Tuple[str, ...]
    weights_history: Tuple[PortfolioWeights, ...]
    returns: Tuple[float, ...]
    timestamps: Tuple[str, ...]
    metrics: Dict[str, Any] = field(default_factory=dict)
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "method": self.method,
            "constituents": list(self.constituents),
            "weights_history": [w.to_dict() for w in self.weights_history],
            "returns": list(self.returns),
            "timestamps": list(self.timestamps),
            "metrics": dict(sorted(self.metrics.items())),
            "provenance_hash": self.provenance_hash,
        }


def compute_equal_weight(streams: List[ReturnStream]) -> PortfolioWeights:
    """Compute 1/N equal-weight allocation.

    This is the mandatory baseline for portfolio combination research.
    """
    if not streams:
        return PortfolioWeights(weights={}, method="equal_weight")

    n = len(streams)
    weight = 1.0 / n
    weights = {s.stream_id: weight for s in streams}

    return PortfolioWeights(weights=weights, method="equal_weight")


def compute_risk_scaled(
    streams: List[ReturnStream],
    target_vol: float = 0.10,
    lookback: int = 63,
) -> PortfolioWeights:
    """Compute risk-scaled (volatility-targeted) allocation.

    Weight_i ∝ 1 / realized_volatility_i

    Args:
        streams: Return streams
        target_vol: Target portfolio volatility (annualized)
        lookback: Lookback for volatility estimation

    Returns:
        PortfolioWeights with risk-scaled allocation
    """
    if not streams:
        return PortfolioWeights(weights={}, method="risk_scaled")

    # Compute inverse volatility weights
    inv_vols = {}
    for s in streams:
        vol = s.volatility
        if vol < 1e-15:
            inv_vols[s.stream_id] = 0.0
        else:
            inv_vols[s.stream_id] = 1.0 / vol

    total_inv_vol = sum(inv_vols.values())
    if total_inv_vol < 1e-15:
        # All zero vol → equal weight
        return compute_equal_weight(streams)

    weights = {sid: iv / total_inv_vol for sid, iv in inv_vols.items()}

    return PortfolioWeights(weights=weights, method="risk_scaled")


def combine_returns(
    streams: List[ReturnStream],
    weights: PortfolioWeights,
) -> Tuple[Tuple[float, ...], Tuple[str, ...]]:
    """Combine return streams using given weights.

    Returns:
        Tuple of (combined_returns, timestamps)
    """
    if not streams or not weights.weights:
        return (), ()

    # Find common timestamps
    all_timestamps = set()
    for s in streams:
        all_timestamps.update(s.timestamps)
    common_ts = sorted(all_timestamps)

    if not common_ts:
        return (), ()

    # Build return lookup
    return_lookup: Dict[str, Dict[str, float]] = {}
    for s in streams:
        return_lookup[s.stream_id] = dict(zip(s.timestamps, s.returns))

    combined = []
    valid_timestamps = []
    for ts in common_ts:
        portfolio_return = 0.0
        total_weight = 0.0
        for sid, weight in weights.weights.items():
            if ts in return_lookup.get(sid, {}):
                portfolio_return += weight * return_lookup[sid][ts]
                total_weight += weight

        if total_weight > 1e-15:
            portfolio_return /= total_weight
            combined.append(portfolio_return)
            valid_timestamps.append(ts)

    return tuple(combined), tuple(valid_timestamps)


def compute_portfolio_metrics(returns: Tuple[float, ...]) -> Dict[str, Any]:
    """Compute standard portfolio performance metrics."""
    if not returns:
        return {}

    n = len(returns)
    mean_ret = sum(returns) / n

    # Volatility
    if n > 1:
        variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
        vol = math.sqrt(variance)
    else:
        vol = 0.0

    # Sharpe (annualized, assuming daily returns)
    sharpe = (mean_ret / vol * math.sqrt(252)) if vol > 1e-15 else 0.0

    # Sortino (downside deviation)
    neg_returns = [r for r in returns if r < 0]
    if neg_returns and n > 1:
        downside_var = sum(r ** 2 for r in neg_returns) / (n - 1)
        downside_dev = math.sqrt(downside_var)
        sortino = (mean_ret / downside_dev * math.sqrt(252)) if downside_dev > 1e-15 else 0.0
    else:
        sortino = 0.0

    # Maximum drawdown
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cum *= (1.0 + r)
        if cum > peak:
            peak = cum
        dd = (peak - cum) / peak
        if dd > max_dd:
            max_dd = dd

    # CAGR
    if n > 0:
        cum_ret = 1.0
        for r in returns:
            cum_ret *= (1.0 + r)
        years = n / 252.0
        cagr = (cum_ret ** (1.0 / years) - 1.0) if years > 0 else 0.0
    else:
        cagr = 0.0

    return {
        "mean_return": mean_ret,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "cagr": cagr,
        "num_periods": n,
        "cumulative_return": cum_ret - 1.0 if n > 0 else 0.0,
    }
