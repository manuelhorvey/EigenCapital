"""Factor model — decomposes portfolio returns into factor exposures.

P3 in the portfolio maturity framework. Enables factor-level risk constraints
instead of per-asset constraints only.

Factor groups:
    USD, EUR, AUD, NZD, CHF, CAD, GBP — currency blocs
    US_EQUITY — ES, NQ, ^DJI
    COMMODITY — GC
    CROSS — mixed-exposure pairs

Usage:
    from shared.factor_model import (
        FACTOR_GROUPS,
        compute_factor_exposures,
        exposure_violations,
    )

    weights = {"EURUSD": 0.05, "AUDUSD": 0.03, ...}
    exposures = compute_factor_exposures(weights)
    violations = exposure_violations(exposures)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ── Factor group definitions ─────────────────────────────────────────────
# Maps factor name -> list of assets with primary exposure to that factor.
# Assets can appear in multiple factor groups when they have dual exposure.

FACTOR_GROUPS: dict[str, frozenset[str]] = {
    "USD": frozenset(
        {
            "EURUSD",
            "AUDUSD",
            "NZDUSD",
            "USDCHF",
            "USDCAD",
            "GBPUSD",
            "GBPCHF",
            "CADCHF",
            "NZDCHF",
            "EURCAD",
            "USDJPY",
        }
    ),
    "EUR": frozenset({"EURUSD", "EURAUD", "EURCHF", "EURNZD", "EURCAD"}),
    "AUD": frozenset({"AUDUSD", "AUDNZD", "EURAUD", "AUDJPY"}),
    "NZD": frozenset({"NZDUSD", "NZDCHF", "AUDNZD", "EURNZD", "NZDJPY"}),
    "CHF": frozenset({"EURCHF", "USDCHF", "NZDCHF", "CADCHF", "GBPCHF"}),
    "CAD": frozenset({"USDCAD", "CADCHF", "EURCAD"}),
    "GBP": frozenset({"GBPUSD", "GBPCHF", "GBPJPY"}),
    "JPY": frozenset({"AUDJPY", "NZDJPY", "GBPJPY", "USDJPY"}),
    "US_EQUITY": frozenset({"ES", "NQ", "^DJI"}),
    "COMMODITY": frozenset({"GC"}),
}

ALL_FACTORS: frozenset[str] = frozenset(FACTOR_GROUPS.keys())

# ── Default factor exposure limits ────────────────────────────────────
# Each limit is (min, max) as a fraction of portfolio capital.
# Applied as constraints during portfolio optimization.

DEFAULT_FACTOR_LIMITS: dict[str, tuple[float, float]] = {
    "USD": (-0.4, 0.6),
    "EUR": (-0.3, 0.3),
    "AUD": (-0.2, 0.2),
    "NZD": (-0.2, 0.2),
    "CHF": (-0.2, 0.2),
    "CAD": (-0.2, 0.2),
    "GBP": (-0.15, 0.15),
    "JPY": (-0.25, 0.25),
    "US_EQUITY": (-0.1, 0.15),
    "COMMODITY": (0.0, 0.05),
}


def compute_factor_exposures(
    weights: dict[str, float],
    factor_groups: dict[str, frozenset[str]] | None = None,
) -> dict[str, float]:
    """Compute net factor exposure from a portfolio weight dict.

    For each factor, exposure = sum of weights of all assets in that factor group.
    Assets that appear in multiple groups contribute to each group.

    Args:
        weights: {asset_name: weight_fraction}
        factor_groups: Factor group dict (defaults to FACTOR_GROUPS)

    Returns:
        {factor_name: net_exposure}
    """
    if factor_groups is None:
        factor_groups = FACTOR_GROUPS

    exposures: dict[str, float] = {}
    for factor, assets in factor_groups.items():
        net = sum(weights.get(a, 0.0) for a in assets)
        exposures[factor] = round(net, 6)

    return exposures


def exposure_violations(
    exposures: dict[str, float],
    limits: dict[str, tuple[float, float]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Check which factor exposures violate their limits.

    Args:
        exposures: {factor: net_exposure}
        limits: {factor: (min, max)} (defaults to DEFAULT_FACTOR_LIMITS)

    Returns:
        {factor: {"exposure": ..., "limit_lo": ..., "limit_hi": ..., "violation": "low"|"high"|None}}
    """
    if limits is None:
        limits = DEFAULT_FACTOR_LIMITS

    violations: dict[str, dict[str, Any]] = {}
    for factor, exposure in exposures.items():
        lo, hi = limits.get(factor, (-1.0, 1.0))
        status: str | None = None
        if exposure < lo:
            status = "low"
        elif exposure > hi:
            status = "high"
        violations[factor] = {
            "exposure": exposure,
            "limit_lo": lo,
            "limit_hi": hi,
            "violation": status,
        }

    return violations


