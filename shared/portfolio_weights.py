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

WeightMethod = Literal[
    "equal_v1",
    "risk_parity_v1",
    "risk_parity_v2",
    "risk_parity_v3",
    "hrp_v1",
    "factor_constrained_v1",
    "factor_constrained_v2",
    "conviction_weighted_v1",
]

WEIGHT_METHOD_VERSIONS = frozenset(
    {
        "equal_v1",
        "risk_parity_v1",
        "risk_parity_v2",
        "risk_parity_v3",
        "hrp_v1",
        "factor_constrained_v1",
        "factor_constrained_v2",
        "conviction_weighted_v1",
    }
)


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


# ── Covariance estimators ────────────────────────────────────────────────────


def _shrinkage_cov(returns: pd.DataFrame) -> pd.DataFrame:
    """Ledoit-Wolf shrinkage covariance matrix.

    Shrinks sample covariance toward a diagonal target, reducing estimation
    error when the number of assets is large relative to the number of
    observations.  Returns a pd.DataFrame with the same index/columns as the
    input returns ``.cov()`` would produce (annualised by *252*).

    Parameters
    ----------
    returns : pd.DataFrame
        Daily returns with assets as columns, datetime index.

    Returns
    -------
    pd.DataFrame of annualised shrinkage covariance.
    """
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf().fit(returns.dropna().values)
    cov = lw.covariance_
    return pd.DataFrame(cov * 252, index=returns.columns, columns=returns.columns)


def _ewma_cov(returns: pd.DataFrame, span: int = 60) -> pd.DataFrame:
    """Exponentially Weighted Moving Average covariance matrix.

    Places more weight on recent observations, making the covariance estimate
    more responsive to the current market regime.  Uses RiskMetrics-style decay
    where *span* maps to ``lambda = 2 / (span + 1)``.

    Parameters
    ----------
    returns : pd.DataFrame
        Daily returns with assets as columns, datetime index.
    span : int
        Decay span in trading days (default 60 ≈ 3 months).

    Returns
    -------
    pd.DataFrame of EWMA annualised covariance.
    """
    centered = returns.dropna() - returns.dropna().mean()
    n = len(centered)
    if n < 2:
        return pd.DataFrame(0.0, index=returns.columns, columns=returns.columns)

    decay = 2.0 / (span + 1)
    weights = (1 - decay) ** np.arange(n - 1, -1, -1)
    weights /= weights.sum()

    weighted = centered.multiply(weights, axis=0)
    cov = weighted.T @ centered  # weighted outer product
    return pd.DataFrame(cov * 252 / (1 - (1 - decay) ** n), index=returns.columns, columns=returns.columns)


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


@register("risk_parity_v2")
def _risk_parity_v2(returns: pd.DataFrame) -> dict[str, float]:
    """Risk parity using Ledoit-Wolf shrinkage covariance.

    Same formulation as v1 but with a shrunk covariance matrix that
    reduces estimation noise, especially when n_assets approaches
    n_observations.
    """
    assets = returns.columns.tolist()
    n = len(assets)
    if n == 0:
        return {}
    if n == 1:
        return {assets[0]: 1.0}

    cov = _shrinkage_cov(returns)
    target_risk = np.ones(n) / n

    def objective(w):
        w = np.clip(w, 0, 1)
        w_sum = w.sum()
        w = np.ones(n) / n if w_sum <= 0 else w / w_sum
        rc = risk_contribution(w, cov.values)
        return float(np.sum((rc - target_risk * rc.sum()) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0) for _ in range(n)]

    result = minimize(objective, np.ones(n) / n, bounds=bounds, constraints=constraints, method="SLSQP")
    w = result.x / max(result.x.sum(), 1e-12)
    return dict(zip(assets, w))


@register("risk_parity_v3")
def _risk_parity_v3(returns: pd.DataFrame) -> dict[str, float]:
    """Risk parity using EWMA covariance.

    Same formulation as v1 but with an exponentially-weighted covariance
    matrix (span=60) that responds more quickly to recent regime shifts.
    """
    assets = returns.columns.tolist()
    n = len(assets)
    if n == 0:
        return {}
    if n == 1:
        return {assets[0]: 1.0}

    cov = _ewma_cov(returns)
    target_risk = np.ones(n) / n

    def objective(w):
        w = np.clip(w, 0, 1)
        w_sum = w.sum()
        w = np.ones(n) / n if w_sum <= 0 else w / w_sum
        rc = risk_contribution(w, cov.values)
        return float(np.sum((rc - target_risk * rc.sum()) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0) for _ in range(n)]

    result = minimize(objective, np.ones(n) / n, bounds=bounds, constraints=constraints, method="SLSQP")
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


# ── factor_constrained_v1 ────────────────────────────────────────────────


