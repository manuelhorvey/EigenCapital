"""Canonical portfolio weight computation — SINGLE source of truth.

Every weight computation in the system (backtest, live rebalance,
walk-forward replay) calls exactly one of the functions in this module.

CONTRACT:
    - compute_weights() is PURE — same returns → same weights.
    - No hidden state, no governance scaling, no runtime engine access.
    - Covariance is computed from RAW historical returns only.
    - Governance multipliers affect per-position sizing at trade time,
      NOT the portfolio weight matrix.

Versioning:
    WeightMethod strings are versioned (e.g. "risk_parity_v1").
    When the optimizer changes, register a new version.
    Old versions remain callable for reproducible backtests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize

WeightMethod = Literal["equal_v1", "risk_parity_v1", "hrp_v1"]

WEIGHT_METHOD_VERSIONS = frozenset({"equal_v1", "risk_parity_v1", "hrp_v1"})


def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Marginal risk contribution per asset.

    rc_i = w_i * (Cov @ w)_i / sqrt(w^T Cov w)
    """
    portfolio_var = weights @ cov @ weights
    if portfolio_var <= 1e-12:
        return np.full_like(weights, 1.0 / len(weights))
    marginal_risk = cov @ weights
    return weights * marginal_risk / np.sqrt(portfolio_var)


# ── WeightVector: the canonical output type ──────────────────────────────────


@dataclass(frozen=True)
class WeightVector:
    """A dated, versioned portfolio weight vector.

    Produced by compute_weights(). Consumed by backtest, live engine,
    and replay verification. Immutable after construction.
    """

    date: str
    method: WeightMethod
    weights: dict[str, float]
    n_iter: int | None = None
    converged: bool | None = None

    def __post_init__(self):
        total = sum(self.weights.values())
        if total <= 0:
            return
        if abs(total - 1.0) > 1e-6:
            normalized = {k: v / total for k, v in self.weights.items()}
            object.__setattr__(self, "weights", normalized)

    def to_series(self) -> pd.Series:
        return pd.Series(self.weights, name=self.date)

    def apply(self, daily_r: pd.Series) -> float:
        """Weighted portfolio return for one date.

        Parameters
        ----------
        daily_r: pd.Series indexed by asset name, values are daily R-multiple.

        Returns
        -------
        Weighted sum of returns = portfolio R for this date.
        """
        w = self.weights
        return sum(daily_r[a] * w[a] for a in w if a in daily_r.index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "method": self.method,
            "weights": dict(self.weights),
            "n_iter": self.n_iter,
            "converged": self.converged,
        }


# ── Strategy registry ────────────────────────────────────────────────────────

_STRATEGIES: dict[WeightMethod, Callable[[pd.DataFrame], dict[str, float]]] = {}


def register(method: WeightMethod):
    """Decorator to register a weight strategy."""

    def decorator(fn: Callable[[pd.DataFrame], dict[str, float]]):
        _STRATEGIES[method] = fn
        return fn

    return decorator


@register("equal_v1")
def _equal_weights(returns: pd.DataFrame) -> dict[str, float]:
    n = len(returns.columns)
    if n == 0:
        return {}
    return {c: 1.0 / n for c in returns.columns}


@register("risk_parity_v1")
def _risk_parity_weights(returns: pd.DataFrame) -> dict[str, float]:
    """Equal risk contribution via SLSQP.

    Covariance is computed from RAW daily returns ONLY.
    No governance scaling, no regime adjustment.
    """
    assets = returns.columns.tolist()
    n = len(assets)
    if n == 0:
        return {}
    if n == 1:
        return {assets[0]: 1.0}

    cov = returns.cov() * 252
    target_risk = np.ones(n) / n

    def objective(w):
        w = np.clip(w, 0, 1)
        w_sum = w.sum()
        w = np.ones(n) / n if w_sum <= 0 else w / w_sum
        rc = risk_contribution(w, cov.values)
        return float(np.sum((rc - target_risk * rc.sum()) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0) for _ in range(n)]

    result = minimize(
        objective,
        np.ones(n) / n,
        bounds=bounds,
        constraints=constraints,
        method="SLSQP",
    )

    w = result.x / max(result.x.sum(), 1e-12)
    return dict(zip(assets, w))


@register("hrp_v1")
def _hrp_weights(returns: pd.DataFrame) -> dict[str, float]:
    """Hierarchical Risk Parity (HRP) allocation.

    Uses scipy hierarchical clustering + recursive bisection.
    NOTE: hrp_allocator.py has a known bug in _get_quasi_diag when called
    with partial linkage (documented in tests/test_portfolio.py).
    This method will be reliable once that bug is fixed.
    """
    from portfolio.hrp_allocator import hrp_allocation

    return hrp_allocation(returns, method="single")


# ── Public API ───────────────────────────────────────────────────────────────


def list_methods() -> frozenset[WeightMethod]:
    """Return all registered weight methods."""
    return frozenset(_STRATEGIES.keys())


def compute_weights(
    method: WeightMethod,
    returns: pd.DataFrame,
    date: str | None = None,
) -> WeightVector:
    """Compute portfolio weights using any registered method.

    PURE FUNCTION: same returns + method → same weights every time.
    No hidden state, no engine access, no governance scaling.

    Parameters
    ----------
    method : WeightMethod
        One of the registered methods (e.g. 'equal_v1', 'risk_parity_v1').
    returns : pd.DataFrame
        Daily returns with assets as columns, datetime index.
        MUST be raw pct_change values — no governance/regime scaling.
    date : str, optional
        ISO date string for the weight vector. Defaults to today.

    Returns
    -------
    WeightVector with normalized weights summing to 1.0.
    """
    if method not in _STRATEGIES:
        available = sorted(_STRATEGIES.keys())
        raise ValueError(f"Unknown method '{method}'. Available: {available}")

    fn = _STRATEGIES[method]
    weights = fn(returns)
    return WeightVector(
        date=date or str(datetime.now().date()),
        method=method,
        weights=weights,
    )


def rolling_weight_matrix(
    returns: pd.DataFrame,
    method: WeightMethod,
    window: int = 252,
    min_periods: int = 60,
) -> pd.DataFrame:
    """Compute a weight matrix for every date in returns.

    For each date t >= window:
        1. Slice returns[t-window : t]
        2. Call compute_weights(method, slice)
        3. Store row

    Parameters
    ----------
    returns : pd.DataFrame
        Daily returns, assets as columns, datetime index.
    method : WeightMethod
        Weight strategy to use.
    window : int
        Rolling covariance window in days (default 252).
    min_periods : int
        Minimum data points required (default 60).

    Returns
    -------
    pd.DataFrame with assets as columns, dates as index.
    Each row sums to 1.0.
    """
    records: list[pd.Series] = []
    for i in range(window, len(returns)):
        hist = returns.iloc[i - window : i]
        if hist.dropna(how="all").shape[0] < min_periods:
            continue
        wv = compute_weights(method, hist, date=str(returns.index[i].date()))
        records.append(wv.to_series())
    if not records:
        return pd.DataFrame(columns=returns.columns)
    return pd.DataFrame(records, index=returns.index[window:])