def factor_exposure_penalty(
    weights: dict[str, float],
    limits: dict[str, tuple[float, float]] | None = None,
    penalty_scale: float = 10.0,
) -> float:
    """Compute penalty for factor exposure violations.

    Used as a penalty term in portfolio optimization objectives.
    Returns 0.0 if all exposures are within limits.

    Args:
        weights: {asset: weight}
        limits: {factor: (min, max)}
        penalty_scale: Scale factor for penalty

    Returns:
        Penalty value (higher = more violations)
    """
    if limits is None:
        limits = DEFAULT_FACTOR_LIMITS
    exposures = compute_factor_exposures(weights)
    penalty = 0.0
    for factor, exposure in exposures.items():
        lo, hi = limits.get(factor, (-1.0, 1.0))
        if exposure < lo:
            penalty += (lo - exposure) ** 2
        elif exposure > hi:
            penalty += (exposure - hi) ** 2
    return penalty * penalty_scale


def compute_factor_returns(
    returns: pd.DataFrame,
    method: str = "simple",
) -> pd.DataFrame:
    """Compute factor portfolio returns from asset returns.

    Two methods:
        - "simple": equal-weight within each factor group
        - "regression": OLS-estimated factor returns (requires >=200 obs)

    Args:
        returns: DataFrame of daily returns with asset columns
        method: "simple" or "regression"

    Returns:
        DataFrame of daily factor returns
    """
    factor_returns: dict[str, pd.Series] = {}

    if method == "simple":
        for factor, assets in FACTOR_GROUPS.items():
            available = [a for a in assets if a in returns.columns]
            if available:
                factor_returns[factor] = returns[available].mean(axis=1)
            else:
                factor_returns[factor] = pd.Series(0.0, index=returns.index)
        return pd.DataFrame(factor_returns)

    if method == "regression":
        from sklearn.linear_model import LinearRegression

        available_assets = [c for c in returns.columns if c in set().union(*FACTOR_GROUPS.values())]
        if len(available_assets) < 5:
            return pd.DataFrame()

        factor_proxies: dict[str, pd.Series] = {}
        for factor, assets in FACTOR_GROUPS.items():
            available = [a for a in assets if a in returns.columns]
            if available:
                factor_proxies[factor] = returns[available].mean(axis=1)

        proxy_df = pd.DataFrame(factor_proxies).dropna()
        if proxy_df.empty or len(proxy_df) < 200:
            return proxy_df

        X = proxy_df.values
        factor_mimicking: dict[str, np.ndarray] = {}
        for factor in proxy_df.columns:
            betas: list[float] = []
            for asset in available_assets:
                if asset not in returns.columns:
                    continue
                y = returns[asset].loc[proxy_df.index].values
                if not np.isfinite(y).all():
                    continue
                try:
                    lr = LinearRegression(fit_intercept=True)
                    lr.fit(X, y)
                    betas.append(lr.coef_[list(proxy_df.columns).index(factor)])
                except (ValueError, IndexError):
                    betas.append(0.0)
            beta_arr = np.array(betas)
            beta_arr = beta_arr / (np.abs(beta_arr).sum() + 1e-10)
            weighted = returns[available_assets].loc[proxy_df.index] @ beta_arr
            factor_mimicking[factor] = weighted.values

        return pd.DataFrame(factor_mimicking, index=proxy_df.index)

    raise ValueError(f"Unknown method: {method}")


def list_factors() -> list[str]:
    """Return sorted list of defined factors."""
    return sorted(ALL_FACTORS)


def summary(weights: dict[str, float]) -> dict[str, Any]:
    """Full factor exposure summary for dashboard/state.json."""
    exposures = compute_factor_exposures(weights)
    violations = exposure_violations(exposures)
    n_violations = sum(1 for v in violations.values() if v["violation"] is not None)
    return {
        "exposures": exposures,
        "violations": violations,
        "n_violations": n_violations,
        "within_limits": n_violations == 0,
    }