@register("factor_constrained_v1")
def _factor_constrained_v1(
    returns: pd.DataFrame,
    **kwargs,
) -> dict[str, float]:
    """Risk parity with factor exposure constraints.

    Uses a penalized optimization: risk parity objective with a penalty
    for violating factor exposure limits (USD, CHF, equity beta, etc.).

    Args:
        returns: Asset return DataFrame
        **kwargs: May include 'factor_limits' to override defaults,
                  'risk_parity_weight' (default 0.7), 'penalty_scale'

    Returns:
        WeightVector with constrained weights.
    """
    from shared.constrained_weights import DEFAULT_FACTOR_LIMITS, factor_constrained_weights

    limits = kwargs.get("factor_limits", DEFAULT_FACTOR_LIMITS)
    rp_weight = float(kwargs.get("risk_parity_weight", 0.7))
    penalty_scale = float(kwargs.get("penalty_scale", 10.0))

    weights = factor_constrained_weights(
        returns,
        limits=limits,
        risk_parity_weight=rp_weight,
        penalty_scale=penalty_scale,
    )
    return weights


@register("factor_constrained_v2")
def _factor_constrained_v2(returns: pd.DataFrame, **kwargs) -> dict[str, float]:
    """Risk parity with hard factor exposure constraints.

    Unlike v1 (penalty method which rarely binds), v2 uses direct linear
    inequality constraints in the SLSQP optimizer, guaranteeing that CHF,
    equity, and other factor limits are satisfied.
    """
    from shared.constrained_weights import DEFAULT_FACTOR_LIMITS, factor_constrained_weights_v2

    limits = kwargs.get("factor_limits", DEFAULT_FACTOR_LIMITS)
    weights = factor_constrained_weights_v2(returns, limits=limits)
    return weights


@register("conviction_weighted_v1")
def _conviction_weighted_v1(returns: pd.DataFrame, **kwargs) -> dict[str, float]:
    """Risk parity tilted by model conviction.

    Assets with higher conviction (IC, mean confidence, or signal quality)
    receive a larger weight allocation than assets with lower conviction.

    The tilt is multiplicative:
        w_i = normalize(w_rp_i * (1 + lambda * (conv_i - mean_conv)))

    where ``conv_i`` is the conviction score for asset *i*, ``mean_conv`` is
    the portfolio-average conviction, and ``lambda`` controls the tilt
    strength (default 0.5).

    Parameters
    ----------
    returns : pd.DataFrame
        Daily asset returns.
    **kwargs
        conviction: dict[str, float] — per-asset conviction scores.
            If empty or missing, equal weights are returned.
        conviction_lambda: float — tilt strength (default 0.5).

    Returns
    -------
    {asset: weight} dict with conviction-tilted weights.
    """
    conviction = kwargs.get("conviction", {})
    tilt_lambda = float(kwargs.get("conviction_lambda", 0.5))

    if not conviction:
        assets = returns.columns.tolist()
        return {a: 1.0 / len(assets) for a in assets} if assets else {}

    base = _risk_parity_weights(returns)
    assets = list(base.keys())

    conv_vals = np.array([conviction.get(a, 0.0) for a in assets], dtype=float)
    mean_conv = np.mean(conv_vals)
    tilt = 1.0 + tilt_lambda * (conv_vals - mean_conv)
    tilt = np.clip(tilt, 0.01, 10.0)

    weights = np.array([base[a] for a in assets]) * tilt
    weights = weights / max(weights.sum(), 1e-12)
    return dict(zip(assets, weights.tolist()))


# ── Public API ───────────────────────────────────────────────────────────────


def list_methods() -> frozenset[WeightMethod]:
    """Return all registered weight methods."""
    return frozenset(_STRATEGIES.keys())


def compute_weights(
    method: WeightMethod,
    returns: pd.DataFrame,
    date: str | None = None,
    **kwargs,
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
    **kwargs
        Extra arguments forwarded to the strategy function (e.g. conviction).

    Returns
    -------
    WeightVector with normalized weights summing to 1.0.
    """
    if method not in _STRATEGIES:
        available = sorted(_STRATEGIES.keys())
        raise ValueError(f"Unknown method '{method}'. Available: {available}")

    fn = _STRATEGIES[method]
    weights = fn(returns, **kwargs)
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
    **kwargs,
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
    **kwargs
        Extra arguments forwarded to ``compute_weights()`` (e.g. conviction).

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
        idx_val = returns.index[i]
        date_str = str(idx_val.date()) if isinstance(idx_val, pd.Timestamp) else str(idx_val)
        wv = compute_weights(method, hist, date=date_str, **kwargs)
        records.append(wv.to_series())
    if not records:
        return pd.DataFrame(columns=returns.columns)
    return pd.DataFrame(records, index=returns.index[window:])
